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
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path
from typing import List, Tuple
from zipfile import ZIP_STORED, BadZipFile, ZipFile

import xml.etree.ElementTree as ET
import defusedxml.ElementTree as DET
from defusedxml.common import DefusedXmlException

from _common import MIN_READABLE_PT, SECTION_N_RE, PARA_ID_RE, PLACEHOLDER_IDS, TBL_ID_RE

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


def _dup_table_ids(hwpx_path: str) -> set[str]:
    ids: list[str] = []
    try:
        with ZipFile(hwpx_path, "r") as zf:
            for name in zf.namelist():
                if SECTION_N_RE.match(name):
                    xml_str = zf.read(name).decode("utf-8")
                    ids.extend(i for i in TBL_ID_RE.findall(xml_str) if i not in PLACEHOLDER_IDS)
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


def _check_table_grid(root: ET.Element) -> list[str]:
    """Check every <hp:tbl>'s cellAddr/cellSpan grid fills rowCnt x colCnt with no gaps or overlaps.

    A hand-written section0.xml with every cell left at colAddr="0" rowAddr="0" (the most common
    copy-paste mistake) passes ZIP/XML/itemCnt/IDRef checks but renders as a blank document in
    Hancom — this is the check that catches that class of error before the file ever reaches HWP.
    Only direct tr/tc children of each tbl are scanned, so a nested table (inside a cell's
    subList) is checked independently against its own rowCnt/colCnt, not folded into the parent grid.

    rowCnt/colCnt are declared attributes on <hp:tbl>, but real documents (including this repo's
    own `minutes` template) sometimes omit them — HWP itself doesn't require them to render. When
    missing or non-positive, the grid bounds are inferred from the actual cellAddr/cellSpan extent
    instead of skipping the table outright, so overlap/duplicate-address bugs are still caught.
    """
    MAX_GRID_DIM = 1000
    errors: list[str] = []
    tbl_tag = f"{{{NS_HP}}}tbl"
    tr_tag = f"{{{NS_HP}}}tr"
    tc_tag = f"{{{NS_HP}}}tc"
    addr_tag = f"{{{NS_HP}}}cellAddr"
    span_tag = f"{{{NS_HP}}}cellSpan"

    for tbl in root.iter(tbl_tag):
        tbl_id = tbl.get("id", "?")

        cells: list[tuple[int, int, int, int]] = []  # (row0, col0, row_span, col_span)
        for tr in tbl.findall(tr_tag):
            for tc in tr.findall(tc_tag):
                addr = tc.find(addr_tag)
                if addr is None:
                    continue
                try:
                    col0 = int(addr.get("colAddr", "0"))
                    row0 = int(addr.get("rowAddr", "0"))
                except ValueError:
                    continue
                span = tc.find(span_tag)
                col_span, row_span = 1, 1
                if span is not None:
                    try:
                        col_span = int(span.get("colSpan", "1"))
                        row_span = int(span.get("rowSpan", "1"))
                    except ValueError:
                        pass
                cells.append((row0, col0, row_span, col_span))

        if not cells:
            continue

        try:
            row_cnt = int(tbl.get("rowCnt", "0"))
            col_cnt = int(tbl.get("colCnt", "0"))
        except ValueError:
            row_cnt = col_cnt = 0

        if row_cnt <= 0 or col_cnt <= 0:
            row_cnt = max(row0 + row_span for row0, _, row_span, _ in cells)
            col_cnt = max(col0 + col_span for _, col0, _, col_span in cells)

        if row_cnt > MAX_GRID_DIM or col_cnt > MAX_GRID_DIM:
            errors.append(
                f"table {tbl_id}: rowCnt/colCnt ({row_cnt}x{col_cnt}) exceeds "
                f"maximum supported grid size of {MAX_GRID_DIM}x{MAX_GRID_DIM}"
            )
            continue

        occupied: dict[tuple[int, int], int] = {}
        out_of_range: set[tuple[int, int]] = set()
        for row0, col0, row_span, col_span in cells:
            for r in range(row0, row0 + row_span):
                for c in range(col0, col0 + col_span):
                    if r < 0 or c < 0 or r >= row_cnt or c >= col_cnt:
                        out_of_range.add((r, c))
                        continue
                    occupied[(r, c)] = occupied.get((r, c), 0) + 1

        overlaps = sorted(cell for cell, n in occupied.items() if n > 1)
        missing = sorted(
            (r, c) for r in range(row_cnt) for c in range(col_cnt) if (r, c) not in occupied
        )
        if overlaps:
            errors.append(
                f"table {tbl_id}: cellAddr grid overlap at {overlaps} "
                f"(rowCnt={row_cnt}, colCnt={col_cnt}) — duplicate/incorrect colAddr,rowAddr"
            )
        if missing:
            errors.append(
                f"table {tbl_id}: cellAddr grid gap — cell(s) {missing} not covered "
                f"(rowCnt={row_cnt}, colCnt={col_cnt}) — every cell likely left at the same colAddr,rowAddr"
            )
        if out_of_range:
            errors.append(
                f"table {tbl_id}: cellAddr out of declared grid bounds: {sorted(out_of_range)} "
                f"(rowCnt={row_cnt}, colCnt={col_cnt})"
            )
    return errors


def _charpr_font_warnings(root: ET.Element, heights: dict[str, int], min_pt: float) -> list[str]:
    """Return warnings for runs with text whose charPr height is below min_pt.

    Walks the section tree with ElementTree so a run is matched regardless of
    where `<hp:t>` sits among its children (e.g. a ctrl/field marker may precede
    the text). Table/cell context comes from ancestor lookup via a parent map,
    avoiding any per-match backward scan of the source string. The caller passes
    the already-parsed section root so the XML is not parsed a second time.
    """
    warns: list[str] = []

    run_tag = f"{{{NS_HP}}}run"
    t_tag = f"{{{NS_HP}}}t"
    tbl_tag = f"{{{NS_HP}}}tbl"
    tc_tag = f"{{{NS_HP}}}tc"
    cell_tag = f"{{{NS_HP}}}cellAddr"

    parent = {child: p for p in root.iter() for child in p}

    for run in root.iter(run_tag):
        cid = run.get("charPrIDRef")
        if cid is None:
            continue
        text = "".join(s for t in run.iter(t_tag) for s in t.itertext()).strip()
        if not text:
            continue
        height = heights.get(cid, 0)
        if height == 0 or height / 100 >= min_pt:
            continue

        tbl_id = None
        cell = None
        node = parent.get(run)
        while node is not None:
            if cell is None and node.tag == tc_tag:
                ca = node.find(cell_tag)
                if ca is not None:
                    cell = (ca.get("colAddr", "?"), ca.get("rowAddr", "?"))
            if node.tag == tbl_tag:
                tbl_id = node.get("id", "?")
                break
            node = parent.get(node)

        if tbl_id is not None:
            col = cell[0] if cell else "?"
            row = cell[1] if cell else "?"
            warns.append(
                "WARN: table %s cell(%s,%s) charPr=%s height=%d(%spt) — 가독 불가 크기"
                % (tbl_id, col, row, cid, height, "%g" % (height / 100))
            )
        else:
            warns.append(
                "WARN: (body text) charPr=%s height=%d(%spt) — 가독 불가 크기"
                % (cid, height, "%g" % (height / 100))
            )
    return warns


def do_validate(
    hwpx_path: str,
    baseline_dupes: set[str] | None = None,
    min_pt: float | None = None,
    baseline_table_dupes: set[str] | None = None,
) -> tuple[list[str], list[str]]:
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
                    parsed[name] = DET.fromstring(data)
                except (ET.ParseError, DefusedXmlException) as e:
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
                try:
                    h = int(cp.get("height", "0"))
                except ValueError:
                    continue
                if cid is not None:
                    charpr_heights[cid] = h
        eff_min_pt = min_pt if min_pt is not None else MIN_READABLE_PT
        all_para_ids: list[str] = []
        all_table_ids: list[str] = []
        for sec_name in actual_sections:
            sec_root = parsed.get(sec_name)
            if sec_root is None:
                continue
            xml_str = section_bytes[sec_name].decode("utf-8")
            all_para_ids.extend(_ids_from_xml_str(xml_str))
            all_table_ids.extend(i for i in TBL_ID_RE.findall(xml_str) if i not in PLACEHOLDER_IDS)
            errors.extend(_check_idref(sec_root, defined_ids, sec_name))
            errors.extend(_check_table_grid(sec_root))
            warnings.extend(_charpr_font_warnings(sec_root, charpr_heights, eff_min_pt))
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
        table_dupes = {i for i, n in Counter(all_table_ids).items() if n > 1}
        if table_dupes:
            table_base = baseline_table_dupes or set()
            new_table_dupes = sorted(table_dupes - table_base)
            preexisting_table = sorted(table_dupes & table_base)
            if new_table_dupes:
                errors.append(f"Duplicate hp:tbl id values introduced (not in baseline): {new_table_dupes}")
            if preexisting_table:
                warnings.append(
                    f"Pre-existing duplicate hp:tbl id values (shared with baseline, --table-id may resolve the wrong table): {preexisting_table}"
                )
    return errors, warnings


def cmd_validate(args: argparse.Namespace) -> None:
    baseline_dupes = _dup_para_ids(args.baseline) if args.baseline else None
    baseline_table_dupes = _dup_table_ids(args.baseline) if args.baseline else None
    errors, warnings = do_validate(args.input, baseline_dupes, getattr(args, "min_pt", None), baseline_table_dupes)
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
    root = DET.parse(BytesIO(section_bytes)).getroot()
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
    try:
        ref = collect_metrics(ref_path)
        out = collect_metrics(out_path)
    except (ET.ParseError, DefusedXmlException) as e:
        print(f"Error parsing XML content: {e}", file=sys.stderr)
        return 2
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
        warns = _charpr_font_warnings(ET.fromstring(_section_with_text), _heights, 5.0)
        if not warns:
            failures.append("VAL-1 FAIL: expected warning for 3pt charPr")
        else:
            print("VAL-1 PASS: 3pt charPr triggers warning")
    except Exception as e:
        failures.append("VAL-1 FAIL: %s" % e)

    # VAL-1b: only warns for small charPr (not 10pt)
    try:
        warns = _charpr_font_warnings(ET.fromstring(_section_with_text), _heights, 5.0)
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
        warns_empty = _charpr_font_warnings(ET.fromstring(_section_empty_run), _heights, 5.0)
        if warns_empty:
            failures.append("VAL-2 FAIL: empty run should not warn, got: %r" % warns_empty)
        else:
            print("VAL-2 PASS: empty run excluded from warning")
    except Exception as e:
        failures.append("VAL-2 FAIL: %s" % e)

    # VAL-3: <hp:t> not the immediate first child of <hp:run> still warns
    _section_ctrl_before_text = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:p id="0" paraPrIDRef="10">'
        '<hp:run charPrIDRef="5"><hp:ctrl><hp:fieldBegin/></hp:ctrl><hp:t>작은글자</hp:t></hp:run>'
        '</hp:p>'
        '</hp:BodyText>'
    )
    try:
        warns_ctrl = _charpr_font_warnings(ET.fromstring(_section_ctrl_before_text), _heights, 5.0)
        if not warns_ctrl:
            failures.append("VAL-3 FAIL: expected warning when <hp:t> is not first child of <hp:run>")
        else:
            print("VAL-3 PASS: non-first-child <hp:t> still warns")
    except Exception as e:
        failures.append("VAL-3 FAIL: %s" % e)

    # VAL-4: malformed non-numeric charPr height in header must not raise, AND a valid
    # charPr is still captured alongside it (parity with _common COMMON-1: bad skipped, good kept).
    # The valid charPr id=5 is 3pt (< MIN_READABLE_PT); if it survives the malformed sibling,
    # the section run referencing it produces a font-size warning. Silently dropping heights
    # (e.g. a wrong try scope) would yield no warning and fail this test.
    import tempfile
    _header_bad_height = (
        '<?xml version="1.0"?>'
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" secCnt="1">'
        '<hh:charPr id="5" height="300"/>'
        '<hh:charPr id="9" height="not-a-number"/>'
        '</hh:head>'
    )
    _section_small_font = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:p id="0" paraPrIDRef="10">'
        '<hp:run charPrIDRef="5"><hp:t>작은글자</hp:t></hp:run>'
        '</hp:p>'
        '</hp:BodyText>'
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            arc = Path(d) / "bad.hwpx"
            with ZipFile(str(arc), "w") as zf:
                zf.writestr("mimetype", "application/hwp+zip")
                zf.writestr("Contents/header.xml", _header_bad_height)
                zf.writestr("Contents/section0.xml", _section_small_font)
            _, _warns = do_validate(str(arc))
        if not _warns:
            failures.append("VAL-4 FAIL: valid charPr id=5 (3pt) not captured; expected font warning, got: %r" % _warns)
        else:
            print("VAL-4 PASS: malformed charPr height skipped, valid charPr still captured")
    except ValueError as e:
        failures.append("VAL-4 FAIL: malformed height raised ValueError: %s" % e)
    except Exception as e:
        failures.append("VAL-4 FAIL: %s" % e)

    # VAL-5: 2x2 table with every cell left at colAddr="0" rowAddr="0" (the actual bug this
    # check exists to catch) reports a grid gap error.
    def _tbl_xml(cells: str, row_cnt: int = 2, col_cnt: int = 2) -> str:
        return (
            '<?xml version="1.0"?>'
            '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            f'<hp:tbl id="1" rowCnt="{row_cnt}" colCnt="{col_cnt}">'
            f'{cells}'
            '</hp:tbl>'
            '</hp:BodyText>'
        )

    def _tr(cells: str) -> str:
        return f'<hp:tr>{cells}</hp:tr>'

    def _tc(col: int, row: int, col_span: int = 1, row_span: int = 1) -> str:
        return (
            '<hp:tc>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
            '</hp:tc>'
        )

    _all_zero = _tbl_xml(_tr(_tc(0, 0) + _tc(0, 0)) + _tr(_tc(0, 0) + _tc(0, 0)))
    try:
        errs = _check_table_grid(ET.fromstring(_all_zero))
        if not any("gap" in e for e in errs) or not any("overlap" in e for e in errs):
            failures.append("VAL-5 FAIL: expected gap+overlap errors for all-zero cellAddr, got: %r" % errs)
        else:
            print("VAL-5 PASS: all-cells-at-(0,0) grid reports gap and overlap")
    except Exception as e:
        failures.append("VAL-5 FAIL: %s" % e)

    # VAL-6: correctly addressed 2x2 grid (including a colSpan=2 merged header row) passes clean.
    _valid_grid = _tbl_xml(
        _tr(_tc(0, 0, col_span=2)) + _tr(_tc(0, 1) + _tc(1, 1)),
        row_cnt=2, col_cnt=2,
    )
    try:
        errs = _check_table_grid(ET.fromstring(_valid_grid))
        if errs:
            failures.append("VAL-6 FAIL: valid grid (with colSpan) reported errors: %r" % errs)
        else:
            print("VAL-6 PASS: correctly addressed grid (with colSpan) reports no errors")
    except Exception as e:
        failures.append("VAL-6 FAIL: %s" % e)

    # VAL-7: table with no rowCnt/colCnt attrs at all (e.g. this repo's own `minutes` template)
    # infers grid bounds from cellAddr/cellSpan instead of being skipped outright, so a
    # duplicate-cellAddr bug in such a table is still caught.
    _no_grid_dupe = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:tbl id="1">'
        f'{_tr(_tc(0, 0) + _tc(0, 0))}'
        '</hp:tbl>'
        '</hp:BodyText>'
    )
    try:
        errs = _check_table_grid(ET.fromstring(_no_grid_dupe))
        if not any("overlap" in e for e in errs):
            failures.append("VAL-7 FAIL: expected overlap error for undeclared-grid dupe, got: %r" % errs)
        else:
            print("VAL-7 PASS: table without rowCnt/colCnt still reports overlap")
    except Exception as e:
        failures.append("VAL-7 FAIL: %s" % e)

    # VAL-8: correctly addressed table with no rowCnt/colCnt attrs (mirrors the real `minutes`
    # template) reports no false positive from the inferred-bounds path.
    _no_grid_valid = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:tbl id="1">'
        f'{_tr(_tc(0, 0) + _tc(1, 0))}'
        f'{_tr(_tc(0, 1) + _tc(1, 1))}'
        '</hp:tbl>'
        '</hp:BodyText>'
    )
    try:
        errs = _check_table_grid(ET.fromstring(_no_grid_valid))
        if errs:
            failures.append("VAL-8 FAIL: valid undeclared-grid table reported errors: %r" % errs)
        else:
            print("VAL-8 PASS: correctly addressed table without rowCnt/colCnt reports no errors")
    except Exception as e:
        failures.append("VAL-8 FAIL: %s" % e)

    # VAL-9: header.xml with a billion-laughs entity-expansion payload is rejected as an
    # error, not silently parsed and expanded (XXE/billion-laughs hardening). Archive is
    # otherwise complete/valid so the only possible error source is the malicious payload.
    _header_billion_laughs = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE hh:head [\n'
        ' <!ENTITY a "lol">\n'
        ' <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        ' <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
        ']>\n'
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" secCnt="1">&c;</hh:head>'
    )
    _valid_content_hpf = '<?xml version="1.0"?><opf:package xmlns:opf="http://www.idpf.org/2007/opf"/>'
    _valid_section0 = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"/>'
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            arc = Path(d) / "xxe.hwpx"
            with ZipFile(str(arc), "w") as zf:
                zf.writestr("mimetype", "application/hwp+zip")
                zf.writestr("Contents/content.hpf", _valid_content_hpf)
                zf.writestr("Contents/header.xml", _header_billion_laughs)
                zf.writestr("Contents/section0.xml", _valid_section0)
            _xxe_errors, _ = do_validate(str(arc))
        if not any("header.xml" in e for e in _xxe_errors):
            failures.append("VAL-9 FAIL: billion-laughs header.xml parsed without error: %r" % _xxe_errors)
        else:
            print("VAL-9 PASS: billion-laughs header.xml rejected as malformed/forbidden XML")
    except Exception as e:
        failures.append("VAL-9 FAIL: unhandled exception instead of reported error: %s" % e)

    # VAL-10: cmd_page_guard reports a clean error (not an unhandled traceback/crash) when a
    # section file contains a billion-laughs entity-expansion payload.
    _section_billion_laughs = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE hp:BodyText [\n'
        ' <!ENTITY a "lol">\n'
        ' <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        ' <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
        ']>\n'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">&c;</hp:BodyText>'
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            ref_arc = Path(d) / "ref.hwpx"
            out_arc = Path(d) / "out.hwpx"
            with ZipFile(str(ref_arc), "w") as zf:
                zf.writestr("Contents/section0.xml", _valid_section0)
            with ZipFile(str(out_arc), "w") as zf:
                zf.writestr("Contents/section0.xml", _section_billion_laughs)
            pg_args = argparse.Namespace(
                reference=str(ref_arc), output=str(out_arc), json=False,
                max_text_delta_ratio=0.15, max_paragraph_delta_ratio=0.25,
            )
            rc = cmd_page_guard(pg_args)
        if rc != 2:
            failures.append("VAL-10 FAIL: expected rc=2 for billion-laughs section, got %r" % rc)
        else:
            print("VAL-10 PASS: cmd_page_guard reports clean error for billion-laughs section (no crash)")
    except Exception as e:
        failures.append("VAL-10 FAIL: unhandled exception instead of reported error: %s" % e)

    # VAL-11/VAL-12: duplicate hp:tbl id values, mirroring the hp:p baseline-downgrade
    # pattern (VAL uses the same _dup_para_ids/dupes convention -- see do_validate).
    _header_minimal = (
        '<?xml version="1.0"?>'
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" secCnt="1"/>'
    )
    _section_dup_tables = (
        '<?xml version="1.0"?>'
        '<hp:BodyText xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:tbl id="5"><hp:tr><hp:tc><hp:cellAddr colAddr="0" rowAddr="0"/></hp:tc></hp:tr></hp:tbl>'
        '<hp:tbl id="5"><hp:tr><hp:tc><hp:cellAddr colAddr="0" rowAddr="0"/></hp:tc></hp:tr></hp:tbl>'
        '</hp:BodyText>'
    )

    # VAL-11: duplicate hp:tbl id with no baseline is reported as a new-dupe error
    try:
        with tempfile.TemporaryDirectory() as d:
            arc = Path(d) / "dup_tbl.hwpx"
            with ZipFile(str(arc), "w") as zf:
                zf.writestr("mimetype", "application/hwp+zip")
                zf.writestr("Contents/content.hpf", _valid_content_hpf)
                zf.writestr("Contents/header.xml", _header_minimal)
                zf.writestr("Contents/section0.xml", _section_dup_tables)
            _tbl_errs, _tbl_warns = do_validate(str(arc))
        if not any("hp:tbl id" in e and "5" in e for e in _tbl_errs):
            failures.append(
                "VAL-11 FAIL: expected error for duplicate hp:tbl id, got errors=%r warnings=%r"
                % (_tbl_errs, _tbl_warns)
            )
        else:
            print("VAL-11 PASS: duplicate hp:tbl id (no baseline) reported as error")
    except Exception as e:
        failures.append("VAL-11 FAIL: %s" % e)

    # VAL-12: duplicate hp:tbl id shared with baseline is downgraded to a warning
    try:
        with tempfile.TemporaryDirectory() as d:
            arc = Path(d) / "dup_tbl2.hwpx"
            with ZipFile(str(arc), "w") as zf:
                zf.writestr("mimetype", "application/hwp+zip")
                zf.writestr("Contents/content.hpf", _valid_content_hpf)
                zf.writestr("Contents/header.xml", _header_minimal)
                zf.writestr("Contents/section0.xml", _section_dup_tables)
            _tbl_errs2, _tbl_warns2 = do_validate(str(arc), baseline_table_dupes={"5"})
        if any("introduced" in e for e in _tbl_errs2):
            failures.append("VAL-12 FAIL: baseline-shared hp:tbl id dupe still reported as new error: %r" % _tbl_errs2)
        elif not any("hp:tbl id" in w for w in _tbl_warns2):
            failures.append("VAL-12 FAIL: expected downgraded warning for baseline-shared hp:tbl id dupe, got: %r" % _tbl_warns2)
        else:
            print("VAL-12 PASS: hp:tbl id dupe shared with baseline downgraded to warning")
    except Exception as e:
        failures.append("VAL-12 FAIL: %s" % e)

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
