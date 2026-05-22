#!/usr/bin/env python3
"""Extract text from an HWPX document.

Self-contained: reads section XML directly from the HWPX ZIP and walks the
OWPML tree with lxml (read-only parse — no re-serialization, so Rule 18 is
not violated). Does NOT depend on the external ``hwpx`` package.

Usage:
    python text_extract.py document.hwpx
    python text_extract.py document.hwpx --format markdown
    python text_extract.py document.hwpx --include-tables
"""

import argparse
import re
import sys
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree

SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")


def _local(tag) -> str:
    """Strip XML namespace: '{uri}p' -> 'p'."""
    if isinstance(tag, str):
        return tag.rsplit("}", 1)[-1]
    return ""


def _walk(el, in_tbl: bool, lines: list, cur: list, include_tables: bool) -> None:
    """Depth-first walk collecting paragraph text.

    Each <hp:p> boundary flushes the accumulated run text as one line.
    Table-cell text is skipped unless include_tables is True.
    """
    for child in el:
        tag = _local(child.tag)
        if tag == "tbl":
            _walk(child, True, lines, cur, include_tables)
        elif tag == "p":
            if cur:
                lines.append("".join(cur))
                cur.clear()
            _walk(child, in_tbl, lines, cur, include_tables)
            if cur:
                lines.append("".join(cur))
                cur.clear()
        elif tag == "t":
            if (not in_tbl) or include_tables:
                cur.append(child.text or "")
        else:
            _walk(child, in_tbl, lines, cur, include_tables)


def _section_lines(xml_bytes: bytes, include_tables: bool) -> list:
    root = etree.fromstring(xml_bytes)
    lines: list = []
    cur: list = []
    _walk(root, False, lines, cur, include_tables)
    if cur:
        lines.append("".join(cur))
    return [ln for ln in lines if ln.strip()]


def _iter_sections(hwpx_path: str):
    with ZipFile(hwpx_path, "r") as zf:
        names = sorted(
            (n for n in zf.namelist() if SECTION_RE.match(n)),
            key=lambda n: int(SECTION_RE.match(n).group(1)),
        )
        for name in names:
            yield zf.read(name)


def extract_plain(hwpx_path: str, *, include_tables: bool = False) -> str:
    out: list = []
    for xml_bytes in _iter_sections(hwpx_path):
        out.extend(_section_lines(xml_bytes, include_tables))
    return "\n".join(out)


def extract_markdown(hwpx_path: str) -> str:
    blocks: list = []
    for xml_bytes in _iter_sections(hwpx_path):
        blocks.append("\n".join(_section_lines(xml_bytes, include_tables=True)))
    return "\n\n---\n\n".join(b for b in blocks if b.strip())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract text from an HWPX document"
    )
    parser.add_argument("input", help="Path to .hwpx file")
    parser.add_argument(
        "--format", "-f",
        choices=["plain", "markdown"],
        default="plain",
        help="Output format (default: plain)",
    )
    parser.add_argument(
        "--include-tables",
        action="store_true",
        help="Include text from tables (plain mode; markdown always includes)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    if not Path(args.input).is_file():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.format == "markdown":
            result = extract_markdown(args.input)
        else:
            result = extract_plain(args.input, include_tables=args.include_tables)
    except BadZipFile:
        print(f"Error: not a valid HWPX (ZIP) file: {args.input}", file=sys.stderr)
        sys.exit(1)
    except etree.XMLSyntaxError as e:
        print(f"Error: malformed section XML: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"Extracted to: {args.output}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(result)


if __name__ == "__main__":
    main()
