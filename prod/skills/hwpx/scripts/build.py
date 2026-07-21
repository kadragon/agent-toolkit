#!/usr/bin/env python3
"""HWPX document creation and analysis.

Usage:
    python build.py build --template gonmun --output result.hwpx
    python build.py build --section my.xml --output result.hwpx
    python build.py analyze reference.hwpx
    python build.py analyze reference.hwpx --extract-header /tmp/ref.xml
    python build.py next-id document.hwpx
    python build.py next-id document.hwpx --count 5
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from _common import (
    collect_ids,
    configure_io,
    die,
    get_ids_from_hwpx,
    MIN_USER_ID,
    NS,
    SECTION_RE,
    xml_escape,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
BASE_DIR = TEMPLATES_DIR / "base"
AVAILABLE_TEMPLATES = ["gonmun", "report", "minutes", "proposal"]


# ── build ─────────────────────────────────────────────────────────────────────

def _validate_xml(filepath: Path) -> None:
    try:
        ET.parse(str(filepath))
    except ET.ParseError as e:
        die(f"Malformed XML in {filepath.name}: {e}")


def _update_metadata(content_hpf: Path, title: str | None, creator: str | None) -> None:
    if not title and not creator:
        return
    from datetime import datetime, timezone
    raw = content_hpf.read_bytes().decode("utf-8")
    now = datetime.now(timezone.utc)
    iso_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now.strftime("%Y년 %m월 %d일")
    if title:
        safe_title = xml_escape(title).replace("&quot;", '"')
        raw = re.sub(r"<opf:title\s*/>", f"<opf:title>{safe_title}</opf:title>", raw)
        raw = re.sub(r"<opf:title>[^<]*</opf:title>", f"<opf:title>{safe_title}</opf:title>", raw)
    if creator:
        safe_creator = xml_escape(creator)
        raw = re.sub(
            r'(<opf:meta name="creator" content=")[^"]*(")',
            lambda m: m.group(1) + safe_creator + m.group(2), raw,
        )
        raw = re.sub(
            r'(<opf:meta name="lastsaveby" content=")[^"]*(")',
            lambda m: m.group(1) + safe_creator + m.group(2), raw,
        )
    raw = re.sub(r'(<opf:meta name="CreatedDate" content=")[^"]*(")', rf'\g<1>{iso_now}\2', raw)
    raw = re.sub(r'(<opf:meta name="ModifiedDate" content=")[^"]*(")', rf'\g<1>{iso_now}\2', raw)
    raw = re.sub(r'(<opf:meta name="date" content=")[^"]*(")', rf'\g<1>{date_str}\2', raw)
    content_hpf.write_bytes(raw.encode("utf-8"))


def _pack_hwpx(input_dir: Path, output_path: Path) -> None:
    from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
    mimetype_file = input_dir / "mimetype"
    if not mimetype_file.is_file():
        die(f"Missing 'mimetype' in {input_dir}")
    all_files = sorted(
        p.relative_to(input_dir).as_posix()
        for p in input_dir.rglob("*")
        if p.is_file()
    )
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        zf.write(mimetype_file, "mimetype", compress_type=ZIP_STORED)
        for rel_path in all_files:
            if rel_path != "mimetype":
                zf.write(input_dir / rel_path, rel_path, compress_type=ZIP_DEFLATED)


def _validate_hwpx(hwpx_path: Path) -> list[str]:
    from zipfile import BadZipFile, ZIP_STORED, ZipFile
    errors: list[str] = []
    required = ["mimetype", "Contents/content.hpf", "Contents/header.xml", "Contents/section0.xml"]
    try:
        zf = ZipFile(hwpx_path, "r")
    except BadZipFile:
        return [f"Not a valid ZIP: {hwpx_path}"]
    except OSError as e:
        return [f"Cannot open: {hwpx_path}: {e}"]
    with zf:
        names = zf.namelist()
        for r in required:
            if r not in names:
                errors.append(f"Missing: {r}")
        if "mimetype" in names:
            content = zf.read("mimetype").decode("utf-8").strip()
            if content != "application/hwp+zip":
                errors.append(f"Bad mimetype content: {content}")
            if names[0] != "mimetype":
                errors.append("mimetype is not the first ZIP entry")
            info = zf.getinfo("mimetype")
            if info.compress_type != ZIP_STORED:
                errors.append("mimetype is not ZIP_STORED")
        for name in names:
            if name.endswith(".xml") or name.endswith(".hpf"):
                try:
                    ET.fromstring(zf.read(name))
                except ET.ParseError as e:
                    errors.append(f"Malformed XML: {name}: {e}")
    return errors


def _update_preview(work_dir: Path) -> None:
    section_path = work_dir / "Contents" / "section0.xml"
    prv_text_path = work_dir / "Preview" / "PrvText.txt"
    if not section_path.is_file() or not prv_text_path.is_file():
        return
    try:
        root = ET.fromstring(section_path.read_bytes())
        texts = [t.text for t in root.findall(".//hp:t", NS) if t.text]
        prv_text_path.write_text("".join(texts)[:500], encoding="utf-8")
    except ET.ParseError:
        pass


def cmd_build(args: argparse.Namespace) -> None:
    if not BASE_DIR.is_dir():
        die(f"Base template not found: {BASE_DIR}")

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir) / "build"
        shutil.copytree(BASE_DIR, work)

        if args.template:
            overlay_dir = TEMPLATES_DIR / args.template
            if not overlay_dir.is_dir():
                die(
                    f"Template '{args.template}' not found. "
                    f"Available: {', '.join(AVAILABLE_TEMPLATES)}"
                )
            for overlay_file in overlay_dir.iterdir():
                if overlay_file.is_file() and overlay_file.suffix == ".xml":
                    shutil.copy2(overlay_file, work / "Contents" / overlay_file.name)

        if args.header:
            header_path = Path(args.header)
            if not header_path.is_file():
                die(f"Header file not found: {args.header}")
            shutil.copy2(header_path, work / "Contents" / "header.xml")

        if args.section:
            section_path = Path(args.section)
            if not section_path.is_file():
                die(f"Section file not found: {args.section}")
            shutil.copy2(section_path, work / "Contents" / "section0.xml")

        _update_metadata(work / "Contents" / "content.hpf", args.title, args.creator)

        if args.update_preview:
            _update_preview(work)

        for xml_file in work.rglob("*.xml"):
            _validate_xml(xml_file)
        for hpf_file in work.rglob("*.hpf"):
            _validate_xml(hpf_file)

        _pack_hwpx(work, Path(args.output))

    errors = _validate_hwpx(Path(args.output))
    if errors:
        print(f"WARNING: {args.output} has issues:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
    else:
        print(f"VALID: {args.output}")
        print(f"  Template: {args.template or 'base'}")
        if args.header:
            print(f"  Header: {args.header}")
        if args.section:
            print(f"  Section: {args.section}")


# ── analyze ───────────────────────────────────────────────────────────────────

FONT_MAP: dict[tuple[str, str], str] = {}


def _get_text(el: Element) -> str:
    return "".join(t.text for t in el.findall(".//hp:t", NS) if t.text)


def _analyze_fonts(root: Element) -> list[str]:
    lines = ["▶ 폰트 정의"]
    for fontface in root.findall(".//hh:fontface", NS):
        lang = fontface.get("lang", "?")
        for font in fontface.findall("hh:font", NS):
            fid = font.get("id", "")
            face = font.get("face", "")
            FONT_MAP[(lang, fid)] = face
            if lang == "HANGUL":
                lines.append(f"  hangul/{fid}: {face}")
    lines.append("")
    return lines


def _analyze_borderfills(root: Element) -> list[str]:
    lines = ["▶ borderFill (테두리/배경)"]
    for bf in root.findall(".//hh:borderFill", NS):
        bid = bf.get("id")
        parts = []
        for side in ["left", "right", "top", "bottom"]:
            b = bf.find(f"hh:{side}Border", NS)
            if b is not None:
                btype = b.get("type", "NONE")
                bwidth = b.get("width", "")
                parts.append(f"{side}={btype} {bwidth}".strip() if btype != "NONE" else f"{side}=NONE")
        bg = "없음"
        fill = bf.find(".//hc:winBrush", NS)
        if fill is not None:
            fc = fill.get("faceColor", "none")
            if fc != "none":
                bg = fc
        lines.append(f"  [{bid}] {', '.join(parts)}")
        if bg != "없음":
            lines.append(f"       배경={bg}")
    lines.append("")
    return lines


def _analyze_charprops(root: Element) -> list[str]:
    lines = ["▶ charPr (글자 스타일)"]
    for cp in root.findall(".//hh:charPr", NS):
        cid = cp.get("id")
        pt = int(cp.get("height", "0")) / 100
        color = cp.get("textColor", "#000000")
        bfref = cp.get("borderFillIDRef", "?")
        fontref = cp.find("hh:fontRef", NS)
        font_id = fontref.get("hangul", "0") if fontref is not None else "0"
        font_name = FONT_MAP.get(("HANGUL", font_id), f"font{font_id}")
        spacing_el = cp.find("hh:spacing", NS)
        spacing = int(spacing_el.get("hangul", "0")) if spacing_el is not None else 0
        ratio_el = cp.find("hh:ratio", NS)
        ratio_drift = []
        if ratio_el is not None:
            for script in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"):
                val = ratio_el.get(script, "100")
                if val != "100":
                    ratio_drift.append(f"{script}:{val}")
        flags = []
        if cp.find("hh:bold", NS) is not None:
            flags.append("볼드")
        if cp.find("hh:italic", NS) is not None:
            flags.append("이탤릭")
        ul = cp.find("hh:underline", NS)
        if ul is not None and ul.get("type", "NONE") != "NONE":
            flags.append(f"밑줄({ul.get('shape', 'SOLID')})")
        so = cp.find("hh:strikeout", NS)
        if so is not None and so.get("shape", "NONE") != "NONE":
            flags.append("취소선")
        spacing_str = f" spacing={spacing}" if spacing != 0 else ""
        ratio_str = f" ratio={','.join(ratio_drift)}%" if ratio_drift else ""
        lines.append(f"  [{cid}] {pt}pt {font_name} {color}{spacing_str}{ratio_str} {' '.join(flags)}".rstrip())
        lines.append(f"       fontRef=hangul:{font_id} borderFillIDRef={bfref}")
    lines.append("")
    return lines


def _analyze_paraprops(root: Element) -> list[str]:
    lines = ["▶ paraPr (문단 스타일)"]
    for pp in root.findall(".//hh:paraPr", NS):
        pid = pp.get("id")
        align = pp.find("hh:align", NS)
        h_align = align.get("horizontal", "?") if align is not None else "?"
        heading = pp.find("hh:heading", NS)
        h_type = heading.get("type", "NONE") if heading is not None else "NONE"
        h_level = heading.get("level", "0") if heading is not None else "0"
        ls = pp.find(".//hh:lineSpacing", NS)
        ls_val = ls.get("value", "?") if ls is not None else "?"
        ls_type = ls.get("type", "PERCENT") if ls is not None else "?"
        margins: dict[str, str] = {}
        for m_name in ["intent", "left", "right", "prev", "next"]:
            m_el = pp.find(f".//hc:{m_name}", NS)
            if m_el is not None:
                margins[m_name] = m_el.get("value", "0")
        border = pp.find("hh:border", NS)
        bf_ref = border.get("borderFillIDRef", "2") if border is not None else "2"
        b_offsets: dict[str, str] = {}
        if border is not None:
            for attr in ["offsetLeft", "offsetRight", "offsetTop", "offsetBottom"]:
                v = border.get(attr, "0")
                if v != "0":
                    b_offsets[attr] = v
        margin_str = ", ".join(f"{k}={v}" for k, v in margins.items() if v != "0") or "없음"
        heading_str = f" heading={h_type} level={h_level}" if h_type != "NONE" else ""
        lines.append(f"  [{pid}] {h_align} lineSpacing={ls_val}{ls_type}{heading_str}")
        lines.append(f"       여백({margin_str}) borderFillIDRef={bf_ref}")
        if b_offsets:
            lines.append(f"       borderOffset({', '.join(f'{k}={v}' for k, v in b_offsets.items())})")
    lines.append("")
    return lines


def _analyze_cell(tc: Element, indent: str = "") -> str:
    lines = []
    bf = tc.get("borderFillIDRef", "?")
    addr = tc.find("hp:cellAddr", NS)
    col = addr.get("colAddr", "?") if addr is not None else "?"
    row = addr.get("rowAddr", "?") if addr is not None else "?"
    span = tc.find("hp:cellSpan", NS)
    cs = span.get("colSpan", "1") if span is not None else "1"
    rs = span.get("rowSpan", "1") if span is not None else "1"
    sz = tc.find("hp:cellSz", NS)
    w = sz.get("width", "?") if sz is not None else "?"
    h = sz.get("height", "?") if sz is not None else "?"
    margin = tc.find("hp:cellMargin", NS)
    cm_str = ""
    if margin is not None:
        ml, mr, mt, mb = margin.get("left", "0"), margin.get("right", "0"), margin.get("top", "0"), margin.get("bottom", "0")
        cm_str = f" cellMargin=[{ml},{mr},{mt},{mb}]"
    span_str = (f" colSpan={cs}" if cs != "1" else "") + (f" rowSpan={rs}" if rs != "1" else "")
    lines.append(f"{indent}Cell({col},{row}) w={w} h={h}{span_str} borderFill={bf}{cm_str}")
    sublist = tc.find("hp:subList", NS)
    if sublist is not None:
        valign = sublist.get("vertAlign", "?")
        if valign != "CENTER":
            lines.append(f"{indent}  vertAlign={valign}")
        for p in sublist.findall("hp:p", NS):
            ppr = p.get("paraPrIDRef", "0")
            run_parts = []
            for run in p.findall("hp:run", NS):
                cpr = run.get("charPrIDRef", "0")
                txt = _get_text(run)
                if run.find("hp:tbl", NS) is not None:
                    run_parts.append("[내부테이블]")
                elif txt:
                    display = txt[:40] + "..." if len(txt) > 40 else txt
                    run_parts.append(f'charPr={cpr}:"{display}"')
                else:
                    run_parts.append(f"charPr={cpr}:(빈)")
            content = " + ".join(run_parts) if run_parts else "(빈)"
            lines.append(f"{indent}  P paraPr={ppr} {content}")
    return "\n".join(lines)


def _analyze_table(tbl: Element, indent: str = "") -> str:
    lines = []
    rows = int(tbl.get("rowCnt", "0"))
    cols = int(tbl.get("colCnt", "0"))
    tbl_id = tbl.get("id", "?")
    bf = tbl.get("borderFillIDRef", "?")
    sz = tbl.find("hp:sz", NS)
    w = sz.get("width", "?") if sz is not None else "?"
    h = sz.get("height", "?") if sz is not None else "?"
    pos = tbl.find("hp:pos", NS)
    treat_as_char = pos.get("treatAsChar", "?") if pos is not None else "?"
    h_align = pos.get("horzAlign", "?") if pos is not None else "?"
    lines.append(f"{indent}┌─ TABLE id={tbl_id} {rows}행×{cols}열 w={w} h={h}")
    lines.append(f"{indent}│  borderFill={bf} treatAsChar={treat_as_char} horzAlign={h_align}")
    col_widths: dict[int, str] = {}
    for tr in tbl.findall("hp:tr", NS):
        for tc in tr.findall("hp:tc", NS):
            addr = tc.find("hp:cellAddr", NS)
            if addr is not None:
                col_idx = int(addr.get("colAddr", "0"))
                span_el = tc.find("hp:cellSpan", NS)
                cs = int(span_el.get("colSpan", "1")) if span_el is not None else 1
                if cs == 1 and col_idx not in col_widths:
                    csz = tc.find("hp:cellSz", NS)
                    if csz is not None:
                        col_widths[col_idx] = csz.get("width", "?")
    sorted_widths = [col_widths.get(i, "?") for i in range(cols)]
    lines.append(f"{indent}│  열너비: [{', '.join(sorted_widths)}]")
    total = sum(int(v) for v in sorted_widths if v != "?" and v.isdigit())
    lines.append(f"{indent}│  합계: {total}")
    lines.append(f"{indent}│")
    for ri, tr in enumerate(tbl.findall("hp:tr", NS)):
        lines.append(f"{indent}│  ── Row {ri}")
        for tc in tr.findall("hp:tc", NS):
            lines.append(_analyze_cell(tc, indent + "│     "))
    lines.append(f"{indent}└─────")
    lines.append("")
    return "\n".join(lines)


def _analyze_paragraph(p: Element, indent: str = "", table_id_filter: str | None = None) -> str:
    lines = []
    pid = p.get("id", "?")
    ppr = p.get("paraPrIDRef", "0")
    run_parts = []
    has_table = False
    has_secpr = False
    for run in p.findall("hp:run", NS):
        cpr = run.get("charPrIDRef", "0")
        if run.find("hp:secPr", NS) is not None:
            has_secpr = True
            continue
        if run.find("hp:ctrl", NS) is not None:
            continue
        tbl = run.find("hp:tbl", NS)
        if tbl is not None:
            has_table = True
            tbl_id = tbl.get("id", "?")
            if table_id_filter is None or tbl_id == table_id_filter:
                if run_parts and table_id_filter is None:
                    lines.append(f"{indent}P id={pid} paraPr={ppr} {' + '.join(run_parts)}")
                    run_parts = []
                lines.append(_analyze_table(tbl, indent))
            continue
        txt = _get_text(run)
        if txt:
            display = txt[:50] + "..." if len(txt) > 50 else txt
            run_parts.append(f'charPr={cpr}:"{display}"')
        else:
            run_parts.append(f"charPr={cpr}:(빈)")
    if table_id_filter is not None:
        return "\n".join(lines) if lines else ""
    if not has_table:
        content = " + ".join(run_parts) if run_parts else "(빈)"
        prefix = "[secPr] " if has_secpr else ""
        lines.append(f"{indent}P id={pid} paraPr={ppr} {prefix}{content}")
    elif run_parts:
        lines.append(f"{indent}P id={pid} paraPr={ppr} {' + '.join(run_parts)}")
    return "\n".join(lines)


def _analyze_section(section_root: Element, table_id_filter: str | None = None) -> str:
    lines = ["▶ 문서 구조"]
    secpr = section_root.find(".//hp:secPr", NS)
    if secpr is not None:
        pagepr = secpr.find("hp:pagePr", NS)
        if pagepr is not None:
            w = pagepr.get("width", "?")
            h = pagepr.get("height", "?")
            landscape = pagepr.get("landscape", "?")
            lines.append(f"  페이지: {w} × {h} ({landscape})")
            margin = pagepr.find("hp:margin", NS)
            if margin is not None:
                lines.append(f"  여백: 좌={margin.get('left')} 우={margin.get('right')} 상={margin.get('top')} 하={margin.get('bottom')}")
                lines.append(f"  머리말={margin.get('header')} 꼬리말={margin.get('footer')}")
                left = int(margin.get("left", "0"))
                right = int(margin.get("right", "0"))
                lines.append(f"  본문폭: {int(w) - left - right} ({w}-{left}-{right})")
        for pbf in secpr.findall("hp:pageBorderFill", NS):
            if pbf.get("type", "?") == "BOTH":
                bfref = pbf.get("borderFillIDRef", "?")
                tb = pbf.get("textBorder", "?")
                off = pbf.find("hp:offset", NS)
                if off is not None:
                    lines.append(f"  페이지테두리: borderFill={bfref} textBorder={tb} offset=[{off.get('left')},{off.get('right')},{off.get('top')},{off.get('bottom')}]")
    lines.append("")
    lines.append("  ════════ 본문 ════════")
    lines.append("")
    sec = section_root.find(".//hs:sec", NS)
    if sec is None:
        sec = section_root
    for p in sec.findall("hp:p", NS):
        para_lines = _analyze_paragraph(p, "  ", table_id_filter=table_id_filter)
        if para_lines:
            lines.append(para_lines)
    return "\n".join(lines)


def cmd_analyze(args: argparse.Namespace) -> None:
    FONT_MAP.clear()
    if not os.path.exists(args.input):
        die(f"{args.input} not found")

    tmpdir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(args.input, "r") as z:
            all_names = z.namelist()
            z.extractall(tmpdir)

        header_path = os.path.join(tmpdir, "Contents", "header.xml")
        if not os.path.exists(header_path):
            die("Contents/header.xml not found")

        section_names = sorted(
            [n for n in all_names if SECTION_RE.match(n)],
            key=lambda n: int(SECTION_RE.match(n).group(1)),  # type: ignore[union-attr]
        )
        if not section_names:
            die("no section XML files found in archive")

        header_root = ET.parse(header_path).getroot()

        if args.extract_header:
            shutil.copy2(header_path, args.extract_header)
            print(f"header.xml → {args.extract_header}")

        if args.extract_section:
            section0_path = os.path.join(tmpdir, section_names[0].replace("/", os.sep))
            shutil.copy2(section0_path, args.extract_section)
            print(f"{section_names[0]} → {args.extract_section}")

        print("=" * 64)
        print(f"  HWPX 심층 분석: {os.path.basename(args.input)}")
        print("=" * 64)
        print()

        if args.table_id:
            found = False
            for sec_name in section_names:
                sec_path = os.path.join(tmpdir, sec_name.replace("/", os.sep))
                section_root = ET.parse(sec_path).getroot()
                result = _analyze_section(section_root, table_id_filter=args.table_id)
                if "TABLE id=" in result:
                    print(result)
                    found = True
            if not found:
                print(
                    f"Warning: table id={args.table_id} not found "
                    "(only top-level tables are searched; nested tables are not traversed)",
                    file=sys.stderr,
                )
        else:
            for line in _analyze_fonts(header_root):
                print(line)
            for line in _analyze_borderfills(header_root):
                print(line)
            for line in _analyze_charprops(header_root):
                print(line)
            for line in _analyze_paraprops(header_root):
                print(line)
            for sec_name in section_names:
                sec_path = os.path.join(tmpdir, sec_name.replace("/", os.sep))
                section_root = ET.parse(sec_path).getroot()
                if len(section_names) > 1:
                    sec_idx = SECTION_RE.match(sec_name).group(1)  # type: ignore[union-attr]
                    print(f"\n── section {sec_idx} ──")
                print(_analyze_section(section_root))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── next-id ───────────────────────────────────────────────────────────────────

def cmd_next_id(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    if not input_path.is_file():
        die(f"File not found: {args.input}")

    is_hwpx = input_path.suffix.lower() == ".hwpx"
    existing = get_ids_from_hwpx(input_path) if is_hwpx else collect_ids(input_path.read_bytes().decode("utf-8"))

    if args.list:
        sorted_ids = sorted(existing)
        print(f"Existing IDs ({len(sorted_ids)} total):")
        for i in sorted_ids:
            print(f"  {i}")
        return

    start = max(max(existing) + 1, MIN_USER_ID) if existing else MIN_USER_ID
    new_ids = list(range(start, start + args.count))
    print(" ".join(str(i) for i in new_ids))


_CONTENT_HPF = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<opf:package xmlns:opf="http://www.hancom.co.kr/hwpml/2011/opf">'
    '<opf:metadata>'
    '<opf:title/>'
    '<opf:meta name="creator" content="old"/>'
    '<opf:meta name="lastsaveby" content="old"/>'
    '<opf:meta name="CreatedDate" content="2000-01-01T00:00:00Z"/>'
    '<opf:meta name="ModifiedDate" content="2000-01-01T00:00:00Z"/>'
    '<opf:meta name="date" content="2000년 01월 01일"/>'
    '</opf:metadata>'
    '</opf:package>'
)

_HEADER_XML = (
    '<?xml version="1.0"?>'
    '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">'
    '<hh:fontfaces>'
    '<hh:fontface lang="HANGUL">'
    '<hh:font id="1" face="바탕"/>'
    '</hh:fontface>'
    '</hh:fontfaces>'
    '<hh:charProperties>'
    '<hh:charPr id="5" height="1000" textColor="#000000" borderFillIDRef="2">'
    '<hh:fontRef hangul="1"/>'
    '<hh:bold/>'
    '</hh:charPr>'
    '</hh:charProperties>'
    '</hh:head>'
)


def _run_tests() -> None:
    import tempfile

    failures = []

    # BUILD-1: _validate_xml accepts well-formed XML
    try:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ok.xml"
            p.write_text('<?xml version="1.0"?><root><child/></root>', encoding="utf-8")
            _validate_xml(p)
        print("BUILD-1 PASS: well-formed XML accepted")
    except Exception as e:
        failures.append(f"BUILD-1 FAIL: {e!r}")

    # BUILD-2: _validate_xml raises SystemExit on malformed XML
    try:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.xml"
            p.write_text("<root><unclosed></root>", encoding="utf-8")
            try:
                _validate_xml(p)
                failures.append("BUILD-2 FAIL: malformed XML did not raise")
            except SystemExit:
                print("BUILD-2 PASS: malformed XML raises SystemExit")
    except Exception as e:
        failures.append(f"BUILD-2 FAIL: {e!r}")

    # BUILD-3: _update_metadata fills empty title, replaces creator/lastsaveby, bumps dates
    try:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "content.hpf"
            p.write_text(_CONTENT_HPF, encoding="utf-8")
            _update_metadata(p, "새제목", "작성자")
            result = p.read_text(encoding="utf-8")
            checks = [
                "<opf:title>새제목</opf:title>" in result,
                result.count('content="작성자"') == 2,
                "2000-01-01T00:00:00Z" not in result,
            ]
            if all(checks):
                print("BUILD-3 PASS: title/creator/lastsaveby/date replaced")
            else:
                failures.append(f"BUILD-3 FAIL: {checks!r} not fully updated: {result}")
    except Exception as e:
        failures.append(f"BUILD-3 FAIL: {e!r}")

    # BUILD-4: _pack_hwpx + _validate_hwpx round trip has no errors
    try:
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            (work / "Contents").mkdir(parents=True)
            (work / "mimetype").write_text("application/hwp+zip", encoding="utf-8")
            (work / "Contents" / "content.hpf").write_text(_CONTENT_HPF, encoding="utf-8")
            (work / "Contents" / "header.xml").write_text(_HEADER_XML, encoding="utf-8")
            (work / "Contents" / "section0.xml").write_text(
                '<?xml version="1.0"?><hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"/>',
                encoding="utf-8",
            )
            out = Path(d) / "out.hwpx"
            _pack_hwpx(work, out)
            errors = _validate_hwpx(out)
            if errors:
                failures.append(f"BUILD-4 FAIL: unexpected validation errors: {errors!r}")
            else:
                print("BUILD-4 PASS: packed archive validates clean")
    except Exception as e:
        failures.append(f"BUILD-4 FAIL: {e!r}")

    # BUILD-5: _get_text concatenates run text nodes
    try:
        frag = (
            '<hp:run xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            '<hp:t>안녕</hp:t><hp:t>하세요</hp:t></hp:run>'
        )
        el = ET.fromstring(frag)
        text = _get_text(el)
        if text == "안녕하세요":
            print("BUILD-5 PASS: _get_text concatenates run text")
        else:
            failures.append(f"BUILD-5 FAIL: got {text!r}")
    except Exception as e:
        failures.append(f"BUILD-5 FAIL: {e!r}")

    # BUILD-6: _analyze_charprops reports pt conversion, resolved font name, bold flag
    try:
        FONT_MAP.clear()
        root = ET.fromstring(_HEADER_XML)
        _analyze_fonts(root)
        lines = "\n".join(_analyze_charprops(root))
        if "10.0pt 바탕" in lines and "볼드" in lines:
            print("BUILD-6 PASS: charPr pt/font/bold reported")
        else:
            failures.append(f"BUILD-6 FAIL: unexpected output: {lines}")
    except Exception as e:
        failures.append(f"BUILD-6 FAIL: {e!r}")

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All build tests passed")
    sys.exit(0)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    configure_io()
    if sys.argv[1:] == ["--test"]:
        _run_tests()
        return
    parser = argparse.ArgumentParser(description="HWPX document creation and analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # build
    p_build = sub.add_parser("build", help="Assemble HWPX from templates and XML overrides")
    p_build.add_argument("--template", "-t", choices=AVAILABLE_TEMPLATES,
                         help="Document type template overlay")
    p_build.add_argument("--header", help="Custom header.xml override")
    p_build.add_argument("--section", help="Custom section0.xml override")
    p_build.add_argument("--title", help="Document title (content.hpf metadata)")
    p_build.add_argument("--creator", help="Document creator (content.hpf metadata)")
    p_build.add_argument("--output", "-o", type=Path, required=True, help="Output .hwpx file path")
    p_build.add_argument("--update-preview", action="store_true",
                         help="Refresh Preview/PrvText.txt from section0.xml content")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Deep-analyze HWPX document structure")
    p_analyze.add_argument("input", help="Input .hwpx file")
    p_analyze.add_argument("--extract-header", metavar="PATH", help="Extract header.xml to path")
    p_analyze.add_argument("--extract-section", metavar="PATH", help="Extract first section XML to path")
    p_analyze.add_argument("--table-id", metavar="TABLE_ID", help="Show only this table's analysis")

    # next-id
    p_next = sub.add_parser("next-id", help="Get next available hp:p ID(s)")
    p_next.add_argument("input", help="Input .hwpx file or section XML")
    p_next.add_argument("--count", type=int, default=1, help="Number of IDs to generate (default: 1)")
    p_next.add_argument("--list", action="store_true", help="List all existing non-placeholder IDs")

    args = parser.parse_args()

    if args.cmd == "build":
        cmd_build(args)
    elif args.cmd == "analyze":
        cmd_analyze(args)
    elif args.cmd == "next-id":
        cmd_next_id(args)


if __name__ == "__main__":
    main()
