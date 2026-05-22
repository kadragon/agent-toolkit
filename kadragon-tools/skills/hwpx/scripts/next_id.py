#!/usr/bin/env python3
"""Get the next available hp:p ID(s) from an HWPX or section XML.

All <hp:p id="N"> values in the document must be unique (except placeholder
IDs 0 and 2147483648). This script finds the current maximum ID and returns
the next N available IDs, safe to use when inserting new paragraphs.

Usage:
    # Single next ID from HWPX
    python next_id.py document.hwpx
    # → 1000000023

    # Multiple IDs (e.g. need 5 new paragraphs)
    python next_id.py document.hwpx --count 5
    # → 1000000023 1000000024 1000000025 1000000026 1000000027

    # From a raw section XML file
    python next_id.py section0.xml
    # → 1000000008

    # List all existing IDs (for debugging)
    python next_id.py document.hwpx --list
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

PARA_ID_RE = re.compile(r'<hp:p\s[^>]*\bid="(\d+)"')
TBL_ID_RE = re.compile(r'<hp:tbl\s[^>]*\bid="(\d+)"')
PLACEHOLDER_IDS = {0, 2147483648}
SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")

# IDs below this are framework-reserved in Skeleton templates
MIN_USER_ID = 1_000_000_000


def collect_ids(xml_str: str) -> set[int]:
    ids: set[int] = set()
    for m in PARA_ID_RE.finditer(xml_str):
        ids.add(int(m.group(1)))
    for m in TBL_ID_RE.finditer(xml_str):
        ids.add(int(m.group(1)))
    return ids - PLACEHOLDER_IDS


def get_ids_from_hwpx(path: Path) -> set[int]:
    all_ids: set[int] = set()
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            if SECTION_RE.match(name):
                xml_str = zf.read(name).decode("utf-8")
                all_ids |= collect_ids(xml_str)
    return all_ids


def get_ids_from_xml(path: Path) -> set[int]:
    return collect_ids(path.read_bytes().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Get next available hp:p ID(s) for safe paragraph insertion"
    )
    parser.add_argument("input", help="Input .hwpx file or section XML")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of IDs to generate (default: 1)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all existing non-placeholder IDs",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    is_hwpx = input_path.suffix.lower() == ".hwpx"
    existing = get_ids_from_hwpx(input_path) if is_hwpx else get_ids_from_xml(input_path)

    if args.list:
        sorted_ids = sorted(existing)
        print(f"Existing IDs ({len(sorted_ids)} total):")
        for i in sorted_ids:
            print(f"  {i}")
        return

    if existing:
        max_id = max(existing)
        start = max(max_id + 1, MIN_USER_ID)
    else:
        start = MIN_USER_ID

    new_ids = list(range(start, start + args.count))
    print(" ".join(str(i) for i in new_ids))


if __name__ == "__main__":
    main()
