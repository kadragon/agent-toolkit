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

import argparse
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from _common import LINESEG_RE, SECTION_RE, check_para_ids, configure_io, die


# ── extract ───────────────────────────────────────────────────────────────────

def _local(tag: object) -> str:
    if isinstance(tag, str):
        return tag.rsplit("}", 1)[-1]
    return ""


def _walk(el: object, in_tbl: bool, lines: list[str], cur: list[str], include_tables: bool, skipped: list[int]) -> None:
    for child in el:
        tag = _local(child.tag)
        if tag == "tbl":
            _walk(child, True, lines, cur, include_tables, skipped)
        elif tag == "p":
            if cur:
                lines.append("".join(cur))
                cur.clear()
            _walk(child, in_tbl, lines, cur, include_tables, skipped)
            if cur:
                lines.append("".join(cur))
                cur.clear()
        elif tag == "t":
            if (not in_tbl) or include_tables:
                cur.append(child.text or "")
            elif in_tbl and not include_tables:
                skipped[0] += 1
        else:
            _walk(child, in_tbl, lines, cur, include_tables, skipped)


def _section_lines(xml_bytes: bytes, include_tables: bool) -> tuple[list[str], int]:
    root = ET.fromstring(xml_bytes)
    lines: list[str] = []
    cur: list[str] = []
    skipped = [0]
    _walk(root, False, lines, cur, include_tables, skipped)
    if cur:
        lines.append("".join(cur))
    return [ln for ln in lines if ln.strip()], skipped[0]


def _iter_sections(hwpx_path: str):  # type: ignore[return]
    with ZipFile(hwpx_path, "r") as zf:
        names = sorted(
            (n for n in zf.namelist() if SECTION_RE.match(n)),
            key=lambda n: int(SECTION_RE.match(n).group(1)),  # type: ignore[union-attr]
        )
        for name in names:
            yield zf.read(name)


def extract_plain(hwpx_path: str, *, include_tables: bool = False) -> tuple[str, int]:
    out: list[str] = []
    total_skipped = 0
    for xml_bytes in _iter_sections(hwpx_path):
        lines, skipped = _section_lines(xml_bytes, include_tables)
        out.extend(lines)
        total_skipped += skipped
    return "\n".join(out), total_skipped


def extract_markdown(hwpx_path: str) -> str:
    blocks: list[str] = []
    for xml_bytes in _iter_sections(hwpx_path):
        lines, _ = _section_lines(xml_bytes, include_tables=True)
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(b for b in blocks if b.strip())


def cmd_extract(args: argparse.Namespace) -> None:
    if not Path(args.input).is_file():
        die(f"File not found: {args.input}")
    try:
        if args.format == "markdown":
            result = extract_markdown(args.input)
            skipped = 0
        else:
            result, skipped = extract_plain(args.input, include_tables=args.include_tables)
    except BadZipFile:
        die(f"not a valid HWPX (ZIP) file: {args.input}")
    except ET.ParseError as e:
        die(f"malformed section XML: {e}")
    if args.format != "markdown" and skipped > 0:
        print(f"[warn] {skipped} table text node(s) omitted; pass --include-tables to include", file=sys.stderr)
    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"Extracted to: {args.output}", file=sys.stderr)
    else:
        print(result)


# ── patch ─────────────────────────────────────────────────────────────────────

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
    errors = check_para_ids(new_str)
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
        die(f"File not found: {args.input}")
    if not args.dry_run and not args.output:
        die("--output required (or use --dry-run)")
    target = f"Contents/section{args.section}.xml"
    if args.dry_run:
        with zipfile.ZipFile(input_path, "r") as zin:
            if target not in zin.namelist():
                die(f"{target} not found in archive")
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


def _run_tests() -> None:
    failures = []

    _section_with_table = (
        '<?xml version="1.0"?>'
        '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:p><hp:run><hp:t>본문 텍스트</hp:t></hp:run></hp:p>'
        '<hp:tbl id="1000000003">'
        '<hp:tc><hp:subList>'
        '<hp:p><hp:run><hp:t>표 안 텍스트</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:tc>'
        '</hp:tbl>'
        '</hp:sec>'
    ).encode("utf-8")

    # TEXT-1: table text skipped by default, counted in skipped
    try:
        lines, skipped = _section_lines(_section_with_table, include_tables=False)
        if lines == ["본문 텍스트"] and skipped == 1:
            print("TEXT-1 PASS: table text skipped and counted")
        else:
            failures.append(f"TEXT-1 FAIL: lines={lines!r} skipped={skipped!r}")
    except Exception as e:
        failures.append(f"TEXT-1 FAIL: {e!r}")

    # TEXT-2: table text included when include_tables=True
    try:
        lines, skipped = _section_lines(_section_with_table, include_tables=True)
        if lines == ["본문 텍스트", "표 안 텍스트"] and skipped == 0:
            print("TEXT-2 PASS: table text included with include_tables=True")
        else:
            failures.append(f"TEXT-2 FAIL: lines={lines!r} skipped={skipped!r}")
    except Exception as e:
        failures.append(f"TEXT-2 FAIL: {e!r}")

    _plain_section = (
        '<?xml version="1.0"?>'
        '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:p id="0" paraPrIDRef="10"><hp:run><hp:t>기존 텍스트 반복 기존</hp:t></hp:run></hp:p>'
        '</hp:sec>'
    ).encode("utf-8")

    # TEXT-3: _patch_xml replaces one occurrence by default (count=1)
    try:
        new_bytes, replaced, errors = _patch_xml(_plain_section, "기존", "새로운", 1)
        text = new_bytes.decode("utf-8")
        if replaced == 1 and text.count("새로운") == 1 and text.count("기존") == 1 and not errors:
            print("TEXT-3 PASS: count=1 replaces first occurrence only")
        else:
            failures.append(f"TEXT-3 FAIL: replaced={replaced!r} errors={errors!r} text={text}")
    except Exception as e:
        failures.append(f"TEXT-3 FAIL: {e!r}")

    # TEXT-4: _patch_xml count=0 replaces all occurrences
    try:
        new_bytes, replaced, errors = _patch_xml(_plain_section, "기존", "새로운", 0)
        text = new_bytes.decode("utf-8")
        if replaced == 2 and "기존" not in text and not errors:
            print("TEXT-4 PASS: count=0 replaces all occurrences")
        else:
            failures.append(f"TEXT-4 FAIL: replaced={replaced!r} errors={errors!r} text={text}")
    except Exception as e:
        failures.append(f"TEXT-4 FAIL: {e!r}")

    # TEXT-5: _patch_xml with --after only replaces occurrences past the anchor
    try:
        new_bytes, replaced, errors = _patch_xml(
            _plain_section, "기존", "새로운", 0, after="반복 "
        )
        text = new_bytes.decode("utf-8")
        if replaced == 1 and text.count("새로운") == 1 and "기존 텍스트 반복" in text and not errors:
            print("TEXT-5 PASS: --after scopes replacement past anchor")
        else:
            failures.append(f"TEXT-5 FAIL: replaced={replaced!r} errors={errors!r} text={text}")
    except Exception as e:
        failures.append(f"TEXT-5 FAIL: {e!r}")

    # TEXT-6: _patch_xml strips linesegarray from the patched result
    _section_with_lineseg = (
        '<?xml version="1.0"?>'
        '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:linesegarray><hp:lineseg textpos="0"/></hp:linesegarray>'
        '<hp:p id="0"><hp:run><hp:t>기존</hp:t></hp:run></hp:p>'
        '</hp:sec>'
    ).encode("utf-8")
    try:
        new_bytes, replaced, errors = _patch_xml(_section_with_lineseg, "기존", "새로운", 1)
        text = new_bytes.decode("utf-8")
        if replaced == 1 and "linesegarray" not in text and not errors:
            print("TEXT-6 PASS: linesegarray stripped after patch")
        else:
            failures.append(f"TEXT-6 FAIL: replaced={replaced!r} errors={errors!r} text={text}")
    except Exception as e:
        failures.append(f"TEXT-6 FAIL: {e!r}")

    # TEXT-7: _patch_xml surfaces duplicate hp:p id errors via check_para_ids
    _section_dup_ids = (
        '<?xml version="1.0"?>'
        '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:p id="5"><hp:run><hp:t>기존</hp:t></hp:run></hp:p>'
        '<hp:p id="5"><hp:run><hp:t>다른</hp:t></hp:run></hp:p>'
        '</hp:sec>'
    ).encode("utf-8")
    try:
        _, replaced, errors = _patch_xml(_section_dup_ids, "기존", "새로운", 1)
        if replaced == 1 and errors and "5" in errors[0]:
            print("TEXT-7 PASS: duplicate hp:p id flagged after patch")
        else:
            failures.append(f"TEXT-7 FAIL: replaced={replaced!r} errors={errors!r}")
    except Exception as e:
        failures.append(f"TEXT-7 FAIL: {e!r}")

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All text tests passed")
    sys.exit(0)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    configure_io()
    if sys.argv[1:] == ["--test"]:
        _run_tests()
        return
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
