# Reference Restore / Reference-based Generation — Commands and Principles

Moved out of SKILL.md Workflow 5. The mode checklists (99%-close restore, same page count) and the flow stay in SKILL.md; this file holds the full command sequence, what `build.py analyze` reports, and the principles for writing the new section0.xml.

## Usage

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
# 1. 심층 분석 (구조 청사진 출력)
python3 "$SKILL_DIR/scripts/build.py" analyze reference.hwpx

set -euo pipefail
# 2. header.xml과 section0.xml을 추출하여 참고용으로 보관
mkdir -p .hwpx_work
python3 "$SKILL_DIR/scripts/build.py" analyze reference.hwpx \
  --extract-header .hwpx_work/ref_header.xml \
  --extract-section .hwpx_work/ref_section.xml

# 3. 분석 결과를 보고 새 section0.xml 작성
#    - 동일한 charPrIDRef, paraPrIDRef 사용
#    - 동일한 테이블 구조 (열 수, 열 너비, 행 수, rowSpan/colSpan)
#    - 동일한 borderFillIDRef, cellMargin

# 4. 추출한 header.xml + 새 section0.xml로 빌드
python3 "$SKILL_DIR/scripts/build.py" build \
  --header .hwpx_work/ref_header.xml \
  --section .hwpx_work/new_section0.xml \
  --output result.hwpx

# 5. 검증 (원본 대비 — 기존 중복 ID 오탐 방지)
python3 "$SKILL_DIR/scripts/validate.py" validate result.hwpx --baseline reference.hwpx

# 6. 쪽수 드리프트 가드 (필수)
python3 "$SKILL_DIR/scripts/validate.py" page-guard \
  --reference reference.hwpx \
  --output result.hwpx

# 7. 완료 후 임시 디렉토리 정리
rm -rf .hwpx_work/
# 사용자에게 알림: "result.hwpx 완성. 임시 폴더 .hwpx_work/ 삭제했습니다."
```

## Analysis output items

| Item | Description |
|------|------|
| Font definitions | hangul/latin font mapping |
| borderFill | border type/thickness + background color (detail per side) |
| charPr | font size (pt), font name, color, ratio(장평)/spacing(자간) when non-default, bold/italic/underline/strikeout, fontRef |
| paraPr | align, line spacing, margin (left/right/prev/next/intent), heading, borderFillIDRef |
| Document structure | page size, margin, page border, body width |
| Body detail | every paragraph's id/paraPr/charPr + text content |
| Table detail | rows×cols, column-width array, per-cell span/margin/borderFill/vertAlign + content |

## Core principles

- **Use charPrIDRef/paraPrIDRef as-is**: do not change style IDs of extracted header.xml
- **Reusing header.xml wholesale imports every charPr's ratio/spacing drift, not just size/font/color**: each `hh:charPr` carries `<hh:ratio>` (장평, character width %) and `<hh:spacing>` (자간, letter spacing) alongside size/font/color — `build.py analyze` reports both (only when non-default: ratio≠100%, spacing≠0). A one-off hand-adjustment the original author made to fit a fixed-width cell (e.g. ratio=95%) carries into the new document unless you notice it in the analyze output. Before treating "identical charPrIDRef reference system" as satisfied, scan the analyze output for any `ratio=`/`spacing=` annotation and confirm it's a deliberate style choice worth preserving in the new document, not stray drift from the original author's manual squeeze.
- **Sum of column widths = body width**: copy analyzed column-width array exactly
- **Keep rowSpan/colSpan patterns**: reproduce analyzed cell-merge structure exactly
- **Preserve cellMargin**: apply analyzed cell margin values identically
- **No page increase**: do not increase result page count without explicit user approval
- **Replace-first editing**: prefer replacing existing text nodes over adding new paragraphs/tables
