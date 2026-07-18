#!/usr/bin/env python3
"""HWPX table operations and utilities.

Usage:
    python table.py dump doc.hwpx                              # list all tables
    python table.py dump doc.hwpx --table-id 1000000003       # dump specific table
    python table.py dump doc.hwpx --contains "항목명"          # find by text
    python table.py dump doc.hwpx --table-id ID --cell 2,1    # verbose cell
    python table.py locate doc.hwpx --tag hp:tbl --contains "항목명"
    python table.py insert doc.hwpx --table-id ID --after-row 3 --row-file row.xml -o out.hwpx
    python table.py replace doc.hwpx --table-id ID --cell 1,0 --para 0 0 "text" -o out.hwpx
    python table.py replace doc.hwpx --table-id ID --cell 1,0 --append-para 0 0 "한 줄 추가" -o out.hwpx
    python table.py replace doc.hwpx --table-id ID --cell 1,0 --match-style 0 "형제 스타일로 추가" -o out.hwpx
    python table.py toggle-check doc.hwpx --table-id ID --cell 1,0 --label "승인" -o out.hwpx
    python table.py delete doc.hwpx --table-id ID --rows 2,3 -o out.hwpx
    python table.py calc-widths 3
    python table.py calc-widths 1:4
    python table.py strip-lineseg input.hwpx --output clean.hwpx
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from _common import (
    LINESEG_RE,
    MIN_READABLE_PT,
    PARA_ID_RE,
    PLACEHOLDER_IDS,
    SECTION_RE,
    charpr_pt,
    configure_io,
    die,
    find_table,
    load_charpr_heights,
    load_section,
    save_section,
    strip_linesegarray,
    top_cells,
    top_trs,
    xml_escape,
)

A4_BODY_WIDTH = 42520


# ── shared table helpers ──────────────────────────────────────────────────────

def _own_cell_addr(tc: str) -> tuple[int, int] | None:
    tbl_depth = 0
    for m in re.finditer(
        r'<hp:tbl\b|</hp:tbl>|<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"/>',
        tc,
    ):
        g = m.group()
        if g == "<hp:tbl":
            tbl_depth += 1
        elif g == "</hp:tbl>":
            tbl_depth -= 1
        elif tbl_depth == 0:
            return int(m.group(1)), int(m.group(2))
    return None


def _cell_span(tc: str) -> tuple[int, int]:
    m = re.search(r'<hp:cellSpan colSpan="(\d+)" rowSpan="(\d+)"/>', tc)
    return (int(m.group(1)), int(m.group(2))) if m else (1, 1)


def _cell_text(tc: str) -> str:
    tbl_depth = 0
    parts = []
    for m in re.finditer(r"<hp:tbl\b|</hp:tbl>|<hp:t>(.*?)</hp:t>", tc, re.DOTALL):
        g = m.group()
        if g == "<hp:tbl":
            tbl_depth += 1
        elif g == "</hp:tbl>":
            tbl_depth -= 1
        elif tbl_depth == 0:
            txt = m.group(1).strip()
            if txt:
                parts.append(txt)
    return " ".join(parts)


# ── dump ──────────────────────────────────────────────────────────────────────

def _find_all_table_spans(xml: str) -> list[tuple[str, int, int]]:
    depth = 0
    start = None
    table_id = None
    out: list[tuple[str, int, int]] = []
    for m in re.finditer(r'<hp:tbl\b[^>]*(?<!/)>|</hp:tbl>', xml):
        if m.group().startswith("</"):
            depth -= 1
            if depth == 0 and start is not None:
                out.append((table_id or "?", start, m.end()))
                start = None
                table_id = None
        else:
            depth += 1
            if depth == 1:
                start = m.start()
                id_m = re.search(r'\bid="(\d+)"', m.group())
                table_id = id_m.group(1) if id_m else "?"
    return out


def _find_all_table_spans_deep(xml: str) -> list[tuple[str, int, int]]:
    stack: list[tuple[str, int]] = []
    out: list[tuple[str, int, int]] = []
    for m in re.finditer(r'<hp:tbl\b[^>]*(?<!/)>|</hp:tbl>', xml):
        if m.group().startswith("</"):
            if stack:
                t_id, t_start = stack.pop()
                out.append((t_id, t_start, m.end()))
        else:
            id_m = re.search(r'\bid="(\d+)"', m.group())
            stack.append((id_m.group(1) if id_m else "?", m.start()))
    return out


def _dump_table(tbl_xml: str, table_id: str) -> None:
    cells = []
    for cs, ce in top_cells(tbl_xml):
        tc = tbl_xml[cs:ce]
        addr = _own_cell_addr(tc)
        if addr is None:
            continue
        col_addr, row_addr = addr
        col_span, row_span = _cell_span(tc)
        text = _cell_text(tc)
        cells.append((row_addr, col_addr, col_span, row_span, text))
    cells.sort(key=lambda x: (x[0], x[1]))
    print(f"table id={table_id}: {len(cells)} cells")
    print(f"  {'row':6} {'col':6} {'cSpan':6} {'rSpan':6}  text")
    print(f"  {'-' * 60}")
    for row, col, cs, rs, text in cells:
        display = text[:55] + ("…" if len(text) > 55 else "")
        print(f"  {int(row):-6} {int(col):-6} {int(cs):-6} {int(rs):-6}  {display}")
    print("  [col,row for --cell: e.g. row=1 col=2 → --cell 2,1]")


def _dump_cell_verbose(tbl_xml: str, table_id: str, col: int, row: int) -> None:
    for cs, ce in top_cells(tbl_xml):
        tc = tbl_xml[cs:ce]
        addr = _own_cell_addr(tc)
        if addr != (col, row):
            continue
        col_span, row_span = _cell_span(tc)
        has_lineseg = bool(re.search(r"<hp:linesegarray>", tc))
        print(f"table id={table_id}  cell col={col} row={row}  cSpan={col_span} rSpan={row_span}")
        print(f"  linesegarray: {'YES (replace will strip)' if has_lineseg else 'no'}")
        sublist_m = re.search(r"<hp:subList\b[^>]*>", tc)
        if sublist_m is None:
            print("  (no hp:subList found)")
            return
        sublist_start = tc.index(">", sublist_m.start()) + 1
        depth = 1
        sublist_end = len(tc)
        for m in re.finditer(r"<hp:subList\b|</hp:subList>", tc[sublist_start:]):
            if m.group().startswith("</"):
                depth -= 1
                if depth == 0:
                    sublist_end = sublist_start + m.start()
                    break
            else:
                depth += 1
        sublist_content = tc[sublist_start:sublist_end]
        tbl_depth = 0
        para_spans = []
        stack: list[int] = []
        for m in re.finditer(r"<hp:tbl\b|</hp:tbl>|<hp:p\b[^/]|</hp:p>", sublist_content):
            g = m.group()
            if g == "<hp:tbl":
                tbl_depth += 1
            elif g == "</hp:tbl>":
                tbl_depth -= 1
            elif g.startswith("<hp:p") and tbl_depth == 0:
                stack.append(m.start())
            elif g == "</hp:p>" and tbl_depth == 0 and stack:
                ps = stack.pop()
                para_spans.append((ps, m.end()))
        print(f"  paragraphs: {len(para_spans)}")
        for i, (ps, pe) in enumerate(para_spans):
            para_xml = sublist_content[ps:pe]
            para_pr_m = re.search(r'paraPrIDRef="(\d+)"', para_xml)
            para_pr = para_pr_m.group(1) if para_pr_m else "?"
            runs = re.findall(r'charPrIDRef="(\d+)"[^>]*>.*?<hp:t>(.*?)</hp:t>', para_xml, re.DOTALL)
            runs_empty = re.findall(r'charPrIDRef="(\d+)"[^>]*/>', para_xml)
            runs_t_empty = re.findall(r'charPrIDRef="(\d+)"[^>]*><hp:t/>', para_xml)
            run_desc = []
            for cpr, txt in runs:
                display = f"{txt[:30]}..." if len(txt) > 30 else txt
                run_desc.append(f"charPr={cpr}:{display!r}")
            for cpr in runs_empty:
                run_desc.append(f"charPr={cpr}:(empty)")
            for cpr in runs_t_empty:
                run_desc.append(f"charPr={cpr}:(empty)")
            run_str = " + ".join(run_desc) if run_desc else "(empty)"
            print(f"  P[{int(i)}] paraPr={para_pr}  {run_str}")
        return
    die(f"cell col={col} row={row} not found in table {table_id}")


def cmd_dump(args: argparse.Namespace) -> None:
    if args.cell and not args.table_id:
        die("--cell requires --table-id")
    inp = Path(args.input)
    xml, _ = load_section(inp, args.section)
    if args.table_id:
        span = find_table(xml, args.table_id)
        if span is None:
            die(f"table id={args.table_id} not found")
        if args.cell:
            try:
                col, row = (int(x) for x in args.cell.split(","))
            except ValueError:
                die(f"--cell expects col,row (got {args.cell!r})")
            _dump_cell_verbose(xml[span[0]:span[1]], args.table_id, col, row)
        elif args.style_map:
            heights = load_charpr_heights(inp)
            _dump_style_map(xml[span[0]:span[1]], args.table_id, heights)
        else:
            _dump_table(xml[span[0]:span[1]], args.table_id)
        return
    all_tables = _find_all_table_spans(xml)
    if args.contains:
        candidates = _find_all_table_spans_deep(xml)
        matches = [
            (tid, s, e) for tid, s, e in candidates
            if all(c in xml[s:e] for c in args.contains)
        ]
        matches = [
            (tid, s, e) for tid, s, e in matches
            if not any(s <= s2 and e2 <= e and (s, e) != (s2, e2)
                       for _, s2, e2 in matches)
        ]
        if not matches:
            die(f"no table found containing: {', '.join(args.contains)}", 2)
        for tid, s, e in matches:
            _dump_table(xml[s:e], tid)
            print()
        return
    print(f"{len(all_tables)} table(s) in section {int(args.section)}:")
    for tid, s, e in all_tables:
        tbl = xml[s:e]
        cells = top_cells(tbl)
        rows_m = re.search(r'rowCnt="(\d+)"', tbl)
        cols_m = re.search(r'colCnt="(\d+)"', tbl)
        rows = rows_m.group(1) if rows_m else "?"
        cols = cols_m.group(1) if cols_m else "?"
        preview_texts = []
        for cs, ce in cells[:3]:
            t = _cell_text(tbl[cs:ce])
            if t:
                preview_texts.append(t)
        preview = " | ".join(preview_texts[:3])[:60]
        print(f"  id={tid:12}  {rows}×{cols} cells  {preview}")
    print("\nRe-run with --table-id ID or --contains TEXT to dump cell map.")


# ── locate ────────────────────────────────────────────────────────────────────

def _matched_spans(xml: str, tag: str) -> list[tuple[int, int, int]]:
    events: list[tuple[int, str, int | None]] = []
    for m in re.finditer(rf"<{tag}\b", xml):
        events.append((m.start(), "o", None))
    for m in re.finditer(rf"</{tag}>", xml):
        events.append((m.start(), "c", m.end()))
    events.sort(key=lambda x: x[0])
    stack: list[int] = []
    out: list[tuple[int, int, int]] = []
    for pos, kind, end in events:
        if kind == "o":
            stack.append(pos)
        else:
            if not stack:
                raise ValueError(f"unbalanced </{tag}> at offset {int(pos)}")
            start = stack.pop()
            assert end is not None
            out.append((start, end, len(stack)))
    if stack:
        raise ValueError(f"unclosed <{tag}> at offset {int(stack[-1])}")
    out.sort(key=lambda x: x[0])
    return out


def _text_preview(fragment: str, limit: int = 70) -> str:
    txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", fragment, re.DOTALL))
    txt = txt.replace("\n", " ").strip()
    return txt[:limit] + ("…" if len(txt) > limit else "")


def cmd_locate(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    xml, target = load_section(inp, args.section)
    try:
        spans = _matched_spans(xml, args.tag)
    except ValueError as e:
        die(str(e))
    matches = []
    for start, end, depth in spans:
        if args.depth is not None and depth != args.depth:
            continue
        frag = xml[start:end]
        if all(c in frag for c in args.contains):
            matches.append((start, end, depth, frag))
    print(f"{len(matches)} match(es) for <{args.tag}> in {target}")
    for i, (start, end, depth, frag) in enumerate(matches):
        print(f"  [{i}] span={start}:{end} depth={depth} len={end - start}  {_text_preview(frag)}")
    if args.extract_dir and matches:
        out_dir = Path(args.extract_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, (_s, _e, _d, frag) in enumerate(matches):
            if args.pretty:
                frag = re.sub(r"><", ">\n<", frag)
            (out_dir / (f"match_{int(i)}.xml")).write_text(frag, encoding="utf-8")
        print(f"  extracted {len(matches)} file(s) to {out_dir}")
    sys.exit(0 if matches else 2)


# ── insert ────────────────────────────────────────────────────────────────────

def _set_row_addr(row: str, new_idx: int) -> str:
    """Replace rowAddr only in top-level cells, not inside nested tables."""
    depth = 0
    result = []
    last = 0
    for m in re.finditer(r'<hp:tbl\b|</hp:tbl>|rowAddr="\d+"', row):
        g = m.group()
        if g.startswith("<hp:tbl"):
            depth += 1
            result.append(row[last:m.end()])
            last = m.end()
        elif g == "</hp:tbl>":
            depth -= 1
            result.append(row[last:m.end()])
            last = m.end()
        else:
            result.append(row[last:m.start()])
            last = m.end()
            result.append(f'rowAddr="{int(new_idx)}"' if depth == 0 else g)
    result.append(row[last:])
    return "".join(result)


CELL_RE = re.compile(
    r'(<hp:cellAddr colAddr=")(\d+)(" rowAddr=")(\d+)("/>)'
    r'(<hp:cellSpan colSpan="\d+" rowSpan=")(\d+)("/>)'
)


def _insert_row(xml: str, table_id: str, at_index: int,
                row_xml: str, grow: set[tuple[int, int]]) -> tuple[str, list[str]]:
    span = find_table(xml, table_id)
    if span is None:
        raise ValueError(f"table id={table_id} not found")
    ti, tend = span
    tbl = xml[ti:tend]
    trs = top_trs(tbl)
    n = len(trs)
    if at_index < 0 or at_index > n:
        raise ValueError(f"--at {int(at_index)} out of range (table has {int(n)} rows; 0..{int(n)})")
    row_xml = LINESEG_RE.sub("", row_xml).strip()
    if not (row_xml.startswith("<hp:tr") and row_xml.endswith("</hp:tr>")):
        raise ValueError("row file must contain exactly one <hp:tr>...</hp:tr>")
    existing = {i for i in PARA_ID_RE.findall(xml) if i not in PLACEHOLDER_IDS}
    incoming = [i for i in PARA_ID_RE.findall(row_xml) if i not in PLACEHOLDER_IDS]
    clash = sorted(set(incoming) & existing)
    if clash:
        raise ValueError(f"inserted row reuses hp:p id(s) {clash} — renumber them in the row file (or set to placeholder 0)")
    if len(incoming) != len(set(incoming)):
        raise ValueError("inserted row has duplicate hp:p id(s) internally")
    prefix = tbl[:trs[0][0]]
    suffix = tbl[trs[-1][1]:]
    rows = [tbl[s:e] for s, e in trs]
    grown = 0

    def adjust(m: re.Match, row_index: int) -> str:
        col = int(m.group(2))
        ra = int(m.group(4))
        rs = int(m.group(7))
        straddle = ra <= at_index - 1 and ra + rs - 1 >= at_index
        explicit = (ra, col) in grow
        new_rs = rs + 1 if (straddle or explicit) else rs
        return (m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5)
                + m.group(6) + str(new_rs) + m.group(8))

    new_rows = []
    for idx, row in enumerate(rows):
        before = row
        row = CELL_RE.sub(lambda m, i=idx: adjust(m, i), row)
        grown += sum(1 for a, b in zip(CELL_RE.findall(before), CELL_RE.findall(row))
                     if a[6] != b[6])
        new_rows.append(row)
    new_rows.insert(at_index, row_xml)
    new_rows = [_set_row_addr(r, i) for i, r in enumerate(new_rows)]
    new_prefix, nc = re.subn(
        r'(<hp:tbl\b[^>]*\browCnt=")(\d+)(")',
        lambda m: m.group(1) + str(int(m.group(2)) + 1) + m.group(3),
        prefix, count=1,
    )
    if nc != 1:
        raise ValueError("rowCnt attribute not found on <hp:tbl>")
    new_tbl = new_prefix + "".join(new_rows) + suffix
    new_xml = xml[:ti] + new_tbl + xml[tend:]
    info = [
        f"inserted row at index {int(at_index)} (rowCnt {int(n)} -> {int(n + 1)})",
        f"rowSpan cells extended: {int(grown)}",
    ]
    return new_xml, info


def _list_rows_insert(xml: str, table_id: str) -> None:
    span = find_table(xml, table_id)
    if span is None:
        die(f"table id={table_id} not found")
    tbl = xml[span[0]:span[1]]
    trs = top_trs(tbl)
    print(f"table id={table_id}: {len(trs)} rows")
    for i, (s, e) in enumerate(trs):
        row = tbl[s:e]
        txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", row))
        spans = [m[6] for m in CELL_RE.findall(row)]
        print(f"  [{int(i)}] cells={len(spans)} rowSpans={spans}  {txt[:60]}")


def cmd_insert(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    is_dir_mode = inp.is_dir()
    xml, target = load_section(inp, args.section)
    if args.list:
        _list_rows_insert(xml, args.table_id)
        sys.exit(0)
    if args.at is None and args.after_row is None:
        die("--at or --after-row required (or use --list)")
    at_index = args.at if args.at is not None else args.after_row + 1
    if not args.row_file or (not is_dir_mode and not args.output):
        die("--row-file required (and --output required for .hwpx input)")
    row_xml = Path(args.row_file).read_text(encoding="utf-8")
    grow: set[tuple[int, int]] = set()
    for g in args.grow:
        try:
            r, c = (int(x) for x in g.split(","))
        except ValueError:
            die(f"--grow expects rowAddr,colAddr (got {g!r})")
        grow.add((r, c))
    try:
        new_xml, info = _insert_row(xml, args.table_id, at_index, row_xml, grow)
    except ValueError as e:
        die(str(e))
    new_xml, n_ls = LINESEG_RE.subn("", new_xml)
    out_path = save_section(inp, target, new_xml, args.output)
    print(f"DONE (in-place): {out_path}" if is_dir_mode else f"DONE: {out_path}")
    for line in info:
        print(f"  {line}")
    print(f"  linesegarray stripped: {n_ls}")


# ── replace ───────────────────────────────────────────────────────────────────

def _direct_sublist(tc: str) -> tuple[int, int] | None:
    events: list[tuple[int, str, int]] = []
    for m in re.finditer(r"<hp:subList\b", tc):
        events.append((m.start(), "o", tc.index(">", m.start()) + 1))
    for m in re.finditer(r"</hp:subList>", tc):
        events.append((m.start(), "c", m.end()))
    events.sort(key=lambda x: x[0])
    depth = 0
    open_inner: int | None = None
    for pos, kind, off in events:
        if kind == "o":
            if depth == 0:
                open_inner = off
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                assert open_inner is not None
                return open_inner, pos
    return None


def _build_run(char_pr: str, text: str) -> str:
    if not text:
        return f'<hp:run charPrIDRef="{char_pr}"><hp:t/></hp:run>'
    return f'<hp:run charPrIDRef="{char_pr}"><hp:t>{xml_escape(text)}</hp:t></hp:run>'


def _build_para_runs(para_pr: str, runs: list[tuple[str, str]]) -> str:
    run_xml = "".join(_build_run(c, t) for c, t in runs)
    return (f'<hp:p id="0" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">{run_xml}</hp:p>')


def _replace_cell(xml: str, table_id: str, col: int, row: int,
                  content: str) -> tuple[str, list[str]]:
    span = find_table(xml, table_id)
    if span is None:
        raise ValueError(f"table id={table_id} not found")
    ti, tend = span
    tbl = xml[ti:tend]
    target = None
    for cs, ce in top_cells(tbl):
        addr = _own_cell_addr(tbl[cs:ce])
        if addr == (col, row):
            if target is not None:
                raise ValueError(f"cell {int(col)},{int(row)} is not unique in table")
            target = (cs, ce)
    if target is None:
        raise ValueError(f"cell colAddr={int(col)} rowAddr={int(row)} not found")
    cs, ce = target
    tc = tbl[cs:ce]
    sl = _direct_sublist(tc)
    if sl is None:
        raise ValueError(f"cell {int(col)},{int(row)} has no <hp:subList>")
    in_s, in_e = sl
    rest = xml[:ti] + xml[tend:] + tbl[:cs] + tc[:in_s] + tc[in_e:] + tbl[ce:]
    existing = {i for i in PARA_ID_RE.findall(rest) if i not in PLACEHOLDER_IDS}
    incoming = [i for i in PARA_ID_RE.findall(content) if i not in PLACEHOLDER_IDS]
    clash = sorted(set(incoming) & existing)
    if clash:
        raise ValueError(f"new content reuses hp:p id(s) {clash} — set them to placeholder 0 or renumber")
    if len(incoming) != len(set(incoming)):
        raise ValueError("new content has duplicate hp:p id(s) internally")
    new_tc = tc[:in_s] + content + tc[in_e:]
    new_tbl = tbl[:cs] + new_tc + tbl[ce:]
    new_xml = xml[:ti] + new_tbl + xml[tend:]
    n_para = content.count("<hp:p ")
    return new_xml, [f"cell {int(col)},{int(row)} content replaced ({int(n_para)} paragraph(s))"]


def _set_text_cell(xml: str, table_id: str, col: int, row: int,
                   old_text: str, new_text: str) -> tuple[str, list[str]]:
    span = find_table(xml, table_id)
    if span is None:
        raise ValueError(f"table id={table_id} not found")
    ti, tend = span
    tbl = xml[ti:tend]
    target = None
    for cs, ce in top_cells(tbl):
        addr = _own_cell_addr(tbl[cs:ce])
        if addr == (col, row):
            if target is not None:
                raise ValueError(f"cell {int(col)},{int(row)} is not unique in table")
            target = (cs, ce)
    if target is None:
        raise ValueError(f"cell colAddr={int(col)} rowAddr={int(row)} not found")
    cs, ce = target
    tc = tbl[cs:ce]
    sl = _direct_sublist(tc)
    if sl is None:
        raise ValueError(f"cell {int(col)},{int(row)} has no <hp:subList>")
    in_s, in_e = sl
    cell_content = tc[in_s:in_e]
    escaped_old = xml_escape(old_text)
    t_matches = re.findall(rf"<hp:t>{re.escape(escaped_old)}</hp:t>", cell_content)
    count = len(t_matches)
    if count == 0:
        raise ValueError(
            f"--set-text: '{old_text}' not found in cell {col},{row} subList; "
            "OLD must match the *entire* content of a single <hp:t> element, not a "
            "substring — check for a partial/substring mismatch first. If OLD really is "
            "the full text of a run, the text may instead be split across runs; "
            "use --para or --content-file in that case."
        )
    if count > 1:
        raise ValueError(
            f"--set-text: '{old_text}' found {count} times in cell {col},{row} subList (ambiguous); "
            "provide a more specific old_text or use --content-file."
        )
    new_content = cell_content.replace(
        f"<hp:t>{escaped_old}</hp:t>",
        f"<hp:t>{xml_escape(new_text)}</hp:t>",
        1,
    )
    new_content, _ = strip_linesegarray(new_content)
    new_tc = tc[:in_s] + new_content + tc[in_e:]
    new_tbl = tbl[:cs] + new_tc + tbl[ce:]
    new_xml = xml[:ti] + new_tbl + xml[tend:]
    msg = f"cell {int(col)},{int(row)} text '{old_text}' -> '{new_text}' (charPr preserved)"
    return new_xml, [msg]


def _locate_cell_sublist(
    xml: str, table_id: str, col: int, row: int
) -> tuple[int, int, str, int, int, str, int, int]:
    """Resolve a unique cell's direct subList span.

    Returns (ti, tend, tbl, cs, ce, tc, in_s, in_e) where in_s..in_e bound the
    inner content of the cell's direct <hp:subList>. Raises ValueError if the
    table/cell is missing, the cell is non-unique, or it has no subList. Factors
    out the lookup boilerplate shared by the append/toggle ops below.
    """
    span = find_table(xml, table_id)
    if span is None:
        raise ValueError(f"table id={table_id} not found")
    ti, tend = span
    tbl = xml[ti:tend]
    target = None
    for cs, ce in top_cells(tbl):
        if _own_cell_addr(tbl[cs:ce]) == (col, row):
            if target is not None:
                raise ValueError(f"cell {int(col)},{int(row)} is not unique in table")
            target = (cs, ce)
    if target is None:
        raise ValueError(f"cell colAddr={int(col)} rowAddr={int(row)} not found")
    cs, ce = target
    tc = tbl[cs:ce]
    sl = _direct_sublist(tc)
    if sl is None:
        raise ValueError(f"cell {int(col)},{int(row)} has no <hp:subList>")
    in_s, in_e = sl
    return ti, tend, tbl, cs, ce, tc, in_s, in_e


def _splice_cell_inner(
    xml: str, ti: int, tend: int, tbl: str, cs: int, ce: int,
    tc: str, in_s: int, in_e: int, new_inner: str,
) -> str:
    """Rebuild the document with new subList inner content for one cell."""
    new_tc = tc[:in_s] + new_inner + tc[in_e:]
    new_tbl = tbl[:cs] + new_tc + tbl[ce:]
    return xml[:ti] + new_tbl + xml[tend:]


def _append_para_cell(
    xml: str, table_id: str, col: int, row: int,
    para_pr: str, char_pr: str, text: str,
) -> tuple[str, list[str]]:
    """Append one paragraph to a cell, keeping existing paragraphs intact.

    Unlike replace (which rebuilds the whole subList), this preserves the cell's
    current multi-run boilerplate — the common "공문/서식: add one line under the
    existing content" pattern. The new paragraph uses placeholder id=0, so it
    never clashes with existing hp:p ids.
    """
    ti, tend, tbl, cs, ce, tc, in_s, in_e = _locate_cell_sublist(xml, table_id, col, row)
    inner = tc[in_s:in_e]
    new_para = _build_para_runs(para_pr, [(char_pr, text)])
    inner, _ = strip_linesegarray(inner + new_para)
    new_xml = _splice_cell_inner(xml, ti, tend, tbl, cs, ce, tc, in_s, in_e, inner)
    msg = f"cell {int(col)},{int(row)}: appended 1 paragraph (paraPr={para_pr} charPr={char_pr})"
    return new_xml, [msg]


def _direct_paras(inner: str) -> list[tuple[int, int]]:
    """Spans of <hp:p>...</hp:p> that are *direct* children of the cell subList.

    A cell may contain a nested table, whose cells carry their own paragraphs. We
    track subList-nesting depth so only paragraphs at depth 0 (the cell's own) are
    returned — nested-table paragraphs must not be mistaken for siblings. `inner`
    is already the content *between* the cell subList's open/close tags, so depth 0
    is the direct level.
    """
    events = sorted(
        [(m.start(), 1) for m in re.finditer(r"<hp:subList\b", inner)]
        + [(m.start(), -1) for m in re.finditer(r"</hp:subList>", inner)]
    )

    def depth_at(pos: int) -> int:
        d = 0
        for ep, delta in events:
            if ep >= pos:
                break
            d += delta
        return d

    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"<hp:p\b[^>]*>", inner):
        if depth_at(m.start()) != 0:
            continue
        end = inner.find("</hp:p>", m.end())
        if end == -1:
            continue
        spans.append((m.start(), end + len("</hp:p>")))
    return spans


def _hp_t_spans(fragment: str) -> list[tuple[int, int, str]]:
    """(start, end, text) for each <hp:t>...</hp:t> inner text run in a fragment."""
    return [
        (m.start(1), m.end(1), m.group(1))
        for m in re.finditer(r"<hp:t>(.*?)</hp:t>", fragment, re.DOTALL)
    ]


def _concat_to_raw(segs: list[tuple[int, int, str]], ci: int) -> int:
    """Map an index in the concatenated <hp:t> text back to a raw fragment offset."""
    acc = 0
    for rs, _re, t in segs:
        if ci <= acc + len(t):
            return rs + (ci - acc)
        acc += len(t)
    return segs[-1][1] if segs else 0


def _append_para_match(
    xml: str, table_id: str, col: int, row: int, n: int, text: str,
) -> tuple[str, list[str]]:
    """Append a paragraph inheriting paraPr/charPr from the cell's Nth sibling.

    Saves the caller from having to look up style IDs when the goal is simply to
    add a line in the same style as an existing one. N indexes only the cell's
    *direct* paragraphs (nested-table paragraphs are skipped).
    """
    _, _, _, _, _, tc, in_s, in_e = _locate_cell_sublist(xml, table_id, col, row)
    inner = tc[in_s:in_e]
    paras = _direct_paras(inner)
    if not paras:
        raise ValueError(f"cell {int(col)},{int(row)} has no paragraph to match style from")
    if n < 0 or n >= len(paras):
        raise ValueError(
            f"cell {col},{row} has {len(paras)} paragraph(s); --match-style index {n} out of range"
        )
    sib = inner[paras[n][0]:paras[n][1]]
    pm = re.search(r'paraPrIDRef="(\d+)"', sib)
    cm = re.search(r'charPrIDRef="(\d+)"', sib)
    para_pr = pm.group(1) if pm else "0"
    char_pr = cm.group(1) if cm else "0"
    return _append_para_cell(xml, table_id, col, row, para_pr, char_pr, text)


_CHECK_EMPTY = "[  ]"
_CHECK_DONE = "[√]"
_CHECK_RE = re.compile(r"\[ {2}\]|\[√\]")


def _toggle_check_cell(
    xml: str, table_id: str, col: int, row: int, label: str,
) -> tuple[str, list[str]]:
    """Toggle the checkbox glyph belonging to a label inside one cell.

    KR government forms pack several boxes in one line — "[  ] 승인  [  ] 불가
    [  ] 조건부" — so a plain text replace of "[  ] " is ambiguous. The box toggled
    is the nearest one *preceding* the label, flipping [  ] <-> [√] and leaving
    every other box untouched. Matching is done on the visible <hp:t> text only
    (so an attribute like paraPrIDRef="10" can't be mistaken for the label "10")
    and is confined to the label's own direct paragraph (so a box in a different
    paragraph is never toggled). Box and label may live in separate runs.
    """
    ti, tend, tbl, cs, ce, tc, in_s, in_e = _locate_cell_sublist(xml, table_id, col, row)
    inner = tc[in_s:in_e]
    target = None
    for ps, pe in _direct_paras(inner):
        segs = _hp_t_spans(inner[ps:pe])
        concat = "".join(t for _, _, t in segs)
        if label in concat:
            target = (ps, pe, segs, concat)
            break
    if target is None:
        raise ValueError(f"toggle-check: label {label!r} not found in cell {int(col)},{int(row)}")
    ps, pe, segs, concat = target
    li = concat.find(label)
    before = [m for m in _CHECK_RE.finditer(concat) if m.end() <= li]
    if not before:
        raise ValueError(
            f"toggle-check: no checkbox precedes label {label!r} in cell {int(col)},{int(row)}")
    box = before[-1]
    new_tok = _CHECK_DONE if box.group() == _CHECK_EMPTY else _CHECK_EMPTY
    raw_s = _concat_to_raw(segs, box.start())
    raw_e = _concat_to_raw(segs, box.end())
    para = inner[ps:pe]
    new_para = para[:raw_s] + new_tok + para[raw_e:]
    new_inner = inner[:ps] + new_para + inner[pe:]
    new_inner, _ = strip_linesegarray(new_inner)
    new_xml = _splice_cell_inner(xml, ti, tend, tbl, cs, ce, tc, in_s, in_e, new_inner)
    state = "checked" if new_tok == _CHECK_DONE else "cleared"
    return new_xml, [f"cell {int(col)},{int(row)}: {label!r} {state}"]


def _read_cell_style(tc: str) -> tuple[str, str]:
    """Returns (paraPrIDRef, charPrIDRef) from first run in the cell's direct subList."""
    sl = _direct_sublist(tc)
    if sl is None:
        return "0", "0"
    content = tc[sl[0]:sl[1]]
    para_m = re.search(r'paraPrIDRef="(\d+)"', content)
    char_m = re.search(r'charPrIDRef="(\d+)"', content)
    return (para_m.group(1) if para_m else "0"), (char_m.group(1) if char_m else "0")


def _replace_cell_preserve_style(
    xml: str, table_id: str, col: int, row: int,
    text: str, charpr_override: str | None, heights: dict[str, int],
) -> tuple[str, list[str]]:
    span = find_table(xml, table_id)
    if span is None:
        raise ValueError(f"table id={table_id} not found")
    ti, tend = span
    tbl = xml[ti:tend]
    tc = None
    for cs, ce in top_cells(tbl):
        if _own_cell_addr(tbl[cs:ce]) == (col, row):
            tc = tbl[cs:ce]
            break
    if tc is None:
        raise ValueError(f"cell colAddr={int(col)} rowAddr={int(row)} not found")
    para_pr, char_pr = _read_cell_style(tc)
    if charpr_override is not None:
        char_pr = charpr_override
    info: list[str] = []
    height = heights.get(char_pr, 0)
    if height > 0 and charpr_pt(height) < MIN_READABLE_PT:
        warn = f"WARN: cell({col},{row}) charPr={char_pr} height={height}({charpr_pt(height):g}pt) — 가독 불가 크기"
        info.append(warn)
    content = _build_para_runs(para_pr, [(char_pr, text)])
    new_xml, replace_info = _replace_cell(xml, table_id, col, row, content)
    info.extend(replace_info)
    return new_xml, info


def _dump_style_map(tbl_xml: str, table_id: str, heights: dict[str, int]) -> None:
    rows: dict[int, list[tuple[int, str, str, float]]] = {}
    for cs, ce in top_cells(tbl_xml):
        tc = tbl_xml[cs:ce]
        addr = _own_cell_addr(tc)
        if addr is None:
            continue
        col, row = addr
        para_pr, char_pr = _read_cell_style(tc)
        height = heights.get(char_pr, 0)
        pt = charpr_pt(height) if height > 0 else 0.0
        rows.setdefault(row, []).append((col, para_pr, char_pr, pt))
    for row_idx in sorted(rows.keys()):
        cells = sorted(rows[row_idx], key=lambda x: x[0])
        parts = [f"c{col}=p{pp}/c{cp}({pt:g}pt)" for col, pp, cp, pt in cells]
        print(f"row{int(row_idx)}: {' '.join(parts)}")


def cmd_fill(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    is_dir_mode = inp.is_dir()
    xml, target = load_section(inp, args.section)
    heights = load_charpr_heights(inp)
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    all_warns: list[str] = []
    for table_id, cells in data.items():
        for cell_key, text in cells.items():
            try:
                col_s, row_s = cell_key.split(",")
                col, row = int(col_s), int(row_s)
            except ValueError:
                die(f"invalid cell key {cell_key!r} (expected col,row)")
            try:
                xml, info = _replace_cell_preserve_style(xml, table_id, col, row, text, None, heights)
                all_warns.extend(i for i in info if i.startswith("WARN"))
            except ValueError as e:
                die(f"table {table_id} cell {cell_key}: {e}")
    xml, n_ls = LINESEG_RE.subn("", xml)
    if is_dir_mode:
        out_path = save_section(inp, target, xml, None)
        print(f"DONE (in-place): {out_path}")
    else:
        if not args.output and inp.suffix.lower() != ".hwpx":
            die("--output required for non-.hwpx archive input")
        out = args.output or str(inp.with_stem(f"{inp.stem}_filled"))
        if not args.output:
            print(f"Warning: no --output specified, writing to {out}", file=sys.stderr)
        out_path = save_section(inp, target, xml, out)
        print(f"DONE: {out_path}")
    print(f"  linesegarray stripped: {n_ls}")
    if all_warns:
        print(f"WARNINGS ({len(all_warns)}):")
        for w in all_warns:
            print(f"  {w}")


def _list_cells(xml: str, table_id: str) -> None:
    span = find_table(xml, table_id)
    if span is None:
        die(f"table id={table_id} not found")
    tbl = xml[span[0]:span[1]]
    cells = []
    for cs, ce in top_cells(tbl):
        tc = tbl[cs:ce]
        addr = _own_cell_addr(tc)
        txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", tc))
        cells.append((addr, txt))
    cells.sort(key=lambda x: (x[0][1], x[0][0]) if x[0] else (0, 0))
    print(f"table id={table_id}: {len(cells)} cells")
    for addr, txt in cells:
        if addr:
            print(f"  col={addr[0]} row={addr[1]}  {txt[:55]}")


def cmd_replace(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    is_dir_mode = inp.is_dir()
    xml, target = load_section(inp, args.section)
    if args.list:
        _list_cells(xml, args.table_id)
        sys.exit(0)
    if not args.cell or (not is_dir_mode and not args.output):
        die("--cell required (and --output required for .hwpx input)")
    mode_append = args.append_para is not None
    mode_match = args.match_style is not None
    if mode_append and mode_match:
        die("--append-para and --match-style are mutually exclusive")
    if (mode_append or mode_match) and (
        args.preserve_style or args.set_text or args.content_file or args.para or args.run):
        die("--append-para/--match-style cannot combine with other replace modes")
    if mode_append or mode_match:
        pass
    elif args.preserve_style:
        if args.set_text or args.content_file or args.para or args.run:
            die("--preserve-style is mutually exclusive with --set-text/--content-file/--para/--run")
        if args.text is None:
            die("--preserve-style requires --text (use --text \"\" to clear)")
    elif args.set_text:
        if args.content_file or args.para or args.run:
            die("--set-text cannot be combined with --content-file, --para, or --run")
    elif bool(args.content_file) == (bool(args.para) or bool(args.run)):
        die("provide exactly one of --content-file / --para[+--run]")
    try:
        col, row = (int(x) for x in args.cell.split(","))
    except ValueError:
        die(f"--cell expects colAddr,rowAddr (got {args.cell!r})")
    if mode_append:
        para_pr, char_pr, text = args.append_para
        try:
            new_xml, info = _append_para_cell(xml, args.table_id, col, row, para_pr, char_pr, text)
        except ValueError as e:
            die(str(e))
    elif mode_match:
        n_s, text = args.match_style
        try:
            n = int(n_s)
        except ValueError:
            die(f"--match-style N must be an integer (got {n_s!r})")
        try:
            new_xml, info = _append_para_match(xml, args.table_id, col, row, n, text)
        except ValueError as e:
            die(str(e))
    elif args.preserve_style:
        heights = load_charpr_heights(inp)
        try:
            new_xml, info = _replace_cell_preserve_style(
                xml, args.table_id, col, row, args.text or "", args.charpr, heights)
        except ValueError as e:
            die(str(e))
    elif args.set_text:
        old_text, new_text = args.set_text
        try:
            new_xml, info = _set_text_cell(xml, args.table_id, col, row, old_text, new_text)
        except ValueError as e:
            die(str(e))
    else:
        if args.content_file:
            content = Path(args.content_file).read_text(encoding="utf-8")
            content = LINESEG_RE.sub("", content)
            content = re.sub(r">[ \t\r\n]+<", "><", content).strip()
        else:
            if args.run and not args.para:
                die("--run requires at least one --para")
            paras = [(p[0], [(p[1], p[2])]) for p in args.para]
            for char_pr, text in args.run:
                paras[-1][1].append((char_pr, text))
            content = "".join(_build_para_runs(pp, runs) for pp, runs in paras)
        try:
            new_xml, info = _replace_cell(xml, args.table_id, col, row, content)
        except ValueError as e:
            die(str(e))
    new_xml, n_ls = LINESEG_RE.subn("", new_xml)
    out_path = save_section(inp, target, new_xml, args.output)
    print(f"DONE (in-place): {out_path}" if is_dir_mode else f"DONE: {out_path}")
    for line in info:
        print(f"  {line}")
    print(f"  linesegarray stripped: {n_ls}")


def cmd_toggle_check(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    is_dir_mode = inp.is_dir()
    xml, target = load_section(inp, args.section)
    if not is_dir_mode and not args.output:
        die("--output required for .hwpx input")
    try:
        col, row = (int(x) for x in args.cell.split(","))
    except ValueError:
        die(f"--cell expects colAddr,rowAddr (got {args.cell!r})")
    try:
        new_xml, info = _toggle_check_cell(xml, args.table_id, col, row, args.label)
    except ValueError as e:
        die(str(e))
    out_path = save_section(inp, target, new_xml, args.output)
    print(f"DONE (in-place): {out_path}" if is_dir_mode else f"DONE: {out_path}")
    for line in info:
        print(f"  {line}")


# ── delete ────────────────────────────────────────────────────────────────────

TRIPLET_RE = re.compile(
    r'(<hp:cellAddr colAddr="\d+" rowAddr=")(\d+)("/>)'
    r'(<hp:cellSpan colSpan="\d+" rowSpan=")(\d+)("/>)'
    r'(<hp:cellSz width="\d+" height=")(\d+)("/>)'
)


def _row_cells(row: str) -> list[tuple[int, int, int]]:
    return [
        (int(m.group(2)), int(m.group(5)), int(m.group(8)))
        for m in TRIPLET_RE.finditer(row)
    ]


def _delete_rows(xml: str, table_id: str, del_idx: set[int]) -> tuple[str, list[str]]:
    span = find_table(xml, table_id)
    if span is None:
        raise ValueError(f"table id={table_id} not found")
    ti, tend = span
    tbl = xml[ti:tend]
    trs = top_trs(tbl)
    n = len(trs)
    for i in del_idx:
        if i < 0 or i >= n:
            raise ValueError(f"row index {i} out of range (table has {n} rows)")
    del_height: dict[int, int] = {}
    for i in del_idx:
        cells = _row_cells(tbl[trs[i][0]:trs[i][1]])
        if any(rs > 1 for (_ra, rs, _h) in cells):
            raise ValueError(f"row {i} contains a rowSpan>1 cell (anchor row) — unsupported")
        del_height[i] = cells[0][2] if cells else 0
    total_del_h = sum(del_height.values())
    prefix = tbl[:trs[0][0]]
    suffix = tbl[trs[-1][1]:]
    kept = []
    for i, (s, e) in enumerate(trs):
        if i in del_idx:
            continue
        row = tbl[s:e]

        def _fix(m: re.Match, old_i: int = i) -> str:
            ra, rs = int(m.group(2)), int(m.group(5))
            h = int(m.group(8))
            covered = [d for d in del_idx if ra < d <= ra + rs - 1]
            new_rs = rs - len(covered)
            new_h = h - sum(del_height[d] for d in covered)
            return (m.group(1) + str(ra) + m.group(3)
                    + m.group(4) + str(new_rs) + m.group(6)
                    + m.group(7) + str(new_h) + m.group(9))

        row = TRIPLET_RE.sub(_fix, row)
        kept.append(row)
    kept = [_set_row_addr(r, idx) for idx, r in enumerate(kept)]
    new_prefix, nc = re.subn(
        r'(<hp:tbl\b[^>]*\browCnt=")(\d+)(")',
        lambda m: m.group(1) + str(int(m.group(2)) - len(del_idx)) + m.group(3),
        prefix, count=1,
    )
    if nc != 1:
        raise ValueError("rowCnt attribute not found on <hp:tbl>")
    new_prefix, _ = re.subn(
        r'(<hp:sz width="\d+" height=")(\d+)(")',
        lambda m: m.group(1) + str(int(m.group(2)) - total_del_h) + m.group(3),
        new_prefix, count=1,
    )
    new_tbl = new_prefix + "".join(kept) + suffix
    new_xml = xml[:ti] + new_tbl + xml[tend:]
    info = [
        f"deleted rows {sorted(del_idx)} ({len(del_idx)} rows, {total_del_h} HWPUNIT)",
        f"rowCnt {n} -> {n - len(del_idx)}",
    ]
    return new_xml, info


def _list_rows_delete(xml: str, table_id: str) -> None:
    span = find_table(xml, table_id)
    if span is None:
        die(f"table id={table_id} not found")
    tbl = xml[span[0]:span[1]]
    trs = top_trs(tbl)
    print(f"table id={table_id}: {len(trs)} rows")
    for i, (s, e) in enumerate(trs):
        row = tbl[s:e]
        txt = "".join(re.findall(r"<hp:t>(.*?)</hp:t>", row))
        cells = _row_cells(row)
        spans = [rs for (_ra, rs, _h) in cells]
        print(f"  [{i}] cells={len(cells)} rowSpans={spans}  {txt[:60]}")


def cmd_delete(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    is_dir_mode = inp.is_dir()
    xml, target = load_section(inp, args.section)
    if args.list:
        _list_rows_delete(xml, args.table_id)
        sys.exit(0)
    if not args.rows or (not is_dir_mode and not args.output):
        die("--rows required (and --output required for .hwpx input, or use --list)")
    del_idx = {int(x) for x in args.rows.split(",") if x.strip() != ""}
    try:
        new_xml, info = _delete_rows(xml, args.table_id, del_idx)
    except ValueError as e:
        die(str(e))
    new_xml, n_ls = LINESEG_RE.subn("", new_xml)
    out_path = save_section(inp, target, new_xml, args.output)
    print(f"DONE (in-place): {out_path}" if is_dir_mode else f"DONE: {out_path}")
    for line in info:
        print(f"  {line}")
    print(f"  linesegarray stripped: {n_ls}")


# ── calc-widths ───────────────────────────────────────────────────────────────

def _calc_widths(ratios: list[int], body_width: int) -> list[int]:
    total = sum(ratios)
    widths = [body_width * r // total for r in ratios]
    remainder = body_width - sum(widths)
    for i in range(remainder):
        widths[i] += 1
    return widths


def _parse_width_spec(spec: str) -> list[int]:
    if ":" in spec:
        return [int(p) for p in spec.split(":")]
    n = int(spec)
    if n <= 0:
        raise ValueError("Column count must be positive")
    return [1] * n


def cmd_calc_widths(args: argparse.Namespace) -> None:
    if args.verify:
        total = sum(args.verify)
        if total == args.body:
            print(f"OK: sum={total} == body width {args.body}")
        else:
            diff = total - args.body
            die(f"sum={total}, body={args.body}, diff={diff:+d}")
        return
    try:
        ratios = _parse_width_spec(args.spec)
    except ValueError as e:
        die(str(e))
    widths = _calc_widths(ratios, args.body)
    print(" ".join(str(w) for w in widths))
    print(f"# {len(widths)} columns, sum={sum(widths)}, body={args.body}", file=sys.stderr)


# ── strip-lineseg ─────────────────────────────────────────────────────────────

def _strip_hwpx(input_path: Path, output_path: Path) -> int:
    total_removed = 0
    entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(input_path, "r") as zin:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if SECTION_RE.match(info.filename):
                xml_str, count = strip_linesegarray(data.decode("utf-8"))
                data = xml_str.encode("utf-8")
                if count:
                    print(f"  {info.filename}: removed {count} linesegarray")
                    total_removed += count
            entries.append((info, data))
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in entries:
            ct = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zout.writestr(info.filename, data, compress_type=ct)
    return total_removed


def cmd_strip_lineseg(args: argparse.Namespace) -> None:
    import shutil
    input_path = Path(args.input)
    if not input_path.is_file():
        die(f"File not found: {args.input}")
    if args.inplace and args.output:
        die("--inplace and --output are mutually exclusive")
    tmp = input_path.with_suffix(".tmp")
    if args.inplace:
        output_path = tmp
    elif args.output:
        output_path = Path(args.output)
    else:
        die("specify --output or --inplace")
    is_hwpx = input_path.suffix.lower() == ".hwpx"
    if is_hwpx:
        count = _strip_hwpx(input_path, output_path)
    else:
        data, count = strip_linesegarray(input_path.read_bytes().decode("utf-8"))
        output_path.write_bytes(data.encode("utf-8"))
    if args.inplace:
        shutil.move(str(tmp), str(input_path))
        output_path = input_path
    if count:
        print(f"STRIPPED: {output_path} (removed {count} linesegarray elements)")
    else:
        print(f"CLEAN: no linesegarray found in {input_path}")


# ── self-test ─────────────────────────────────────────────────────────────────

_FIXTURE = '''\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentFile xmlns:hpf="urn:schemas:hwpml:2.0:hpf" xmlns:hp="urn:schemas:hwpml:2.0:body-text">
  <hp:BodyText>
    <hp:SectionDef SubListIDRef="0">
      <hp:SecPr><hp:ColumnDef Type="0" Count="1" Gap="0"/></hp:SecPr>
      <hp:SubList id="100">
        <hp:tbl id="1" tableIDRef="1" cellIDRef="0" borderFillIDRef="1" width="8000" height="2000">
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:subList id="101">
                <hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000" baseline="800" spacing="0" horzpos="0" horzsize="8000" flags="0"/></hp:linesegarray>
                <hp:p id="200" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>위원</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:SubList>
    </hp:SectionDef>
  </hp:BodyText>
</hpf:HWPFDocumentFile>'''

_FIXTURE_SPLIT = '''\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentFile xmlns:hpf="urn:schemas:hwpml:2.0:hpf" xmlns:hp="urn:schemas:hwpml:2.0:body-text">
  <hp:BodyText>
    <hp:SectionDef SubListIDRef="0">
      <hp:SecPr><hp:ColumnDef Type="0" Count="1" Gap="0"/></hp:SecPr>
      <hp:SubList id="100">
        <hp:tbl id="1" tableIDRef="1" cellIDRef="0" borderFillIDRef="1" width="8000" height="2000">
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:subList id="101">
                <hp:p id="200" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>위</hp:t></hp:run><hp:run charPrIDRef="3"><hp:t>원</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:SubList>
    </hp:SectionDef>
  </hp:BodyText>
</hpf:HWPFDocumentFile>'''

_FIXTURE_CHECK = '''\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentFile xmlns:hpf="urn:schemas:hwpml:2.0:hpf" xmlns:hp="urn:schemas:hwpml:2.0:body-text">
  <hp:BodyText>
    <hp:SectionDef SubListIDRef="0">
      <hp:SecPr><hp:ColumnDef Type="0" Count="1" Gap="0"/></hp:SecPr>
      <hp:SubList id="100">
        <hp:tbl id="1" tableIDRef="1" cellIDRef="0" borderFillIDRef="1" width="8000" height="2000">
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:subList id="101">
                <hp:p id="200" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>[  ] 승인   [  ] 불가   [  ] 조건부</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:SubList>
    </hp:SectionDef>
  </hp:BodyText>
</hpf:HWPFDocumentFile>'''

# cell 0,0: one DIRECT paragraph (charPr 5) + a nested table whose cell holds a
# paragraph (charPr 9). match-style must see only the 1 direct paragraph.
_FIXTURE_NESTED = '''\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentFile xmlns:hpf="urn:schemas:hwpml:2.0:hpf" xmlns:hp="urn:schemas:hwpml:2.0:body-text">
  <hp:BodyText>
    <hp:SectionDef SubListIDRef="0">
      <hp:SecPr><hp:ColumnDef Type="0" Count="1" Gap="0"/></hp:SecPr>
      <hp:SubList id="100">
        <hp:tbl id="1" tableIDRef="1" cellIDRef="0" borderFillIDRef="1" width="8000" height="2000">
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:subList id="101">
                <hp:p id="200" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>직접</hp:t></hp:run></hp:p>
                <hp:tbl id="2" tableIDRef="2" cellIDRef="0" borderFillIDRef="1" width="4000" height="1000">
                  <hp:tr>
                    <hp:tc>
                      <hp:cellAddr colAddr="0" rowAddr="0"/>
                      <hp:subList id="102">
                        <hp:p id="300" paraPrIDRef="20" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="9"><hp:t>중첩</hp:t></hp:run></hp:p>
                      </hp:subList>
                    </hp:tc>
                  </hp:tr>
                </hp:tbl>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:SubList>
    </hp:SectionDef>
  </hp:BodyText>
</hpf:HWPFDocumentFile>'''

# checkbox + label split across separate runs (real KR forms do this)
_FIXTURE_CHECK_MULTI = '''\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentFile xmlns:hpf="urn:schemas:hwpml:2.0:hpf" xmlns:hp="urn:schemas:hwpml:2.0:body-text">
  <hp:BodyText>
    <hp:SectionDef SubListIDRef="0">
      <hp:SecPr><hp:ColumnDef Type="0" Count="1" Gap="0"/></hp:SecPr>
      <hp:SubList id="100">
        <hp:tbl id="1" tableIDRef="1" cellIDRef="0" borderFillIDRef="1" width="8000" height="2000">
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:subList id="101">
                <hp:p id="200" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>[  ] </hp:t></hp:run><hp:run charPrIDRef="6"><hp:t>승인</hp:t></hp:run><hp:run charPrIDRef="5"><hp:t>   [  ] </hp:t></hp:run><hp:run charPrIDRef="6"><hp:t>불가</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:SubList>
    </hp:SectionDef>
  </hp:BodyText>
</hpf:HWPFDocumentFile>'''

# two direct paragraphs: para0 has a box, para1 (with label 승인) has none
_FIXTURE_CHECK_2PARA = '''\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentFile xmlns:hpf="urn:schemas:hwpml:2.0:hpf" xmlns:hp="urn:schemas:hwpml:2.0:body-text">
  <hp:BodyText>
    <hp:SectionDef SubListIDRef="0">
      <hp:SecPr><hp:ColumnDef Type="0" Count="1" Gap="0"/></hp:SecPr>
      <hp:SubList id="100">
        <hp:tbl id="1" tableIDRef="1" cellIDRef="0" borderFillIDRef="1" width="8000" height="2000">
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:subList id="101">
                <hp:p id="200" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>[  ] 기타</hp:t></hp:run></hp:p>
                <hp:p id="201" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>승인 여부</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:SubList>
    </hp:SectionDef>
  </hp:BodyText>
</hpf:HWPFDocumentFile>'''


# two-row table (rowCnt="2") used to test the insert/delete dir-mode CLI path
_FIXTURE_DIR_MODE = '''\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentFile xmlns:hpf="urn:schemas:hwpml:2.0:hpf" xmlns:hp="urn:schemas:hwpml:2.0:body-text">
  <hp:BodyText>
    <hp:SectionDef SubListIDRef="0">
      <hp:SecPr><hp:ColumnDef Type="0" Count="1" Gap="0"/></hp:SecPr>
      <hp:SubList id="100">
        <hp:tbl id="1" tableIDRef="1" cellIDRef="0" borderFillIDRef="1" rowCnt="2" colCnt="1">
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:subList id="101">
                <hp:p id="200" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>행0</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="1"/>
              <hp:subList id="102">
                <hp:p id="201" paraPrIDRef="10" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="5"><hp:t>행1</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:SubList>
    </hp:SectionDef>
  </hp:BodyText>
</hpf:HWPFDocumentFile>'''


def _run_tests() -> None:
    failures = []

    # AC-1a: --set-text preserves charPrIDRef="5"
    try:
        result, _ = _set_text_cell(_FIXTURE, "1", 0, 0, "위원", "새위원")
        if 'charPrIDRef="5"' not in result:
            failures.append("AC-1a FAIL: charPrIDRef='5' not preserved after --set-text")
        else:
            print("AC-1a PASS: charPr preserved")
    except Exception as e:
        failures.append(f"AC-1a FAIL: {e}")

    # AC-1b: linesegarray stripped after --set-text
    try:
        result, _ = _set_text_cell(_FIXTURE, "1", 0, 0, "위원", "새위원")
        if "<hp:linesegarray" in result:
            failures.append("AC-1b FAIL: linesegarray still present after --set-text")
        else:
            print("AC-1b PASS: linesegarray removed")
    except Exception as e:
        failures.append(f"AC-1b FAIL: {e}")

    # AC-1c: --set-text OLD "" clears text, preserves charPr
    try:
        result, _ = _set_text_cell(_FIXTURE, "1", 0, 0, "위원", "")
        if 'charPrIDRef="5"' not in result:
            failures.append("AC-1c FAIL: charPrIDRef='5' not preserved after clearing text")
        elif "<hp:t></hp:t>" not in result and "<hp:t/>" not in result:
            failures.append(f"AC-1c FAIL: expected empty hp:t after clear, result: {result[result.find('<hp:t'):result.find('<hp:t') + 40]!r}")
        else:
            print("AC-1c PASS: empty text with charPr preserved")
    except Exception as e:
        failures.append(f"AC-1c FAIL: {e}")

    # AC-1d: fragmented text (split across runs) raises ValueError
    try:
        _set_text_cell(_FIXTURE_SPLIT, "1", 0, 0, "위원", "새위원")
        failures.append("AC-1d FAIL: expected ValueError for split run, none raised")
    except ValueError as e:
        msg = str(e)
        if "contiguously" in msg or "split across runs" in msg:
            print("AC-1d PASS: ValueError with correct message")
        else:
            failures.append(f"AC-1d FAIL: ValueError raised but message lacks expected keyword: {msg}")
    except Exception as e:
        failures.append(f"AC-1d FAIL: unexpected exception: {e}")

    # Regression: _replace_cell (--para path) still works
    try:
        content = _build_para_runs("10", [("5", "위원장")])
        result, info = _replace_cell(_FIXTURE, "1", 0, 0, content)
        if "위원장" not in result:
            failures.append("Regression FAIL: _replace_cell did not insert expected text")
        else:
            print("Regression PASS: _replace_cell --para path intact")
    except Exception as e:
        failures.append(f"Regression FAIL: {e}")

    # AC-2a: preserve-style reuses charPr/paraPr from existing cell
    try:
        result, info = _replace_cell_preserve_style(_FIXTURE, "1", 0, 0, "새글", None, {})
        if 'charPrIDRef="5"' not in result:
            failures.append("AC-2a FAIL: preserve-style did not keep charPrIDRef=5")
        elif 'paraPrIDRef="10"' not in result:
            failures.append("AC-2b FAIL: preserve-style did not keep paraPrIDRef=10")
        else:
            print("AC-2a PASS: preserve-style reuses existing charPr/paraPr")
    except Exception as e:
        failures.append(f"AC-2a FAIL: {e}")

    # AC-2c: 5pt WARN for 3pt charPr
    try:
        heights_3pt = {"5": 300}
        result, info = _replace_cell_preserve_style(_FIXTURE, "1", 0, 0, "새글", None, heights_3pt)
        warns = [i for i in info if "WARN" in i]
        if not warns:
            failures.append(f"AC-2c FAIL: expected WARN for 3pt charPr, info={info!r}")
        else:
            print("AC-2c PASS: 3pt charPr triggers WARN")
    except Exception as e:
        failures.append(f"AC-2c FAIL: {e}")

    # AC-2d: --charpr override
    try:
        result, info = _replace_cell_preserve_style(_FIXTURE, "1", 0, 0, "새글", "99", {})
        if 'charPrIDRef="99"' not in result:
            failures.append("AC-2d FAIL: --charpr override did not apply")
        else:
            print("AC-2d PASS: --charpr override applied")
    except Exception as e:
        failures.append(f"AC-2d FAIL: {e}")

    # AC-3: style-map format
    try:
        import io as _io
        _buf = _io.StringIO()
        _old = sys.stdout
        sys.stdout = _buf
        try:
            _span = find_table(_FIXTURE, "1")
            assert _span is not None, "AC-3: table '1' not found in fixture"
            _dump_style_map(_FIXTURE[_span[0]:_span[1]], "1", {})
        finally:
            sys.stdout = _old
        _out = _buf.getvalue()
        if not _out.startswith("row0:"):
            failures.append(f"AC-3 FAIL: style-map does not start with 'row0:', got {_out[:60]!r}")
        elif "c0=p10/c5" not in _out:
            failures.append(f"AC-3 FAIL: style-map missing c0=p10/c5, got {_out[:80]!r}")
        else:
            print("AC-3 PASS: style-map format correct")
    except Exception as e:
        failures.append(f"AC-3 FAIL: {e}")

    # AC-4: fill-style multi-cell
    try:
        _data = {"1": {"0,0": "채움"}}
        _xml = _FIXTURE
        for _tid, _cells in _data.items():
            for _ck, _txt in _cells.items():
                _c, _r = (int(x) for x in _ck.split(","))
                _xml, _info = _replace_cell_preserve_style(_xml, _tid, _c, _r, _txt, None, {})
        if "채움" not in _xml:
            failures.append("AC-4 FAIL: fill did not insert text")
        elif 'charPrIDRef="5"' not in _xml:
            failures.append("AC-4 FAIL: fill did not preserve charPr")
        else:
            print("AC-4 PASS: fill inserts text with style preserved")
    except Exception as e:
        failures.append(f"AC-4 FAIL: {e}")

    # AC-AP-1: append-para keeps existing paragraph and adds a new one
    try:
        result, info = _append_para_cell(_FIXTURE, "1", 0, 0, "10", "7", "신규")
        if "위원" not in result:
            failures.append("AC-AP-1 FAIL: existing paragraph '위원' lost on append")
        elif "신규" not in result:
            failures.append("AC-AP-1 FAIL: appended text '신규' missing")
        elif result.count("<hp:p ") < 2:
            failures.append(f"AC-AP-1 FAIL: expected >=2 paragraphs, got {int(result.count('<hp:p '))}")
        elif 'charPrIDRef="5"' not in result or 'charPrIDRef="7"' not in result:
            failures.append("AC-AP-1 FAIL: charPr 5 (old) and 7 (new) not both present")
        else:
            print("AC-AP-1 PASS: append-para preserves siblings, adds styled para")
    except Exception as e:
        failures.append(f"AC-AP-1 FAIL: {e}")

    # AC-AP-2: append-para strips a stray linesegarray in the cell
    try:
        result, info = _append_para_cell(_FIXTURE, "1", 0, 0, "10", "7", "신규")
        if "<hp:linesegarray" in result:
            failures.append("AC-AP-2 FAIL: linesegarray not stripped after append")
        else:
            print("AC-AP-2 PASS: linesegarray removed on append")
    except Exception as e:
        failures.append(f"AC-AP-2 FAIL: {e}")

    # AC-AP-3: match-style inherits paraPr/charPr from the Nth sibling paragraph
    try:
        result, info = _append_para_match(_FIXTURE, "1", 0, 0, 0, "상속")
        if "상속" not in result:
            failures.append("AC-AP-3 FAIL: appended text '상속' missing")
        elif result.count('paraPrIDRef="10"') < 2:
            failures.append(f"AC-AP-3 FAIL: paraPr 10 not inherited (count={result.count('paraPrIDRef=\"10\"')})")
        elif result.count('charPrIDRef="5"') < 2:
            failures.append(f"AC-AP-3 FAIL: charPr 5 not inherited (count={result.count('charPrIDRef=\"5\"')})")
        else:
            print("AC-AP-3 PASS: match-style inherits sibling para style")
    except Exception as e:
        failures.append(f"AC-AP-3 FAIL: {e}")

    # AC-TC-1: toggle-check flips the box belonging to the named label only
    try:
        result, info = _toggle_check_cell(_FIXTURE_CHECK, "1", 0, 0, "승인")
        if "[√] 승인" not in result:
            failures.append(f"AC-TC-1 FAIL: 승인 box not checked, got {result[result.find('['):result.find('[') + 30]!r}")
        elif "[  ] 불가" not in result or "[  ] 조건부" not in result:
            failures.append("AC-TC-1 FAIL: other boxes (불가/조건부) were altered")
        else:
            print("AC-TC-1 PASS: toggle-check checks only the matched label")
    except Exception as e:
        failures.append(f"AC-TC-1 FAIL: {e}")

    # AC-TC-2: toggle-check is reversible (checked -> empty)
    try:
        checked, _ = _toggle_check_cell(_FIXTURE_CHECK, "1", 0, 0, "승인")
        back, _ = _toggle_check_cell(checked, "1", 0, 0, "승인")
        if "[  ] 승인" not in back:
            failures.append("AC-TC-2 FAIL: second toggle did not restore empty box")
        else:
            print("AC-TC-2 PASS: toggle-check reverses an already-checked box")
    except Exception as e:
        failures.append(f"AC-TC-2 FAIL: {e}")

    # AC-TC-3: unknown label raises ValueError
    try:
        _toggle_check_cell(_FIXTURE_CHECK, "1", 0, 0, "없는라벨")
        failures.append("AC-TC-3 FAIL: expected ValueError for missing label, none raised")
    except ValueError:
        print("AC-TC-3 PASS: missing label raises ValueError")
    except Exception as e:
        failures.append(f"AC-TC-3 FAIL: unexpected exception: {e}")

    # AC-AP-4: match-style counts only DIRECT paragraphs (ignores nested table)
    try:
        # cell has 1 direct paragraph; index 1 would only be valid if a nested-table
        # paragraph were wrongly counted, so it must raise.
        _append_para_match(_FIXTURE_NESTED, "1", 0, 0, 1, "x")
        failures.append("AC-AP-4 FAIL: nested-table paragraph counted (index 1 accepted)")
    except ValueError:
        # and index 0 must inherit the DIRECT para's charPr=5, not nested charPr=9
        try:
            result, _ = _append_para_match(_FIXTURE_NESTED, "1", 0, 0, 0, "상속")
            if "상속" not in result:
                failures.append("AC-AP-4 FAIL: appended text missing")
            elif result.count('charPrIDRef="9"') != 1:
                failures.append("AC-AP-4 FAIL: nested charPr=9 was touched")
            elif result.count('charPrIDRef="5"') < 2:
                failures.append("AC-AP-4 FAIL: direct charPr=5 not inherited")
            else:
                print("AC-AP-4 PASS: match-style ignores nested-table paragraphs")
        except Exception as e:
            failures.append(f"AC-AP-4 FAIL: index 0 path: {e}")
    except Exception as e:
        failures.append(f"AC-AP-4 FAIL: unexpected exception: {e}")

    # AC-TC-4: toggle-check works when box and label are in separate runs
    try:
        result, _ = _toggle_check_cell(_FIXTURE_CHECK_MULTI, "1", 0, 0, "승인")
        if result.count("[√]") != 1:
            failures.append(f"AC-TC-4 FAIL: expected exactly 1 checked box, got {int(result.count('[√]'))}")
        elif result.count("[  ]") != 1:
            failures.append("AC-TC-4 FAIL: 불가 box should stay empty (one [  ] expected)")
        else:
            print("AC-TC-4 PASS: toggle-check handles box/label split across runs")
    except Exception as e:
        failures.append(f"AC-TC-4 FAIL: {e}")

    # AC-TC-5: toggle-check stays inside the label's own paragraph
    try:
        # label 승인 lives in para1 which has NO box; the box in para0 must NOT toggle.
        _toggle_check_cell(_FIXTURE_CHECK_2PARA, "1", 0, 0, "승인")
        failures.append("AC-TC-5 FAIL: toggled a box from a different paragraph")
    except ValueError:
        print("AC-TC-5 PASS: toggle-check confined to the label's paragraph")
    except Exception as e:
        failures.append(f"AC-TC-5 FAIL: unexpected exception: {e}")

    # AC-DIR-1: cmd_insert dir-mode writes the new row into the unpacked
    # section file in place, with no --output required.
    try:
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as _td:
            _td_path = Path(_td)
            (_td_path / "Contents").mkdir()
            _section_file = _td_path / "Contents" / "section0.xml"
            _section_file.write_text(_FIXTURE_DIR_MODE, encoding="utf-8")
            _row_file = _td_path / "row.xml"
            _row_file.write_text(
                '<hp:tr><hp:tc><hp:cellAddr colAddr="0" rowAddr="1"/>'
                '<hp:subList id="103"><hp:p id="0" paraPrIDRef="10" styleIDRef="0" '
                'pageBreak="0" columnBreak="0" merged="0">'
                '<hp:run charPrIDRef="5"><hp:t>새행</hp:t></hp:run></hp:p></hp:subList>'
                "</hp:tc></hp:tr>",
                encoding="utf-8",
            )
            _ns = argparse.Namespace(
                input=str(_td_path), table_id="1", at=1, after_row=None,
                row_file=str(_row_file), grow=[], section=0, list=False, output=None,
            )
            cmd_insert(_ns)
            _result = _section_file.read_text(encoding="utf-8")
        if "새행" not in _result:
            failures.append("AC-DIR-1 FAIL: cmd_insert dir-mode did not write new row into section file")
        elif 'rowCnt="3"' not in _result:
            failures.append("AC-DIR-1 FAIL: rowCnt not updated after dir-mode insert")
        else:
            print("AC-DIR-1 PASS: cmd_insert dir-mode writes new row in place (no --output)")
    except SystemExit as e:
        failures.append(f"AC-DIR-1 FAIL: cmd_insert exited unexpectedly (code {e.code!r})")
    except Exception as e:
        failures.append(f"AC-DIR-1 FAIL: {e}")

    # AC-DIR-2: cmd_delete dir-mode writes the row removal into the unpacked
    # section file in place, with no --output required.
    try:
        with _tempfile.TemporaryDirectory() as _td:
            _td_path = Path(_td)
            (_td_path / "Contents").mkdir()
            _section_file = _td_path / "Contents" / "section0.xml"
            _section_file.write_text(_FIXTURE_DIR_MODE, encoding="utf-8")
            _ns = argparse.Namespace(
                input=str(_td_path), table_id="1", rows="1", section=0, list=False, output=None,
            )
            cmd_delete(_ns)
            _result = _section_file.read_text(encoding="utf-8")
        if "행1" in _result:
            failures.append("AC-DIR-2 FAIL: cmd_delete dir-mode did not remove deleted row from section file")
        elif "행0" not in _result:
            failures.append("AC-DIR-2 FAIL: cmd_delete dir-mode removed the wrong row")
        elif 'rowCnt="1"' not in _result:
            failures.append("AC-DIR-2 FAIL: rowCnt not updated after dir-mode delete")
        else:
            print("AC-DIR-2 PASS: cmd_delete dir-mode removes row in place (no --output)")
    except SystemExit as e:
        failures.append(f"AC-DIR-2 FAIL: cmd_delete exited unexpectedly (code {e.code!r})")
    except Exception as e:
        failures.append(f"AC-DIR-2 FAIL: {e}")

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All tests passed")
    sys.exit(0)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    configure_io()
    if sys.argv[1:] == ["--test"]:
        _run_tests()
        return
    parser = argparse.ArgumentParser(description="HWPX table operations and utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # dump
    p_dump = sub.add_parser("dump", help="Dump table cell map (rowAddr, colAddr, span, text)")
    p_dump.add_argument("input", help="Input .hwpx file or unpacked directory")
    p_dump.add_argument("--table-id", help="Dump specific table by id")
    p_dump.add_argument("--contains", action="append", default=[],
                        help="Dump table(s) containing text (repeatable, AND)")
    p_dump.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_dump.add_argument("--cell", help="Verbose dump of specific cell as colAddr,rowAddr (requires --table-id)")
    p_dump.add_argument("--style-map", action="store_true", help="Show paraPr/charPr/pt per cell grid (requires --table-id)")

    # locate
    p_loc = sub.add_parser("locate", help="Find HWPX elements by contained text (nesting-aware)")
    p_loc.add_argument("input", help="Input .hwpx file or unpacked directory")
    p_loc.add_argument("--tag", required=True, help="Element tag, e.g. hp:tbl, hp:tr, hp:p, hp:tc")
    p_loc.add_argument("--contains", action="append", default=[],
                       help="Required substring (repeatable; AND semantics)")
    p_loc.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_loc.add_argument("--depth", type=int, default=None, help="Only report matches at this nesting depth")
    p_loc.add_argument("--extract-dir", help="Write each match to <dir>/match_<i>.xml")
    p_loc.add_argument("--pretty", action="store_true", help="Format extracted XML (one tag per line)")

    # insert
    p_ins = sub.add_parser("insert", help="Insert a table row, fixing rowAddr/rowCnt/rowSpan")
    p_ins.add_argument("input", help="Input .hwpx file or unpacked directory")
    p_ins.add_argument("--table-id", required=True, help="HWP table id attribute")
    p_ins.add_argument("--at", type=int, help="Final 0-based index of the new row")
    p_ins.add_argument("--after-row", type=int, help="Insert after this 0-based row index (= --at N+1)")
    p_ins.add_argument("--row-file", help="File with the <hp:tr>...</hp:tr> to insert")
    p_ins.add_argument("--grow", action="append", default=[],
                       help="rowAddr,colAddr of anchor cell to extend rowSpan +1 (repeatable)")
    p_ins.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_ins.add_argument("--list", action="store_true", help="List rows and exit")
    p_ins.add_argument("--output", "-o", help="Output .hwpx file")

    # replace
    p_rep = sub.add_parser("replace", help="Replace a table cell's paragraph content")
    p_rep.add_argument("input", help="Input .hwpx file or unpacked directory")
    p_rep.add_argument("--table-id", required=True, help="HWP table id attribute")
    p_rep.add_argument("--cell", help="Target cell as colAddr,rowAddr")
    p_rep.add_argument("--preserve-style", action="store_true",
                       help="Replace cell text keeping existing charPr/paraPr (mutually exclusive with --set-text/--content-file/--para/--run)")
    p_rep.add_argument("--text", help="Text to write (for --preserve-style)")
    p_rep.add_argument("--charpr", help="Override charPrIDRef (for --preserve-style)")
    p_rep.add_argument("--set-text", nargs=2, default=None, metavar=("OLD", "NEW"),
                       help="Replace text OLD->NEW preserving charPr/paraPr structure (mutually exclusive with --content-file/--para/--run)")
    p_rep.add_argument("--content-file", help="File with raw <hp:p>...</hp:p> XML")
    p_rep.add_argument("--para", action="append", nargs=3, default=[],
                       metavar=("PARAPR", "CHARPR", "TEXT"), help="One text paragraph (repeatable)")
    p_rep.add_argument("--run", action="append", nargs=2, default=[],
                       metavar=("CHARPR", "TEXT"), help="Extra run appended to last --para (repeatable)")
    p_rep.add_argument("--append-para", nargs=3, default=None, metavar=("PARAPR", "CHARPR", "TEXT"),
                       help="Append one paragraph keeping existing cell paragraphs (公文 'add a line below')")
    p_rep.add_argument("--match-style", nargs=2, default=None, metavar=("N", "TEXT"),
                       help="Append a paragraph inheriting paraPr/charPr from the cell's Nth (0-based) paragraph")
    p_rep.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_rep.add_argument("--list", action="store_true", help="List table cells and exit")
    p_rep.add_argument("--output", "-o", help="Output .hwpx file")

    # delete
    p_del = sub.add_parser("delete", help="Delete table rows, fixing rowAddr/rowCnt/rowSpan")
    p_del.add_argument("input", help="Input .hwpx file or unpacked directory")
    p_del.add_argument("--table-id", required=True, help="HWP table id attribute")
    p_del.add_argument("--rows", help="Comma-separated 0-based row indices to delete")
    p_del.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_del.add_argument("--list", action="store_true", help="List rows and exit")
    p_del.add_argument("--output", "-o", help="Output .hwpx file")

    # fill
    p_fill = sub.add_parser("fill", help="Bulk-fill cells from JSON data preserving style")
    p_fill.add_argument("input", help="Input .hwpx file or unpacked directory")
    p_fill.add_argument("--data", required=True, help='JSON file: {"table_id": {"col,row": "text"}}')
    p_fill.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_fill.add_argument("--output", "-o", help="Output .hwpx file (required for .hwpx input)")

    # toggle-check
    p_tc = sub.add_parser("toggle-check", help="Toggle a checkbox [  ] <-> [√] next to a label in a cell")
    p_tc.add_argument("input", help="Input .hwpx file or unpacked directory")
    p_tc.add_argument("--table-id", required=True, help="HWP table id attribute")
    p_tc.add_argument("--cell", required=True, help="Target cell as colAddr,rowAddr")
    p_tc.add_argument("--label", required=True, help="Label text whose preceding checkbox is toggled (e.g. 승인)")
    p_tc.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_tc.add_argument("--output", "-o", help="Output .hwpx file (required for .hwpx input)")

    # calc-widths
    p_cw = sub.add_parser("calc-widths", help="Calculate table column widths (HWPUNIT) summing to body width")
    cw_group = p_cw.add_mutually_exclusive_group(required=True)
    cw_group.add_argument("spec", nargs="?", help="Column count (e.g. 3) or ratio spec (e.g. 1:4)")
    cw_group.add_argument("--verify", nargs="+", type=int, metavar="WIDTH",
                          help="Verify that provided widths sum to body width")
    p_cw.add_argument("--body", type=int, default=A4_BODY_WIDTH,
                      help=f"Body width in HWPUNIT (default: {A4_BODY_WIDTH} = A4 150mm)")

    # strip-lineseg
    p_sl = sub.add_parser("strip-lineseg", help="Strip stale hp:linesegarray elements from HWPX or section XML")
    p_sl.add_argument("input", help="Input .hwpx or section XML file")
    p_sl.add_argument("--output", "-o", help="Output file path")
    p_sl.add_argument("--inplace", action="store_true", help="Modify input file in-place")

    args = parser.parse_args()

    if args.cmd == "dump":
        cmd_dump(args)
    elif args.cmd == "locate":
        cmd_locate(args)
    elif args.cmd == "insert":
        cmd_insert(args)
    elif args.cmd == "replace":
        cmd_replace(args)
    elif args.cmd == "fill":
        cmd_fill(args)
    elif args.cmd == "delete":
        cmd_delete(args)
    elif args.cmd == "toggle-check":
        cmd_toggle_check(args)
    elif args.cmd == "calc-widths":
        cmd_calc_widths(args)
    elif args.cmd == "strip-lineseg":
        cmd_strip_lineseg(args)


if __name__ == "__main__":
    main()
