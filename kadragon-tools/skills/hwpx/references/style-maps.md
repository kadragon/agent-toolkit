# Per-Template Style ID Maps

Look up `charPrIDRef` / `paraPrIDRef` / `borderFillIDRef` when writing section0.xml or header.xml.

## base

| ID | Type | Description |
|----|------|------|
| charPr 0 | Char | 10pt 함초롬바탕, default |
| charPr 1 | Char | 10pt 함초롬돋움 |
| charPr 2~6 | Char | Skeleton default styles |
| paraPr 0 | Para | JUSTIFY, 160% line spacing |
| paraPr 1~19 | Para | Skeleton defaults (outline, footnote, etc.) |
| borderFill 1 | Border | None (page border) |
| borderFill 2 | Border | None + transparent background (reference use) |

## gonmun (공문, official document) — base + additions

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

## report (보고서) — base + additions

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

## minutes (회의록, meeting minutes) — base + additions

| ID | Type | Description |
|----|------|------|
| charPr 7 | Char | 18pt bold (title) |
| charPr 8 | Char | 12pt bold (section label) |
| charPr 9 | Char | 10pt bold (table header) |
| paraPr 20~22 | Para | CENTER/JUSTIFY variants |
| borderFill 3 | Border | SOLID 0.12mm 4 sides |
| borderFill 4 | Border | SOLID 0.12mm + #E2EFDA background |

## proposal (제안서/사업개요) — base + additions

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

### proposal layout pattern

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
