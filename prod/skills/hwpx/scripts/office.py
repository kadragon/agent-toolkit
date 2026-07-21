#!/usr/bin/env python3
"""HWPX ZIP packaging operations.

Usage:
    python office.py unpack input.hwpx output_dir/
    python office.py pack input_dir/ output.hwpx
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from _common import configure_io, die

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


def _run_tests() -> None:
    import tempfile

    failures = []

    # OFFICE-1: pack() with no manifest -> mimetype first, ZIP_STORED, rest ZIP_DEFLATED
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "in"
            root.mkdir()
            (root / "mimetype").write_text("application/hwp+zip", encoding="utf-8")
            (root / "Contents").mkdir()
            (root / "Contents" / "content.hpf").write_text("<x/>", encoding="utf-8")
            out = Path(d) / "out.hwpx"
            pack(str(root), str(out))
            with ZipFile(out, "r") as zf:
                names = zf.namelist()
                mimetype_info = zf.getinfo("mimetype")
                content_info = zf.getinfo("Contents/content.hpf")
            checks = [
                names[0] == "mimetype",
                mimetype_info.compress_type == ZIP_STORED,
                content_info.compress_type == ZIP_DEFLATED,
            ]
            if all(checks):
                print("OFFICE-1 PASS: no-manifest pack orders mimetype first, ZIP_STORED")
            else:
                failures.append(f"OFFICE-1 FAIL: {checks!r} (names={names!r})")
    except Exception as e:
        failures.append(f"OFFICE-1 FAIL: {e!r}")

    # OFFICE-2: unpack -> pack round trip preserves entry order and compress types
    try:
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "original.hwpx"
            with ZipFile(original, "w") as zf:
                zf.writestr("mimetype", "application/hwp+zip", compress_type=ZIP_STORED)
                zf.writestr("Contents/header.xml", "<h/>", compress_type=ZIP_DEFLATED)
                zf.writestr("Contents/section0.xml", "<s/>", compress_type=ZIP_STORED)
            unpack_dir = Path(d) / "unpacked"
            unpack(str(original), str(unpack_dir))
            manifest_path = unpack_dir / ORDER_MANIFEST
            if not manifest_path.is_file():
                failures.append("OFFICE-2 FAIL: manifest not written")
            else:
                repacked = Path(d) / "repacked.hwpx"
                pack(str(unpack_dir), str(repacked))
                with ZipFile(original, "r") as zorig, ZipFile(repacked, "r") as zrep:
                    orig_names = zorig.namelist()
                    rep_names = [n for n in zrep.namelist() if n != ORDER_MANIFEST]
                    orig_types = {i.filename: i.compress_type for i in zorig.infolist()}
                    rep_types = {i.filename: i.compress_type for i in zrep.infolist() if i.filename != ORDER_MANIFEST}
                if rep_names == orig_names and rep_types == orig_types:
                    print("OFFICE-2 PASS: unpack->pack round trip preserves order + compress type")
                else:
                    failures.append(
                        f"OFFICE-2 FAIL: order/types not preserved: {rep_names!r} vs {orig_names!r}, "
                        f"{rep_types!r} vs {orig_types!r}"
                    )
    except Exception as e:
        failures.append(f"OFFICE-2 FAIL: {e!r}")

    # OFFICE-3: pack() raises FileNotFoundError when mimetype is missing
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "in"
            root.mkdir()
            (root / "Contents").mkdir()
            (root / "Contents" / "content.hpf").write_text("<x/>", encoding="utf-8")
            try:
                pack(str(root), str(Path(d) / "out.hwpx"))
                failures.append("OFFICE-3 FAIL: missing mimetype did not raise")
            except FileNotFoundError:
                print("OFFICE-3 PASS: missing mimetype raises FileNotFoundError")
    except Exception as e:
        failures.append(f"OFFICE-3 FAIL: {e!r}")

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All office tests passed")
    sys.exit(0)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    configure_io()
    if sys.argv[1:] == ["--test"]:
        _run_tests()
        return
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
            die(f"File not found: {args.input}")
        unpack(args.input, args.output)

    elif args.cmd == "pack":
        if not os.path.isdir(args.input):
            die(f"Directory not found: {args.input}")
        try:
            pack(args.input, args.output)
        except FileNotFoundError as e:
            die(str(e))


if __name__ == "__main__":
    main()
