# Reference Restore / Reference-based Generation — Commands and Principles

Moved out of SKILL.md Workflow 5. The mode checklists (99%-close restore, same page count) and the flow stay in SKILL.md; this file holds the full command sequence and two notes the checklists do not cover.

## Usage

```bash
set -euo pipefail
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
# 1. 심층 분석 (구조 청사진 출력)
python3 "$SKILL_DIR/scripts/build.py" analyze reference.hwpx

# 2. header.xml과 section0.xml을 추출하여 참고용으로 보관
HWPX_WORK=$(mktemp -d .hwpx_work_XXXXXX)
python3 "$SKILL_DIR/scripts/build.py" analyze reference.hwpx \
  --extract-header "$HWPX_WORK/ref_header.xml" \
  --extract-section "$HWPX_WORK/ref_section.xml"

# 3. 분석 결과를 보고 새 section0.xml 작성
#    - 동일한 charPrIDRef, paraPrIDRef 사용
#    - 동일한 테이블 구조 (열 수, 열 너비, 행 수, rowSpan/colSpan)
#    - 동일한 borderFillIDRef, cellMargin

# 4. 추출한 header.xml + 새 section0.xml로 빌드
python3 "$SKILL_DIR/scripts/build.py" build \
  --header "$HWPX_WORK/ref_header.xml" \
  --section "$HWPX_WORK/new_section0.xml" \
  --output result.hwpx

# 5. 검증 (원본 대비 — 기존 중복 ID 오탐 방지)
python3 "$SKILL_DIR/scripts/validate.py" validate result.hwpx --baseline reference.hwpx

# 6. 쪽수 드리프트 가드 (필수)
python3 "$SKILL_DIR/scripts/validate.py" page-guard \
  --reference reference.hwpx \
  --output result.hwpx

# 7. 완료 후 임시 디렉토리 정리
rm -rf "$HWPX_WORK"
```

## Checks beyond the SKILL.md checklists

- **Reusing header.xml wholesale imports every charPr's ratio/spacing drift, not just size/font/color**: each `hh:charPr` carries `<hh:ratio>` (장평, character width %) and `<hh:spacing>` (자간, letter spacing) alongside size/font/color — `build.py analyze` reports both (only when non-default: ratio≠100%, spacing≠0). A one-off hand-adjustment the original author made to fit a fixed-width cell (e.g. ratio=95%) carries into the new document unless you notice it in the analyze output. Before treating "identical charPrIDRef reference system" as satisfied, scan the analyze output for any `ratio=`/`spacing=` annotation and confirm it's a deliberate style choice worth preserving in the new document, not stray drift from the original author's manual squeeze.
- **Replace-first editing**: prefer replacing existing text nodes over adding new paragraphs/tables
