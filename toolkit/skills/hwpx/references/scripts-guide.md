# Script Usage Guide

Utility scripts in `scripts/`. See SKILL.md "Script summary" table for one-line descriptions.

## Safe text replacement (patch_section.py)

Use instead of raw `str.replace()` for text edits in existing HWPX. Handles str.replace + linesegarray removal + ID duplicate check as one atomic operation.

```bash
# 기본 (첫 번째 일치만 교체)
python3 "$SKILL_DIR/scripts/patch_section.py" input.hwpx "기존 텍스트" "새 텍스트" --output result.hwpx

# 전체 교체
python3 "$SKILL_DIR/scripts/patch_section.py" input.hwpx "기존" "새" --count 0 --output result.hwpx

# 앵커 지정 (같은 텍스트 여러 개일 때)
python3 "$SKILL_DIR/scripts/patch_section.py" input.hwpx "기존" "새" --after "앵커 텍스트" --output result.hwpx

# 미리보기 (파일 미수정)
python3 "$SKILL_DIR/scripts/patch_section.py" input.hwpx "기존" "새" --dry-run
```

## Bulk linesegarray removal (strip_linesegarray.py)

Bulk-remove when section XML heavily modified after reference extraction.

```bash
python3 "$SKILL_DIR/scripts/strip_linesegarray.py" result.hwpx --output clean.hwpx
# 또는 in-place
python3 "$SKILL_DIR/scripts/strip_linesegarray.py" result.hwpx --inplace
```

## Column-width calculation (calc_col_widths.py)

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

## Next hp:p ID lookup (next_id.py)

Always confirm ID collision before inserting new paragraph.

```bash
python3 "$SKILL_DIR/scripts/next_id.py" document.hwpx
# → 1000000023

python3 "$SKILL_DIR/scripts/next_id.py" document.hwpx --count 5
# → 1000000023 1000000024 1000000025 1000000026 1000000027
```

## Table editing helpers

`section0.xml` is one giant single-line XML — finding table/paragraph positions by hand is hard. Use these helpers for table structure changes — automate `rowAddr` renumbering, `rowCnt`, `rowSpan` correction.

### 1) Find element position (locate.py)

Search table/row/paragraph spans by text. Accepts `.hwpx` file **or** already-unpacked directory (avoids re-unpack cycle when probing repeatedly):

```bash
# '항목명' 포함하는 hp:tbl 모두
python3 "$SKILL_DIR/scripts/locate.py" doc.hwpx --tag hp:tbl --contains "항목명"

# unpack된 디렉토리 직접 사용 (반복 probe 시 re-unpack 불필요)
python3 "$SKILL_DIR/scripts/locate.py" ./unpacked/ --tag hp:tc --contains "이름"

# 여러 --contains는 AND — 특정 표만 좁히기
python3 "$SKILL_DIR/scripts/locate.py" doc.hwpx --tag hp:tbl --contains "항목명" --contains "열제목"

# 매치 요소를 파일로 추출 (clone 원본 확보용)
# Note: create _work/ before using --extract-dir (it will fail if missing)
mkdir -p ./_work
python3 "$SKILL_DIR/scripts/locate.py" doc.hwpx --tag hp:tr --contains "항목코드" --extract-dir ./_work --pretty
```

### 2) Insert table row (insert_table_row.py)

Add row + fix metadata:

```bash
# 행 목록 확인
python3 "$SKILL_DIR/scripts/insert_table_row.py" doc.hwpx --table-id TABLE_ID --list

# rowAddr 3 다음에 삽입
python3 "$SKILL_DIR/scripts/insert_table_row.py" doc.hwpx --table-id TABLE_ID \
  --after-row 3 --row-file new_tr.xml --grow 2,0 --grow 2,3 -o result.hwpx
```

- `--row-file`: `<hp:tr>...</hp:tr>` to insert (extract existing row with locate, edit text only)
- rowSpan cells passing through insertion point auto-increment +1. Adding at group **end**: auto-detection impossible → specify anchor cell with `--grow rowAddr,colAddr`
- In-cell count text (e.g. `"3"→"4"`) — handle separately with `patch_section.py`
- Only `rowAddr`/`rowCnt`/`rowSpan` auto-fixed. **borderFill not handled** — for zebra-pattern tables, manually check `borderFillIDRef` of inserted and adjacent rows

### 3) Replace table cell content (replace_cell.py)

Replace cell's paragraphs wholesale:

```bash
# 셀 목록 (colAddr,rowAddr 확인)
python3 "$SKILL_DIR/scripts/replace_cell.py" doc.hwpx --table-id TABLE_ID --list

# 간단 텍스트 문단
python3 "$SKILL_DIR/scripts/replace_cell.py" doc.hwpx --table-id TABLE_ID --cell 1,0 \
  --para 1 0 "헤더 텍스트" --para 0 0 "본문 내용" -o result.hwpx

# 또는 raw <hp:p> XML 파일
python3 "$SKILL_DIR/scripts/replace_cell.py" doc.hwpx --table-id TABLE_ID --cell 1,0 \
  --content-file paras.xml -o result.hwpx
```

### 4) Delete table rows (delete_table_rows.py)

```bash
# 행 목록 확인
python3 "$SKILL_DIR/scripts/delete_table_rows.py" doc.hwpx --table-id TABLE_ID --list

# rowAddr 2 삭제
python3 "$SKILL_DIR/scripts/delete_table_rows.py" doc.hwpx --table-id TABLE_ID --row 2 -o result.hwpx
```

> After any table helper, always validate: `validate.py result.hwpx --baseline original.hwpx`