"""Shared utilities for hwpx scripts."""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import NoReturn

MIN_READABLE_PT = 5

# Hancom OWPML namespace URIs (HWPML 2011). Import these instead of re-declaring
# the literal strings per script — they are the single source of truth.
NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS_HS = "http://www.hancom.co.kr/hwpml/2011/section"
NS_HC = "http://www.hancom.co.kr/hwpml/2011/core"
NS_HH = "http://www.hancom.co.kr/hwpml/2011/head"
NS = {"hp": NS_HP, "hs": NS_HS, "hc": NS_HC, "hh": NS_HH}


def configure_io() -> None:
    """Force UTF-8 on stdout/stderr so Korean text and box-drawing chars survive a
    non-UTF-8 console (e.g. Windows cp949). Call once at the top of each script's
    main(), before any output, so every script handles encoding identically."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def die(msg: str, code: int = 1) -> NoReturn:
    """Print `Error: <msg>` to stderr and exit. Single convention for the
    CLI-boundary aborts every script would otherwise hand-roll."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


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
            print(f"Warning: could not load charPr heights from {p}: {e}", file=sys.stderr)
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
        except ValueError:
            continue
        if cid is not None:
            result[cid] = height
    return result

LINESEG_RE = re.compile(r"<hp:linesegarray>.*?</hp:linesegarray>", re.DOTALL)
PARA_ID_RE = re.compile(r'<hp:p\s[^>]*\bid="(\d+)"')
TBL_ID_RE = re.compile(r'<hp:tbl\s[^>]*\bid="(\d+)"')
# Single canonical section-file pattern. The capture group yields the section
# index; `.match()` alone still works as a boolean test for callers that only
# need "is this a section file?".
SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")
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


def load_section(inp: Path, section: int = 0) -> tuple[str, str]:
    """Read Contents/section{N}.xml from a .hwpx archive OR an unpacked directory.

    Returns (xml_text, target_name). `target_name` is handed back so the caller
    can pass it straight to save_section() without re-deriving the path. Aborts
    via die() when the input or the section is missing — the single load path all
    section-editing commands share instead of hand-rolling the dir/archive fork.
    """
    target = f"Contents/section{section}.xml"
    if inp.is_dir():
        section_file = inp / target
        if not section_file.is_file():
            die(f"{target} not found in {inp}")
        return section_file.read_text(encoding="utf-8"), target
    if inp.is_file():
        with zipfile.ZipFile(inp, "r") as zin:
            if target not in zin.namelist():
                die(f"{target} not in archive")
            return zin.read(target).decode("utf-8"), target
    die(f"not found: {inp}")


def save_section(inp: Path, target: str, new_xml: str, output: str | None) -> str:
    """Write `new_xml` back as the `target` entry, mirroring load_section().

    Directory input is edited in place; archive input is copied to `output` with
    every other entry preserved byte-for-byte and mimetype forced to ZIP_STORED
    (HWPX requires the first entry uncompressed). Returns the path written so the
    caller can report it. The archive branch requires `output`.
    """
    if inp.is_dir():
        section_file = inp / target
        section_file.write_text(new_xml, encoding="utf-8")
        return str(section_file)
    if output is None:
        die("--output required for .hwpx input")
    with zipfile.ZipFile(inp, "r") as zin:
        entries = [(zi, zin.read(zi.filename)) for zi in zin.infolist()]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
        for zi, data in entries:
            if zi.filename == target:
                data = new_xml.encode("utf-8")
            ct = zipfile.ZIP_STORED if zi.filename == "mimetype" else zi.compress_type
            zout.writestr(zi.filename, data, compress_type=ct)
    return output


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
                failures.append(f"COMMON-1 FAIL: valid height not loaded, got {heights!r}")
            elif "9" in heights:
                failures.append(f"COMMON-1 FAIL: malformed height should be skipped, got {heights!r}")
            else:
                print("COMMON-1 PASS: malformed height skipped, valid height kept")
        except Exception as e:
            failures.append(f"COMMON-1 FAIL: raised {e!r}")

    # COMMON-2: load_section / save_section round trip for archive and dir input
    with tempfile.TemporaryDirectory() as d:
        section_xml = (
            '<?xml version="1.0"?>'
            '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            '<hp:p id="0"><hp:run><hp:t>원본</hp:t></hp:run></hp:p></hp:sec>'
        )
        # archive round trip
        try:
            arc = Path(d) / "in.hwpx"
            with zipfile.ZipFile(arc, "w") as zf:
                zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
                zf.writestr("Contents/section0.xml", section_xml)
            loaded, target = load_section(arc, 0)
            out = Path(d) / "out.hwpx"
            written = save_section(arc, target, loaded.replace("원본", "수정"), str(out))
            with zipfile.ZipFile(written, "r") as zf:
                got = zf.read("Contents/section0.xml").decode("utf-8")
                mt = zf.getinfo("mimetype").compress_type
            if "수정" in got and mt == zipfile.ZIP_STORED:
                print("COMMON-2a PASS: archive load/save round trip keeps mimetype STORED")
            else:
                failures.append(f"COMMON-2a FAIL: got={got!r} mimetype_ct={mt}")
        except Exception as e:
            failures.append(f"COMMON-2a FAIL: {e!r}")
        # dir round trip (in place)
        try:
            unpacked = Path(d) / "unpacked"
            (unpacked / "Contents").mkdir(parents=True)
            (unpacked / "Contents" / "section0.xml").write_text(section_xml, encoding="utf-8")
            loaded, target = load_section(unpacked, 0)
            written = save_section(unpacked, target, loaded.replace("원본", "덮음"), None)
            got = Path(written).read_text(encoding="utf-8")
            if "덮음" in got:
                print("COMMON-2b PASS: dir load/save edits section in place")
            else:
                failures.append(f"COMMON-2b FAIL: got={got!r}")
        except Exception as e:
            failures.append(f"COMMON-2b FAIL: {e!r}")

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All _common tests passed")
    sys.exit(0)


if __name__ == "__main__":
    configure_io()
    if sys.argv[1:] == ["--test"]:
        _run_tests()
