#!/usr/bin/env python3
"""Pack a directory back into an HWPX (ZIP) file.

The mimetype file is stored as the first entry with ZIP_STORED (no compression),
per OPC packaging conventions.

Usage:
    python pack.py input_dir/ output.hwpx
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
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


ORDER_MANIFEST = ".hwpx_pack_order"


def pack(input_dir: str, hwpx_path: str) -> None:
    """Create HWPX archive from a directory.

    If unpack.py left a .hwpx_pack_order manifest, the original entry order
    and per-entry compression type are reproduced exactly (lossless
    round-trip). Otherwise falls back to mimetype-first + sorted order.
    """

    root = Path(input_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Directory not found: {input_dir}")

    mimetype_file = root / "mimetype"
    if not mimetype_file.is_file():
        raise FileNotFoundError(
            f"Missing required 'mimetype' file in {input_dir}"
        )

    all_files = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).as_posix() != ORDER_MANIFEST
    )

    manifest_path = root / ORDER_MANIFEST
    ordered: list[tuple[int, str]] = []
    if manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ctype_str, name = line.split("\t", 1)
            ordered.append((int(ctype_str), name))

    with ZipFile(hwpx_path, "w", ZIP_DEFLATED) as zf:
        written: set[str] = set()

        if ordered:
            # Reproduce original entry order and compression exactly.
            for ctype, name in ordered:
                full_path = root / name
                if not full_path.is_file():
                    continue  # entry deleted since unpack
                ct = ZIP_STORED if name == "mimetype" else ctype
                zf.write(full_path, name, compress_type=ct)
                written.add(name)
            # Append any files added after unpack (not in manifest).
            for rel_path in all_files:
                if rel_path not in written:
                    zf.write(root / rel_path, rel_path, compress_type=ZIP_DEFLATED)
        else:
            # No manifest: mimetype first, remaining entries sorted.
            zf.write(mimetype_file, "mimetype", compress_type=ZIP_STORED)
            for rel_path in all_files:
                if rel_path != "mimetype":
                    zf.write(root / rel_path, rel_path, compress_type=ZIP_DEFLATED)

    count = len(all_files)
    mode = "manifest order" if ordered else "sorted (no manifest)"
    print(f"Packed: {input_dir} -> {hwpx_path}")
    print(f"  Files: {count} entries (mimetype first, ZIP_STORED; {mode})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pack a directory into an HWPX (ZIP) file"
    )
    parser.add_argument("input", help="Input directory path")
    parser.add_argument("output", help="Output .hwpx file path")
    args = parser.parse_args()

    if not os.path.isdir(args.input):
        print(f"Error: Directory not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    pack(args.input, args.output)


if __name__ == "__main__":
    main()
