#!/usr/bin/env python3
"""Validate the structural integrity of an HWPX file.

Checks:
  - Valid ZIP archive
  - Required files present (mimetype, content.hpf, header.xml, section0.xml)
  - mimetype content is correct, first entry, ZIP_STORED
  - All XML files are well-formed
  - secCnt in header.xml matches actual section count in archive
  - itemCnt attributes match actual child element counts (charProperties,
    paraProperties, borderFills, fontfaces)
  - IDRef cross-validation: charPrIDRef/paraPrIDRef/borderFillIDRef in
    section XML all resolve to defined IDs in header.xml
  - hp:p ID uniqueness across all sections. NOTE: real-world HWPX files can
    contain pre-existing duplicate IDs that HWP tolerates. Pass --baseline to
    compare against the source document; only NEWLY introduced duplicates are
    then treated as errors.

Usage:
    python validate.py document.hwpx
    python validate.py document.hwpx --strict              # warnings -> errors
    python validate.py result.hwpx --baseline original.hwpx  # diff-aware ID check
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
from collections import Counter
from pathlib import Path
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from lxml import etree

REQUIRED_FILES = [
    "mimetype",
    "Contents/content.hpf",
    "Contents/header.xml",
    "Contents/section0.xml",
]

EXPECTED_MIMETYPE = "application/hwp+zip"

NS_HH = "http://www.hancom.co.kr/hwpml/2011/head"
NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS_HS = "http://www.hancom.co.kr/hwpml/2011/section"
NS = {"hh": NS_HH, "hp": NS_HP, "hs": NS_HS}

SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")
PARA_ID_RE = re.compile(r'<hp:p\s[^>]*\bid="(\d+)"')
PLACEHOLDER_IDS = {"0", "2147483648"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _ids_from_xml_str(xml_str: str) -> list[str]:
    return [i for i in PARA_ID_RE.findall(xml_str) if i not in PLACEHOLDER_IDS]


def _dup_para_ids(hwpx_path: str) -> set[str]:
    """Return non-placeholder hp:p IDs that are duplicated within the file."""
    ids: list[str] = []
    try:
        with ZipFile(hwpx_path, "r") as zf:
            for name in zf.namelist():
                if SECTION_RE.match(name):
                    ids.extend(_ids_from_xml_str(zf.read(name).decode("utf-8")))
    except (BadZipFile, OSError):
        return set()
    return {i for i, n in Counter(ids).items() if n > 1}


def _check_itemcnt(root: etree._Element) -> list[str]:
    """Verify itemCnt attributes match actual child count in header.xml."""
    errors = []
    checks = [
        (".//hh:charProperties", "hh:charPr"),
        (".//hh:paraProperties", "hh:paraPr"),
        (".//hh:borderFills", "hh:borderFill"),
        (".//hh:fontfaces", "hh:fontface"),
    ]
    for parent_xpath, child_tag in checks:
        parent = root.find(parent_xpath, NS)
        if parent is None:
            continue
        declared = parent.get("itemCnt")
        if declared is None:
            continue
        child_local = child_tag.split(":")[1]
        child_ns = NS_HH
        actual = len(parent.findall(f"{{{child_ns}}}{child_local}"))
        if int(declared) != actual:
            errors.append(
                f"itemCnt mismatch in <{parent.tag.split('}')[1]}> "
                f"declared={declared}, actual={actual}"
            )
    return errors


def _collect_defined_ids(header_root: etree._Element) -> dict[str, set[str]]:
    """Collect all defined IDs for charPr, paraPr, borderFill from header.xml."""
    defined: dict[str, set[str]] = {
        "charPrIDRef": set(),
        "paraPrIDRef": set(),
        "borderFillIDRef": set(),
    }
    for el in header_root.findall(f".//{{{NS_HH}}}charPr"):
        if el.get("id") is not None:
            defined["charPrIDRef"].add(el.get("id"))
    for el in header_root.findall(f".//{{{NS_HH}}}paraPr"):
        if el.get("id") is not None:
            defined["paraPrIDRef"].add(el.get("id"))
    for el in header_root.findall(f".//{{{NS_HH}}}borderFill"):
        if el.get("id") is not None:
            defined["borderFillIDRef"].add(el.get("id"))
    return defined


def _check_idref(section_root: etree._Element, defined: dict[str, set[str]], section_name: str) -> list[str]:
    """Validate that all IDRef values in section XML resolve in header.xml."""
    errors = []
    checks = [
        (f".//{{{NS_HP}}}run", "charPrIDRef"),
        (f".//{{{NS_HP}}}p", "paraPrIDRef"),
        (f".//{{{NS_HP}}}tbl", "borderFillIDRef"),
        (f".//{{{NS_HP}}}tc", "borderFillIDRef"),
    ]
    for xpath, attr in checks:
        dangling: set[str] = set()
        for el in section_root.findall(xpath):
            val = el.get(attr)
            if val is not None and val not in defined[attr]:
                dangling.add(val)
        if dangling:
            errors.append(
                f"{section_name}: undefined {attr} value(s): {sorted(dangling)}"
            )
    return errors


# ── main validation ───────────────────────────────────────────────────────────

def validate(hwpx_path: str, baseline_dupes: set | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). errors = must fix; warnings = should fix.

    baseline_dupes: duplicate hp:p IDs known to exist in the source document.
    Duplicates shared with the baseline become warnings; only newly introduced
    duplicates are errors. When None, every duplicate is an error.
    """
    errors: list[str] = []
    warnings: list[str] = []
    path = Path(hwpx_path)

    if not path.is_file():
        return [f"File not found: {hwpx_path}"], []

    try:
        zf = ZipFile(hwpx_path, "r")
    except BadZipFile:
        return [f"Not a valid ZIP archive: {hwpx_path}"], []

    with zf:
        names = zf.namelist()

        # ── Required files ────────────────────────────────────────────────
        for required in REQUIRED_FILES:
            if required not in names:
                errors.append(f"Missing required file: {required}")

        # ── mimetype checks ───────────────────────────────────────────────
        if "mimetype" in names:
            content = zf.read("mimetype").decode("utf-8").strip()
            if content != EXPECTED_MIMETYPE:
                errors.append(f"Bad mimetype: expected '{EXPECTED_MIMETYPE}', got '{content}'")
            if names[0] != "mimetype":
                errors.append(f"mimetype is not the first ZIP entry (index {names.index('mimetype')})")
            info = zf.getinfo("mimetype")
            if info.compress_type != ZIP_STORED:
                errors.append("mimetype must be ZIP_STORED (uncompressed)")

        # ── XML well-formedness ───────────────────────────────────────────
        parsed: dict[str, etree._Element] = {}
        for name in names:
            if name.endswith(".xml") or name.endswith(".hpf"):
                try:
                    root = etree.fromstring(zf.read(name))
                    parsed[name] = root
                except etree.XMLSyntaxError as e:
                    errors.append(f"Malformed XML in {name}: {e}")

        # Abort deep checks if header/section can't be parsed
        header_root = parsed.get("Contents/header.xml")
        if header_root is None:
            return errors, warnings

        # ── secCnt vs actual section files ───────────────────────────────
        sec_cnt_declared = int(header_root.get("secCnt", "0"))
        actual_sections = sorted(
            n for n in names if SECTION_RE.match(n)
        )
        if sec_cnt_declared != len(actual_sections):
            errors.append(
                f"secCnt mismatch: header declares secCnt={sec_cnt_declared}, "
                f"archive has {len(actual_sections)} section file(s)"
            )

        # ── itemCnt consistency ───────────────────────────────────────────
        errors.extend(_check_itemcnt(header_root))

        # ── IDRef cross-validation ────────────────────────────────────────
        defined_ids = _collect_defined_ids(header_root)

        # ── hp:p ID uniqueness + IDRef per section ────────────────────────
        all_para_ids: list[str] = []
        for sec_name in actual_sections:
            sec_root = parsed.get(sec_name)
            if sec_root is None:
                continue
            xml_str = zf.read(sec_name).decode("utf-8")
            all_para_ids.extend(_ids_from_xml_str(xml_str))
            errors.extend(_check_idref(sec_root, defined_ids, sec_name))

        dupes = {i for i, n in Counter(all_para_ids).items() if n > 1}
        if dupes:
            base = baseline_dupes or set()
            new_dupes = sorted(dupes - base)
            preexisting = sorted(dupes & base)
            if new_dupes:
                errors.append(f"Duplicate hp:p IDs introduced (not in baseline): {new_dupes}")
            if preexisting:
                warnings.append(
                    f"Pre-existing duplicate hp:p IDs (shared with baseline, HWP tolerates): {preexisting}"
                )

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate HWPX file structure and internal consistency"
    )
    parser.add_argument("input", help="Path to .hwpx file")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    parser.add_argument(
        "--baseline",
        help="Reference .hwpx (source document); duplicate hp:p IDs shared with "
             "it are downgraded from errors to warnings",
    )
    args = parser.parse_args()

    baseline_dupes = _dup_para_ids(args.baseline) if args.baseline else None
    errors, warnings = validate(args.input, baseline_dupes)

    if warnings:
        print(f"WARNINGS: {args.input}")
        for w in warnings:
            print(f"  ~ {w}")

    if errors:
        print(f"INVALID: {args.input}", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    if args.strict and warnings:
        sys.exit(1)

    print(f"VALID: {args.input}")
    print("  All structural checks passed.")


if __name__ == "__main__":
    main()
