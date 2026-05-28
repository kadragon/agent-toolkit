#!/usr/bin/env python3
"""Dump table cell map from an HWPX document.

Outputs (rowAddr, colAddr, colSpan, rowSpan, text) for every cell in matching tables.
Saves time vs. manually reading XML — see cell layout before editing with replace_cell.py.

Usage:
    python dump_table.py doc.hwpx                          # list all table IDs
    python dump_table.py doc.hwpx --table-id 1000000003   # dump specific table
    python dump_table.py doc.hwpx --contains "항목명"     # dump table(s) containing text
    python dump_table.py ./unpacked/ --contains "합계"    # from unpacked directory
"""
# Windows console: emit UTF-8 (avoid cp949 mojibake)
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import re
import sys
import zipfile
from pathlib import Path


def _load_xml(inp: Path, section: int) -> str:
    target = "Contents/section%d.xml" % section
    if inp.is_dir():
        section_file = inp / target
        if not section_file.is_file():
            print("Error: %s not found in directory %s" % (target, inp), file=sys.stderr)
            sys.exit(1)
        return section_file.read_text(encoding="utf-8")
    with zipfile.ZipFile(inp, "r") as zin:
        if target not in zin.namelist():
            print("Error: %s not in archive" % target, file=sys.stderr)
            sys.exit(1)
        return zin.read(target).decode("utf-8")


def _find_all_table_spans(xml: str) -> list[tuple[str, int, int]]:
    """Return list of (table_id, start, end) for every top-level hp:tbl."""
    depth = 0
    start = None
    table_id = None
    out = []
    for m in re.finditer(r'<hp:tbl\b[^>]*(?<!/)>|</hp:tbl>', xml):
        if m.group().startswith("</"):
            depth -= 1
            if depth == 0 and start is not None:
                out.append((table_id, start, m.end()))
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
    """Return (table_id, start, end) for all hp:tbl at any nesting depth."""
    stack: list[tuple[str, int]] = []
    out = []
    for m in re.finditer(r'<hp:tbl\b[^>]*(?<!/)>|</hp:tbl>', xml):
        if m.group().startswith("</"):
            if stack:
                t_id, t_start = stack.pop()
                out.append((t_id, t_start, m.end()))
        else:
            id_m = re.search(r'\bid="(\d+)"', m.group())
            stack.append((id_m.group(1) if id_m else "?", m.start()))
    return out


def _find_table_span(xml: str, table_id: str) -> tuple[int, int] | None:
    m = re.search(r'<hp:tbl\b[^>]*\bid="%s"' % re.escape(table_id), xml)
    if not m:
        return None
    depth = 0
    for mm in re.finditer(r"<hp:tbl\b|</hp:tbl>", xml[m.start():]):
        if mm.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return m.start(), m.start() + mm.end()
        else:
            depth += 1
    return None


def _top_cells(tbl: str) -> list[tuple[int, int]]:
    """(start, end) of top-level <hp:tc> elements (not inside nested tables)."""
    tbl_depth = 0
    stack: list[tuple[int, int]] = []
    out = []
    for m in re.finditer(r"<hp:tbl\b|</hp:tbl>|<hp:tc\b|</hp:tc>", tbl):
        g = m.group()
        if g == "<hp:tbl":
            tbl_depth += 1
        elif g == "</hp:tbl>":
            tbl_depth -= 1
        elif g == "<hp:tc":
            stack.append((m.start(), tbl_depth))
        elif g == "</hp:tc>":
            start, d = stack.pop()
            if d == 1:
                out.append((start, m.end()))
    return out


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
    """(colSpan, rowSpan) — defaults to (1,1) if not found."""
    m = re.search(r'<hp:cellSpan colSpan="(\d+)" rowSpan="(\d+)"/>', tc)
    return (int(m.group(1)), int(m.group(2))) if m else (1, 1)


def _cell_text(tc: str) -> str:
    """Concatenate all direct hp:t text (ignores nested table text)."""
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


def dump_table(tbl_xml: str, table_id: str) -> None:
    cells = []
    for cs, ce in _top_cells(tbl_xml):
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


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Dump table cell map (rowAddr, colAddr, span, text) from HWPX"
    )
    ap.add_argument("input", help="Input .hwpx file or unpacked directory")
    ap.add_argument("--table-id", help="Dump specific table by id")
    ap.add_argument("--contains", action="append", default=[],
                    help="Dump table(s) whose XML contains this text (repeatable, AND)")
    ap.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print("Error: not found: %s" % args.input, file=sys.stderr)
        sys.exit(1)

    xml = _load_xml(inp, args.section)

    if args.table_id:
        span = _find_table_span(xml, args.table_id)
        if span is None:
            print("Error: table id=%s not found" % args.table_id, file=sys.stderr)
            sys.exit(1)
        dump_table(xml[span[0]:span[1]], args.table_id)
        return

    all_tables = _find_all_table_spans(xml)

    if args.contains:
        candidates = _find_all_table_spans_deep(xml)
        matches = [
            (tid, s, e) for tid, s, e in candidates
            if all(c in xml[s:e] for c in args.contains)
        ]
        # Keep only innermost: drop any match whose span contains another match
        matches = [
            (tid, s, e) for tid, s, e in matches
            if not any(s <= s2 and e2 <= e and (s, e) != (s2, e2)
                       for _, s2, e2 in matches)
        ]
        if not matches:
            print("No table found containing: %s" % ", ".join(args.contains), file=sys.stderr)
            sys.exit(2)
        for tid, s, e in matches:
            dump_table(xml[s:e], tid)
            print()
        return

    # default: list all tables with row/col count and text preview
    print("%d table(s) in section %d:" % (len(all_tables), args.section))
    for tid, s, e in all_tables:
        tbl = xml[s:e]
        cells = _top_cells(tbl)
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


if __name__ == "__main__":
    main()
