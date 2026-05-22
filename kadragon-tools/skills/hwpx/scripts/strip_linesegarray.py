#!/usr/bin/env python3
"""Strip stale <hp:linesegarray> elements from HWPX section XML.

linesegarray stores the layout engine's line-break cache. After text is
modified the cached values no longer match the content, causing HWP to
display "document may be damaged or altered" warnings. Removing the element
is safe — HWP recomputes it on open.

Usage:
    # Write to new file (safe default)
    python strip_linesegarray.py input.hwpx --output clean.hwpx

    # Modify in-place
    python strip_linesegarray.py input.hwpx --inplace

    # Strip a raw section XML (not HWPX)
    python strip_linesegarray.py section0.xml --output section0_clean.xml
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
import shutil
import sys
import zipfile
from pathlib import Path

LINESEG_RE = re.compile(r"<hp:linesegarray>.*?</hp:linesegarray>", re.DOTALL)
SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")


def strip_bytes(data: bytes) -> tuple[bytes, int]:
    xml_str = data.decode("utf-8")
    new_str, count = LINESEG_RE.subn("", xml_str)
    return new_str.encode("utf-8"), count


def strip_hwpx(input_path: Path, output_path: Path) -> int:
    total_removed = 0
    entries: list[tuple[zipfile.ZipInfo, bytes]] = []

    with zipfile.ZipFile(input_path, "r") as zin:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if SECTION_RE.match(info.filename):
                data, count = strip_bytes(data)
                if count:
                    print(f"  {info.filename}: removed {count} linesegarray")
                    total_removed += count
            entries.append((info, data))

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in entries:
            ct = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zout.writestr(info.filename, data, compress_type=ct)

    return total_removed


def strip_xml_file(input_path: Path, output_path: Path) -> int:
    data, count = strip_bytes(input_path.read_bytes())
    output_path.write_bytes(data)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip stale hp:linesegarray elements from HWPX or section XML"
    )
    parser.add_argument("input", help="Input .hwpx or section XML file")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument(
        "--inplace", action="store_true", help="Modify input file in-place"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    if args.inplace and args.output:
        print("Error: --inplace and --output are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if args.inplace:
        tmp = input_path.with_suffix(".tmp")
        output_path = tmp
    elif args.output:
        output_path = Path(args.output)
    else:
        print("Error: specify --output or --inplace", file=sys.stderr)
        sys.exit(1)

    is_hwpx = input_path.suffix.lower() == ".hwpx"

    if is_hwpx:
        count = strip_hwpx(input_path, output_path)
    else:
        count = strip_xml_file(input_path, output_path)

    if args.inplace:
        shutil.move(str(tmp), str(input_path))
        output_path = input_path

    if count:
        print(f"STRIPPED: {output_path} (removed {count} linesegarray elements)")
    else:
        print(f"CLEAN: no linesegarray found in {input_path}")


if __name__ == "__main__":
    main()
