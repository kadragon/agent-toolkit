#!/usr/bin/env python3
"""HWPX text extraction and safe text replacement.

Usage:
    python text.py extract document.hwpx
    python text.py extract document.hwpx --format markdown
    python text.py extract document.hwpx --include-tables
    python text.py extract document.hwpx --output out.txt
    python text.py patch input.hwpx "기존 텍스트" "새 텍스트" --output result.hwpx
    python text.py patch input.hwpx "기존" "새" --count 0 --output result.hwpx
    python text.py patch input.hwpx "기존" "새" --after "앵커" --output result.hwpx
    python text.py patch input.hwpx "기존" "새" --dry-run
"""
from __future__ import annotations

import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import argparse
import importlib.util
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from _common import LINESEG_RE, PARA_ID_RE, PLACEHOLDER_IDS

_HAS_LXML = importlib.util.find_spec("lxml") is not None

SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")


# ── extract ───────────────────────────────────────────────────────────────────

def _local(tag: object) -> str:
    if isinstance(tag, str):
        return tag.rsplit("}", 1)[-1]
    return ""


def _walk(el: object, in_tbl: bool, lines: list[str], cur: list[str], include_tables: bool) -> None:
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


def _section_lines(xml_bytes: bytes, include_tables: bool) -> list[str]:
    from lxml import etree
    root = etree.fromstring(xml_bytes)
    lines: list[str] = []
    cur: list[str] = []
    _walk(root, False, lines, cur, include_tables)
    if cur:
        lines.append("".join(cur))
    return [ln for ln in lines if ln.strip()]


def _iter_sections(hwpx_path: str):  # type: ignore[return]
    with ZipFile(hwpx_path, "r") as zf:
        names = sorted(
            (n for n in zf.namelist() if SECTION_RE.match(n)),
            key=lambda n: int(SECTION_RE.match(n).group(1)),  # type: ignore[union-attr]
        )
        for name in names:
            yield zf.read(name)


def extract_plain(hwpx_path: str, *, include_tables: bool = False) -> str:
    out: list[str] = []
    for xml_bytes in _iter_sections(hwpx_path):
        out.extend(_section_lines(xml_bytes, include_tables))
    return "\n".join(out)


def extract_markdown(hwpx_path: str) -> str:
    blocks: list[str] = []
    for xml_bytes in _iter_sections(hwpx_path):
        blocks.append("\n".join(_section_lines(xml_bytes, include_tables=True)))
    return "\n\n---\n\n".join(b for b in blocks if b.strip())


def cmd_extract(args: argparse.Namespace) -> None:
    if not _HAS_LXML:
        print("Error: lxml required for 'extract'. Install: pip install lxml", file=sys.stderr)
        sys.exit(1)
    from lxml import etree
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
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        print(result)


# ── patch ─────────────────────────────────────────────────────────────────────

def _check_para_ids(xml_str: str) -> list[str]:
    ids = [i for i in PARA_ID_RE.findall(xml_str) if i not in PLACEHOLDER_IDS]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        return [f"Duplicate hp:p IDs detected (HWP crash risk): {dupes}"]
    return []


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
    new_str, _ = LINESEG_RE.subn("", prefix + new_body)
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
                data, replaced, errors = _patch_xml(data, old_text, new_text, replace_count, after)
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


def cmd_patch(args: argparse.Namespace) -> None:
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
        print("  linesegarray stripped, ID uniqueness verified")
        if errors:
            print(f"  WARNINGS: {len(errors)}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="HWPX text extraction and safe replacement")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # extract
    p_ex = sub.add_parser("extract", help="Extract text from an HWPX document")
    p_ex.add_argument("input", help="Path to .hwpx file")
    p_ex.add_argument("--format", "-f", choices=["plain", "markdown"], default="plain",
                      help="Output format (default: plain)")
    p_ex.add_argument("--include-tables", action="store_true",
                      help="Include text from tables (plain mode; markdown always includes)")
    p_ex.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # patch
    p_patch = sub.add_parser("patch", help="Safe text replacement: str.replace + linesegarray strip + ID check")
    p_patch.add_argument("input", help="Input .hwpx file")
    p_patch.add_argument("old_text", help="Text to replace")
    p_patch.add_argument("new_text", help="Replacement text")
    p_patch.add_argument("--output", "-o", help="Output .hwpx file (required unless --dry-run)")
    p_patch.add_argument("--count", type=int, default=1,
                         help="Max replacements per section (0 = all, default: 1)")
    p_patch.add_argument("--section", type=int, default=0,
                         help="Section index to patch (default: 0 → section0.xml)")
    p_patch.add_argument("--after",
                         help="Only replace occurrences after the first match of this anchor string")
    p_patch.add_argument("--dry-run", action="store_true",
                         help="Preview replacement without writing output")

    args = parser.parse_args()

    if args.cmd == "extract":
        cmd_extract(args)
    elif args.cmd == "patch":
        cmd_patch(args)


if __name__ == "__main__":
    main()
