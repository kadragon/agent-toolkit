#!/usr/bin/env python3
"""Insert a row into a table in an HWPX section, fixing structural metadata.

Reliably fixes (these matter for HWP not to corrupt the file):
  - inserts the <hp:tr> at the requested position
  - rowCnt on <hp:tbl>
  - rowAddr renumbering on every cell (sequential by final row index)
  - rowSpan of cells whose merge region straddles the insertion point
    (auto-extended +1)
  - rowSpan of explicitly named anchor cells via --grow (for appending a row
    at the END of a rowSpan group, which auto-detection cannot infer)

Strips <hp:linesegarray> from the inserted row and from the whole section
(stale layout cache — HWP recomputes on open).

The inserted <hp:tr> XML is supplied by --row-file. Build it by cloning an
existing sibling row (use locate.py / delete_table_rows.py --list to find one)
and editing its text. Cell-internal <hp:p> placeholder ids (0, 2147483648) are
fine to duplicate; any other duplicate hp:p id aborts the script.

Best-effort (HWP recomputes table layout on open anyway):
  - table <hp:sz> height and spanned-cell <hp:cellSz> height are left as-is

Usage:
    python insert_table_row.py doc.hwpx --table-id TABLE_ID --list
    python insert_table_row.py doc.hwpx --table-id TABLE_ID \
        --at 4 --row-file newrow.xml -o result.hwpx
    # append after row 3 (same as --at 4); grow the rowSpan group anchored
    # at rowAddr=2 in columns 0 and 3:
    python insert_table_row.py doc.hwpx --table-id TABLE_ID \
        --after-row 3 --row-file newrow.xml --grow 2,0 --grow 2,3 -o result.hwpx
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
from collections import Counter
from pathlib import Path

LINESEG_RE = re.compile(r"<hp:linesegarray>.*?</hp:linesegarray>", re.DOTALL)
PARA_ID_RE = re.compile(r'<hp:p\s[^>]*\bid="(\d+)"')
PLACEHOLDER_IDS = {"0", "2147483648"}
CELL_RE = re.compile(
    r'(<hp:cellAddr colAddr=")(\d+)(" rowAddr=")(\d+)("/>)'
    r'(<hp:cellSpan colSpan="\d+" rowSpan=")(\d+)("/>)'
)


def _find_table(xml: str, table_id: str):
    m = re.search(r'<hp:tbl\b[^>]*\bid="%s"' % re.escape(table_id), xml)
    if not m:
        return None
    ti = m.start()
    depth = 0
    for mm in re.finditer(r"<hp:tbl\b|</hp:tbl>", xml[ti:]):
        if mm.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return ti, ti + mm.end()
        else:
            depth += 1
    return None


def _top_trs(tbl: str):
    """Spans of <hp:tr> directly under this table (not nested tables)."""
    depth = 0
    out = []
    st = None
    for m in re.finditer(r"<hp:tbl\b|</hp:tbl>|<hp:tr>|</hp:tr>", tbl):
        g = m.group()
        if g == "<hp:tbl":
            depth += 1
        elif g == "</hp:tbl>":
            depth -= 1
        elif g == "<hp:tr>":
            if depth == 1:
                st = m.start()
        elif g == "</hp:tr>":
            if depth == 1:
                out.append((st, m.end()))
    return out


def insert_row(xml: str, table_id: str, at_index: int,
               row_xml: str, grow: set) -> tuple[str, list]:
    """Return (new_xml, info). Raises ValueError on unsupported input."""
    span = _find_table(xml, table_id)
    if span is None:
        raise ValueError("table id=%s not found" % table_id)
    ti, tend = span
    tbl = xml[ti:tend]
    trs = _top_trs(tbl)
    n = len(trs)
    if at_index < 0 or at_index > n:
        raise ValueError("--at %d out of range (table has %d rows; 0..%d)"
                         % (at_index, n, n))

    row_xml = LINESEG_RE.sub("", row_xml).strip()
    if not (row_xml.startswith("<hp:tr") and row_xml.endswith("</hp:tr>")):
        raise ValueError("row file must contain exactly one <hp:tr>...</hp:tr>")

    # hp:p id collision guard
    existing = {i for i in PARA_ID_RE.findall(xml) if i not in PLACEHOLDER_IDS}
    incoming = [i for i in PARA_ID_RE.findall(row_xml) if i not in PLACEHOLDER_IDS]
    clash = sorted(set(incoming) & existing)
    if clash:
        raise ValueError("inserted row reuses hp:p id(s) %s — renumber them "
                         "in the row file (or set to placeholder 0)" % clash)
    if len(incoming) != len(set(incoming)):
        raise ValueError("inserted row has duplicate hp:p id(s) internally")

    prefix = tbl[:trs[0][0]]
    suffix = tbl[trs[-1][1]:]
    rows = [tbl[s:e] for s, e in trs]

    grown = 0

    def adjust(m, row_index):
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

    # renumber rowAddr sequentially by final index
    new_rows = [re.sub(r'rowAddr="\d+"', 'rowAddr="%d"' % i, r)
                for i, r in enumerate(new_rows)]

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


def list_rows(xml: str, table_id: str) -> None:
    span = _find_table(xml, table_id)
    if span is None:
        print("table id=%s not found" % table_id, file=sys.stderr)
        sys.exit(1)
    tbl = xml[span[0]:span[1]]
    trs = _top_trs(tbl)
    print("table id=%s: %d rows" % (table_id, len(trs)))
    for i, (s, e) in enumerate(trs):
        row = tbl[s:e]
        txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", row))
        spans = [m[6] for m in CELL_RE.findall(row)]
        print("  [%d] cells=%d rowSpans=%s  %s"
              % (i, len(spans), spans, txt[:60]))


def main() -> None:
    ap = argparse.ArgumentParser(description="Insert a table row into an HWPX section")
    ap.add_argument("input", help="Input .hwpx file")
    ap.add_argument("--table-id", required=True, help="HWP table id attribute")
    ap.add_argument("--at", type=int, help="Final 0-based index of the new row")
    ap.add_argument("--after-row", type=int,
                    help="Insert after this 0-based row index (= --at N+1)")
    ap.add_argument("--row-file", help="File with the <hp:tr>...</hp:tr> to insert")
    ap.add_argument("--grow", action="append", default=[],
                    help="rowAddr,colAddr of an anchor cell to extend rowSpan "
                         "+1 (repeatable; for appending at a group's end)")
    ap.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    ap.add_argument("--list", action="store_true", help="List rows and exit")
    ap.add_argument("--output", "-o", help="Output .hwpx file")
    args = ap.parse_args()

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
        list_rows(xml, args.table_id)
        sys.exit(0)

    if args.at is None and args.after_row is None:
        print("Error: --at or --after-row required (or use --list)", file=sys.stderr)
        sys.exit(1)
    at_index = args.at if args.at is not None else args.after_row + 1
    if not args.row_file or not args.output:
        print("Error: --row-file and --output required", file=sys.stderr)
        sys.exit(1)

    row_xml = Path(args.row_file).read_text(encoding="utf-8")
    grow = set()
    for g in args.grow:
        try:
            r, c = (int(x) for x in g.split(","))
        except ValueError:
            print("Error: --grow expects rowAddr,colAddr (got %r)" % g, file=sys.stderr)
            sys.exit(1)
        grow.add((r, c))

    try:
        new_xml, info = insert_row(xml, args.table_id, at_index, row_xml, grow)
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


if __name__ == "__main__":
    main()
