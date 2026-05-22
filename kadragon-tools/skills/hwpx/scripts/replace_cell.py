#!/usr/bin/env python3
"""Replace the paragraph content of one table cell in an HWPX section.

Rebuilding a cell's <hp:p> list by hand means: find the table, find the
<hp:tc> whose cellAddr matches, isolate its direct <hp:subList>, splice new
paragraphs in. This does all of that, then strips <hp:linesegarray>
section-wide (stale layout cache — HWP recomputes on open).

The cell is addressed by table id + colAddr,rowAddr. Only the targeted cell's
direct content is replaced; nested tables inside other cells are untouched.

New content comes from either:
  --content-file FILE   raw <hp:p>...</hp:p> paragraph XML (compacted on load)
  --para PARAPR CHARPR TEXT   one simple text paragraph (repeatable)

New paragraphs use placeholder id="0". Any non-placeholder hp:p id in
--content-file that collides with the rest of the document aborts the script.

Usage:
    python replace_cell.py doc.hwpx --table-id TABLE_ID --list
    python replace_cell.py doc.hwpx --table-id TABLE_ID --cell 1,0 \
        --para 0 0 "셀 첫 번째 줄" \
        --para 0 0 "셀 두 번째 줄" \
        -o result.hwpx
    python replace_cell.py doc.hwpx --table-id TABLE_ID --cell 1,0 \
        --content-file paras.xml -o result.hwpx
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


def _top_cells(tbl: str):
    """Top-level <hp:tc> spans (those not inside a nested table)."""
    tbl_depth = 0
    stack = []
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
            if d == 1:  # depth 1 == directly in the target table
                out.append((start, m.end()))
    return out


def _own_cell_addr(tc: str):
    """(colAddr, rowAddr) of the tc itself (the cellAddr at table-depth 0)."""
    tbl_depth = 0
    for m in re.finditer(
        r"<hp:tbl\b|</hp:tbl>|<hp:cellAddr colAddr=\"(\d+)\" rowAddr=\"(\d+)\"/>",
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


def _direct_sublist(tc: str):
    """(inner_start, inner_end) of the tc's own first <hp:subList>."""
    events = []
    for m in re.finditer(r"<hp:subList\b", tc):
        events.append((m.start(), "o", tc.index(">", m.start()) + 1))
    for m in re.finditer(r"</hp:subList>", tc):
        events.append((m.start(), "c", m.end()))
    events.sort(key=lambda x: x[0])
    depth = 0
    open_inner = None
    for pos, kind, off in events:
        if kind == "o":
            if depth == 0:
                open_inner = off
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return open_inner, pos
    return None


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_para(para_pr: str, char_pr: str, text: str) -> str:
    return ('<hp:p id="0" paraPrIDRef="%s" styleIDRef="0" pageBreak="0" '
            'columnBreak="0" merged="0"><hp:run charPrIDRef="%s"><hp:t>%s'
            "</hp:t></hp:run></hp:p>"
            % (para_pr, char_pr, _xml_escape(text)))


def replace_cell(xml: str, table_id: str, col: int, row: int,
                 content: str) -> tuple[str, list]:
    span = _find_table(xml, table_id)
    if span is None:
        raise ValueError("table id=%s not found" % table_id)
    ti, tend = span
    tbl = xml[ti:tend]

    target = None
    for cs, ce in _top_cells(tbl):
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

    # hp:p id collision guard for incoming content
    rest = xml[:ti] + xml[tend:] + tbl[:cs] + tc[:in_s] + tc[in_e:] + tbl[ce:]
    existing = {i for i in PARA_ID_RE.findall(rest) if i not in PLACEHOLDER_IDS}
    incoming = [i for i in PARA_ID_RE.findall(content) if i not in PLACEHOLDER_IDS]
    clash = sorted(set(incoming) & existing)
    if clash:
        raise ValueError("new content reuses hp:p id(s) %s — set them to "
                         "placeholder 0 or renumber" % clash)
    if len(incoming) != len(set(incoming)):
        raise ValueError("new content has duplicate hp:p id(s) internally")

    new_tc = tc[:in_s] + content + tc[in_e:]
    new_tbl = tbl[:cs] + new_tc + tbl[ce:]
    new_xml = xml[:ti] + new_tbl + xml[tend:]
    n_para = content.count("<hp:p ")
    return new_xml, ["cell %d,%d content replaced (%d paragraph(s))"
                     % (col, row, n_para)]


def list_cells(xml: str, table_id: str) -> None:
    span = _find_table(xml, table_id)
    if span is None:
        print("table id=%s not found" % table_id, file=sys.stderr)
        sys.exit(1)
    tbl = xml[span[0]:span[1]]
    cells = []
    for cs, ce in _top_cells(tbl):
        tc = tbl[cs:ce]
        addr = _own_cell_addr(tc)
        txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", tc))
        cells.append((addr, txt))
    cells.sort(key=lambda x: (x[0][1], x[0][0]) if x[0] else (0, 0))
    print("table id=%s: %d cells" % (table_id, len(cells)))
    for addr, txt in cells:
        print("  col=%s row=%s  %s" % (addr[0], addr[1], txt[:55]))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Replace a table cell's paragraph content in an HWPX section"
    )
    ap.add_argument("input", help="Input .hwpx file")
    ap.add_argument("--table-id", required=True, help="HWP table id attribute")
    ap.add_argument("--cell", help="Target cell as colAddr,rowAddr")
    ap.add_argument("--content-file", help="File with raw <hp:p>...</hp:p> XML")
    ap.add_argument("--para", action="append", nargs=3, default=[],
                    metavar=("PARAPR", "CHARPR", "TEXT"),
                    help="One text paragraph (repeatable)")
    ap.add_argument("--section", type=int, default=0, help="Section index (default 0)")
    ap.add_argument("--list", action="store_true", help="List table cells and exit")
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
        list_cells(xml, args.table_id)
        sys.exit(0)

    if not args.cell or not args.output:
        print("Error: --cell and --output required (or use --list)", file=sys.stderr)
        sys.exit(1)
    if bool(args.content_file) == bool(args.para):
        print("Error: provide exactly one of --content-file / --para", file=sys.stderr)
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
        content = "".join(build_para(p, c, t) for p, c, t in args.para)

    try:
        new_xml, info = replace_cell(xml, args.table_id, col, row, content)
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
