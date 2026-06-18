#!/usr/bin/env python3
"""HWPX structural validation and page-drift guard.

Usage:
    python validate.py validate document.hwpx
    python validate.py validate result.hwpx --baseline original.hwpx
    python validate.py validate document.hwpx --strict
    python validate.py page-guard --reference ref.hwpx --output result.hwpx
    python validate.py page-guard --reference ref.hwpx --output result.hwpx --json
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path
from typing import List, Tuple
from zipfile import ZIP_STORED, BadZipFile, ZipFile

import xml.etree.ElementTree as ET

from _common import MIN_READABLE_PT, SECTION_N_RE, PARA_ID_RE, PLACEHOLDER_IDS

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


# ── validate ──────────────────────────────────────────────────────────────────

def _ids_from_xml_str(xml_str: str) -> list[str]:
    return [i for i in PARA_ID_RE.findall(xml_str) if i not in PLACEHOLDER_IDS]


def _dup_para_ids(hwpx_path: str) -> set[str]:
    ids: list[str] = []
    try:
        with ZipFile(hwpx_path, "r") as zf:
            for name in zf.namelist():
                if SECTION_N_RE.match(name):
                    ids.extend(_ids_from_xml_str(zf.read(name).decode("utf-8")))
    except (BadZipFile, OSError):
        return set()
    return {i for i, n in Counter(ids).items() if n > 1}


def _check_itemcnt(root: ET.Element) -> list[str]:
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
        actual = len(parent.findall(f"{{{NS_HH}}}{child_local}"))
        if int(declared) != actual:
            errors.append(
                f"itemCnt mismatch in <{parent.tag.split('}')[1]}> "
                f"declared={declared}, actual={actual}"
            )
    return errors


def _collect_defined_ids(header_root: ET.Element) -> dict[str, set[str]]:
    defined: dict[str, set[str]] = {
        "charPrIDRef": set(),
        "paraPrIDRef": set(),
        "borderFillIDRef": set(),
    }
    for el in header_root.findall(f".//{{{NS_HH}}}charPr"):
        if el.get("id") is not None:
            defined["charPrIDRef"].add(el.get("id", ""))
    for el in header_root.findall(f".//{{{NS_HH}}}paraPr"):
        if el.get("id") is not None:
            defined["paraPrIDRef"].add(el.get("id", ""))
    for el in header_root.findall(f".//{{{NS_HH}}}borderFill"):
        if el.get("id") is not None:
            defined["borderFillIDRef"].add(el.get("id", ""))
    return defined


def _check_idref(section_root: ET.Element, defined: dict[str, set[str]], section_name: str) -> list[str]:
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
            errors.append(f"{section_name}: undefined {attr} value(s): {sorted(dangling)}")
    return errors


def _charpr_font_warnings(xml_str: str, heights: dict[str, int], min_pt: float) -> list[str]:
    """Return warnings for runs with text whose charPr height is below min_pt."""
    warns = []
    for m in re.finditer(r'charPrIDRef="(\d+)"[^>]*><hp:t>(.*?)</hp:t>', xml_str, re.DOTALL):
        cid = m.group(1)
        text = m.group(2).strip()
        if not text:
            continue
        height = heights.get(cid, 0)
        if height == 0 or height / 100 >= min_pt:
            continue
        pos = m.start()
        tbl_m = None
        for tm in re.finditer(r'<hp:tbl\b[^>]*\bid="(\d+)"', xml_str[:pos]):
            tbl_m = tm
        cell_m = None
        for cm in re.finditer(r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"/>', xml_str[:pos]):
            cell_m = cm
        tbl_id = tbl_m.group(1) if tbl_m else "?"
        col = cell_m.group(1) if cell_m else "?"
        row = cell_m.group(2) if cell_m else "?"
        warns.append(
            "WARN: table %s cell(%s,%s) charPr=%s height=%d(%spt) — 가독 불가 크기"
            % (tbl_id, col, row, cid, height, "%g" % (height / 100))
        )
    return warns


def do_validate(hwpx_path: str, baseline_dupes: set[str] | None = None, min_pt: float | None = None) -> tuple[list[str], list[str]]:
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
        for required in REQUIRED_FILES:
            if required not in names:
                errors.append(f"Missing required file: {required}")
        if "mimetype" in names:
            content = zf.read("mimetype").decode("utf-8").strip()
            if content != EXPECTED_MIMETYPE:
                errors.append(f"Bad mimetype: expected '{EXPECTED_MIMETYPE}', got '{content}'")
            if names[0] != "mimetype":
                errors.append(f"mimetype is not the first ZIP entry (index {names.index('mimetype')})")
            info = zf.getinfo("mimetype")
            if info.compress_type != ZIP_STORED:
                errors.append("mimetype must be ZIP_STORED (uncompressed)")
        parsed: dict[str, ET.Element] = {}
        section_bytes: dict[str, bytes] = {}
        for name in names:
            if name.endswith(".xml") or name.endswith(".hpf"):
                try:
                    data = zf.read(name)
                    if SECTION_N_RE.match(name):
                        section_bytes[name] = data
                    parsed[name] = ET.fromstring(data)
                except ET.ParseError as e:
                    errors.append(f"Malformed XML in {name}: {e}")
        header_root = parsed.get("Contents/header.xml")
        if header_root is None:
            return errors, warnings
        sec_cnt_declared = int(header_root.get("secCnt", "0"))
        actual_sections = sorted(n for n in names if SECTION_N_RE.match(n))
        if sec_cnt_declared != len(actual_sections):
            errors.append(
                f"secCnt mismatch: header declares secCnt={sec_cnt_declared}, "
                f"archive has {len(actual_sections)} section file(s)"
            )
        errors.extend(_check_itemcnt(header_root))
        defined_ids = _collect_defined_ids(header_root)
        charpr_heights: dict[str, int] = {}
        for cp in header_root.iter():
            if cp.tag.endswith("}charPr") or cp.tag == "charPr":
                cid = cp.get("id")
                h = int(cp.get("height", "0"))
                if cid is not None:
                    charpr_heights[cid] = h
        eff_min_pt = min_pt if min_pt is not None else MIN_READABLE_PT
        all_para_ids: list[str] = []
        for sec_name in actual_sections:
            sec_root = parsed.get(sec_name)
            if sec_root is None:
                continue
            xml_str = section_bytes[sec_name].decode("utf-8")
            all_para_ids.extend(_ids_from_xml_str(xml_str))
            errors.extend(_check_idref(sec_root, defined_ids, sec_name))
            warnings.extend(_charpr_font_warnings(xml_str, charpr_heights, eff_min_pt))
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


def cmd_validate(args: argparse.Namespace) -> None:
    baseline_dupes = _dup_para_ids(args.baseline) if args.baseline else None
    errors, warnings = do_validate(args.input, baseline_dupes, getattr(args, "min_pt", None))
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


# ── page-guard ────────────────────────────────────────────────────────────────

NS_PG = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
}


@dataclass
class Metrics:
    paragraph_count: int
    page_break_count: int
    column_break_count: int
    table_count: int
    table_shapes: List[Tuple[str, str, str, str, str, str]]
    text_char_total: int
    text_char_total_nospace: int
    paragraph_text_lengths: List[int]


def _text_of_t(t_node: ET.Element) -> str:
    return "".join(t_node.itertext())


def _collect_one_section(section_bytes: bytes) -> Metrics:
    """Parse one section XML and return its Metrics."""
    root = ET.parse(BytesIO(section_bytes)).getroot()
    paragraphs = root.findall(".//hp:p", NS_PG)
    page_break_count = sum(1 for p in paragraphs if p.get("pageBreak") == "1")
    column_break_count = sum(1 for p in paragraphs if p.get("columnBreak") == "1")
    tables = root.findall(".//hp:tbl", NS_PG)
    table_shapes: List[Tuple[str, str, str, str, str, str]] = []
    for t in tables:
        sz = t.find("hp:sz", NS_PG)
        width = sz.get("width", "") if sz is not None else ""
        height = sz.get("height", "") if sz is not None else ""
        table_shapes.append((
            t.get("rowCnt", ""),
            t.get("colCnt", ""),
            width,
            height,
            t.get("repeatHeader", ""),
            t.get("pageBreak", ""),
        ))
    t_nodes = root.findall(".//hp:t", NS_PG)
    text_char_total = 0
    text_char_total_nospace = 0
    for t in t_nodes:
        s = _text_of_t(t)
        text_char_total += len(s)
        text_char_total_nospace += len("".join(s.split()))
    paragraph_text_lengths: List[int] = []
    for p in paragraphs:
        plen = sum(len(_text_of_t(t)) for t in p.findall(".//hp:t", NS_PG))
        paragraph_text_lengths.append(plen)
    return Metrics(
        paragraph_count=len(paragraphs),
        page_break_count=page_break_count,
        column_break_count=column_break_count,
        table_count=len(tables),
        table_shapes=table_shapes,
        text_char_total=text_char_total,
        text_char_total_nospace=text_char_total_nospace,
        paragraph_text_lengths=paragraph_text_lengths,
    )


def collect_metrics(hwpx_path: Path) -> Metrics:
    """Aggregate Metrics across all sections in an HWPX file."""
    with zipfile.ZipFile(hwpx_path, "r") as zf:
        section_names = sorted(
            [n for n in zf.namelist() if SECTION_N_RE.match(n)],
            key=lambda n: int(SECTION_N_RE.match(n).group(1)),  # type: ignore[union-attr]
        )
        if not section_names:
            return Metrics(0, 0, 0, 0, [], 0, 0, [])
        sections = [_collect_one_section(zf.read(name)) for name in section_names]
    return Metrics(
        paragraph_count=sum(s.paragraph_count for s in sections),
        page_break_count=sum(s.page_break_count for s in sections),
        column_break_count=sum(s.column_break_count for s in sections),
        table_count=sum(s.table_count for s in sections),
        table_shapes=[shape for s in sections for shape in s.table_shapes],
        text_char_total=sum(s.text_char_total for s in sections),
        text_char_total_nospace=sum(s.text_char_total_nospace for s in sections),
        paragraph_text_lengths=[length for s in sections for length in s.paragraph_text_lengths],
    )


def _ratio_delta(a: int, b: int) -> float:
    return abs(b - a) / max(a, 1)


def compare_metrics(
    ref: Metrics,
    out: Metrics,
    max_text_delta_ratio: float,
    max_paragraph_delta_ratio: float,
) -> List[str]:
    errors: List[str] = []
    if ref.paragraph_count != out.paragraph_count:
        errors.append(f"문단 수 불일치: ref={ref.paragraph_count}, out={out.paragraph_count}")
    if ref.page_break_count != out.page_break_count:
        errors.append(f"명시적 pageBreak 수 불일치: ref={ref.page_break_count}, out={out.page_break_count}")
    if ref.column_break_count != out.column_break_count:
        errors.append(f"명시적 columnBreak 수 불일치: ref={ref.column_break_count}, out={out.column_break_count}")
    if ref.table_count != out.table_count:
        errors.append(f"표 수 불일치: ref={ref.table_count}, out={out.table_count}")
    if ref.table_shapes != out.table_shapes:
        errors.append("표 구조(rowCnt/colCnt/width/height/pageBreak) 불일치")
    td = _ratio_delta(ref.text_char_total_nospace, out.text_char_total_nospace)
    if td > max_text_delta_ratio:
        errors.append(
            "전체 텍스트 길이 편차 초과: "
            f"ref={ref.text_char_total_nospace}, out={out.text_char_total_nospace}, "
            f"delta={td:.2%}, limit={max_text_delta_ratio:.2%}"
        )
    if len(ref.paragraph_text_lengths) == len(out.paragraph_text_lengths):
        for idx, (a, b) in enumerate(zip(ref.paragraph_text_lengths, out.paragraph_text_lengths), start=1):
            if a == 0 and b == 0:
                continue
            pd = _ratio_delta(a, b)
            if pd > max_paragraph_delta_ratio:
                errors.append(
                    f"{idx}번째 문단 텍스트 길이 편차 초과: "
                    f"ref={a}, out={b}, delta={pd:.2%}, limit={max_paragraph_delta_ratio:.2%}"
                )
    return errors


def cmd_page_guard(args: argparse.Namespace) -> int:
    ref_path = Path(args.reference)
    out_path = Path(args.output)
    if not ref_path.exists():
        print(f"Error: reference not found: {ref_path}", file=sys.stderr)
        return 2
    if not out_path.exists():
        print(f"Error: output not found: {out_path}", file=sys.stderr)
        return 2
    ref = collect_metrics(ref_path)
    out = collect_metrics(out_path)
    if args.json:
        print(json.dumps({"reference": asdict(ref), "output": asdict(out)}, ensure_ascii=False, indent=2))
    errors = compare_metrics(ref, out,
                             max_text_delta_ratio=args.max_text_delta_ratio,
                             max_paragraph_delta_ratio=args.max_paragraph_delta_ratio)
    if errors:
        print("FAIL: page-guard")
        for e in errors:
            print(f" - {e}")
        return 1
    print("PASS: page-guard")
    print("  paragraph/table/pageBreak 구조와 텍스트 길이 편차가 허용 범위 내입니다.")
    return 0


# ── self-test ─────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    failures = []

    _section_with_text = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:tbl id="1000000003">'
        '<hp:tc>'
        '<hp:cellAddr colAddr="0" rowAddr="0"/>'
        '<hp:subList>'
        '<hp:p id="0" paraPrIDRef="10">'
        '<hp:run charPrIDRef="5"><hp:t>텍스트</hp:t></hp:run>'
        '<hp:run charPrIDRef="10"><hp:t>큰글자</hp:t></hp:run>'
        '</hp:p>'
        '</hp:subList>'
        '</hp:tc>'
        '</hp:tbl>'
        '</hp:BodyText>'
    )
    _heights = {"5": 300, "10": 1000}

    # VAL-1: 3pt charPr triggers warning
    try:
        warns = _charpr_font_warnings(_section_with_text, _heights, 5.0)
        if not warns:
            failures.append("VAL-1 FAIL: expected warning for 3pt charPr")
        else:
            print("VAL-1 PASS: 3pt charPr triggers warning")
    except Exception as e:
        failures.append("VAL-1 FAIL: %s" % e)

    # VAL-1b: only warns for small charPr (not 10pt)
    try:
        warns = _charpr_font_warnings(_section_with_text, _heights, 5.0)
        if len(warns) > 1:
            failures.append("VAL-1b FAIL: expected 1 warning, got %d: %r" % (len(warns), warns))
        else:
            print("VAL-1b PASS: only small charPr warns (10pt not warned)")
    except Exception as e:
        failures.append("VAL-1b FAIL: %s" % e)

    # VAL-2: empty run excluded from warning
    _section_empty_run = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:tbl id="1000000003">'
        '<hp:tc>'
        '<hp:cellAddr colAddr="0" rowAddr="0"/>'
        '<hp:subList>'
        '<hp:p id="0" paraPrIDRef="10">'
        '<hp:run charPrIDRef="5"><hp:t/></hp:run>'
        '</hp:p>'
        '</hp:subList>'
        '</hp:tc>'
        '</hp:tbl>'
        '</hp:BodyText>'
    )
    try:
        warns_empty = _charpr_font_warnings(_section_empty_run, _heights, 5.0)
        if warns_empty:
            failures.append("VAL-2 FAIL: empty run should not warn, got: %r" % warns_empty)
        else:
            print("VAL-2 PASS: empty run excluded from warning")
    except Exception as e:
        failures.append("VAL-2 FAIL: %s" % e)

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All validate tests passed")
    sys.exit(0)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if sys.argv[1:] == ["--test"]:
        _run_tests()
        return
    parser = argparse.ArgumentParser(description="HWPX structural validation and page-drift guard")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # validate
    p_val = sub.add_parser("validate", help="Validate HWPX file structure and internal consistency")
    p_val.add_argument("input", help="Path to .hwpx file")
    p_val.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    p_val.add_argument(
        "--baseline",
        help="Reference .hwpx (source document); duplicate hp:p IDs shared with it are downgraded to warnings",
    )
    p_val.add_argument(
        "--min-pt", type=float, dest="min_pt", default=None,
        help="Minimum readable font size in pt (default: %g). Runs below this threshold warn." % MIN_READABLE_PT,
    )

    # page-guard
    p_pg = sub.add_parser("page-guard", help="Detect page-drift risk vs. reference HWPX")
    p_pg.add_argument("--reference", "-r", required=True, help="Reference HWPX path")
    p_pg.add_argument("--output", "-o", required=True, help="Result HWPX path")
    p_pg.add_argument("--max-text-delta-ratio", type=float, default=0.15,
                      help="Total text length deviation limit (default: 0.15)")
    p_pg.add_argument("--max-paragraph-delta-ratio", type=float, default=0.25,
                      help="Per-paragraph text length deviation limit (default: 0.25)")
    p_pg.add_argument("--json", action="store_true", help="Output metrics as JSON")

    args = parser.parse_args()

    if args.cmd == "validate":
        cmd_validate(args)
    elif args.cmd == "page-guard":
        raise SystemExit(cmd_page_guard(args))


if __name__ == "__main__":
    main()
