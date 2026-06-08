#!/usr/bin/env python3
"""HWPX ZIP packaging operations.

Usage:
    python office.py unpack input.hwpx output_dir/
    python office.py pack input_dir/ output.hwpx
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import argparse
import os
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

ORDER_MANIFEST = ".hwpx_pack_order"


# ── unpack ────────────────────────────────────────────────────────────────────

def unpack(hwpx_path: str, output_dir: str) -> None:
    """Extract HWPX archive preserving raw bytes for all files.

    Records original entry order and per-entry compression type in a manifest
    so pack can reproduce the archive faithfully. HWPX readers can be sensitive
    to entry order, so a lossless round-trip matters.
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


# ── pack ──────────────────────────────────────────────────────────────────────

def pack(input_dir: str, hwpx_path: str) -> None:
    """Create HWPX archive from a directory.

    If unpack left a .hwpx_pack_order manifest, original entry order and
    per-entry compression type are reproduced exactly. Otherwise falls back
    to mimetype-first + sorted order.
    """
    root = Path(input_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Directory not found: {input_dir}")

    mimetype_file = root / "mimetype"
    if not mimetype_file.is_file():
        raise FileNotFoundError(f"Missing required 'mimetype' file in {input_dir}")

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
            for ctype, name in ordered:
                full_path = root / name
                if not full_path.is_file():
                    continue
                ct = ZIP_STORED if name == "mimetype" else ctype
                zf.write(full_path, name, compress_type=ct)
                written.add(name)
            for rel_path in all_files:
                if rel_path not in written:
                    zf.write(root / rel_path, rel_path, compress_type=ZIP_DEFLATED)
        else:
            zf.write(mimetype_file, "mimetype", compress_type=ZIP_STORED)
            for rel_path in all_files:
                if rel_path != "mimetype":
                    zf.write(root / rel_path, rel_path, compress_type=ZIP_DEFLATED)

    count = len(all_files)
    mode = "manifest order" if ordered else "sorted (no manifest)"
    print(f"Packed: {input_dir} -> {hwpx_path}")
    print(f"  Files: {count} entries (mimetype first, ZIP_STORED; {mode})")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HWPX ZIP packaging operations"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_unpack = sub.add_parser("unpack", help="Extract HWPX to directory (raw bytes, no re-serialization)")
    p_unpack.add_argument("input", help="Path to .hwpx file")
    p_unpack.add_argument("output", help="Output directory path")

    p_pack = sub.add_parser("pack", help="Pack directory into HWPX (mimetype first, ZIP_STORED)")
    p_pack.add_argument("input", help="Input directory path")
    p_pack.add_argument("output", help="Output .hwpx file path")

    args = parser.parse_args()

    if args.cmd == "unpack":
        if not os.path.isfile(args.input):
            print(f"Error: File not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        unpack(args.input, args.output)

    elif args.cmd == "pack":
        if not os.path.isdir(args.input):
            print(f"Error: Directory not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        try:
            pack(args.input, args.output)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
