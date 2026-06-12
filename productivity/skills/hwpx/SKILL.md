---
name: hwpx
description: >-
  Create, edit, or read HWPX (Hancom/한글) documents. "hwpx 만들어", "한글 문서 작성", "공문 만들어", "보고서 생성", "회의록 만들어", "제안서 작성", "hwpx 편집", "create hwpx", "make a hancom document", "edit hwp file". Also: .hwpx attachment, extract text from hwpx, OWPML, Hancom document conversion, Korean gov/biz document without saying "hwpx". NOT for Hancom product/company discussion without a document task.
---

# HWPX Document Skill — XML-first Workflow

Skill to create, edit, read Hancom Office HWPX files. Centered on **writing XML directly**.
HWPX = ZIP-based XML container (OWPML standard). Bypasses python-hwpx API formatting bugs, allows fine-grained format control.

## Handling attached HWPX — judge intent first

When user attaches `.hwpx`, do not auto-restore. Judge **request intent** first, pick mode. Restore = one mode, not default.

| Intent | Mode | Workflow |
|------|------|-----------|
| Reproduce attached doc near-exactly, swap only values/field names | Reference restore | Workflow 5 |
| Explicit request to add/delete/restructure content | Content edit | Workflow 2 |
| Only text/table content needed | Read/extract | Workflow 3 |
| Attachment is style reference only, content written fresh | Reference-based generation | Workflow 5 |
| No attachment | New creation | Workflow 1 |

Intent unclear → ask user, do not assume restore.

### Per-mode page-count rules / completion gates

| Mode | Page count | Completion gate |
|------|------|------------|
| Reference restore | Must match reference | `validate.py validate --baseline` + `validate.py page-guard` |
| Content edit | Changing is normal | `validate.py validate --baseline` + actually open in Hancom |
| New / reference-based generation | No constraint | `validate.py validate` |

"Same page count", `validate.py page-guard`, "compress/summarize text" rules apply **only to reference restore mode**. In content edit mode, do not revert work on page count change. For restore-mode steps and checklist, see **Workflow 5**.

> **`validate.py validate --baseline` scope**: real-world HWPX originals often contain duplicate `hp:p` IDs that HWP allows. Validating without `--baseline` flags these pre-existing duplicates as `INVALID` (false positive). **`--baseline` is required when validating against an original attached document (Workflows 2, 5); omit for new documents (Workflow 1).**

## Environment

No external packages required. Scripts use stdlib `xml.etree.ElementTree` only.
- `SKILL_DIR` = absolute path of directory holding this SKILL.md (`.../skills/hwpx`)
- OS-specific Python invocation, encoding gotchas (Windows cp949/UTF-8, codepoint escaping), subprocess encoding, and temp-file placement: see `$SKILL_DIR/references/environment.md`

## Directory structure

```
.../skills/hwpx/
├── SKILL.md                              # 이 파일
├── scripts/
│   ├── _common.py                        # 공유 유틸리티 (regex, ZIP helpers, table helpers)
│   ├── office.py unpack|pack             # HWPX ↔ 디렉토리 (raw bytes + 순서 manifest)
│   ├── build.py build|analyze|next-id    # 문서 조립 + 심층 분석 + ID 조회
│   ├── table.py dump|locate|insert|replace|delete|calc-widths|strip-lineseg  # 표 편집 전체
│   ├── validate.py validate|page-guard   # 구조 검증 + 페이지 드리프트 위험 검사
│   └── text.py extract|patch             # 텍스트 추출 + 원자적 텍스트 교체
├── templates/
│   ├── base/                             # 베이스 템플릿 (Skeleton 기반)
│   │   ├── mimetype, META-INF/*, version.xml, settings.xml, Preview/*
│   │   └── Contents/ (header.xml, section0.xml, content.hpf)
│   ├── gonmun/                           # 공문 오버레이 (header.xml, section0.xml)
│   ├── report/                           # 보고서 오버레이
│   ├── minutes/                          # 회의록 오버레이
│   └── proposal/                         # 제안서/사업개요 오버레이 (색상 헤더바, 번호 배지)
└── references/
    ├── hwpx-format.md                    # OWPML XML element reference
    ├── editing-gotchas.md                # Editing traps (FORMULA, substring collision, count, deletion)
    ├── xml-integrity.md                  # XML serialization safe patterns (lxml rules + code examples)
    ├── style-maps.md                     # Per-template charPrIDRef/paraPrIDRef/borderFillIDRef
    ├── section-writing.md                # section0.xml XML templates (paragraph, table, structure)
    ├── scripts-guide.md                  # Utility script CLI usage details
    └── environment.md                    # OS-specific Python invocation, encoding gotchas, temp-file rules
```

---

## Workflow 1: XML-first new document creation (no attached reference)

### Flow

**Template selection matrix:**

| Template | Use for |
|----------|---------|
| `gonmun` | Official correspondence (공문) |
| `report` | Multi-section reports with figures |
| `minutes` | Meeting records |
| `proposal` | Proposals with approval signatures |
| `base` | Everything else |

1. **Pick template** (base/gonmun/report/minutes/proposal) → look up style IDs in `$SKILL_DIR/references/style-maps.md`
2. **Write section0.xml** (body content)
3. **(Optional) edit header.xml** (when new styles needed) → see `$SKILL_DIR/references/hwpx-format.md` § "header.xml Editing Guide"
4. **Build with build.py build**
5. **Validate with validate.py**

> If attached reference exists and intent is restore/edit, use Workflow 5 instead.

### Basic usage

```bash
# 빈 문서 (base 템플릿)
python3 "$SKILL_DIR/scripts/build.py" build --output result.hwpx

# 템플릿 사용
python3 "$SKILL_DIR/scripts/build.py" build --template gonmun --output result.hwpx

# 커스텀 section0.xml 오버라이드
python3 "$SKILL_DIR/scripts/build.py" build --template gonmun --section my_section0.xml --output result.hwpx

# header도 오버라이드
python3 "$SKILL_DIR/scripts/build.py" build --header my_header.xml --section my_section0.xml --output result.hwpx

# 메타데이터 설정
python3 "$SKILL_DIR/scripts/build.py" build --template report --section my.xml \
  --title "제목" --creator "작성자" --output result.hwpx
```

### Practical pattern: write section0.xml inline → build

```bash
# 1. section0.xml을 임시파일로 작성
mkdir -p ./_work
SECTION=$(mktemp ./_work/section0_XXXX.xml)
cat > "$SECTION" << 'XMLEOF'
<?xml version='1.0' encoding='UTF-8'?>
<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"
        xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">
  <!-- secPr 포함 첫 문단 (base/section0.xml에서 복사) -->
  <!-- ... -->
  <hp:p id="1000000002" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:t>본문 내용</hp:t>
    </hp:run>
  </hp:p>
</hs:sec>
XMLEOF

# 2. 빌드
python3 "$SKILL_DIR/scripts/build.py" build --section "$SECTION" --output result.hwpx

# 3. 정리
rm -f "$SECTION"
```

---

## section0.xml writing guide

> Full XML templates (paragraph, empty line, mixed runs, table, ID rules) — read `$SKILL_DIR/references/section-writing.md`.

Key rules:
- Copy first paragraph from `templates/base/Contents/section0.xml` (secPr + colPr required in first run)
- Empty line: `<hp:t/>` (self-closing, not `<hp:t></hp:t>`)
- Table total width must equal body width (42520 HWPUNIT); use `table.py calc-widths` for ratios
- Paragraph id: sequential from `1000000001` — use `build.py next-id` to avoid collisions

---

## header.xml editing guide

> Full guide (charPr/paraPr/borderFill addition, font reference system, paraPr caution) — read `$SKILL_DIR/references/hwpx-format.md` § "header.xml Editing Guide".

**Key rules:**
- Copy `templates/base/Contents/header.xml`, add needed charPr/paraPr/borderFill, update `itemCnt`
- paraPr requires `hp:switch` structure (`hp:case` + `hp:default`); keep `borderFillIDRef="2"`

---

## Per-template style ID map

> Full style ID tables for all templates — read `$SKILL_DIR/references/style-maps.md`.

Pick template → look up `charPrIDRef`/`paraPrIDRef`/`borderFillIDRef` in style-maps.md before writing section0.xml.

---

## Workflow 2: edit existing document (unpack → Edit → pack)

> **Prerequisite**: read `$SKILL_DIR/references/editing-gotchas.md` before any edits — covers FORMULA fields, substring collision, count verification, paragraph deletion, and other silent-failure traps.

```bash
# 1. HWPX → 디렉토리 (raw bytes 추출, .hwpx_pack_order manifest 기록)
python3 "$SKILL_DIR/scripts/office.py" unpack document.hwpx ./unpacked/

# 2. XML 편집 — 편집 유형별 도구 선택:
#    - 표 셀 내용 수정 → table.py replace 필수 (lineseg + ID 충돌 자동 처리)
#      str.replace()로 셀 직접 수정 금지 — linesegarray 미제거로 "문서 변경됨" 경고 발생
#    - 일반 텍스트 (표 外) → text.py patch (safe str.replace + lineseg strip)
#    - 행 삽입/삭제 → table.py insert / table.py delete
#    본문: ./unpacked/Contents/section0.xml
#    스타일: ./unpacked/Contents/header.xml

# 3. 다시 HWPX로 패키징
python3 "$SKILL_DIR/scripts/office.py" pack ./unpacked/ edited.hwpx

# 4. 검증 (원본 대비)
python3 "$SKILL_DIR/scripts/validate.py" validate edited.hwpx --baseline document.hwpx
```

> **Validate timing when overwriting original**: if planning to overwrite with the original filename, run `validate --baseline` **first**. Order: `pack to temp → validate --baseline original → copy to final`. Overwriting the original first removes the baseline, forcing validation without `--baseline` and risking false-positive duplicate ID reports.

### Bulk / multi-stage edits

Many items → split into stages to catch silent failures early, verify each stage in Hancom.

1. **unpack once**. All later stages cumulatively modify `unpacked/Contents/section0.xml`.
2. **Per-stage scripts**: write each stage as small `.py`, put **`assert s.count(old) == expected`** on every `str.replace()`. Count off → aborts before corrupted file produced (`references/editing-gotchas.md` §3).
3. **Each stage: pack → validate → confirm opens in Hancom**, then proceed. Package per-stage output as `_work_stepN.hwpx` to avoid file-lock conflicts.
4. After all stages pass, apply final version to real file.

> **Multi-cell dir-mode**: when replacing many cells in one file, use `table.py replace` directly on the unpacked dir — reads/writes section0.xml in-place, no zip overhead per call:
> ```bash
> python3 "$SKILL_DIR/scripts/table.py" replace ./unpacked/ --table-id TABLE_ID --cell 2,1 --para 0 0 "값1"
> python3 "$SKILL_DIR/scripts/table.py" replace ./unpacked/ --table-id TABLE_ID --cell 3,1 --para 0 0 "값2"
> python3 "$SKILL_DIR/scripts/office.py" pack ./unpacked/ result.hwpx
> ```

### Bulk File Edit — N files simultaneously

Pattern for editing N template-based files simultaneously:

```python
import sys
sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 guard
import shutil
import subprocess
from pathlib import Path

SKILL_DIR = Path("/path/to/skills/hwpx")  # set to absolute path of this skill
UNPACK_PY = str(SKILL_DIR / "scripts/office.py")
PACK_PY = str(SKILL_DIR / "scripts/office.py")
VALIDATE_PY = str(SKILL_DIR / "scripts/validate.py")

# 파일별 데이터를 설정으로 분리
FILES = [
    {"src": "template_A.hwpx", "out": "result_A.hwpx", "name": "홍길동", "dept": "총무과"},
    {"src": "template_B.hwpx", "out": "result_B.hwpx", "name": "이순신", "dept": "인사과"},
]

for cfg in FILES:
    slug = Path(cfg["out"]).stem
    unpack_dir = Path(f"./_work/unpack_{slug}/")  # slug 포함 필수 — 충돌 방지

    subprocess.run(["python3", UNPACK_PY, "unpack", cfg["src"], str(unpack_dir)], check=True)
    section_path = unpack_dir / "Contents/section0.xml"
    s = section_path.read_text(encoding="utf-8")

    # 파일별 값 치환
    assert s.count("<hp:t>이름</hp:t>") == 1
    s = s.replace("<hp:t>이름</hp:t>", f'<hp:t>{cfg["name"]}</hp:t>')

    section_path.write_text(s, encoding="utf-8")

    tmp_out = Path(f"./_work/{slug}_tmp.hwpx")
    subprocess.run(["python3", PACK_PY, "pack", str(unpack_dir), str(tmp_out)], check=True)
    subprocess.run(["python3", VALIDATE_PY, "validate", str(tmp_out), "--baseline", cfg["src"]], check=True)
    shutil.copy(tmp_out, cfg["out"])
    print(f"[done] {cfg['out']}")
```

- Include slug in `unpack_dir` — prevents directory collision in N-file parallel runs
- `validate --baseline` first, overwrite second — maintain order (see §"Validate timing when overwriting original")
- After each stage, open at least one file in Hancom to verify — `validate.py` checks structure only

### Hancom-open verification (content-edit completion gate)

`validate.py` checks structure only. Completion gate for content edit = confirming it **actually opens in Hancom**.

- **Launch check**: open packaged hwpx (Windows: `Start-Process`), confirm Hancom process (`Hwp`) alive. On crash, process doesn't appear or exits immediately.
- **Fully close before repackaging**: close Hancom before re-pack/re-copying same file. **Multiple documents open in Hancom: `CloseMainWindow` closes only one main window** — remaining window locks file. Confirm full close (`Stop-Process` if not closed) before proceeding.
- **Verify copy success**: copying to locked file can fail silently as non-blocking error. After applying to real file, **confirm content match via md5** or similar.

---

## Workflow 3: read / text extraction

**When skill receives a filepath argument** (e.g. `read path/to/file.hwpx`, bare `path/to/file.hwpx`, or user requests "read file.hwpx" / "file.hwpx 읽어줘"): interpret any filepath as a text-extraction request regardless of the `read` keyword → run `text.py extract`. Skill does not auto-execute on invoke — run the commands below explicitly.

```bash
python3 "$SKILL_DIR/scripts/text.py" extract path/to/file.hwpx --format markdown
```

```bash
# 순수 텍스트
python3 "$SKILL_DIR/scripts/text.py" extract document.hwpx

# 테이블 포함
python3 "$SKILL_DIR/scripts/text.py" extract document.hwpx --include-tables

# 마크다운 형식
python3 "$SKILL_DIR/scripts/text.py" extract document.hwpx --format markdown
```

### Batch extraction (multiple folders × multiple files)

```bash
# Batch extraction from folder list (bash)
for f in ./folder1/*.hwpx ./folder2/*.hwpx ./folder3/*.hwpx; do
  echo "=== $f ==="
  python3 "$SKILL_DIR/scripts/text.py" extract "$f" --format markdown
done

# Recursive search + save results to files
find . -name "*.hwpx" | while IFS= read -r f; do
  out="${f%.hwpx}.txt"
  python3 "$SKILL_DIR/scripts/text.py" extract "$f" > "$out"
  echo "→ $out"
done
```

**Windows PowerShell** (`$SKILL_DIR` is a bash variable — not usable in PowerShell directly. Replace with absolute or relative path):
```powershell
$skillScripts = "C:\path\to\skills\hwpx\scripts"  # Replace with absolute path to SKILL_DIR\scripts
Get-ChildItem -Recurse -Filter "*.hwpx" | ForEach-Object {
    Write-Host "=== $($_.FullName) ==="
    python "$skillScripts\text.py" extract $_.FullName --format markdown
}
```

---

## Workflow 4: validation

```bash
# 단독 새 문서
python3 "$SKILL_DIR/scripts/validate.py" validate document.hwpx
# 첨부 원본을 편집/복원한 결과 — 기존 중복 ID 오탐 방지
python3 "$SKILL_DIR/scripts/validate.py" validate result.hwpx --baseline original.hwpx
```

Validation items: ZIP validity, required files present, mimetype content/position/compression method, XML well-formedness, secCnt/itemCnt/IDRef, `hp:p` ID duplicates (with `--baseline`, only new duplicates are errors).

---

## Workflow 5: reference restore / reference-based generation

Workflow to analyze attached HWPX and (a) make restored copy with only values/field names swapped, or (b) fill same layout with new content. Use when intent classified as "reference restore" or "reference-based generation".

### 99%-close restore criteria (restore-mode checklist)

- Identical `charPrIDRef`, `paraPrIDRef`, `borderFillIDRef` reference system
- Identical table `rowCnt`, `colCnt`, `colSpan`, `rowSpan`, `cellSz`, `cellMargin`
- Identical paragraph order, paragraph count, key empty-line/section positions
- Identical page/margin/section (secPr)
- Changes limited to user's requested scope (body text, values, field names, etc.)

### Same page count (100%) criteria — restore mode only

- Result document's final page count must match reference
- If page count likely to grow, compress/summarize text to fit existing layout first
- Do not change `hp:p`, `hp:tbl`, `rowCnt`, `colCnt`, `pageBreak`, `secPr` without explicit user request
- Do not mark complete on `validate.py validate` pass alone. `validate.py page-guard` must also pass
- On `validate.py page-guard` failure, do not submit as complete — fix cause (excess length / structure change) and rebuild
- If possible, confirm final page count in Hancom, recheck against reference

> For reference-based **generation** (style reference only, content written fresh), page-count criteria above do not apply — like new creation, `validate.py` is only gate.

### Flow

1. **Analyze** — deep-analyze reference document with `build.py analyze`
2. **Extract header.xml** — use reference's style definitions as-is
3. **Write section0.xml** — write new content following analyzed structure
4. **Build** — build with extracted header.xml + new section0.xml
5. **Validate** — `validate.py validate`
6. **Page guard** — `validate.py page-guard` (re-fix on failure)

### Usage

```bash
# 1. 심층 분석 (구조 청사진 출력)
python3 "$SKILL_DIR/scripts/build.py" analyze reference.hwpx

# 2. header.xml과 section0.xml을 추출하여 참고용으로 보관
mkdir -p ./_work
python3 "$SKILL_DIR/scripts/build.py" analyze reference.hwpx \
  --extract-header ./_work/ref_header.xml \
  --extract-section ./_work/ref_section.xml

# 3. 분석 결과를 보고 새 section0.xml 작성
#    - 동일한 charPrIDRef, paraPrIDRef 사용
#    - 동일한 테이블 구조 (열 수, 열 너비, 행 수, rowSpan/colSpan)
#    - 동일한 borderFillIDRef, cellMargin

# 4. 추출한 header.xml + 새 section0.xml로 빌드
python3 "$SKILL_DIR/scripts/build.py" build \
  --header ./_work/ref_header.xml \
  --section ./_work/new_section0.xml \
  --output result.hwpx

# 5. 검증 (원본 대비 — 기존 중복 ID 오탐 방지)
python3 "$SKILL_DIR/scripts/validate.py" validate result.hwpx --baseline reference.hwpx

# 6. 쪽수 드리프트 가드 (필수)
python3 "$SKILL_DIR/scripts/validate.py" page-guard \
  --reference reference.hwpx \
  --output result.hwpx
```

### Analysis output items

| Item | Description |
|------|------|
| Font definitions | hangul/latin font mapping |
| borderFill | border type/thickness + background color (detail per side) |
| charPr | font size (pt), font name, color, bold/italic/underline/strikeout, fontRef |
| paraPr | align, line spacing, margin (left/right/prev/next/intent), heading, borderFillIDRef |
| Document structure | page size, margin, page border, body width |
| Body detail | every paragraph's id/paraPr/charPr + text content |
| Table detail | rows×cols, column-width array, per-cell span/margin/borderFill/vertAlign + content |

### Core principles

- **Use charPrIDRef/paraPrIDRef as-is**: do not change style IDs of extracted header.xml
- **Sum of column widths = body width**: copy analyzed column-width array exactly
- **Keep rowSpan/colSpan patterns**: reproduce analyzed cell-merge structure exactly
- **Preserve cellMargin**: apply analyzed cell margin values identically
- **No page increase**: do not increase result page count without explicit user approval
- **Replace-first editing**: prefer replacing existing text nodes over adding new paragraphs/tables

---

## Script summary

| Script | Purpose |
|----------|------|
| `scripts/build.py build` | **Core** — template + XML → HWPX assembly (includes `--update-preview`) |
| `scripts/build.py analyze` | HWPX deep analysis (blueprint for reference-based generation) |
| `scripts/build.py next-id` | look up next `hp:p` ID — for collision-free new paragraph insertion |
| `scripts/office.py unpack` | HWPX → directory (raw bytes + `.hwpx_pack_order` manifest) |
| `scripts/office.py pack` | directory → HWPX (restores entry order/compression from manifest, mimetype first) |
| `scripts/validate.py validate` | HWPX structure validation — ZIP/mimetype/XML + secCnt/itemCnt/IDRef/duplicate ID. With `--baseline ref.hwpx`, only new duplicate IDs vs. original are errors |
| `scripts/validate.py page-guard` | page-drift risk check vs. reference (restore-mode gate / edit-mode reference) |
| `scripts/text.py extract` | HWPX text extraction — plain or markdown, optional table inclusion |
| `scripts/text.py patch` | safe text replacement — str.replace + lineseg strip + ID verification. `--after anchor` for context-limited replacement |
| `scripts/table.py dump` | table cell map dump — list all table IDs or dump (rowAddr, colAddr, colSpan, rowSpan, text) for specific table; `--cell col,row` for verbose cell inspector (paraPr/charPr/runs/linesegarray) |
| `scripts/table.py locate` | byte-span search for text-containing elements (`hp:tbl`/`hp:tr`/`hp:p`/`hp:tc`) — find table/paragraph positions in single-line section0.xml (extract with `--extract-dir`); accepts `.hwpx` or unpacked directory |
| `scripts/table.py delete` | delete table rows — remove `<hp:tr>` + auto-fix rowCnt/rowSpan/rowAddr (`--list` to view rows) |
| `scripts/table.py insert` | insert table row — insert `<hp:tr>` + auto-fix rowCnt/rowAddr/rowSpan (`--grow` to extend group-end rowSpan) |
| `scripts/table.py replace` | replace table cell content — replace paragraphs of target `<hp:tc>`'s direct `<hp:subList>` + lineseg strip + ID collision check; accepts `.hwpx` or unpacked directory (in-place); `--run` for multi-charPr runs within a paragraph |
| `scripts/table.py strip-lineseg` | remove `<hp:linesegarray>` — prevent "document corrupted" warning after text edits |
| `scripts/table.py calc-widths` | table column-width calculation — ratio → HWPUNIT (guarantees sum = body width) |

## New utility usage

> Full CLI examples for all utility scripts — read `$SKILL_DIR/references/scripts-guide.md`.

Covers: `text.py patch` (safe text replace) · `table.py strip-lineseg` · `table.py calc-widths` · `build.py next-id` · `table.py locate` / `table.py insert` / `table.py replace` / `table.py delete` (table editing helpers).

---

## Unit conversion

| Value | HWPUNIT | Meaning |
|----|---------|------|
| 1pt | 100 | Base unit |
| 10pt | 1000 | Default font size |
| 1mm | 283.5 | Millimeter |
| 1cm | 2835 | Centimeter |
| A4 width | 59528 | 210mm |
| A4 height | 84186 | 297mm |
| Left/right margin | 8504 | 30mm |
| Body width | 42520 | 150mm (A4 - left/right margins) |

---


## Critical Rules

Severity: 🔴 crash/data corruption · 🟡 silent failure/bad output · 🔵 style/consistency

1. 🔵 **HWPX only**: `.hwp` (binary) files not supported. If user provides `.hwp`, guide them to **re-save as `.hwpx` from Hancom Office**. (File → Save As → File type: HWPX)
2. 🔴 **secPr required**: first run of section0.xml's first paragraph must contain secPr + colPr
3. 🔴 **mimetype order**: when packaging HWPX, mimetype = first ZIP entry, ZIP_STORED
4. 🔴 **Preserve namespaces**: keep `hp:`, `hs:`, `hh:`, `hc:` prefixes when editing XML
5. 🟡 **itemCnt consistency**: header.xml's charProperties/paraProperties/borderFills itemCnt must match actual child count
6. 🟡 **ID reference consistency**: section0.xml's charPrIDRef/paraPrIDRef must match header.xml definitions
7. 🔵 **Python version**: any Python 3.8+ works (stdlib only; no external packages required)
8. 🔵 **References**: XML structure → `hwpx-format.md`; editing traps → `editing-gotchas.md`; XML serialization rules → `xml-integrity.md`; style IDs → `style-maps.md`; XML templates → `section-writing.md`; script CLI → `scripts-guide.md`; environment/encoding → `environment.md`
9. 🔵 **build.py build first**: use `build.py build` for new document creation (avoid calling python-hwpx API directly)
10. 🔵 **Process attached HWPX after intent judgment**: do not auto-restore on attachment. Judge restore/edit/extract/generate intent first (see "Handling attached HWPX — judge intent first" table). Only when classified as restore, do `build.py analyze` + extracted-XML-based restore/rewrite
11. 🟡 **Same page count required (reference restore mode only)**: in restore mode, keep final result's page count identical to reference. Does not apply to content-edit / new-creation modes
12. 🟡 **No unauthorized page increase (reference restore mode only)**: in restore mode, no structure changes causing page increase without explicit user request/approval
13. 🟡 **page-guard must pass (reference restore mode only)**: in restore mode, `validate.py page-guard` must also pass — separate from `validate.py validate` — to mark complete. In content-edit mode, `validate.py page-guard` is reference info, and `validate.py validate --baseline` + actually opening in Hancom is completion gate
14. 🔴 **No XML re-serialization**: do not `ET.fromstring()` then `ET.tostring()` existing section0.xml/header.xml — pretty-print / standalone removal / xmlns addition cause HWP parser crashes. **Same applies to content.hpf** (contains 14 Hancom namespace declarations)
15. 🟡 **Text modification via str.replace()**: apply `str.replace()` directly on raw XML string for text changes — **except table cell text: use `table.py replace` instead (see rule 24)**
16. 🔴 **Compact required on new-paragraph insertion**: after extracting element content, apply `re.sub(r'>[ \t\r\n]+<', '><', xml)` compact before string insertion
17. 🟡 **Compute insertion position last**: recompute `insert_pos` after all `str.replace()` done (computing before modification gives wrong offset)
18. 🔴 **No duplicate hp:p IDs**: when copying paragraph from another document, must check for ID duplication — duplicate IDs cause HWP crashes
19. 🟡 **linesegarray removal required**: when modifying text in existing section, remove that paragraph's `<hp:linesegarray>` — stale line-break cache makes HWP show "document corrupted/modified" warning (HWP auto-recalculates on open)
20. 🔵 **unpack.py raw-bytes guarantee**: `unpack.py` extracts raw bytes with no XML re-serialization. When modifying script directly, this invariant must be kept

> Rules 14–20 — code examples and safe patterns: `$SKILL_DIR/references/xml-integrity.md`.

21. 🟡 **FORMULA field caution**: if table's sum/calculation cell is `type="FORMULA"` field, modifying cached `<hp:t>` value = no-op — Hancom recalculates and overwrites on open. Replace whole `fieldBegin`~`fieldEnd` span with static text, or fix formula input cell (`references/editing-gotchas.md` §1)
22. 🟡 **Assert count on every replacement**: when editing existing document, put `assert s.count(old) == expected` before every `str.replace()` — catches run splitting (0 matches) and substring collision (excess) before silent failure
23. 🔵 **Content-edit completion gate**: after `validate.py --baseline` passes, confirm actually opens in Hancom. Fully close Hancom before repackaging (multiple windows: `CloseMainWindow` closes only main window), after applying to real file verify copy success via md5 or similar (see Workflow 2)
24. 🟡 **Table cell text edit → table.py replace only**: for any text change inside a table cell (`<hp:tc>`), use `table.py replace` — not `str.replace()` or `text.py patch`. Table cells have per-subList `<hp:linesegarray>`; `table.py replace` strips it and checks ID collisions automatically. Raw `str.replace()` on cell content leaves stale lineseg → "문서가 변경됨" warning in Hancom.
25. 🔴 **Floating table must be anchored in `<hp:p><hp:run>`**: `treatAsChar="0"` (floating) tables must be a direct child of `<hp:run>` inside `<hp:p>` — never a bare sibling of `<hs:sec>` or `<hp:p>`. Bare-sibling floating tables are not rendered by Hancom. See `section-writing.md` § "Table placement patterns" for both placement forms.
26. 🟡 **Escape angle brackets in text nodes**: Korean legal/administrative text commonly contains `<개정 2026. 6.>` or similar angle-bracket spans — always write as `&lt;개정 2026. 6.&gt;`. Unescaped `<` inside `<hp:t>` causes XML parse failure at document load.
