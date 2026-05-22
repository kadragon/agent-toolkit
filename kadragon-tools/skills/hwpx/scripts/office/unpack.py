#!/usr/bin/env python3
"""Unpack an HWPX file into a directory.

XML files are written as-is (raw bytes) to preserve Hancom namespace prefixes,
standalone declarations, and compact serialization. Repacking with pack.py
after editing produces a valid HWPX without re-serialization artifacts.

Usage:
    python unpack.py input.hwpx output_dir/
"""
# Windows console: emit UTF-8 (avoid cp949 mojibake)
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import os
import sys
from pathlib import Path
from zipfile import ZipFile


ORDER_MANIFEST = ".hwpx_pack_order"


def unpack(hwpx_path: str, output_dir: str) -> None:
    """Extract HWPX archive preserving raw bytes for all files.

    Also records the original entry order and per-entry compression type in
    a manifest file so pack.py can reproduce the archive faithfully. HWPX
    readers can be sensitive to entry order, so a lossless round-trip matters.
    """

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    manifest = []
    with ZipFile(hwpx_path, "r") as zf:
        for entry in zf.infolist():
            data = zf.read(entry.filename)
            dest = output / entry.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            manifest.append(f"{entry.compress_type}\t{entry.filename}")

    (output / ORDER_MANIFEST).write_text("\n".join(manifest), encoding="utf-8")

    print(f"Unpacked: {hwpx_path} -> {output_dir}")
    print(f"  Files: {len(manifest)} entries (order manifest written)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unpack HWPX file into a directory (raw bytes, no re-serialization)"
    )
    parser.add_argument("input", help="Path to .hwpx file")
    parser.add_argument("output", help="Output directory path")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    unpack(args.input, args.output)


if __name__ == "__main__":
    main()
