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

**Indentation rule**: no space chars — use paraPr left margin. □ → paraPr 24, ①②③ → paraPr 25, deep - → paraPr 26.

**Section header rule**: paraPr 27 + charPr 13. `borderFillIDRef="5"` auto-shows top thick + bottom thin line.

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

Formal docs with visual separation. Color-background header bars + number badges via table layout.

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

## Reusable pattern: color banner / stripe title bar (any template)

Korean gov/biz documents commonly wrap a title or section header in a colored 1-cell banner,
or a 3-column stripe (accent color | title | accent color). This is not template-specific —
add the border/char styles to whichever template's `header.xml` you're already using, following
the `itemCnt` bump rule in "header.xml editing guide".

**1. Add a background-color `borderFill` to header.xml:**
```xml
<hh:borderFill id="NEW_ID" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
  <hc:leftBorder type="NONE" width="0.1mm" color="#000000"/>
  <hc:rightBorder type="NONE" width="0.1mm" color="#000000"/>
  <hc:topBorder type="NONE" width="0.1mm" color="#000000"/>
  <hc:bottomBorder type="NONE" width="0.1mm" color="#000000"/>
  <hc:diagonal type="NONE" width="0.1mm" color="#000000"/>
  <hc:fillBrush>
    <hc:winBrush faceColor="#4472C4" hatchColor="#000000" alpha="0"/>
  </hc:fillBrush>
</hh:borderFill>
```
Swap `faceColor` for the banner color (e.g. `#7B8B3D` olive, `#D6DCE4` light blue-gray). Bump
`<hh:borderFills itemCnt="...">` to match.

**2. Add a white/bold `charPr` for text sitting on the colored background** (dark banners need
light text — reusing a body-text charPr on a dark fill is unreadable):
```xml
<hh:charPr id="NEW_ID" height="1400" textColor="#FFFFFF" ...>
```

**3. 1-cell full-width banner** (title bar spanning the whole table width — `rowCnt="1" colCnt="1"`):
same single-`<hp:tc>` shape as any 1x1 table; give that one `<hp:tc>` the new `borderFillIDRef`
and its `<hp:run>` the new white/bold `charPrIDRef`. `cellAddr` is `colAddr="0" rowAddr="0"` —
trivially satisfies the grid check since there's only one cell.

**4. 3-column stripe** (accent | title | accent — `rowCnt="1" colCnt="3"`): three `<hp:tc>` in
one `<hp:tr>`, `cellAddr` `(0,0)`, `(1,0)`, `(2,0)` — remember each needs its **own** `colAddr`
(see section-writing.md's cellAddr warning). Give the outer two cells the accent `borderFillIDRef`
with no text run (or a decorative glyph), and the middle cell the title text with a plain/white
`borderFillIDRef` background.

This is exactly the `proposal` template's major/sub-item header pattern generalized — see above
for a working column-count-2 example with concrete IDs.