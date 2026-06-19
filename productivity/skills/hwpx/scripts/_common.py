"""Shared utilities for hwpx scripts."""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

MIN_READABLE_PT = 5


def charpr_pt(height_hwpunit: int) -> float:
    return height_hwpunit / 100


def load_charpr_heights(path) -> dict:
    """unpacked dir, header.xml path, or .hwpx archive → {charPr_id_str: height_int}"""
    p = Path(path)
    if p.is_dir():
        header = p / "Contents" / "header.xml"
        if not header.exists():
            return {}
        try:
            root = ET.parse(str(header)).getroot()
        except ET.ParseError:
            return {}
    elif p.suffix.lower() in (".hwpx", ".zip"):
        try:
            with zipfile.ZipFile(str(p), "r") as zf:
                if "Contents/header.xml" not in zf.namelist():
                    return {}
                data = zf.read("Contents/header.xml")
            root = ET.fromstring(data)
        except (zipfile.BadZipFile, KeyError, EOFError, ET.ParseError) as e:
            print("Warning: could not load charPr heights from %s: %s" % (p, e), file=sys.stderr)
            return {}
    else:
        if not p.exists():
            return {}
        try:
            root = ET.parse(str(p)).getroot()
        except ET.ParseError:
            return {}
    result = {}
    for cp in root.iter():
        if not (cp.tag.endswith("}charPr") or cp.tag == "charPr"):
            continue
        cid = cp.get("id")
        try:
            height = int(cp.get("height", "0"))
        except (TypeError, ValueError):
            continue
        if cid is not None:
            result[cid] = height
    return result

LINESEG_RE = re.compile(r"<hp:linesegarray>.*?</hp:linesegarray>", re.DOTALL)
PARA_ID_RE = re.compile(r'<hp:p\s[^>]*\bid="(\d+)"')
TBL_ID_RE = re.compile(r'<hp:tbl\s[^>]*\bid="(\d+)"')
SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")
SECTION_N_RE = re.compile(r"^Contents/section(\d+)\.xml$")
PLACEHOLDER_IDS = {"0", "2147483648"}
MIN_USER_ID = 1_000_000_000


def strip_linesegarray(xml_str: str) -> tuple[str, int]:
    new_str, count = LINESEG_RE.subn("", xml_str)
    return new_str, count


def check_para_ids(xml_str: str) -> list[str]:
    ids = [i for i in PARA_ID_RE.findall(xml_str) if i not in PLACEHOLDER_IDS]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        return [f"Duplicate hp:p IDs detected (HWP crash risk): {dupes}"]
    return []


def collect_ids(xml_str: str) -> set[int]:
    """Collect all non-placeholder hp:p and hp:tbl IDs from XML string."""
    ids: set[int] = set()
    for m in PARA_ID_RE.finditer(xml_str):
        ids.add(int(m.group(1)))
    for m in TBL_ID_RE.finditer(xml_str):
        ids.add(int(m.group(1)))
    return ids - {0, 2147483648}


def get_ids_from_hwpx(path: Path) -> set[int]:
    all_ids: set[int] = set()
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            if SECTION_RE.match(name):
                xml_str = zf.read(name).decode("utf-8")
                all_ids |= collect_ids(xml_str)
    return all_ids


def load_section_xml(inp: Path, section: int = 0) -> str:
    target = f"Contents/section{section}.xml"
    if inp.is_dir():
        section_file = inp / target
        if not section_file.is_file():
            print(f"Error: {target} not found in directory {inp}", file=sys.stderr)
            sys.exit(1)
        return section_file.read_text(encoding="utf-8")
    with zipfile.ZipFile(inp, "r") as zin:
        if target not in zin.namelist():
            print(f"Error: {target} not in archive", file=sys.stderr)
            sys.exit(1)
        return zin.read(target).decode("utf-8")


def find_table(xml: str, table_id: str) -> tuple[int, int] | None:
    m = re.search(r'<hp:tbl\b[^>]*\bid="%s"' % re.escape(table_id), xml)
    if not m:
        return None
    ti = m.start()
    depth = 0
    for mm in re.finditer(r"<hp:tbl\b|</hp:tbl>", xml[ti:]):
        if mm.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return ti, ti + mm.end()
        else:
            depth += 1
    return None


def top_cells(tbl: str) -> list[tuple[int, int]]:
    tbl_depth = 0
    stack: list[tuple[int, int]] = []
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"<hp:tbl\b|</hp:tbl>|<hp:tc\b|</hp:tc>", tbl):
        g = m.group()
        if g == "<hp:tbl":
            tbl_depth += 1
        elif g == "</hp:tbl>":
            tbl_depth -= 1
        elif g == "<hp:tc":
            stack.append((m.start(), tbl_depth))
        elif g == "</hp:tc>":
            start, d = stack.pop()
            if d == 1:
                out.append((start, m.end()))
    return out


def top_trs(tbl: str) -> list[tuple[int, int]]:
    depth = 0
    out: list[tuple[int, int]] = []
    st = None
    for m in re.finditer(r"<hp:tbl\b|</hp:tbl>|<hp:tr>|</hp:tr>", tbl):
        g = m.group()
        if g == "<hp:tbl":
            depth += 1
        elif g == "</hp:tbl>":
            depth -= 1
        elif g == "<hp:tr>":
            if depth == 1:
                st = m.start()
        elif g == "</hp:tr>":
            if depth == 1 and st is not None:
                out.append((st, m.end()))
    return out


def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _run_tests() -> None:
    import tempfile

    failures = []

    # COMMON-1: malformed non-numeric height must not raise; entry skipped, valid kept
    xml = (
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">'
        '<hh:charPr id="5" height="1000"/>'
        '<hh:charPr id="9" height="not-a-number"/>'
        '</hh:head>'
    )
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "header.xml"
        p.write_text(xml, encoding="utf-8")
        try:
            heights = load_charpr_heights(p)
            if heights.get("5") != 1000:
                failures.append("COMMON-1 FAIL: valid height not loaded, got %r" % heights)
            elif "9" in heights:
                failures.append("COMMON-1 FAIL: malformed height should be skipped, got %r" % heights)
            else:
                print("COMMON-1 PASS: malformed height skipped, valid height kept")
        except Exception as e:
            failures.append("COMMON-1 FAIL: raised %r" % e)

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All _common tests passed")
    sys.exit(0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        _run_tests()
