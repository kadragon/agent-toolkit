#!/usr/bin/env python3
"""Safe text replacement in HWPX section XML.

Bundles the entire safe-modification pipeline (Rules 19-23):
  1. str.replace() on raw XML bytes (no lxml re-serialization)
  2. Strip all hp:linesegarray (stale layout cache)
  3. Verify hp:p ID uniqueness (crash guard)
  4. Write output HWPX preserving original ZIP entry order and compression

Usage:
    python patch_section.py input.hwpx "기존 텍스트" "새 텍스트" --output result.hwpx
    python patch_section.py input.hwpx "기존" "새" --count 0 --output result.hwpx  # replace all
    python patch_section.py input.hwpx "기존" "새" --section 1 --output result.hwpx  # section1.xml
    python patch_section.py input.hwpx "기존" "새" --after "앵커" --output result.hwpx  # only after anchor
    python patch_section.py input.hwpx "기존" "새" --dry-run   # preview only

--after restricts replacement to the region following the first occurrence of
the anchor string. Use it when the same text appears in several places (e.g. a
summary table and the body) and only the later one should change.
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


def _strip_linesegarray(xml_str: str) -> tuple[str, int]:
    new_str, count = LINESEG_RE.subn("", xml_str)
    return new_str, count


def _check_para_ids(xml_str: str) -> list[str]:
    errors = []
    ids = [i for i in PARA_ID_RE.findall(xml_str) if i not in PLACEHOLDER_IDS]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        errors.append(f"Duplicate hp:p IDs detected (HWP crash risk): {dupes}")
    return errors


def _patch_xml(
    xml_bytes: bytes, old: str, new: str, count: int, after: str | None = None
) -> tuple[bytes, int, list[str]]:
    xml_str = xml_bytes.decode("utf-8")

    prefix = ""
    body = xml_str
    if after:
        idx = xml_str.find(after)
        if idx == -1:
            return xml_bytes, 0, [f'Anchor not found: "{after}"']
        split = idx + len(after)
        prefix, body = xml_str[:split], xml_str[split:]

    if count == 0:
        new_body = body.replace(old, new)
        replaced = body.count(old)
    else:
        new_body = body.replace(old, new, count)
        replaced = min(body.count(old), count)

    if replaced == 0:
        return xml_bytes, 0, []

    new_str, _ = _strip_linesegarray(prefix + new_body)
    errors = _check_para_ids(new_str)
    return new_str.encode("utf-8"), replaced, errors


def patch_hwpx(
    input_path: Path,
    output_path: Path,
    old_text: str,
    new_text: str,
    replace_count: int,
    section_index: int,
    after: str | None = None,
) -> tuple[int, list[str]]:
    target = f"Contents/section{section_index}.xml"
    entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    total_replaced = 0
    all_errors: list[str] = []

    with zipfile.ZipFile(input_path, "r") as zin:
        if target not in zin.namelist():
            return 0, [f"Section not found: {target}"]

        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == target:
                data, replaced, errors = _patch_xml(
                    data, old_text, new_text, replace_count, after
                )
                total_replaced += replaced
                all_errors.extend(errors)
            entries.append((info, data))

    if total_replaced == 0:
        return 0, all_errors or [f'Text not found in {target}: "{old_text}"']

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in entries:
            ct = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zout.writestr(info.filename, data, compress_type=ct)

    return total_replaced, all_errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safe text replacement in HWPX — str.replace + linesegarray strip + ID check"
    )
    parser.add_argument("input", help="Input .hwpx file")
    parser.add_argument("old_text", help="Text to replace")
    parser.add_argument("new_text", help="Replacement text")
    parser.add_argument("--output", "-o", help="Output .hwpx file (required unless --dry-run)")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Max replacements per section (0 = all, default: 1)",
    )
    parser.add_argument(
        "--section",
        type=int,
        default=0,
        help="Section index to patch (default: 0 → section0.xml)",
    )
    parser.add_argument(
        "--after",
        help="Only replace occurrences after the first match of this anchor string",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview replacement without writing output",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and not args.output:
        print("Error: --output required (or use --dry-run)", file=sys.stderr)
        sys.exit(1)

    target = f"Contents/section{args.section}.xml"

    if args.dry_run:
        with zipfile.ZipFile(input_path, "r") as zin:
            if target not in zin.namelist():
                print(f"Error: {target} not found in archive", file=sys.stderr)
                sys.exit(1)
            xml_str = zin.read(target).decode("utf-8")

        scope = xml_str
        if args.after:
            idx = xml_str.find(args.after)
            if idx == -1:
                print(f'DRY RUN: anchor not found: "{args.after}"', file=sys.stderr)
                sys.exit(1)
            scope = xml_str[idx + len(args.after):]
        count = scope.count(args.old_text)
        effective = count if args.count == 0 else min(count, args.count)
        region = " (after anchor)" if args.after else ""
        print(f"DRY RUN: found {count} occurrence(s) of target text in {target}{region}")
        print(f"  Would replace: {effective}")
        if count == 0:
            print(f'  Text not found: "{args.old_text}"')
        sys.exit(0)

    output_path = Path(args.output)
    replaced, errors = patch_hwpx(
        input_path, output_path, args.old_text, args.new_text,
        args.count, args.section, args.after,
    )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        if replaced == 0:
            sys.exit(1)

    if replaced > 0:
        print(f"PATCHED: {output_path}")
        print(f"  Replacements: {replaced} in section{args.section}.xml")
        print(f"  linesegarray stripped, ID uniqueness verified")
        if errors:
            print(f"  WARNINGS: {len(errors)}")


if __name__ == "__main__":
    main()
