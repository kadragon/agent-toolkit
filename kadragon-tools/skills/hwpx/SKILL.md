---
name: hwpx
description: "한글(HWPX) 문서 생성/읽기/편집 스킬. .hwpx 파일, 한글 문서, Hancom, OWPML 관련 요청 시 사용."
---

# HWPX Document Skill — XML-first Workflow

Skill to create, edit, and read Hancom Office HWPX files, centered on **writing XML directly**.
HWPX is a ZIP-based XML container (OWPML standard). This fully bypasses python-hwpx API formatting bugs and allows fine-grained format control.

## Handling attached HWPX — judge intent first

Even when the user attaches a `.hwpx`, do not auto-restore. First judge the **request intent** and pick a mode. Restore is one mode among several, not the default.

| Intent | Mode | Workflow |
|------|------|-----------|
| Reproduce the attached document near-exactly, swap only values/field names | Reference restore | Workflow 5 |
| Explicit request to add/delete/restructure content | Content edit | Workflow 2 |
| Only text/table content needed | Read/extract | Workflow 3 |
| Attachment is a style reference only, content written fresh | Reference-based generation | Workflow 5 |
| No attachment | New creation | Workflow 1 |

If intent is unclear, ask the user — do not assume restore.

### Per-mode page-count rules / completion gates

| Mode | Page count | Completion gate |
|------|------|------------|
| Reference restore | Must match the reference | `validate.py --baseline` + `page_guard.py` |
| Content edit | Changing is normal | `validate.py --baseline` + actually open in Hancom |
| New / reference-based generation | No constraint | `validate.py` |

The "same page count", `page_guard.py`, and "compress/summarize text" rules apply **only to reference restore mode**. In content edit mode, do not revert work just because the page count changed. For restore-mode detailed steps and checklist, see **Workflow 5**.

> **`validate.py --baseline` required**: real-world HWPX originals often contain duplicate `hp:p` IDs that HWP allows. Validating without `--baseline` flags these pre-existing duplicates as `INVALID` (false positive). **When editing/restoring an attached document, always pass `--baseline original.hwpx`.** Omit `--baseline` only when creating a new document from scratch.

## Environment

The only required package is **`lxml`**. Any Python that can import `lxml` works, regardless of venv vs. system.

| OS | Python invocation | Note |
|----|------------|------|
| Windows | `python` (system) or `.venv\Scripts\python` | `python3` alias may not exist |
| macOS/Linux | `python3` or `.venv/bin/python` | |

- venv is optional. If `python -c "import lxml"` succeeds, use it as-is. Otherwise `pip install lxml`.
- Examples in this doc use `python3` / `source "$VENV"`. **On Windows, use `python` and omit the `source` line.**
- `SKILL_DIR` is the absolute path of the directory holding this SKILL.md (`.../skills/hwpxskill`).
- **Windows console Korean output**: `print`ing Korean in a diagnostic `python -c "..."` or heredoc produces cp949 mojibake. To print Korean, put `import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")` as the script's first line. (Always specify `encoding="utf-8"` for file I/O — unrelated to mojibake.) Bundled scripts in `scripts/` apply UTF-8 stdout/stderr themselves, so no extra step is needed.
- **Match special characters by codepoint**: quote variants (`ʹ` U+02B9 vs U+0374), PUA (U+F0E8), dash/middle-dot variants, etc. — typing visually similar characters as **literals in a script/heredoc is encoding-unstable**: the same glyph can be interpreted as a different codepoint each run. Always specify special characters to match/replace via `'\uXXXX'` escapes.
- **No `python -c` for non-ASCII matching logic**: putting non-ASCII like `■`, `○`, Korean into `python -c "..."` source and running via Bash can corrupt it in transit through the shell/encoding — leading to silent failure where `str.index()`/`rfind()` returns `-1`. Write check/replace code containing non-ASCII matching to a `.py` file with `Write` and run via `python script.py`.
- Make temp files **under the working document's folder** (e.g. `./_work/`), not `/tmp`. Windows `python` interprets `/tmp` as a drive-relative path, diverging from the Bash tool's `/tmp`.

## Directory structure

```
.claude/skills/hwpxskill/
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
    └── editing-gotchas.md                # 편집 함정 (FORMULA·부분문자열·count·삭제)
```

---

## Workflow 1: XML-first new document creation (no attached reference)

### Flow

1. **Pick template** (base/gonmun/report/minutes/proposal)
2. **Write section0.xml** (body content)
3. **(Optional) edit header.xml** (when new styles needed)
4. **Build with build_hwpx.py**
5. **Validate with validate.py**

> If there is an attached reference and you intend to restore/edit it, use Workflow 5 (reference restore) instead of this one.

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
SECTION=$(mktemp /tmp/section0_XXXX.xml)
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

### Required structure

The first paragraph (`<hp:p>`) of section0.xml — its first run (`<hp:run>`) must contain `<hp:secPr>` and `<hp:colPr>`:

```xml
<hp:p id="1000000001" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0">
    <hp:secPr ...>
      <!-- 페이지 크기, 여백, 각주/미주 설정 등 -->
    </hp:secPr>
    <hp:ctrl>
      <hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/>
    </hp:ctrl>
  </hp:run>
  <hp:run charPrIDRef="0"><hp:t/></hp:run>
</hp:p>
```

**Tip**: just copy the first paragraph from `templates/base/Contents/section0.xml`.

### Paragraph

```xml
<hp:p id="고유ID" paraPrIDRef="문단스타일ID" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="글자스타일ID">
    <hp:t>텍스트 내용</hp:t>
  </hp:run>
</hp:p>
```

### Empty line

```xml
<hp:p id="고유ID" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0"><hp:t/></hp:run>
</hp:p>
```

### Mixed-format runs (multiple styles in one paragraph)

```xml
<hp:p id="고유ID" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0"><hp:t>일반 텍스트 </hp:t></hp:run>
  <hp:run charPrIDRef="7"><hp:t>볼드 텍스트</hp:t></hp:run>
  <hp:run charPrIDRef="0"><hp:t> 다시 일반</hp:t></hp:run>
</hp:p>
```

### How to write a table

```xml
<hp:p id="고유ID" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0">
    <hp:tbl id="고유ID" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM"
            textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL"
            repeatHeader="0" rowCnt="행수" colCnt="열수" cellSpacing="0"
            borderFillIDRef="3" noAdjust="0">
      <hp:sz width="42520" widthRelTo="ABSOLUTE" height="전체높이" heightRelTo="ABSOLUTE" protect="0"/>
      <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0"
              holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP"
              horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
      <hp:outMargin left="0" right="0" top="0" bottom="0"/>
      <hp:inMargin left="0" right="0" top="0" bottom="0"/>
      <hp:tr>
        <hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="4">
          <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER"
                     linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0"
                     hasTextRef="0" hasNumRef="0">
            <hp:p paraPrIDRef="21" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="고유ID">
              <hp:run charPrIDRef="9"><hp:t>헤더 셀</hp:t></hp:run>
            </hp:p>
          </hp:subList>
          <hp:cellAddr colAddr="0" rowAddr="0"/>
          <hp:cellSpan colSpan="1" rowSpan="1"/>
          <hp:cellSz width="열너비" height="행높이"/>
          <hp:cellMargin left="0" right="0" top="0" bottom="0"/>
        </hp:tc>
        <!-- 나머지 셀... -->
      </hp:tr>
    </hp:tbl>
  </hp:run>
</hp:p>
```

### Table size calculation

- **A4 body width**: 42520 HWPUNIT = 59528 (paper) - 8504×2 (left/right margins)
- **Sum of column widths = body width** (42520)
- e.g. 3 equal columns → 14173 + 14173 + 14174 = 42520
- e.g. 2 columns (label:content = 1:4) → 8504 + 34016 = 42520
- **Row height**: usually 2400–3600 HWPUNIT per cell

### ID rules

- Paragraph id: sequential increment from `1000000001`
- Table id: recommend a separate range, e.g. `1000000099`
- Every id must be unique within the document

---

## header.xml editing guide

### How to add a custom style

1. Copy `templates/base/Contents/header.xml`
2. Add the needed charPr/paraPr/borderFill
3. Update each group's `itemCnt` attribute

### charPr addition example (bold 14pt)

```xml
<hh:charPr id="8" height="1400" textColor="#000000" shadeColor="none"
           useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="2">
  <hh:fontRef hangul="1" latin="1" hanja="1" japanese="1" other="1" symbol="1" user="1"/>
  <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
  <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
  <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
  <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
  <hh:bold/>
  <hh:underline type="NONE" shape="SOLID" color="#000000"/>
  <hh:strikeout shape="NONE" color="#000000"/>
  <hh:outline type="NONE"/>
  <hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/>
</hh:charPr>
```

### Font reference system

- `fontRef` values are font ids defined in `fontfaces`
- `hangul="0"` → 함초롬돋움 (gothic / sans-serif)
- `hangul="1"` → 함초롬바탕 (myeongjo / serif)
- Set all 7 languages identically

### Caution when adding paraPr

- Must include the `hp:switch` structure (`hp:case` + `hp:default`)
- `hp:case` and `hp:default` values are usually identical (or default is 2×)
- Keep `borderFillIDRef="2"`

---

## Per-template style ID map

### base

| ID | Type | Description |
|----|------|------|
| charPr 0 | Char | 10pt 함초롬바탕, default |
| charPr 1 | Char | 10pt 함초롬돋움 |
| charPr 2~6 | Char | Skeleton default styles |
| paraPr 0 | Para | JUSTIFY, 160% line spacing |
| paraPr 1~19 | Para | Skeleton defaults (outline, footnote, etc.) |
| borderFill 1 | Border | None (page border) |
| borderFill 2 | Border | None + transparent background (reference use) |

### gonmun (공문, official document) — base + additions

| ID | Type | Description |
|----|------|------|
| charPr 7 | Char | 22pt bold 함초롬바탕 (org name/title) |
| charPr 8 | Char | 16pt bold 함초롬바탕 (signer) |
| charPr 9 | Char | 8pt 함초롬바탕 (footer contact) |
| charPr 10 | Char | 10pt bold 함초롬바탕 (table header) |
| paraPr 20 | Para | CENTER, 160% line spacing |
| paraPr 21 | Para | CENTER, 130% (table cell) |
| paraPr 22 | Para | JUSTIFY, 130% (table cell) |
| borderFill 3 | Border | SOLID 0.12mm 4 sides |
| borderFill 4 | Border | SOLID 0.12mm + #D6DCE4 background |

### report (보고서) — base + additions

| ID | Type | Description |
|----|------|------|
| charPr 7 | Char | 20pt bold (document title) |
| charPr 8 | Char | 14pt bold (subtitle) |
| charPr 9 | Char | 10pt bold (table header) |
| charPr 10 | Char | 10pt bold+underline (emphasis text) |
| charPr 11 | Char | 9pt 함초롬바탕 (small/footnote) |
| charPr 12 | Char | 16pt bold 함초롬바탕 (single-line title) |
| charPr 13 | Char | 12pt bold 함초롬돋움 (section header) |
| paraPr 20~22 | Para | CENTER/JUSTIFY variants |
| paraPr 23 | Para | RIGHT align, 160% line spacing |
| paraPr 24 | Para | JUSTIFY, left 600 (□ checklist indent) |
| paraPr 25 | Para | JUSTIFY, left 1200 (sub-item ①②③ indent) |
| paraPr 26 | Para | JUSTIFY, left 1800 (deep sub-item - indent) |
| paraPr 27 | Para | LEFT, top/bottom border lines (for section header), prev 400 |
| borderFill 3 | Border | SOLID 0.12mm 4 sides |
| borderFill 4 | Border | SOLID 0.12mm + #DAEEF3 background |
| borderFill 5 | Border | top 0.4mm thick line + bottom 0.12mm thin line (section header) |

**Indentation rule**: never use space characters — always use paraPr left margin. □ items use paraPr 24, sub ①②③ use paraPr 25, deep - items use paraPr 26.

**Section header rule**: paraPr 27 + charPr 13 combo. The paragraph border (borderFillIDRef="5") auto-shows a top thick line + bottom thin line.

### minutes (회의록, meeting minutes) — base + additions

| ID | Type | Description |
|----|------|------|
| charPr 7 | Char | 18pt bold (title) |
| charPr 8 | Char | 12pt bold (section label) |
| charPr 9 | Char | 10pt bold (table header) |
| paraPr 20~22 | Para | CENTER/JUSTIFY variants |
| borderFill 3 | Border | SOLID 0.12mm 4 sides |
| borderFill 4 | Border | SOLID 0.12mm + #E2EFDA background |

### proposal (제안서/사업개요) — base + additions

For formal documents needing visual separation. Color-background header bars and number badges, implemented as table-based layout.

| ID | Type | Description |
|----|------|------|
| charPr 7 | Char | 20pt bold 함초롬바탕 (document title) |
| charPr 8 | Char | 14pt bold 함초롬바탕 (subtitle) |
| charPr 9 | Char | 10pt bold 함초롬바탕 (table header) |
| charPr 10 | Char | 14pt bold white 함초롬돋움 (major-item number, green background) |
| charPr 11 | Char | 11pt bold white 함초롬돋움 (sub-item number, blue background) |
| paraPr 20 | Para | CENTER, 160% line spacing |
| paraPr 21 | Para | CENTER, 130% (table cell) |
| paraPr 22 | Para | JUSTIFY, 130% (table cell) |
| borderFill 3 | Border | SOLID 0.12mm 4 sides |
| borderFill 4 | Border | SOLID 0.12mm + #DAEEF3 background |
| borderFill 5 | Border | olive-green background #7B8B3D (major-item number cell) |
| borderFill 6 | Border | light gray background #F2F2F2 + gray border (major-item title cell) |
| borderFill 7 | Border | blue background #4472C4 (sub-item number badge) |
| borderFill 8 | Border | bottom border only #D0D0D0 (sub-item title area) |

#### proposal layout pattern

**Major-item header** (2-cell table: number + title):
```xml
<!-- borderFillIDRef="5" + charPrIDRef="10" → 녹색배경 흰색 로마숫자 -->
<!-- borderFillIDRef="6" + charPrIDRef="8"  → 회색배경 검정 볼드 제목 -->
```

**Sub-item header** (2-cell table: number badge + title):
```xml
<!-- borderFillIDRef="7" + charPrIDRef="11" → 파란배경 흰색 아라비아숫자 -->
<!-- borderFillIDRef="8" + charPrIDRef="8"  → 하단선만 검정 볼드 제목 -->
```

---

## Workflow 2: edit existing document (unpack → Edit → pack)

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

> Before editing text/tables, **read `references/editing-gotchas.md`** — FORMULA fields, substring collision, count verification, paragraph deletion, and other silent-failure traps.

### Bulk / multi-stage edits

When editing many items, do not do it all at once — split into stages, to catch silent failures early and verify each stage in Hancom.

1. **unpack only once**. All later stages cumulatively modify `unpacked/Contents/section0.xml`.
2. **Per-stage scripts**: write each stage as a small `.py`, and put **`assert s.count(old) == expected`** on every `str.replace()`. If the count is off, it aborts before a corrupted file is produced (`references/editing-gotchas.md` §3).
3. **Each stage: pack → validate → confirm it opens in Hancom**, then proceed. Packaging per-stage output as a separate file like `_work_stepN.hwpx` avoids file-lock conflicts.
4. After all stages pass, apply the final version to the real file.

### Hancom-open verification (content-edit completion gate)

`validate.py` only checks structure. The completion gate for content edit mode is confirming it **actually opens in Hancom**.

- **Launch check**: open the packaged hwpx (Windows: `Start-Process`) and confirm the Hancom process (`Hwp`) is alive. On crash, the process doesn't appear or exits immediately.
- **Fully close before repackaging**: close Hancom before re-pack/re-copying the same file. With **multiple documents open in Hancom, `CloseMainWindow` closes only one main window** — a remaining window locks the file. Confirm full close (`Stop-Process` if not closed) before proceeding.
- **Verify copy success**: copying to a locked file can fail and pass silently as a non-blocking error. After applying to the real file, **confirm content match via md5** or similar.

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

Workflow to analyze an attached HWPX and (a) make a restored copy with only values/field names swapped, or (b) fill the same layout with new content. Use when intent judgment classified the request as "reference restore" or "reference-based generation".

### 99%-close restore criteria (restore-mode checklist)

- Identical `charPrIDRef`, `paraPrIDRef`, `borderFillIDRef` reference system
- Identical table `rowCnt`, `colCnt`, `colSpan`, `rowSpan`, `cellSz`, `cellMargin`
- Identical paragraph order, paragraph count, key empty-line/section positions
- Identical page/margin/section (secPr)
- Changes limited to the user's requested scope (body text, values, field names, etc.)

### Same page count (100%) criteria — restore mode only

- The result document's final page count must match the reference
- If page count looks likely to grow, first compress/summarize text to fit the existing layout
- Do not change `hp:p`, `hp:tbl`, `rowCnt`, `colCnt`, `pageBreak`, `secPr` without an explicit user request
- Do not mark complete on `validate.py` pass alone. `page_guard.py` must also pass
- On `page_guard.py` failure, do not submit as complete — fix the cause (excess length / structure change) and rebuild
- If possible, confirm the final page count in Hancom and recheck it matches the reference

> For reference-based **generation** (style reference only, content written fresh), the page-count criteria above do not apply — like new creation, `validate.py` is the only gate.

### Flow

1. **Analyze** — deep-analyze the reference document with `analyze_template.py`
2. **Extract header.xml** — use the reference's style definitions as-is
3. **Write section0.xml** — write new content following the analyzed structure
4. **Build** — build with the extracted header.xml + new section0.xml
5. **Validate** — `validate.py`
6. **Page guard** — `page_guard.py` (re-fix on failure)

### Usage

```bash
source "$VENV"

# 1. 심층 분석 (구조 청사진 출력)
python3 "$SKILL_DIR/scripts/analyze_template.py" reference.hwpx

# 2. header.xml과 section0.xml을 추출하여 참고용으로 보관
python3 "$SKILL_DIR/scripts/analyze_template.py" reference.hwpx \
  --extract-header /tmp/ref_header.xml \
  --extract-section /tmp/ref_section.xml

# 3. 분석 결과를 보고 새 section0.xml 작성
#    - 동일한 charPrIDRef, paraPrIDRef 사용
#    - 동일한 테이블 구조 (열 수, 열 너비, 행 수, rowSpan/colSpan)
#    - 동일한 borderFillIDRef, cellMargin

# 4. 추출한 header.xml + 새 section0.xml로 빌드
python3 "$SKILL_DIR/scripts/build_hwpx.py" \
  --header /tmp/ref_header.xml \
  --section /tmp/new_section0.xml \
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

- **Use charPrIDRef/paraPrIDRef as-is**: do not change the style IDs of the extracted header.xml
- **Sum of column widths = body width**: copy the analyzed column-width array exactly
- **Keep rowSpan/colSpan patterns**: reproduce the analyzed cell-merge structure exactly
- **Preserve cellMargin**: apply the analyzed cell margin values identically
- **No page increase**: do not increase the result page count without explicit user approval
- **Replace-first editing**: prefer replacing existing text nodes over adding new paragraphs/tables

---

## Script summary

| Script | Purpose |
|----------|------|
| `scripts/build_hwpx.py` | **Core** — template + XML → HWPX assembly (includes `--update-preview`) |
| `scripts/analyze_template.py` | HWPX deep analysis (blueprint for reference-based generation) |
| `scripts/office/unpack.py` | HWPX → directory (raw bytes + `.hwpx_pack_order` manifest) |
| `scripts/office/pack.py` | directory → HWPX (restores entry order/compression from manifest, mimetype first) |
| `scripts/validate.py` | HWPX structure validation — ZIP/mimetype/XML + secCnt/itemCnt/IDRef/duplicate ID. With `--baseline ref.hwpx`, only new duplicate IDs vs. the original are errors |
| `scripts/page_guard.py` | page-drift risk check vs. reference (restore-mode gate / edit-mode reference) |
| `scripts/text_extract.py` | HWPX text extraction — self-implemented, no external `hwpx` package needed |
| `scripts/locate.py` | byte-span search for text-containing elements (`hp:tbl`/`hp:tr`/`hp:p`/`hp:tc`) — find table/paragraph positions in a single-line section0.xml (extract with `--extract-dir`) |
| `scripts/delete_table_rows.py` | delete table rows — remove `<hp:tr>` + auto-fix rowCnt/rowSpan/rowAddr (`--list` to view rows) |
| `scripts/insert_table_row.py` | insert table row — insert `<hp:tr>` + auto-fix rowCnt/rowAddr/rowSpan (`--grow` to extend the group-end rowSpan) |
| `scripts/replace_cell.py` | replace table cell content — replace the paragraphs of the target `<hp:tc>`'s direct `<hp:subList>` + lineseg strip + ID collision check |
| `scripts/strip_linesegarray.py` | remove `<hp:linesegarray>` — prevent the "document corrupted" warning after text edits |
| `scripts/patch_section.py` | safe text replacement — str.replace + lineseg strip + ID verification. `--after anchor` for context-limited replacement |
| `scripts/calc_col_widths.py` | table column-width calculation — ratio → HWPUNIT (guarantees sum = body width) |
| `scripts/next_id.py` | look up next `hp:p` ID — for collision-free new paragraph insertion |

## New utility usage

### Safe text replacement (patch_section.py)

When editing text in an existing HWPX, use this script instead of a direct str.replace. It handles str.replace + linesegarray removal + ID duplicate check as one atomic operation.

```bash
# 기본 (첫 번째 일치만 교체)
python3 "$SKILL_DIR/scripts/patch_section.py" input.hwpx "기존 텍스트" "새 텍스트" --output result.hwpx

# 전체 교체
python3 "$SKILL_DIR/scripts/patch_section.py" input.hwpx "기존" "새" --count 0 --output result.hwpx

# 미리보기 (파일 미수정)
python3 "$SKILL_DIR/scripts/patch_section.py" input.hwpx "기존" "새" --dry-run
```

### Bulk linesegarray removal (strip_linesegarray.py)

Bulk-remove when the section XML was heavily modified after reference extraction.

```bash
python3 "$SKILL_DIR/scripts/strip_linesegarray.py" result.hwpx --output clean.hwpx
# 또는 in-place
python3 "$SKILL_DIR/scripts/strip_linesegarray.py" result.hwpx --inplace
```

### Column-width calculation (calc_col_widths.py)

```bash
# 3열 균등
python3 "$SKILL_DIR/scripts/calc_col_widths.py" 3
# → 14174 14173 14173

# 비율 지정 (라벨:내용 = 1:4)
python3 "$SKILL_DIR/scripts/calc_col_widths.py" 1:4
# → 8504 34016

# 검증
python3 "$SKILL_DIR/scripts/calc_col_widths.py" --verify 14174 14173 14173
```

### Next hp:p ID lookup (next_id.py)

Always confirm ID collision before inserting a new paragraph.

```bash
python3 "$SKILL_DIR/scripts/next_id.py" document.hwpx
# → 1000000023

python3 "$SKILL_DIR/scripts/next_id.py" document.hwpx --count 5
# → 1000000023 1000000024 1000000025 1000000026 1000000027
```

### Table editing helpers (locate.py / insert_table_row.py / replace_cell.py)

`section0.xml` is one giant single-line XML, so finding table/paragraph positions by hand is hard.
Handle table structure changes (add/delete rows, replace cell content) with the helpers below — they automate `rowAddr` renumbering, `rowCnt`, and `rowSpan` correction to eliminate manual mistakes.

**1) Find element position (locate.py)** — search table/row/paragraph spans by text:

```bash
# 'ECR-001' 포함하는 hp:tbl 모두 (총괄표 + 상세표)
python3 "$SKILL_DIR/scripts/locate.py" doc.hwpx --tag hp:tbl --contains "ECR-001"
# 여러 --contains는 AND — 상세표만 특정
python3 "$SKILL_DIR/scripts/locate.py" doc.hwpx --tag hp:tbl --contains "ECR-001" --contains "산출정보"
# 매치 요소를 파일로 추출 (clone 원본 확보용)
python3 "$SKILL_DIR/scripts/locate.py" doc.hwpx --tag hp:tr --contains "INR-004" --extract-dir ./_work --pretty
```

**2) Insert table row (insert_table_row.py)** — add row + fix metadata:

```bash
# 행 목록 확인 (table id는 delete_table_rows.py --list 또는 locate로 확보)
python3 "$SKILL_DIR/scripts/insert_table_row.py" doc.hwpx --table-id 1277099271 --list
# rowAddr 14 다음에 삽입. 새 행이 rowSpan 그룹의 '끝'이면 그룹 앵커 셀을 --grow로 확장
python3 "$SKILL_DIR/scripts/insert_table_row.py" doc.hwpx --table-id 1277099271 \
  --after-row 14 --row-file new_tr.xml --grow 11,0 --grow 11,3 -o result.hwpx
```

- `--row-file`: the `<hp:tr>...</hp:tr>` to insert (extract an existing row with locate and edit only the text)
- rowSpan cells that **pass through** the insertion point auto-increment by +1. When adding at a group **end**, auto-detection is impossible → specify the anchor cell with `--grow rowAddr,colAddr`
- In-cell text like a `요구사항 수` count ("4"→"5") is separate — handle with `patch_section.py`
- Only `rowAddr`/`rowCnt`/`rowSpan` are auto-fixed. **borderFill is not handled** — for a zebra pattern where section first/middle/last rows use different border IDs, manually check `borderFillIDRef` of the inserted row and adjacent rows (e.g. when adding at a group end, change the old last row to a 'middle' border and apply an 'end' border to the new row)

**3) Replace table cell content (replace_cell.py)** — replace the cell's paragraphs wholesale:

```bash
# 셀 목록 (colAddr,rowAddr 확인)
python3 "$SKILL_DIR/scripts/replace_cell.py" doc.hwpx --table-id 1274564310 --list
# --para PARAPR CHARPR TEXT 반복 — 간단 텍스트 문단
python3 "$SKILL_DIR/scripts/replace_cell.py" doc.hwpx --table-id 1274564310 --cell 2,4 \
  --para 1 186 "■ 헤더" --para 20 186 "본문 항목" -o result.hwpx
# 또는 raw <hp:p> XML 파일
python3 "$SKILL_DIR/scripts/replace_cell.py" doc.hwpx --table-id 1274564310 --cell 2,4 \
  --content-file paras.xml -o result.hwpx
```

> After applying a helper, always validate with `validate.py result.hwpx --baseline original.hwpx`.

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

The HWP parser is sensitive to XML serialization. Violating the patterns below makes the file **exit immediately (crash)** in Hancom.

### No lxml re-serialization (fatal risk)

Parsing an existing `section0.xml` or `header.xml` with lxml and **re-serializing the whole thing** breaks the file.

Side effects of `etree.tostring()`:
- Inserts line breaks/whitespace between tags (pretty-print) → HWP parser failure
- Removes the `standalone="yes"` XML declaration
- Deletes `<hp:t></hp:t>` empty-run content
- Standalone serialization adds all namespace declarations to that element → conflict on document insertion

```python
# ❌ 금지: 기존 문서 파싱 후 전체 재직렬화
root = etree.fromstring(section_raw)
# 수정 ...
result = etree.tostring(root, encoding="unicode")  # 크래시 유발
```

### Safe text modification — use `str.replace()`

```python
# ✅ 안전
xml_str = raw.decode("utf-8")
xml_str = xml_str.replace('기존 텍스트', '새 텍스트', 1)
```

> **Run-split caution**: a sentence that looks like one on screen is often split across multiple `<hp:run>`/`<hp:t>` (format boundaries, standalone comma/parenthesis runs, etc.). If the replace target crosses a run boundary, `str.replace()`/`patch_section.py` **silently fails with 0 matches**. If count is 0, suspect run splitting — extract the element with `locate.py`, check the structure, then replace only a **substring that fits within a single `<hp:t>`**.

> **Substring-collision caution**: conversely, if the replace target is part of a longer string, it replaces unintended places too (e.g. `"조직"` inside `"조직의 구성"`). **Put `assert s.count(old) == expected` on every `str.replace()`**, and when the target is the full text of a paragraph/cell, match with the tags like `<hp:t>X</hp:t>`. Detail — `references/editing-gotchas.md` §2·§3.

### Safe new-paragraph insertion — compact then string-insert

When extracting a new paragraph from a modified copy and inserting it into the original as a string:

```python
import re
from lxml import etree

# 1. lxml으로 새 요소 추출 (기존 문서 재직렬화 아님)
new_el = mod_root.find(...)
raw_new = etree.tostring(new_el, encoding="unicode")

# 2. compact 필수 (태그 간 공백 제거)
raw_new = re.sub(r'>[ \t\r\n]+<', '><', raw_new)

# 3. linesegarray 제거 (캐시 데이터 — HWP이 열 때 재계산)
raw_new = re.sub(r'<hp:linesegarray>.*?</hp:linesegarray>', '', raw_new, flags=re.DOTALL)

# 4. 문자열로 직접 삽입
final_xml = orig_str[:insert_pos] + raw_new + orig_str[insert_pos:]
```

### Compute insertion position after text modification is done

`str.replace()` changes string offsets. An `insert_pos` computed before modification points to the wrong place after.

```python
# ❌ 잘못된 순서
anchor_pos = orig_str.find(anchor_text)   # 수정 전 위치
orig_str = orig_str.replace('old', 'new')  # offset shift
# insert_pos now wrong

# ✅ 올바른 순서: 모든 str.replace() 완료 후 위치 계산
orig_str = orig_str.replace('old1', 'new1')
orig_str = orig_str.replace('old2', 'new2')
anchor_pos = orig_str.find(anchor_text)   # 수정 후 재계산
insert_pos = orig_str.find('</hp:p>', anchor_pos) + len('</hp:p>')
```

### No duplicate `hp:p` IDs

Every `<hp:p id="...">` value in the document must be unique. Duplicate ID → HWP crash.

- Exceptions: `id="0"`, `id="2147483648"` (placeholders)
- When copying/inserting a paragraph from a modified copy, must check for ID collision
- Verify: `re.findall(r'<hp:p\s[^>]*\bid="(\d+)"', xml_str)` then check with `Counter`

### linesegarray removal (when modifying an existing section)

When you modify text in an existing section0.xml, you must remove `<hp:linesegarray>` elements.
`linesegarray` is the layout engine's line-break cache; if its values don't match after a text edit, HWP shows a "document corrupted or modified" warning.

```python
import re
xml_str = re.sub(r'<hp:linesegarray>.*?</hp:linesegarray>', '', xml_str, flags=re.DOTALL)
```

HWP automatically recalculates linesegarray when opening the file.

> Some documents have no `<hp:linesegarray>` at all (varies by Hancom version/save method). Here removal is a no-op and normal — absence is not an error.

### Workflow 2 (unpack → Edit → pack) caution

`unpack.py` extracts raw bytes as-is (no lxml re-serialization). Editing must be done by direct text modification:

```
✅ unpack.py → Read/Edit 도구로 텍스트 직접 수정 → pack.py
❌ unpack.py → lxml parse → etree.tostring() → pack.py  (크래시)
```

---

## Critical Rules

1. **HWPX only**: `.hwp` (binary) files are not supported. If the user provides a `.hwp` file, guide them to **re-save it as `.hwpx` from Hancom Office**. (File → Save As → File type: HWPX)
2. **secPr required**: the first run of section0.xml's first paragraph must contain secPr + colPr
3. **mimetype order**: when packaging HWPX, mimetype is the first ZIP entry, ZIP_STORED
4. **Preserve namespaces**: keep the `hp:`, `hs:`, `hh:`, `hc:` prefixes when editing XML
5. **itemCnt consistency**: header.xml's charProperties/paraProperties/borderFills itemCnt must match the actual child count
6. **ID reference consistency**: section0.xml's charPrIDRef/paraPrIDRef must match header.xml definitions
7. **Use venv**: the project's `.venv/bin/python3` (lxml package required)
8. **Validation**: always confirm integrity with `validate.py` after creation
9. **References**: detailed XML structure → `$SKILL_DIR/references/hwpx-format.md`; existing-document editing traps → `$SKILL_DIR/references/editing-gotchas.md`
10. **build_hwpx.py first**: use build_hwpx.py for new document creation (avoid calling the python-hwpx API directly)
11. **Empty line**: use `<hp:t/>` (self-closing tag)
12. **Process attached HWPX after intent judgment**: do not auto-restore on attachment. Judge restore/edit/extract/generate intent first (see the "Handling attached HWPX — judge intent first" table above). Only when classified as restore, do `analyze_template.py` + extracted-XML-based restore/rewrite
13. **Same page count required (reference restore mode only)**: in restore mode, keep the final result's page count identical to the reference. Does not apply to content-edit / new-creation modes
14. **No unauthorized page increase (reference restore mode only)**: in restore mode, no structure changes that cause page increase without explicit user request/approval
15. **Limit structure changes**: no adding/deleting/splitting/merging of paragraphs/tables unless the user requests it (replace-centered editing)
16. **page_guard must pass (reference restore mode only)**: in restore mode, `page_guard.py` must also pass — separate from `validate.py` — to mark complete. In content-edit mode, `page_guard.py` is reference info, and `validate.py --baseline` + actually opening in Hancom is the completion gate
17. **No lxml re-serialization**: do not `etree.fromstring()` then `etree.tostring()` an existing section0.xml/header.xml — pretty-print / standalone removal / xmlns addition cause HWP parser crashes. **Same applies to content.hpf** (contains 14 Hancom namespace declarations)
18. **Text modification via str.replace()**: apply `str.replace()` directly on the raw XML string for text changes (no lxml needed)
19. **Compact required on new-paragraph insertion**: after serializing an lxml-extracted element, apply `re.sub(r'>[ \t\r\n]+<', '><', xml)` compact before string insertion
20. **Compute insertion position last**: recompute `insert_pos` after all `str.replace()` are done (computing before modification gives a wrong offset)
21. **No duplicate hp:p IDs**: when copying a paragraph from another document, must check for ID duplication — duplicate IDs cause HWP crashes
22. **linesegarray removal required**: when modifying text in an existing section, remove that paragraph's `<hp:linesegarray>` — a stale line-break cache makes HWP show a "document corrupted/modified" warning (HWP auto-recalculates on open)
23. **unpack.py raw-bytes guarantee**: `unpack.py` extracts raw bytes with no lxml re-serialization. When modifying the script directly, this invariant must be kept
24. **FORMULA field caution**: if a table's sum/calculation cell is a `type="FORMULA"` field, modifying the cached `<hp:t>` value is a no-op — Hancom recalculates and overwrites it on open. Replace the whole `fieldBegin`~`fieldEnd` span with static text, or fix the formula input cell (`references/editing-gotchas.md` §1)
25. **Assert a count on every replacement**: when editing an existing document, put `assert s.count(old) == expected` before every `str.replace()` — catches run splitting (0 matches) and substring collision (excess) before silent failure
26. **Content-edit completion gate**: after `validate.py --baseline` passes, confirm it actually opens in Hancom. Fully close Hancom before repackaging (with multiple windows, `CloseMainWindow` closes only the main window), and after applying to the real file verify copy success via md5 or similar (see Workflow 2)
