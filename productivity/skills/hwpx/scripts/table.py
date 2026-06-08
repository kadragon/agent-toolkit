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
    python table.py delete doc.hwpx --table-id ID --rows 2,3 -o out.hwpx
    python table.py calc-widths 3
    python table.py calc-widths 1:4
    python table.py strip-lineseg input.hwpx --output clean.hwpx
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import argparse
import re
import sys
import zipfile
from pathlib import Path

from _common import (
    LINESEG_RE,
    PARA_ID_RE,
    PLACEHOLDER_IDS,
    SECTION_RE,
    find_table,
    load_section_xml,
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
    print("table id=%s: %d cells" % (table_id, len(cells)))
    print("  %-6s %-6s %-6s %-6s  %s" % ("row", "col", "cSpan", "rSpan", "text"))
    print("  " + "-" * 60)
    for row, col, cs, rs, text in cells:
        display = text[:55] + ("…" if len(text) > 55 else "")
        print("  %-6d %-6d %-6d %-6d  %s" % (row, col, cs, rs, display))
    print("  [col,row for --cell: e.g. row=1 col=2 → --cell 2,1]")


def _dump_cell_verbose(tbl_xml: str, table_id: str, col: int, row: int) -> None:
    for cs, ce in top_cells(tbl_xml):
        tc = tbl_xml[cs:ce]
        addr = _own_cell_addr(tc)
        if addr != (col, row):
            continue
        col_span, row_span = _cell_span(tc)
        has_lineseg = bool(re.search(r"<hp:linesegarray>", tc))
        print("table id=%s  cell col=%d row=%d  cSpan=%d rSpan=%d"
              % (table_id, col, row, col_span, row_span))
        print("  linesegarray: %s" % ("YES (replace will strip)" if has_lineseg else "no"))
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
        print("  paragraphs: %d" % len(para_spans))
        for i, (ps, pe) in enumerate(para_spans):
            para_xml = sublist_content[ps:pe]
            para_pr_m = re.search(r'paraPrIDRef="(\d+)"', para_xml)
            para_pr = para_pr_m.group(1) if para_pr_m else "?"
            runs = re.findall(r'charPrIDRef="(\d+)"[^>]*>.*?<hp:t>(.*?)</hp:t>', para_xml, re.DOTALL)
            runs_empty = re.findall(r'charPrIDRef="(\d+)"[^>]*/>', para_xml)
            runs_t_empty = re.findall(r'charPrIDRef="(\d+)"[^>]*><hp:t/>', para_xml)
            run_desc = []
            for cpr, txt in runs:
                display = txt[:30] + "..." if len(txt) > 30 else txt
                run_desc.append("charPr=%s:%r" % (cpr, display))
            for cpr in runs_empty:
                run_desc.append("charPr=%s:(empty)" % cpr)
            for cpr in runs_t_empty:
                run_desc.append("charPr=%s:(empty)" % cpr)
            run_str = " + ".join(run_desc) if run_desc else "(empty)"
            print("  P[%d] paraPr=%s  %s" % (i, para_pr, run_str))
        return
    print("Error: cell col=%d row=%d not found in table %s" % (col, row, table_id), file=sys.stderr)
    sys.exit(1)


def cmd_dump(args: argparse.Namespace) -> None:
    if args.cell and not args.table_id:
        print("Error: --cell requires --table-id", file=sys.stderr)
        sys.exit(1)
    inp = Path(args.input)
    if not inp.exists():
        print("Error: not found: %s" % args.input, file=sys.stderr)
        sys.exit(1)
    xml = load_section_xml(inp, args.section)
    if args.table_id:
        span = find_table(xml, args.table_id)
        if span is None:
            print("Error: table id=%s not found" % args.table_id, file=sys.stderr)
            sys.exit(1)
        if args.cell:
            try:
                col, row = (int(x) for x in args.cell.split(","))
            except ValueError:
                print("Error: --cell expects col,row (got %r)" % args.cell, file=sys.stderr)
                sys.exit(1)
            _dump_cell_verbose(xml[span[0]:span[1]], args.table_id, col, row)
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
            print("No table found containing: %s" % ", ".join(args.contains), file=sys.stderr)
            sys.exit(2)
        for tid, s, e in matches:
            _dump_table(xml[s:e], tid)
            print()
        return
    print("%d table(s) in section %d:" % (len(all_tables), args.section))
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
        print("  id=%-12s  %s×%s cells  %s" % (tid, rows, cols, preview))
    print("\nRe-run with --table-id ID or --contains TEXT to dump cell map.")


# ── locate ────────────────────────────────────────────────────────────────────

def _matched_spans(xml: str, tag: str) -> list[tuple[int, int, int]]:
    events: list[tuple[int, str, int | None]] = []
    for m in re.finditer(r"<%s\b" % tag, xml):
        events.append((m.start(), "o", None))
    for m in re.finditer(r"</%s>" % tag, xml):
        events.append((m.start(), "c", m.end()))
    events.sort(key=lambda x: x[0])
    stack: list[int] = []
    out: list[tuple[int, int, int]] = []
    for pos, kind, end in events:
        if kind == "o":
            stack.append(pos)
        else:
            if not stack:
                raise ValueError("unbalanced </%s> at offset %d" % (tag, pos))
            start = stack.pop()
            assert end is not None
            out.append((start, end, len(stack)))
    if stack:
        raise ValueError("unclosed <%s> at offset %d" % (tag, stack[-1]))
    out.sort(key=lambda x: x[0])
    return out


def _text_preview(fragment: str, limit: int = 70) -> str:
    txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", fragment, re.DOTALL))
    txt = txt.replace("\n", " ").strip()
    return txt[:limit] + ("…" if len(txt) > limit else "")


def cmd_locate(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    target = "Contents/section%d.xml" % args.section
    if inp.is_dir():
        section_file = inp / target
        if not section_file.is_file():
            print("Error: %s not found in directory %s" % (target, inp), file=sys.stderr)
            sys.exit(1)
        xml = section_file.read_text(encoding="utf-8")
    elif inp.is_file():
        with zipfile.ZipFile(inp, "r") as zin:
            if target not in zin.namelist():
                print("Error: %s not in archive" % target, file=sys.stderr)
                sys.exit(1)
            xml = zin.read(target).decode("utf-8")
    else:
        print("Error: not found (file or directory): %s" % args.input, file=sys.stderr)
        sys.exit(1)
    try:
        spans = _matched_spans(xml, args.tag)
    except ValueError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(1)
    matches = []
    for start, end, depth in spans:
        if args.depth is not None and depth != args.depth:
            continue
        frag = xml[start:end]
        if all(c in frag for c in args.contains):
            matches.append((start, end, depth, frag))
    print("%d match(es) for <%s> in %s" % (len(matches), args.tag, target))
    for i, (start, end, depth, frag) in enumerate(matches):
        print("  [%d] span=%d:%d depth=%d len=%d  %s"
              % (i, start, end, depth, end - start, _text_preview(frag)))
    if args.extract_dir and matches:
        out_dir = Path(args.extract_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, (_s, _e, _d, frag) in enumerate(matches):
            if args.pretty:
                frag = re.sub(r"><", ">\n<", frag)
            (out_dir / ("match_%d.xml" % i)).write_text(frag, encoding="utf-8")
        print("  extracted %d file(s) to %s" % (len(matches), out_dir))
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
            result.append('rowAddr="%d"' % new_idx if depth == 0 else g)
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
        raise ValueError("table id=%s not found" % table_id)
    ti, tend = span
    tbl = xml[ti:tend]
    trs = top_trs(tbl)
    n = len(trs)
    if at_index < 0 or at_index > n:
        raise ValueError("--at %d out of range (table has %d rows; 0..%d)" % (at_index, n, n))
    row_xml = LINESEG_RE.sub("", row_xml).strip()
    if not (row_xml.startswith("<hp:tr") and row_xml.endswith("</hp:tr>")):
        raise ValueError("row file must contain exactly one <hp:tr>...</hp:tr>")
    existing = {i for i in PARA_ID_RE.findall(xml) if i not in PLACEHOLDER_IDS}
    incoming = [i for i in PARA_ID_RE.findall(row_xml) if i not in PLACEHOLDER_IDS]
    clash = sorted(set(incoming) & existing)
    if clash:
        raise ValueError("inserted row reuses hp:p id(s) %s — renumber them in the row file (or set to placeholder 0)" % clash)
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
        "inserted row at index %d (rowCnt %d -> %d)" % (at_index, n, n + 1),
        "rowSpan cells extended: %d" % grown,
    ]
    return new_xml, info


def _list_rows_insert(xml: str, table_id: str) -> None:
    span = find_table(xml, table_id)
    if span is None:
        print("table id=%s not found" % table_id, file=sys.stderr)
        sys.exit(1)
    tbl = xml[span[0]:span[1]]
    trs = top_trs(tbl)
    print("table id=%s: %d rows" % (table_id, len(trs)))
    for i, (s, e) in enumerate(trs):
        row = tbl[s:e]
        txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", row))
        spans = [m[6] for m in CELL_RE.findall(row)]
        print("  [%d] cells=%d rowSpans=%s  %s" % (i, len(spans), spans, txt[:60]))


def cmd_insert(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    if not inp.is_file():
        print("Error: file not found: %s" % args.input, file=sys.stderr)
        sys.exit(1)
    target = "Contents/section%d.xml" % args.section
    with zipfile.ZipFile(inp, "r") as zin:
        if target not in zin.namelist():
            print("Error: %s not in archive" % target, file=sys.stderr)
            sys.exit(1)
        xml = zin.read(target).decode("utf-8")
    if args.list:
        _list_rows_insert(xml, args.table_id)
        sys.exit(0)
    if args.at is None and args.after_row is None:
        print("Error: --at or --after-row required (or use --list)", file=sys.stderr)
        sys.exit(1)
    at_index = args.at if args.at is not None else args.after_row + 1
    if not args.row_file or not args.output:
        print("Error: --row-file and --output required", file=sys.stderr)
        sys.exit(1)
    row_xml = Path(args.row_file).read_text(encoding="utf-8")
    grow: set[tuple[int, int]] = set()
    for g in args.grow:
        try:
            r, c = (int(x) for x in g.split(","))
        except ValueError:
            print("Error: --grow expects rowAddr,colAddr (got %r)" % g, file=sys.stderr)
            sys.exit(1)
        grow.add((r, c))
    try:
        new_xml, info = _insert_row(xml, args.table_id, at_index, row_xml, grow)
    except ValueError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(1)
    new_xml, n_ls = LINESEG_RE.subn("", new_xml)
    with zipfile.ZipFile(inp, "r") as zin:
        entries = [(zi, zin.read(zi.filename)) for zi in zin.infolist()]
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as zout:
        for zi, data in entries:
            if zi.filename == target:
                data = new_xml.encode("utf-8")
            ct = zipfile.ZIP_STORED if zi.filename == "mimetype" else zi.compress_type
            zout.writestr(zi.filename, data, compress_type=ct)
    print("DONE: %s" % args.output)
    for line in info:
        print("  %s" % line)
    print("  linesegarray stripped: %d" % n_ls)


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
        return '<hp:run charPrIDRef="%s"><hp:t/></hp:run>' % char_pr
    return '<hp:run charPrIDRef="%s"><hp:t>%s</hp:t></hp:run>' % (char_pr, xml_escape(text))


def _build_para_runs(para_pr: str, runs: list[tuple[str, str]]) -> str:
    run_xml = "".join(_build_run(c, t) for c, t in runs)
    return ('<hp:p id="0" paraPrIDRef="%s" styleIDRef="0" pageBreak="0" '
            'columnBreak="0" merged="0">%s</hp:p>' % (para_pr, run_xml))


def _replace_cell(xml: str, table_id: str, col: int, row: int,
                  content: str) -> tuple[str, list[str]]:
    span = find_table(xml, table_id)
    if span is None:
        raise ValueError("table id=%s not found" % table_id)
    ti, tend = span
    tbl = xml[ti:tend]
    target = None
    for cs, ce in top_cells(tbl):
        addr = _own_cell_addr(tbl[cs:ce])
        if addr == (col, row):
            if target is not None:
                raise ValueError("cell %d,%d is not unique in table" % (col, row))
            target = (cs, ce)
    if target is None:
        raise ValueError("cell colAddr=%d rowAddr=%d not found" % (col, row))
    cs, ce = target
    tc = tbl[cs:ce]
    sl = _direct_sublist(tc)
    if sl is None:
        raise ValueError("cell %d,%d has no <hp:subList>" % (col, row))
    in_s, in_e = sl
    rest = xml[:ti] + xml[tend:] + tbl[:cs] + tc[:in_s] + tc[in_e:] + tbl[ce:]
    existing = {i for i in PARA_ID_RE.findall(rest) if i not in PLACEHOLDER_IDS}
    incoming = [i for i in PARA_ID_RE.findall(content) if i not in PLACEHOLDER_IDS]
    clash = sorted(set(incoming) & existing)
    if clash:
        raise ValueError("new content reuses hp:p id(s) %s — set them to placeholder 0 or renumber" % clash)
    if len(incoming) != len(set(incoming)):
        raise ValueError("new content has duplicate hp:p id(s) internally")
    new_tc = tc[:in_s] + content + tc[in_e:]
    new_tbl = tbl[:cs] + new_tc + tbl[ce:]
    new_xml = xml[:ti] + new_tbl + xml[tend:]
    n_para = content.count("<hp:p ")
    return new_xml, ["cell %d,%d content replaced (%d paragraph(s))" % (col, row, n_para)]


def _list_cells(xml: str, table_id: str) -> None:
    span = find_table(xml, table_id)
    if span is None:
        print("table id=%s not found" % table_id, file=sys.stderr)
        sys.exit(1)
    tbl = xml[span[0]:span[1]]
    cells = []
    for cs, ce in top_cells(tbl):
        tc = tbl[cs:ce]
        addr = _own_cell_addr(tc)
        txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", tc))
        cells.append((addr, txt))
    cells.sort(key=lambda x: (x[0][1], x[0][0]) if x[0] else (0, 0))
    print("table id=%s: %d cells" % (table_id, len(cells)))
    for addr, txt in cells:
        if addr:
            print("  col=%s row=%s  %s" % (addr[0], addr[1], txt[:55]))


def cmd_replace(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    is_dir_mode = inp.is_dir()
    target = "Contents/section%d.xml" % args.section
    if is_dir_mode:
        section_file = inp / target
        if not section_file.is_file():
            print("Error: %s not found in %s" % (target, inp), file=sys.stderr)
            sys.exit(1)
        xml = section_file.read_text(encoding="utf-8")
    elif inp.is_file():
        with zipfile.ZipFile(inp, "r") as zin:
            if target not in zin.namelist():
                print("Error: %s not in archive" % target, file=sys.stderr)
                sys.exit(1)
            xml = zin.read(target).decode("utf-8")
    else:
        print("Error: not found: %s" % args.input, file=sys.stderr)
        sys.exit(1)
    if args.list:
        _list_cells(xml, args.table_id)
        sys.exit(0)
    if not args.cell or (not is_dir_mode and not args.output):
        print("Error: --cell required (and --output required for .hwpx input)", file=sys.stderr)
        sys.exit(1)
    if bool(args.content_file) == (bool(args.para) or bool(args.run)):
        print("Error: provide exactly one of --content-file / --para[+--run]", file=sys.stderr)
        sys.exit(1)
    try:
        col, row = (int(x) for x in args.cell.split(","))
    except ValueError:
        print("Error: --cell expects colAddr,rowAddr (got %r)" % args.cell, file=sys.stderr)
        sys.exit(1)
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
        content = LINESEG_RE.sub("", content)
        content = re.sub(r">[ \t\r\n]+<", "><", content).strip()
    else:
        if args.run and not args.para:
            print("Error: --run requires at least one --para", file=sys.stderr)
            sys.exit(1)
        paras = [(p[0], [(p[1], p[2])]) for p in args.para]
        for char_pr, text in args.run:
            paras[-1][1].append((char_pr, text))
        content = "".join(_build_para_runs(pp, runs) for pp, runs in paras)
    try:
        new_xml, info = _replace_cell(xml, args.table_id, col, row, content)
    except ValueError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(1)
    new_xml, n_ls = LINESEG_RE.subn("", new_xml)
    if is_dir_mode:
        section_file = inp / target
        section_file.write_text(new_xml, encoding="utf-8")
        print("DONE (in-place): %s" % section_file)
    else:
        with zipfile.ZipFile(inp, "r") as zin:
            entries = [(zi, zin.read(zi.filename)) for zi in zin.infolist()]
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as zout:
            for zi, data in entries:
                if zi.filename == target:
                    data = new_xml.encode("utf-8")
                ct = zipfile.ZIP_STORED if zi.filename == "mimetype" else zi.compress_type
                zout.writestr(zi.filename, data, compress_type=ct)
        print("DONE: %s" % args.output)
    for line in info:
        print("  %s" % line)
    print("  linesegarray stripped: %d" % n_ls)


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
        print(f"table id={table_id} not found", file=sys.stderr)
        sys.exit(1)
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
    if not inp.is_file():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    target = f"Contents/section{args.section}.xml"
    with zipfile.ZipFile(inp, "r") as zin:
        if target not in zin.namelist():
            print(f"Error: {target} not in archive", file=sys.stderr)
            sys.exit(1)
        xml = zin.read(target).decode("utf-8")
    if args.list:
        _list_rows_delete(xml, args.table_id)
        sys.exit(0)
    if not args.rows or not args.output:
        print("Error: --rows and --output required (or use --list)", file=sys.stderr)
        sys.exit(1)
    del_idx = {int(x) for x in args.rows.split(",") if x.strip() != ""}
    try:
        new_xml, info = _delete_rows(xml, args.table_id, del_idx)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    new_xml, n_ls = LINESEG_RE.subn("", new_xml)
    with zipfile.ZipFile(inp, "r") as zin:
        entries = [(zi, zin.read(zi.filename)) for zi in zin.infolist()]
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as zout:
        for zi, data in entries:
            if zi.filename == target:
                data = new_xml.encode("utf-8")
            ct = zipfile.ZIP_STORED if zi.filename == "mimetype" else zi.compress_type
            zout.writestr(zi.filename, data, compress_type=ct)
    print(f"DONE: {args.output}")
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
            print(f"ERROR: sum={total}, body={args.body}, diff={diff:+d}", file=sys.stderr)
            sys.exit(1)
        return
    try:
        ratios = _parse_width_spec(args.spec)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
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
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    if args.inplace and args.output:
        print("Error: --inplace and --output are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    tmp = input_path.with_suffix(".tmp")
    if args.inplace:
        output_path = tmp
    elif args.output:
        output_path = Path(args.output)
    else:
        print("Error: specify --output or --inplace", file=sys.stderr)
        sys.exit(1)
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


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
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
    p_ins.add_argument("input", help="Input .hwpx file")
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
    p_rep.add_argument("--content-file", help="File with raw <hp:p>...</hp:p> XML")
    p_rep.add_argument("--para", action="append", nargs=3, default=[],
                       metavar=("PARAPR", "CHARPR", "TEXT"), help="One text paragraph (repeatable)")
    p_rep.add_argument("--run", action="append", nargs=2, default=[],
                       metavar=("CHARPR", "TEXT"), help="Extra run appended to last --para (repeatable)")
    p_rep.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_rep.add_argument("--list", action="store_true", help="List table cells and exit")
    p_rep.add_argument("--output", "-o", help="Output .hwpx file")

    # delete
    p_del = sub.add_parser("delete", help="Delete table rows, fixing rowAddr/rowCnt/rowSpan")
    p_del.add_argument("input", help="Input .hwpx file")
    p_del.add_argument("--table-id", required=True, help="HWP table id attribute")
    p_del.add_argument("--rows", help="Comma-separated 0-based row indices to delete")
    p_del.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    p_del.add_argument("--list", action="store_true", help="List rows and exit")
    p_del.add_argument("--output", "-o", help="Output .hwpx file")

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
    elif args.cmd == "delete":
        cmd_delete(args)
    elif args.cmd == "calc-widths":
        cmd_calc_widths(args)
    elif args.cmd == "strip-lineseg":
        cmd_strip_lineseg(args)


if __name__ == "__main__":
    main()
