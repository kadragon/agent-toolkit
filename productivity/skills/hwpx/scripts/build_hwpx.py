#!/usr/bin/env python3
"""Build an HWPX document from templates and XML overrides.

Assembles a valid HWPX file by:
1. Copying the base template
2. Optionally overlaying a document-type template (gonmun, report, minutes, proposal)
3. Optionally overriding header.xml and/or section0.xml with custom files
4. Optionally setting metadata (title, creator)
5. Validating XML well-formedness
6. Packaging as HWPX (ZIP with mimetype first, ZIP_STORED)

Usage:
    # Empty document from base template
    python build_hwpx.py --output result.hwpx

    # Using a document-type template
    python build_hwpx.py --template gonmun --output result.hwpx

    # Custom section XML override
    python build_hwpx.py --template gonmun --section my_section0.xml --output result.hwpx

    # Custom header and section
    python build_hwpx.py --header my_header.xml --section my_section0.xml --output result.hwpx

    # With metadata
    python build_hwpx.py --template gonmun --section my.xml --title "제목" --creator "작성자" --output result.hwpx
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
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from lxml import etree

# Resolve paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
BASE_DIR = TEMPLATES_DIR / "base"

AVAILABLE_TEMPLATES = ["gonmun", "report", "minutes", "proposal"]


def validate_xml(filepath: Path) -> None:
    """Check that an XML file is well-formed. Raises on error."""
    try:
        etree.parse(str(filepath))
    except etree.XMLSyntaxError as e:
        raise SystemExit(f"Malformed XML in {filepath.name}: {e}")


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def update_metadata(content_hpf: Path, title: str | None, creator: str | None) -> None:
    """Update title and/or creator in content.hpf using str.replace (no lxml re-serialization)."""
    if not title and not creator:
        return

    raw = content_hpf.read_bytes().decode("utf-8")

    now = datetime.now(timezone.utc)
    iso_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now.strftime("%Y년 %m월 %d일")

    if title:
        safe_title = _xml_escape(title)
        raw = re.sub(r"<opf:title\s*/>", f"<opf:title>{safe_title}</opf:title>", raw)
        raw = re.sub(r"<opf:title>[^<]*</opf:title>", f"<opf:title>{safe_title}</opf:title>", raw)

    if creator:
        safe_creator = _xml_escape(creator)
        raw = re.sub(
            r'(<opf:meta name="creator" content=")[^"]*(")',
            rf'\g<1>{safe_creator}\2',
            raw,
        )
        raw = re.sub(
            r'(<opf:meta name="lastsaveby" content=")[^"]*(")',
            rf'\g<1>{safe_creator}\2',
            raw,
        )

    raw = re.sub(
        r'(<opf:meta name="CreatedDate" content=")[^"]*(")',
        rf'\g<1>{iso_now}\2',
        raw,
    )
    raw = re.sub(
        r'(<opf:meta name="ModifiedDate" content=")[^"]*(")',
        rf'\g<1>{iso_now}\2',
        raw,
    )
    raw = re.sub(
        r'(<opf:meta name="date" content=")[^"]*(")',
        rf'\g<1>{date_str}\2',
        raw,
    )

    content_hpf.write_bytes(raw.encode("utf-8"))


def pack_hwpx(input_dir: Path, output_path: Path) -> None:
    """Create HWPX archive with mimetype as first entry (ZIP_STORED)."""
    mimetype_file = input_dir / "mimetype"
    if not mimetype_file.is_file():
        raise SystemExit(f"Missing 'mimetype' in {input_dir}")

    all_files = sorted(
        p.relative_to(input_dir).as_posix()
        for p in input_dir.rglob("*")
        if p.is_file()
    )

    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        zf.write(mimetype_file, "mimetype", compress_type=ZIP_STORED)
        for rel_path in all_files:
            if rel_path == "mimetype":
                continue
            zf.write(input_dir / rel_path, rel_path, compress_type=ZIP_DEFLATED)


def validate_hwpx(hwpx_path: Path) -> list[str]:
    """Quick structural validation of the output HWPX."""
    errors: list[str] = []
    required = [
        "mimetype",
        "Contents/content.hpf",
        "Contents/header.xml",
        "Contents/section0.xml",
    ]

    try:
        zf = ZipFile(hwpx_path, "r")
    except (BadZipFile, OSError):
        return [f"Not a valid ZIP: {hwpx_path}"]

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
                    etree.fromstring(zf.read(name))
                except etree.XMLSyntaxError as e:
                    errors.append(f"Malformed XML: {name}: {e}")

    return errors


def update_preview(work_dir: Path) -> None:
    """Extract first 500 chars of text from section0.xml into Preview/PrvText.txt."""
    section_path = work_dir / "Contents" / "section0.xml"
    prv_text_path = work_dir / "Preview" / "PrvText.txt"
    if not section_path.is_file() or not prv_text_path.is_file():
        return
    ns = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}
    try:
        root = etree.fromstring(section_path.read_bytes())
        texts = [t.text for t in root.findall(".//hp:t", ns) if t.text]
        prv_text_path.write_text("".join(texts)[:500], encoding="utf-8")
    except etree.XMLSyntaxError:
        pass


def build(
    template: str | None,
    header_override: Path | None,
    section_override: Path | None,
    title: str | None,
    creator: str | None,
    output: Path,
    update_preview_text: bool = False,
) -> None:
    """Main build logic."""

    if not BASE_DIR.is_dir():
        raise SystemExit(f"Base template not found: {BASE_DIR}")

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir) / "build"

        # 1. Copy base template
        shutil.copytree(BASE_DIR, work)

        # 2. Apply template overlay
        if template:
            overlay_dir = TEMPLATES_DIR / template
            if not overlay_dir.is_dir():
                raise SystemExit(
                    f"Template '{template}' not found. "
                    f"Available: {', '.join(AVAILABLE_TEMPLATES)}"
                )
            for overlay_file in overlay_dir.iterdir():
                if overlay_file.is_file() and overlay_file.suffix == ".xml":
                    dest = work / "Contents" / overlay_file.name
                    shutil.copy2(overlay_file, dest)

        # 3. Apply custom overrides
        if header_override:
            if not header_override.is_file():
                raise SystemExit(f"Header file not found: {header_override}")
            shutil.copy2(header_override, work / "Contents" / "header.xml")

        if section_override:
            if not section_override.is_file():
                raise SystemExit(f"Section file not found: {section_override}")
            shutil.copy2(section_override, work / "Contents" / "section0.xml")

        # 4. Update metadata
        update_metadata(work / "Contents" / "content.hpf", title, creator)

        # 4b. Optionally refresh Preview/PrvText.txt from section content
        if update_preview_text:
            update_preview(work)

        # 5. Validate all XML files
        for xml_file in work.rglob("*.xml"):
            validate_xml(xml_file)
        for hpf_file in work.rglob("*.hpf"):
            validate_xml(hpf_file)

        # 6. Pack
        pack_hwpx(work, output)

    # 7. Final validation
    errors = validate_hwpx(output)
    if errors:
        print(f"WARNING: {output} has issues:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
    else:
        print(f"VALID: {output}")
        print(f"  Template: {template or 'base'}")
        if header_override:
            print(f"  Header: {header_override}")
        if section_override:
            print(f"  Section: {section_override}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build HWPX document from templates and XML overrides"
    )
    parser.add_argument(
        "--template", "-t",
        choices=AVAILABLE_TEMPLATES,
        help="Document type template to use as overlay",
    )
    parser.add_argument(
        "--header",
        type=Path,
        help="Custom header.xml to override",
    )
    parser.add_argument(
        "--section",
        type=Path,
        help="Custom section0.xml to override",
    )
    parser.add_argument(
        "--title",
        help="Document title (updates content.hpf metadata)",
    )
    parser.add_argument(
        "--creator",
        help="Document creator (updates content.hpf metadata)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Output .hwpx file path",
    )
    parser.add_argument(
        "--update-preview",
        action="store_true",
        help="Refresh Preview/PrvText.txt from section0.xml text content",
    )
    args = parser.parse_args()

    build(
        template=args.template,
        header_override=args.header,
        section_override=args.section,
        title=args.title,
        creator=args.creator,
        output=args.output,
        update_preview_text=args.update_preview,
    )


if __name__ == "__main__":
    main()
