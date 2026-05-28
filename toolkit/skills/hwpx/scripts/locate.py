#!/usr/bin/env python3
"""Locate XML elements in an HWPX section by the text they contain.

section0.xml is one long line; finding "the <hp:tbl> that contains '항목명'"
by hand means writing a nesting-aware tag matcher every time. This does it.

Usage:
    python locate.py doc.hwpx --tag hp:tbl --contains "항목명"
    python locate.py doc.hwpx --tag hp:tbl --contains "항목명" --contains "열제목"
    python locate.py doc.hwpx --tag hp:p  --contains "특정텍스트" --section 0
    python locate.py doc.hwpx --tag hp:tbl --contains "합계" --extract-dir ./out --pretty
    python locate.py ./unpacked/ --tag hp:tc --contains "이름"   # unpack 디렉토리 직접

--contains may be repeated; an element must contain ALL given strings (AND).
Reports the byte span (start:end into the section XML), nesting depth, char
length and a text preview for each match. With --extract-dir, writes each
match to match_<i>.xml (raw, or formatted when --pretty).
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


def matched_spans(xml: str, tag: str) -> list[tuple[int, int, int]]:
    """Nesting-aware (start, end, depth) for every <tag>...</tag> pair."""
    events = []
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
            out.append((start, end, len(stack)))
    if stack:
        raise ValueError("unclosed <%s> at offset %d" % (tag, stack[-1]))
    out.sort(key=lambda x: x[0])
    return out


def text_preview(fragment: str, limit: int = 70) -> str:
    txt = " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", fragment, re.DOTALL))
    txt = txt.replace("\n", " ").strip()
    return txt[:limit] + ("…" if len(txt) > limit else "")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Locate HWPX elements by contained text (nesting-aware)"
    )
    ap.add_argument("input", help="Input .hwpx file or unpacked directory")
    ap.add_argument("--tag", required=True,
                    help="Element tag, e.g. hp:tbl, hp:tr, hp:p, hp:tc")
    ap.add_argument("--contains", action="append", default=[],
                    help="Required substring (repeatable; AND semantics)")
    ap.add_argument("--section", type=int, default=0,
                    help="Section index (default 0)")
    ap.add_argument("--depth", type=int, default=None,
                    help="Only report matches at this nesting depth")
    ap.add_argument("--extract-dir",
                    help="Write each match to <dir>/match_<i>.xml")
    ap.add_argument("--pretty", action="store_true",
                    help="Format extracted XML (one tag per line)")
    args = ap.parse_args()

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
        spans = matched_spans(xml, args.tag)
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
              % (i, start, end, depth, end - start, text_preview(frag)))

    if args.extract_dir and matches:
        out_dir = Path(args.extract_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, (_s, _e, _d, frag) in enumerate(matches):
            if args.pretty:
                frag = re.sub(r"><", ">\n<", frag)
            (out_dir / ("match_%d.xml" % i)).write_text(frag, encoding="utf-8")
        print("  extracted %d file(s) to %s" % (len(matches), out_dir))

    sys.exit(0 if matches else 2)


if __name__ == "__main__":
    main()
