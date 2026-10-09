---
name: hwpx
description: >-
  Create, edit, or read HWPX (Hancom/한글) documents — text, tables, styles,
  OWPML, Korean gov/biz forms. Reading an attached .hwpx (extract, translate,
  summarize) goes through here too. Legacy binary .hwp files are accepted via
  conversion to .hwpx (Windows + Hancom; otherwise guide manual re-saving).
  NOT .docx/.xlsx/PDF/Markdown, NOT 한글 app GUI how-to.
  한글 HWPX 문서를 만들고, 편집하고, 읽는 작업 지원. 텍스트, 표, 스타일, OWPML,
  한국 정부·기업 양식 처리. 첨부된 .hwpx 파일 추출·번역·요약도 지원. 한글 문서 작성,
  표 편집, 양식 변환, 본문 추출, 번역, 요약 작업에 사용. 영어·한국어 요청 모두 지원하며
  HWPX 문서 작업에 필요한 XML 구조와 스타일을 함께 처리.
version: 1.0.1
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
| Reference restore | See Workflow 5 restore-mode checklist for full criteria. | See Workflow 5 restore-mode checklist for full criteria. |
| Content edit | Changing is normal | `validate.py validate --baseline` + actually open in Hancom |
| New / reference-based generation | No constraint | `validate.py validate` + actually open in Hancom (title-match check — see "Hancom-open verification") |

Restore-mode page-count/completion-gate rules apply **only to reference restore mode** — see **Workflow 5** for the full checklist. In content edit mode, do not revert work on page count change.

> **`validate.py validate --baseline` scope**: real-world HWPX originals often contain duplicate `hp:p` IDs that HWP allows. Validating without `--baseline` flags these pre-existing duplicates as `INVALID` (false positive). **`--baseline` is required when validating against an original attached document (Workflows 2, 5); omit for new documents (Workflow 1).**

## Environment

Most scripts use stdlib `xml.etree.ElementTree` only. `validate.py` requires `defusedxml` (XXE/billion-laughs hardening); the OLE `.hwp` fallback recipe in `references/environment.md` needs `olefile`. Install both up front:

```bash
python -m pip install olefile defusedxml   # python -m pip, not bare pip — they can bind different interpreters
```

- `SKILL_DIR` = absolute parent directory of the `SKILL.md` loaded this turn (`.../skills/hwpx`). Resolve the concrete path from the loaded file, not from a plugin-root environment variable, at the top of every bash block that references it:
  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
  ```
- OS-specific Python invocation, encoding gotchas (Windows cp949/UTF-8, codepoint escaping), subprocess encoding, and temp-file placement: see `$SKILL_DIR/references/environment.md`
- Layout: `scripts/` (build, office, table, text, validate, `convert_hwp.ps1`) · `templates/` (`base` + `gonmun`/`report`/`minutes`/`proposal` overlays) · `references/` (index in Critical Rule 8). Per-script purpose table and CLI examples: `$SKILL_DIR/references/scripts-guide.md`.

## Temporary working directory

작업 중 `.hwpx_work/` 숨김 폴더가 생성됩니다. 최종 파일 완성 후 반드시 사용자에게 `rm -rf .hwpx_work/`(Windows: `Remove-Item -Recurse -Force .hwpx_work`)를 제시하거나 워크플로우 마지막 단계에서 자동 실행.

## Workflow 1: XML-first new document creation (no attached reference)

### Flow

1. **Pick template** — `gonmun` official correspondence (공문) · `report` multi-section reports with figures · `minutes` meeting records · `proposal` proposals with approval signatures · `base` everything else → look up style IDs in `$SKILL_DIR/references/style-maps.md`
2. **Write section0.xml** (body content)
   > ⚠️ **Don't hand-author `<hp:linesegarray>`/`<hp:lineseg>` for real content.** `hp:lineseg`'s `vertsize`/`textheight`/`horzsize` is a line-break geometry cache sized for the exact text present when Hancom last saved it. Coverage varies by overlay — `report`/`minutes` set one on every body paragraph, `gonmun` on only 1 of 26, `proposal` on none — so check the specific template file rather than assuming presence. Where a paragraph does carry one and you substitute real content into it (especially a longer sentence that wraps to 2+ lines), the cache still describes the placeholder's geometry and Hancom renders the text visibly compressed instead of recomputing it — or, when the substituted text is *shorter* and the cached line count no longer matches, refuses to load the document at all and opens an empty `빈 문서`. New paragraphs you write from scratch: omit `<hp:linesegarray>` entirely (Hancom computes it on open). Paragraphs adapted from a template overlay: after substituting real text, run `table.py strip-lineseg <section0.xml> --inplace` (or `--output`; one of the two is required) before `build.py build` — it strips `<hp:linesegarray>` document-wide despite living in `table.py`, and is a no-op on paragraphs that never had one. Same discipline as rule 19 / Workflow 2, now required here too.
3. **(Optional) edit header.xml** (when new styles needed) → see `$SKILL_DIR/references/hwpx-format.md` § "header.xml Editing Guide"
4. **Build with build.py build**
5. **Validate with validate.py**
6. **Open in Hancom, confirm `MainWindowTitle` matches the filename** (see "Hancom-open verification" under Workflow 2) — `validate.py` passing does not guarantee the file renders; a structurally-valid table with a cellAddr grid gap still opens as a blank document.

> If attached reference exists and intent is restore/edit, use Workflow 5 instead.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
python3 "$SKILL_DIR/scripts/build.py" build --template gonmun --section my_section0.xml --output result.hwpx
```

Header override, metadata (`--title`/`--creator`), and the inline section0.xml → build pattern: `$SKILL_DIR/references/scripts-guide.md` § "build.py build usage".

## XML authoring

- **section0.xml** — full XML templates (paragraph, empty line, mixed runs, table, ID rules): `$SKILL_DIR/references/section-writing.md`. Copy the first paragraph from `templates/base/Contents/section0.xml` (secPr + colPr required in first run); empty line = `<hp:t/>` (self-closing, not `<hp:t></hp:t>`); table total width must equal body width (42520 HWPUNIT) — use `table.py calc-widths` for ratios; paragraph id sequential from `1000000001` — use `build.py next-id` to avoid collisions.
- **header.xml** — full guide: `$SKILL_DIR/references/hwpx-format.md` § "header.xml Editing Guide". Copy `templates/base/Contents/header.xml`, add needed charPr/paraPr/borderFill, update `itemCnt`; paraPr requires `hp:switch` structure (`hp:case` + `hp:default`); keep `borderFillIDRef="2"`.
- **Style IDs** — pick template → look up `charPrIDRef`/`paraPrIDRef`/`borderFillIDRef` in `$SKILL_DIR/references/style-maps.md` before writing section0.xml.
- **Units** — 1pt = 100 HWPUNIT, 1mm ≈ 283.5, A4 = 59528 × 84186, body width 42520: `$SKILL_DIR/references/hwpx-format.md` § "Unit conversion".

## Workflow 2: edit existing document (unpack → Edit → pack)

> **Prerequisite**: read `$SKILL_DIR/references/editing-gotchas.md` before any edits — covers FORMULA fields, substring collision, count verification, paragraph deletion, and other silent-failure traps.

> **Before assuming a `.hwpx` is corrupt**: if `office.py unpack` fails with a ZIP error ("not a valid HWPX (ZIP) file"), check the first 4 bytes before concluding the file is broken — a `.hwpx`-named file is sometimes actually a legacy OLE/CFBF `.hwp` binary (Korean gov/biz email attachments do this often). `D0 CF 11 E0` = legacy OLE `.hwp` (needs `convert_hwp.ps1` first, or see the olefile-based fallback in `references/environment.md` if Hancom/COM isn't available); `50 4B 03 04` = real ZIP/HWPX.
>   - PowerShell: `[System.IO.File]::ReadAllBytes($path)[0..3]`
>   - Python: `open(path, 'rb').read(4)`

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
# 1. HWPX → 디렉토리 (raw bytes 추출, .hwpx_pack_order manifest 기록)
python3 "$SKILL_DIR/scripts/office.py" unpack document.hwpx ./unpacked/

# 2. XML 편집 — 편집 유형별 도구 선택:
#    - 표 셀 내용 수정 → table.py replace 필수 (lineseg + ID 충돌 자동 처리)
#      str.replace()로 셀 직접 수정 금지 — linesegarray 미제거로 "문서 변경됨" 경고,
#      텍스트가 짧아진 경우엔 한글 로드 실패(빈 문서)까지 발생
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

> ⚠️ **`hp:tbl id` collisions**: two unrelated tables can share the same `hp:tbl id` — `--table-id` may still happen to resolve the intended table, but that's not guaranteed. `validate.py validate` now flags duplicate `hp:tbl` ids (see Workflow 4). When uncertain which table `--table-id` resolves to, confirm first with `table.py locate --tag hp:tbl --contains "..."` or `table.py dump --contains "..."` before trusting `--table-id` alone.

### Bulk edits

Many items, many cells, or N files → read `$SKILL_DIR/references/bulk-edit.md` first: stage-by-stage pack → validate → open in Hancom with `assert s.count(old) == expected` on every `str.replace()`; `table.py replace` directly on an unpacked dir for multi-cell edits (`--preserve-style --text` keeps run styling — `--para 0 0 ""` resets charPrIDRef to 0); the N-file loop (slugged unpack dirs, `strip-lineseg` after every text change, `validate --baseline` before overwriting).

### Hancom-open verification (content-edit completion gate)

`validate.py` checks structure only. Completion gate for content edit = confirming it **actually opens in Hancom**.

- **Launch check**: open packaged hwpx (Windows: `Start-Process`), confirm Hancom process (`Hwp`) alive. **Process-alive alone is not sufficient** — a load failure (the cellAddr-grid bug, a stale `<hp:linesegarray>` left on a paragraph whose text got shorter, or any other silent-parse issue) still launches a live Hancom process showing a blank new document, with no crash and no error dialog. Both of those two are caught by `validate.py` — the grid check always, the stale cache only with `--baseline`. The real check: read the process's `MainWindowTitle` and confirm it matches the target filename. If the title reads a generic placeholder (e.g. `빈 문서 1`) instead of the filename, the load failed even though the process is alive.
  ```powershell
  $proc = Get-Process Hwp -ErrorAction SilentlyContinue
  $proc.MainWindowTitle  # must contain the target filename, not "빈 문서 N"
  ```
- **Fully close before repackaging**: close Hancom before re-pack/re-copying same file. **Multiple documents open in Hancom: `CloseMainWindow` closes only one main window** — remaining window locks file. Confirm full close (`Stop-Process` if not closed) before proceeding.
- **Verify copy success**: copying to locked file can fail silently as non-blocking error. After applying to real file, **confirm content match via md5** or similar.

### Row-delete completion gate (verify 0 remaining mentions)

Deleting a table row (`table.py delete`) removes that `<hp:tr>` only — the same item can still be described elsewhere in the document (a narrative section, a separate scoring/criteria table, a required-evidence footnote, etc.), and a scoped delete has no way to know about those. Treat this like the Hancom-open verification above: a structurally-valid delete is not the same as a *complete* delete.

- **Before deleting**: note the keyword(s)/item name being removed (e.g. the row label or a unique phrase from its content).
- **After deleting** (and after re-pack): grep or `str.count()` the full extracted document text (`text.py extract` or `text.py extract --include-tables`) for those keyword(s) and confirm the count is 0 — or, if some mentions are intentionally kept, confirm the remaining count matches expectation.
- Do not declare the edit complete until this check passes. A row deleted from one table while the same item still appears in a narrative section or footnote should not ship without an explicit decision to keep those mentions.

## Workflow 3: read / text extraction

**When skill receives a filepath argument** (e.g. `read path/to/file.hwpx`, bare `path/to/file.hwpx`, or user requests "read file.hwpx" / "file.hwpx 읽어줘"): interpret any filepath as a text-extraction request regardless of the `read` keyword → run `text.py extract`. Skill does not auto-execute on invoke — run the commands below explicitly.

> If `text.py extract` fails with a ZIP error, the same magic-bytes check from Workflow 2 applies — the `.hwpx`-named file may actually be a legacy OLE `.hwp` binary; see the note there and the olefile-based fallback in `references/environment.md`.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
python3 "$SKILL_DIR/scripts/text.py" extract document.hwpx                    # 순수 텍스트
python3 "$SKILL_DIR/scripts/text.py" extract document.hwpx --include-tables   # 테이블 포함
python3 "$SKILL_DIR/scripts/text.py" extract document.hwpx --format markdown  # 마크다운 형식
```

Batch extraction over folders (bash and PowerShell): `$SKILL_DIR/references/scripts-guide.md` § "Batch text extraction".

## Workflow 4: validation

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
python3 "$SKILL_DIR/scripts/validate.py" validate document.hwpx                                   # 단독 새 문서
python3 "$SKILL_DIR/scripts/validate.py" validate result.hwpx --baseline original.hwpx             # 첨부 원본 편집/복원 — 기존 중복 ID 오탐 방지
python3 "$SKILL_DIR/scripts/validate.py" validate result.hwpx --baseline original.hwpx --min-pt 6  # 폰트 크기 경고 임계값 (기본 5pt)
```

Validation items: ZIP validity, required files present, mimetype content/position/compression method, XML well-formedness, secCnt/itemCnt/IDRef, `hp:p` ID duplicates and `hp:tbl` id duplicates (with `--baseline`, only new duplicates are errors — pre-existing dupes shared with baseline are downgraded to warnings), stale `<hp:linesegarray>` (**`--baseline` only**: paragraphs aligned positionally against the baseline — Hancom reuses the placeholder id `2147483648` everywhere, so ids cannot align them — and reported as errors when the text changed but the cache did not; sections whose paragraph count differs from the baseline are skipped), charPr font-size check — texted runs with charPr height below `--min-pt` (default 5pt) emit `WARN`.

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

Read `$SKILL_DIR/references/reference-restore.md` first — full command sequence, `build.py analyze` output items, and the principles for the new section0.xml (keep style IDs, column widths, spans, cellMargin; check analyze output for inherited 장평/자간 drift).

1. **Analyze** — deep-analyze reference document with `build.py analyze`
2. **Extract header.xml** — use reference's style definitions as-is
3. **Write section0.xml** — write new content following analyzed structure
4. **Build** — build with extracted header.xml + new section0.xml
5. **Validate** — `validate.py validate`
6. **Page guard** — `validate.py page-guard` (re-fix on failure)

## Critical Rules

Severity: 🔴 crash/data corruption · 🟡 silent failure/bad output · 🔵 style/consistency

1. 🔵 **HWP → HWPX auto-conversion**: `.hwp` (binary legacy format) cannot be processed directly. When user provides a `.hwp` file, **automatically convert to `.hwpx` first** using `scripts/convert_hwp.ps1` (Windows + Hancom installed), then proceed with normal workflow. Original `.hwp` is deleted after verified conversion. If Hancom is not installed, fall back to guiding the user to re-save as HWPX manually (File → Save As → File type: HWPX).

   Commands (single, batch, `-Force`) and the `forceopen:true` warnings: `$SKILL_DIR/references/environment.md` § "HWP → HWPX conversion". `forceopen:true` bypasses Hancom's macro security prompt — only on trusted input; never pass it to `Hwp.exe` directly.
2. 🔴 **secPr required**: first run of section0.xml's first paragraph must contain secPr + colPr
3. 🔴 **mimetype order**: when packaging HWPX, mimetype = first ZIP entry, ZIP_STORED
4. 🔴 **Preserve namespaces**: keep `hp:`, `hs:`, `hh:`, `hc:` prefixes when editing XML
5. 🟡 **itemCnt consistency**: header.xml's charProperties/paraProperties/borderFills itemCnt must match actual child count
6. 🟡 **ID reference consistency**: section0.xml's charPrIDRef/paraPrIDRef must match header.xml definitions
7. 🔵 **Python version**: any Python 3.8+ works (stdlib only, except `validate.py` which requires `defusedxml` — see `environment.md`)
8. 🔵 **References**: XML structure → `hwpx-format.md`; editing traps → `editing-gotchas.md`; XML serialization rules → `xml-integrity.md`; style IDs → `style-maps.md`; XML templates → `section-writing.md`; script CLI → `scripts-guide.md`; bulk edits → `bulk-edit.md`; restore commands → `reference-restore.md`; environment/encoding → `environment.md`
9. 🔵 **build.py build first**: use `build.py build` for new document creation (avoid calling python-hwpx API directly)
10. 🔵 **Process attached HWPX after intent judgment**: do not auto-restore on attachment. Judge restore/edit/extract/generate intent first (see "Handling attached HWPX — judge intent first" table). Only when classified as restore, do `build.py analyze` + extracted-XML-based restore/rewrite
11. 🟡 **Same page count required (reference restore mode only)**: see Workflow 5 restore-mode checklist for full criteria.
12. 🟡 **No unauthorized page increase (reference restore mode only)**: see Workflow 5 restore-mode checklist for full criteria.
13. 🟡 **page-guard must pass (reference restore mode only)**: see Workflow 5 restore-mode checklist for full criteria.
14. 🔴 **No XML re-serialization**: do not `ET.fromstring()` then `ET.tostring()` existing section0.xml/header.xml — pretty-print / standalone removal / xmlns addition cause HWP parser crashes. **Same applies to content.hpf** (contains 14 Hancom namespace declarations)
15. 🟡 **Text modification via str.replace()**: apply `str.replace()` directly on raw XML string for text changes — **except table cell text: use `table.py replace` instead (see rule 24)**
16. 🔴 **Compact required on new-paragraph insertion**: after extracting element content, apply `re.sub(r'>[ \t\r\n]+<', '><', xml)` compact before string insertion
17. 🟡 **Compute insertion position last**: recompute `insert_pos` after all `str.replace()` done (computing before modification gives wrong offset)
18. 🔴 **No duplicate hp:p IDs**: when copying paragraph from another document, must check for ID duplication — duplicate IDs cause HWP crashes
19. 🔴 **linesegarray removal required**: when modifying text in an existing section, remove the affected paragraph's `<hp:linesegarray>` — the stale line-break cache makes HWP show a "document corrupted/modified" warning, and when the new text is shorter than the cached geometry (2 lines → 1) HWP **silently fails to load the file and opens an empty `빈 문서`** with no error dialog. HWP recalculates the cache on open, so stripping is always safe. Cheapest correct habit: `table.py strip-lineseg <section0.xml> --inplace` once after all text edits, before packing. `validate.py validate --baseline <original>` catches the stale case mechanically
20. 🔵 **unpack.py raw-bytes guarantee**: `unpack.py` extracts raw bytes with no XML re-serialization. When modifying script directly, this invariant must be kept

> Rules 14–20 — code examples and safe patterns: `$SKILL_DIR/references/xml-integrity.md`.

21. 🟡 **FORMULA field caution**: if table's sum/calculation cell is `type="FORMULA"` field, modifying cached `<hp:t>` value = no-op — Hancom recalculates and overwrites on open. Replace whole `fieldBegin`~`fieldEnd` span with static text, or fix formula input cell (`references/editing-gotchas.md` §1)
22. 🟡 **Assert count on every replacement**: when editing existing document, put `assert s.count(old) == expected` before every `str.replace()` — catches run splitting (0 matches) and substring collision (excess) before silent failure
23. 🔵 **Content-edit completion gate**: after `validate.py --baseline` passes, confirm actually opens in Hancom. Fully close Hancom before repackaging (multiple windows: `CloseMainWindow` closes only main window), after applying to real file verify copy success via md5 or similar (see Workflow 2)
24. 🟡 **Table cell text edit → table.py replace only**: for any text change inside a table cell (`<hp:tc>`), use `table.py replace` — not `str.replace()` or `text.py patch`. Table cells have per-subList `<hp:linesegarray>`; `table.py replace` strips it and checks ID collisions automatically. Raw `str.replace()` on cell content leaves stale lineseg → "문서가 변경됨" warning in Hancom. For simple contiguous text changes that must preserve charPr/paraPr (run styling), use `--set-text OLD NEW` — it does a targeted text-only replacement inside the existing runs, keeping all attribute structure intact. **`OLD` must equal the entire content of one `<hp:t>` element, not a substring** — a partial/substring match fails with the same "not found" error as run-splitting, so rule out a substring mismatch first before assuming the text is split across runs. When the target text is fragmented across multiple `<hp:run>` nodes (run-split), or when you want to replace cell content while reusing the existing charPr/paraPr from the cell (preventing charPr reset to 0), use `--preserve-style --text "새내용"` instead — it reads the first paraPrIDRef and charPrIDRef from the cell and rebuilds the paragraph with them. For bulk multi-cell replace with style preservation, use `table.py fill --data data.json`.
25. 🔴 **Floating table must be anchored in `<hp:p><hp:run>`**: `treatAsChar="0"` (floating) tables must be a direct child of `<hp:run>` inside `<hp:p>` — never a bare sibling of `<hs:sec>` or `<hp:p>`. Bare-sibling floating tables are not rendered by Hancom. See `section-writing.md` § "Table placement patterns" for both placement forms.
26. 🟡 **Escape angle brackets in text nodes**: Korean legal/administrative text commonly contains `<개정 2026. 6.>` or similar angle-bracket spans — always write as `&lt;개정 2026. 6.&gt;`. Unescaped `<` inside `<hp:t>` causes XML parse failure at document load.
