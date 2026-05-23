---
name: hwpx
description: |
  This skill should be used when the user asks to "hwpx 만들어", "한글 문서 작성", "공문 만들어", "보고서 생성", "회의록 만들어", "제안서 작성", "hwpx 편집", "한글 파일 수정", "create hwpx", "make a hancom document", "edit hwp file", "generate hwpx", or describes creating, editing, or reading a Korean government or business document. Also trigger when the user attaches a .hwpx file, asks to extract text from hwpx, mentions OWPML, or mentions Hancom document creation, editing, or conversion — even without saying "hwpx" explicitly. NOT when: discussing Hancom as a product/company without a document task (e.g. "Hancom is slow", "Hancom pricing").
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
| Reference restore | Must match reference | `validate.py --baseline` + `page_guard.py` |
| Content edit | Changing is normal | `validate.py --baseline` + actually open in Hancom |
| New / reference-based generation | No constraint | `validate.py` |

"Same page count", `page_guard.py`, "compress/summarize text" rules apply **only to reference restore mode**. In content edit mode, do not revert work on page count change. For restore-mode steps and checklist, see **Workflow 5**.

> **`validate.py --baseline` scope**: real-world HWPX originals often contain duplicate `hp:p` IDs that HWP allows. Validating without `--baseline` flags these pre-existing duplicates as `INVALID` (false positive). **`--baseline` is required when validating against an original attached document (Workflows 2, 5); omit for new documents (Workflow 1).**

## Environment

Only required package: **`lxml`**. Any Python that can import `lxml` works, regardless of venv vs. system.

| OS | Python invocation | Note |
|----|------------|------|
| Windows | `python` (system) or `.venv\Scripts\python` | `python3` alias may not exist |
| macOS/Linux | `python3` or `.venv/bin/python` | |

- venv optional. If `python -c "import lxml"` succeeds, use as-is. Otherwise `pip install lxml`.
- Examples use `python3` / `source "$VENV"`. **On Windows, use `python` and omit `source` line.**
- `SKILL_DIR` = absolute path of directory holding this SKILL.md (`.../skills/hwpx`).
- **Windows console Korean output**: `print`ing Korean in diagnostic `python -c "..."` or heredoc produces cp949 mojibake. To print Korean, put `import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")` as first line. (Always specify `encoding="utf-8"` for file I/O — unrelated to mojibake.) Bundled scripts in `scripts/` apply UTF-8 stdout/stderr themselves, no extra step needed.
- **Match special characters by codepoint**: quote variants (`ʹ` U+02B9 vs U+0374), PUA (U+F0E8), dash/middle-dot variants, etc. — typing visually similar characters as **literals in script/heredoc is encoding-unstable**: same glyph can be interpreted as different codepoint each run. Always specify special characters via `'\uXXXX'` escapes.
- **No `python -c` for non-ASCII matching logic**: putting non-ASCII like `■`, `○`, Korean into `python -c "..."` source and running via Bash can corrupt in transit through shell/encoding — leading to silent failure where `str.index()`/`rfind()` returns `-1`. Write check/replace code with non-ASCII matching to `.py` file with `Write`, run via `python script.py`.
- Temp files **under working document's folder** (e.g. `./_work/`), not `/tmp`. Windows `python` interprets `/tmp` as drive-relative path, diverges from Bash tool's `/tmp`.

## Directory structure

```
.../skills/hwpx/
├── SKILL.md                              # 이 파일
├── scripts/
│   ├── office/
│   │   ├── unpack.py                     # HWPX → 디렉토리 (raw bytes + 순서 manifest)
│   │   └── pack.py                       # 디렉토리 → HWPX (원본 항목 순서·압축 복원)
│   ├── build_hwpx.py                     # 템플릿 + XML → .hwpx 조립 (핵심)
│   ├── analyze_template.py               # HWPX 심층 분석 (레퍼런스 기반 생성용)
│   ├── validate.py                       # HWPX 구조 검증
│   ├── page_guard.py                     # 레퍼런스 대비 페이지 드리프트 위험 검사
│   ├── locate.py                         # 텍스트 포함 요소(hp:tbl/tr/p) span 탐색
│   ├── insert_table_row.py               # 표 행 삽입 + rowAddr/rowCnt/rowSpan 정정
│   ├── replace_cell.py                   # 표 셀 내용 교체 + linesegarray 제거
│   ├── strip_linesegarray.py             # 표 셀의 LineSeg 배열 제거 (렌더링 오류 수정)
│   ├── patch_section.py                  # section XML의 지정 섹션을 원자적으로 패치
│   ├── calc_col_widths.py                # 콘텐츠 기반 표 열 너비 계산
│   ├── next_id.py                        # 문서 내 다음 사용 가능한 고유 요소 ID 생성
│   ├── delete_table_rows.py              # 표 요소에서 지정 행 삭제
│   └── text_extract.py                   # 텍스트 추출
├── templates/
│   ├── base/                             # 베이스 템플릿 (Skeleton 기반)
│   │   ├── mimetype, META-INF/*, version.xml, settings.xml, Preview/*
│   │   └── Contents/ (header.xml, section0.xml, content.hpf)
│   ├── gonmun/                           # 공문 오버레이 (header.xml, section0.xml)
│   ├── report/                           # 보고서 오버레이
│   ├── minutes/                          # 회의록 오버레이
│   └── proposal/                         # 제안서/사업개요 오버레이 (색상 헤더바, 번호 배지)
└── references/
    ├── hwpx-format.md                    # OWPML XML 요소 레퍼런스
    ├── editing-gotchas.md                # 편집 함정 (FORMULA·부분문자열·count·삭제)
    ├── xml-integrity.md                  # XML 직렬화 안전 패턴 (lxml 금지 규칙·코드 예시)
    ├── style-maps.md                     # 템플릿별 charPrIDRef/paraPrIDRef/borderFillIDRef
    ├── section-writing.md                # section0.xml XML 템플릿 (문단·표·구조)
    └── scripts-guide.md                  # 유틸리티 스크립트 CLI 사용법 상세
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
4. **Build with build_hwpx.py**
5. **Validate with validate.py**

> If attached reference exists and intent is restore/edit, use Workflow 5 instead.

### Basic usage

```bash
source "$VENV"

# 빈 문서 (base 템플릿)
python3 "$SKILL_DIR/scripts/build_hwpx.py" --output result.hwpx

# 템플릿 사용
python3 "$SKILL_DIR/scripts/build_hwpx.py" --template gonmun --output result.hwpx

# 커스텀 section0.xml 오버라이드
python3 "$SKILL_DIR/scripts/build_hwpx.py" --template gonmun --section my_section0.xml --output result.hwpx

# header도 오버라이드
python3 "$SKILL_DIR/scripts/build_hwpx.py" --header my_header.xml --section my_section0.xml --output result.hwpx

# 메타데이터 설정
python3 "$SKILL_DIR/scripts/build_hwpx.py" --template report --section my.xml \
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
python3 "$SKILL_DIR/scripts/build_hwpx.py" --section "$SECTION" --output result.hwpx

# 3. 정리
rm -f "$SECTION"
```

---

## section0.xml writing guide

> Full XML templates (paragraph, empty line, mixed runs, table, ID rules) — read `$SKILL_DIR/references/section-writing.md`.

Key rules:
- Copy first paragraph from `templates/base/Contents/section0.xml` (secPr + colPr required in first run)
- Empty line: `<hp:t/>` (self-closing, not `<hp:t></hp:t>`)
- Table total width must equal body width (42520 HWPUNIT); use `calc_col_widths.py` for ratios
- Paragraph id: sequential from `1000000001` — use `next_id.py` to avoid collisions

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
source "$VENV"

# 1. HWPX → 디렉토리 (raw bytes 추출, .hwpx_pack_order manifest 기록)
python3 "$SKILL_DIR/scripts/office/unpack.py" document.hwpx ./unpacked/

# 2. XML 직접 편집 (Claude가 Read/Edit 도구로, 또는 표 헬퍼 스크립트로)
#    본문: ./unpacked/Contents/section0.xml
#    스타일: ./unpacked/Contents/header.xml
#    표 편집은 아래 "표 편집 헬퍼" 참조 (locate / insert_table_row / replace_cell)

# 3. 다시 HWPX로 패키징
python3 "$SKILL_DIR/scripts/office/pack.py" ./unpacked/ edited.hwpx

# 4. 검증 (원본 대비)
python3 "$SKILL_DIR/scripts/validate.py" edited.hwpx --baseline document.hwpx
```

### Bulk / multi-stage edits

Many items → split into stages to catch silent failures early, verify each stage in Hancom.

1. **unpack once**. All later stages cumulatively modify `unpacked/Contents/section0.xml`.
2. **Per-stage scripts**: write each stage as small `.py`, put **`assert s.count(old) == expected`** on every `str.replace()`. Count off → aborts before corrupted file produced (`references/editing-gotchas.md` §3).
3. **Each stage: pack → validate → confirm opens in Hancom**, then proceed. Package per-stage output as `_work_stepN.hwpx` to avoid file-lock conflicts.
4. After all stages pass, apply final version to real file.

### Hancom-open verification (content-edit completion gate)

`validate.py` checks structure only. Completion gate for content edit = confirming it **actually opens in Hancom**.

- **Launch check**: open packaged hwpx (Windows: `Start-Process`), confirm Hancom process (`Hwp`) alive. On crash, process doesn't appear or exits immediately.
- **Fully close before repackaging**: close Hancom before re-pack/re-copying same file. **Multiple documents open in Hancom: `CloseMainWindow` closes only one main window** — remaining window locks file. Confirm full close (`Stop-Process` if not closed) before proceeding.
- **Verify copy success**: copying to locked file can fail silently as non-blocking error. After applying to real file, **confirm content match via md5** or similar.

---

## Workflow 3: read / text extraction

```bash
source "$VENV"

# 순수 텍스트
python3 "$SKILL_DIR/scripts/text_extract.py" document.hwpx

# 테이블 포함
python3 "$SKILL_DIR/scripts/text_extract.py" document.hwpx --include-tables

# 마크다운 형식
python3 "$SKILL_DIR/scripts/text_extract.py" document.hwpx --format markdown
```

---

## Workflow 4: validation

```bash
source "$VENV"
# 단독 새 문서
python3 "$SKILL_DIR/scripts/validate.py" document.hwpx
# 첨부 원본을 편집/복원한 결과 — 기존 중복 ID 오탐 방지
python3 "$SKILL_DIR/scripts/validate.py" result.hwpx --baseline original.hwpx
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
- Do not mark complete on `validate.py` pass alone. `page_guard.py` must also pass
- On `page_guard.py` failure, do not submit as complete — fix cause (excess length / structure change) and rebuild
- If possible, confirm final page count in Hancom, recheck against reference

> For reference-based **generation** (style reference only, content written fresh), page-count criteria above do not apply — like new creation, `validate.py` is only gate.

### Flow

1. **Analyze** — deep-analyze reference document with `analyze_template.py`
2. **Extract header.xml** — use reference's style definitions as-is
3. **Write section0.xml** — write new content following analyzed structure
4. **Build** — build with extracted header.xml + new section0.xml
5. **Validate** — `validate.py`
6. **Page guard** — `page_guard.py` (re-fix on failure)

### Usage

```bash
source "$VENV"

# 1. 심층 분석 (구조 청사진 출력)
python3 "$SKILL_DIR/scripts/analyze_template.py" reference.hwpx

# 2. header.xml과 section0.xml을 추출하여 참고용으로 보관
mkdir -p ./_work
python3 "$SKILL_DIR/scripts/analyze_template.py" reference.hwpx \
  --extract-header ./_work/ref_header.xml \
  --extract-section ./_work/ref_section.xml

# 3. 분석 결과를 보고 새 section0.xml 작성
#    - 동일한 charPrIDRef, paraPrIDRef 사용
#    - 동일한 테이블 구조 (열 수, 열 너비, 행 수, rowSpan/colSpan)
#    - 동일한 borderFillIDRef, cellMargin

# 4. 추출한 header.xml + 새 section0.xml로 빌드
python3 "$SKILL_DIR/scripts/build_hwpx.py" \
  --header ./_work/ref_header.xml \
  --section ./_work/new_section0.xml \
  --output result.hwpx

# 5. 검증 (원본 대비 — 기존 중복 ID 오탐 방지)
python3 "$SKILL_DIR/scripts/validate.py" result.hwpx --baseline reference.hwpx

# 6. 쪽수 드리프트 가드 (필수)
python3 "$SKILL_DIR/scripts/page_guard.py" \
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
| `scripts/build_hwpx.py` | **Core** — template + XML → HWPX assembly (includes `--update-preview`) |
| `scripts/analyze_template.py` | HWPX deep analysis (blueprint for reference-based generation) |
| `scripts/office/unpack.py` | HWPX → directory (raw bytes + `.hwpx_pack_order` manifest) |
| `scripts/office/pack.py` | directory → HWPX (restores entry order/compression from manifest, mimetype first) |
| `scripts/validate.py` | HWPX structure validation — ZIP/mimetype/XML + secCnt/itemCnt/IDRef/duplicate ID. With `--baseline ref.hwpx`, only new duplicate IDs vs. original are errors |
| `scripts/page_guard.py` | page-drift risk check vs. reference (restore-mode gate / edit-mode reference) |
| `scripts/text_extract.py` | HWPX text extraction — self-implemented, no external `hwpx` package needed |
| `scripts/locate.py` | byte-span search for text-containing elements (`hp:tbl`/`hp:tr`/`hp:p`/`hp:tc`) — find table/paragraph positions in single-line section0.xml (extract with `--extract-dir`) |
| `scripts/delete_table_rows.py` | delete table rows — remove `<hp:tr>` + auto-fix rowCnt/rowSpan/rowAddr (`--list` to view rows) |
| `scripts/insert_table_row.py` | insert table row — insert `<hp:tr>` + auto-fix rowCnt/rowAddr/rowSpan (`--grow` to extend group-end rowSpan) |
| `scripts/replace_cell.py` | replace table cell content — replace paragraphs of target `<hp:tc>`'s direct `<hp:subList>` + lineseg strip + ID collision check |
| `scripts/strip_linesegarray.py` | remove `<hp:linesegarray>` — prevent "document corrupted" warning after text edits |
| `scripts/patch_section.py` | safe text replacement — str.replace + lineseg strip + ID verification. `--after anchor` for context-limited replacement |
| `scripts/calc_col_widths.py` | table column-width calculation — ratio → HWPUNIT (guarantees sum = body width) |
| `scripts/next_id.py` | look up next `hp:p` ID — for collision-free new paragraph insertion |

## New utility usage

> Full CLI examples for all utility scripts — read `$SKILL_DIR/references/scripts-guide.md`.

Covers: `patch_section.py` (safe text replace) · `strip_linesegarray.py` · `calc_col_widths.py` · `next_id.py` · `locate.py` / `insert_table_row.py` / `replace_cell.py` / `delete_table_rows.py` (table editing helpers).

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

## XML integrity — prevent HWP parser crashes

> Full code examples — read `$SKILL_DIR/references/xml-integrity.md`.

Key invariants (violating any crashes Hancom):

- **No lxml re-serialization**: never `etree.fromstring()` + `etree.tostring()` existing section0.xml, header.xml, or content.hpf — pretty-print/standalone-removal/xmlns-injection corrupt file
- **str.replace() for text edits**: modify raw XML string directly; no lxml needed
- **Compact new paragraphs**: after `etree.tostring()` on new element, run `re.sub(r'>[ \t\r\n]+<', '><', xml)` before string-inserting
- **Insertion position last**: compute `insert_pos` only after all `str.replace()` calls done (earlier positions shift on replace)
- **No duplicate hp:p IDs**: check with `Counter(re.findall(r'<hp:p\s[^>]*\bid="(\d+)"', xml_str))`
- **linesegarray removal**: after text edit in existing section, strip `<hp:linesegarray>` (HWP recalculates on open)
- **Workflow 2**: `unpack.py` guarantees raw bytes — edit via Read/Edit tools, never via lxml re-serialize

---

## Critical Rules

Severity: 🔴 crash/data corruption · 🟡 silent failure/bad output · 🔵 style/consistency

1. 🔵 **HWPX only**: `.hwp` (binary) files not supported. If user provides `.hwp`, guide them to **re-save as `.hwpx` from Hancom Office**. (File → Save As → File type: HWPX)
2. 🔴 **secPr required**: first run of section0.xml's first paragraph must contain secPr + colPr
3. 🔴 **mimetype order**: when packaging HWPX, mimetype = first ZIP entry, ZIP_STORED
4. 🔴 **Preserve namespaces**: keep `hp:`, `hs:`, `hh:`, `hc:` prefixes when editing XML
5. 🟡 **itemCnt consistency**: header.xml's charProperties/paraProperties/borderFills itemCnt must match actual child count
6. 🟡 **ID reference consistency**: section0.xml's charPrIDRef/paraPrIDRef must match header.xml definitions
7. 🔵 **Use venv**: project's `.venv/bin/python3` (lxml package required)
8. 🔵 **Validation**: always confirm integrity with `validate.py` after creation
9. 🔵 **References**: XML structure → `hwpx-format.md`; editing traps → `editing-gotchas.md`; XML serialization rules → `xml-integrity.md`; style IDs → `style-maps.md`; XML templates → `section-writing.md`; script CLI → `scripts-guide.md`
10. 🔵 **build_hwpx.py first**: use build_hwpx.py for new document creation (avoid calling python-hwpx API directly)
11. 🔵 **Empty line**: use `<hp:t/>` (self-closing tag)
12. 🔵 **Process attached HWPX after intent judgment**: do not auto-restore on attachment. Judge restore/edit/extract/generate intent first (see "Handling attached HWPX — judge intent first" table). Only when classified as restore, do `analyze_template.py` + extracted-XML-based restore/rewrite
13. 🟡 **Same page count required (reference restore mode only)**: in restore mode, keep final result's page count identical to reference. Does not apply to content-edit / new-creation modes
14. 🟡 **No unauthorized page increase (reference restore mode only)**: in restore mode, no structure changes causing page increase without explicit user request/approval
15. 🔵 **Limit structure changes**: no adding/deleting/splitting/merging of paragraphs/tables unless user requests it (replace-centered editing)
16. 🟡 **page_guard must pass (reference restore mode only)**: in restore mode, `page_guard.py` must also pass — separate from `validate.py` — to mark complete. In content-edit mode, `page_guard.py` is reference info, and `validate.py --baseline` + actually opening in Hancom is completion gate
17. 🔴 **No lxml re-serialization**: do not `etree.fromstring()` then `etree.tostring()` existing section0.xml/header.xml — pretty-print / standalone removal / xmlns addition cause HWP parser crashes. **Same applies to content.hpf** (contains 14 Hancom namespace declarations)
18. 🟡 **Text modification via str.replace()**: apply `str.replace()` directly on raw XML string for text changes (no lxml needed)
19. 🔴 **Compact required on new-paragraph insertion**: after serializing lxml-extracted element, apply `re.sub(r'>[ \t\r\n]+<', '><', xml)` compact before string insertion
20. 🟡 **Compute insertion position last**: recompute `insert_pos` after all `str.replace()` done (computing before modification gives wrong offset)
21. 🔴 **No duplicate hp:p IDs**: when copying paragraph from another document, must check for ID duplication — duplicate IDs cause HWP crashes
22. 🟡 **linesegarray removal required**: when modifying text in existing section, remove that paragraph's `<hp:linesegarray>` — stale line-break cache makes HWP show "document corrupted/modified" warning (HWP auto-recalculates on open)
23. 🔵 **unpack.py raw-bytes guarantee**: `unpack.py` extracts raw bytes with no lxml re-serialization. When modifying script directly, this invariant must be kept

> Rules 17–23 — code examples and safe patterns: `$SKILL_DIR/references/xml-integrity.md`.

24. 🟡 **FORMULA field caution**: if table's sum/calculation cell is `type="FORMULA"` field, modifying cached `<hp:t>` value = no-op — Hancom recalculates and overwrites on open. Replace whole `fieldBegin`~`fieldEnd` span with static text, or fix formula input cell (`references/editing-gotchas.md` §1)
25. 🟡 **Assert count on every replacement**: when editing existing document, put `assert s.count(old) == expected` before every `str.replace()` — catches run splitting (0 matches) and substring collision (excess) before silent failure
26. 🔵 **Content-edit completion gate**: after `validate.py --baseline` passes, confirm actually opens in Hancom. Fully close Hancom before repackaging (multiple windows: `CloseMainWindow` closes only main window), after applying to real file verify copy success via md5 or similar (see Workflow 2)