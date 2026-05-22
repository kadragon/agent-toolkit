#!/usr/bin/env python3
"""Delete rows from a table in an HWPX section, fixing structural metadata.

Reliably fixes (these matter for HWP not to corrupt the file):
  - removes the <hp:tr> elements
  - rowCnt on <hp:tbl>
  - rowSpan of cells anchored above the deleted rows that span through them
  - rowAddr renumbering on every remaining cell

Best-effort (HWP recomputes table layout on open anyway):
  - table <hp:sz> height and spanned-cell <hp:cellSz> height

Also strips all <hp:linesegarray> from the section (stale layout cache).

Limitation: a row to delete must NOT contain a rowSpan>1 cell (its own anchor
row). Deleting such a row would orphan the merged cell — the script aborts.
Restructure that case manually.

Usage:
    python delete_table_rows.py doc.hwpx --table-id TABLE_ID --list
    python delete_table_rows.py doc.hwpx --table-id TABLE_ID --rows 3,4 -o result.hwpx
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

LINESEG_RE = re.compile(r"<hp:linesegarray>.*?</hp:linesegarray>", re.DOTALL)
TRIPLET_RE = re.compile(
    r'(<hp:cellAddr colAddr="\d+" rowAddr=")(\d+)("/>)'
    r'(<hp:cellSpan colSpan="\d+" rowSpan=")(\d+)("/>)'
    r'(<hp:cellSz width="\d+" height=")(\d+)("/>)'
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


def _row_cells(row: str):
    """Return list of (rowAddr, rowSpan, height) for each cell triplet in row."""
    return [
        (int(m.group(2)), int(m.group(5)), int(m.group(8)))
        for m in TRIPLET_RE.finditer(row)
    ]


def delete_rows(xml: str, table_id: str, del_idx: set) -> tuple[str, list]:
    """Return (new_xml, info_messages). Raises ValueError on unsupported cases."""
    span = _find_table(xml, table_id)
    if span is None:
        raise ValueError(f"table id={table_id} not found")
    ti, tend = span
    tbl = xml[ti:tend]

    trs = _top_trs(tbl)
    n = len(trs)
    for i in del_idx:
        if i < 0 or i >= n:
            raise ValueError(f"row index {i} out of range (table has {n} rows)")

    # deleted-row heights + anchor-cell guard
    del_height = {}
    for i in del_idx:
        cells = _row_cells(tbl[trs[i][0]:trs[i][1]])
        if any(rs > 1 for (_ra, rs, _h) in cells):
            raise ValueError(
                f"row {i} contains a rowSpan>1 cell (anchor row) — unsupported"
            )
        del_height[i] = cells[0][2] if cells else 0
    total_del_h = sum(del_height.values())

    prefix = tbl[:trs[0][0]]
    suffix = tbl[trs[-1][1]:]

    kept = []  # (old_index, modified_row_string)
    for i, (s, e) in enumerate(trs):
        if i in del_idx:
            continue
        row = tbl[s:e]

        def _fix(m, old_i=i):
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

    # renumber rowAddr to new sequential index
    kept = [re.sub(r'rowAddr="\d+"', 'rowAddr="%d"' % idx, r)
            for idx, r in enumerate(kept)]

    # rowCnt on <hp:tbl>
    new_prefix, nc = re.subn(
        r'(<hp:tbl\b[^>]*\browCnt=")(\d+)(")',
        lambda m: m.group(1) + str(int(m.group(2)) - len(del_idx)) + m.group(3),
        prefix, count=1,
    )
    if nc != 1:
        raise ValueError("rowCnt attribute not found on <hp:tbl>")
    # table <hp:sz> height (best-effort)
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


def list_rows(xml: str, table_id: str) -> None:
    span = _find_table(xml, table_id)
    if span is None:
        print(f"table id={table_id} not found", file=sys.stderr)
        sys.exit(1)
    tbl = xml[span[0]:span[1]]
    trs = _top_trs(tbl)
    print(f"table id={table_id}: {len(trs)} rows")
    for i, (s, e) in enumerate(trs):
        row = tbl[s:e]
        txt = "".join(re.findall(r"<hp:t>(.*?)</hp:t>", row))
        cells = _row_cells(row)
        spans = [rs for (_ra, rs, _h) in cells]
        print(f"  [{i}] cells={len(cells)} rowSpans={spans}  {txt[:60]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Delete table rows from an HWPX section")
    ap.add_argument("input", help="Input .hwpx file")
    ap.add_argument("--table-id", required=True, help="HWP table id attribute")
    ap.add_argument("--rows", help="Comma-separated 0-based row indices to delete")
    ap.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    ap.add_argument("--list", action="store_true", help="List rows and exit")
    ap.add_argument("--output", "-o", help="Output .hwpx file")
    args = ap.parse_args()

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
        list_rows(xml, args.table_id)
        sys.exit(0)

    if not args.rows or not args.output:
        print("Error: --rows and --output required (or use --list)", file=sys.stderr)
        sys.exit(1)

    del_idx = {int(x) for x in args.rows.split(",") if x.strip() != ""}
    try:
        new_xml, info = delete_rows(xml, args.table_id, del_idx)
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


if __name__ == "__main__":
    main()
