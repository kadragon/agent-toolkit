# section0.xml Writing Guide

## Required structure

First `<hp:p>` of section0.xml — first `<hp:run>` must contain `<hp:secPr>` and `<hp:colPr>`:

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

**Tip**: copy first paragraph from `templates/base/Contents/section0.xml`.

## Paragraph

```xml
<hp:p id="고유ID" paraPrIDRef="문단스타일ID" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="글자스타일ID">
    <hp:t>텍스트 내용</hp:t>
  </hp:run>
</hp:p>
```

## Empty line

```xml
<hp:p id="고유ID" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0"><hp:t/></hp:run>
</hp:p>
```

## Mixed-format runs (multiple styles in one paragraph)

```xml
<hp:p id="고유ID" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0"><hp:t>일반 텍스트 </hp:t></hp:run>
  <hp:run charPrIDRef="7"><hp:t>볼드 텍스트</hp:t></hp:run>
  <hp:run charPrIDRef="0"><hp:t> 다시 일반</hp:t></hp:run>
</hp:p>
```

## Table

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
              <hp:run charPrIDRef="9"><hp:t>헤더1</hp:t></hp:run>
            </hp:p>
          </hp:subList>
          <hp:cellAddr colAddr="0" rowAddr="0"/>
          <hp:cellSpan colSpan="1" rowSpan="1"/>
          <hp:cellSz width="열너비" height="행높이"/>
          <hp:cellMargin left="0" right="0" top="0" bottom="0"/>
        </hp:tc>
        <hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="4">
          <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER"
                     linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0"
                     hasTextRef="0" hasNumRef="0">
            <hp:p paraPrIDRef="21" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="고유ID">
              <hp:run charPrIDRef="9"><hp:t>헤더2</hp:t></hp:run>
            </hp:p>
          </hp:subList>
          <hp:cellAddr colAddr="1" rowAddr="0"/>
          <hp:cellSpan colSpan="1" rowSpan="1"/>
          <hp:cellSz width="열너비" height="행높이"/>
          <hp:cellMargin left="0" right="0" top="0" bottom="0"/>
        </hp:tc>
      </hp:tr>
      <hp:tr>
        <hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="3">
          <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER"
                     linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0"
                     hasTextRef="0" hasNumRef="0">
            <hp:p paraPrIDRef="22" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="고유ID">
              <hp:run charPrIDRef="0"><hp:t>값1</hp:t></hp:run>
            </hp:p>
          </hp:subList>
          <hp:cellAddr colAddr="0" rowAddr="1"/>
          <hp:cellSpan colSpan="1" rowSpan="1"/>
          <hp:cellSz width="열너비" height="행높이"/>
          <hp:cellMargin left="0" right="0" top="0" bottom="0"/>
        </hp:tc>
        <hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="3">
          <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER"
                     linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0"
                     hasTextRef="0" hasNumRef="0">
            <hp:p paraPrIDRef="22" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="고유ID">
              <hp:run charPrIDRef="0"><hp:t>값2</hp:t></hp:run>
            </hp:p>
          </hp:subList>
          <hp:cellAddr colAddr="1" rowAddr="1"/>
          <hp:cellSpan colSpan="1" rowSpan="1"/>
          <hp:cellSz width="열너비" height="행높이"/>
          <hp:cellMargin left="0" right="0" top="0" bottom="0"/>
        </hp:tc>
      </hp:tr>
    </hp:tbl>
  </hp:run>
</hp:p>
```

> **`colAddr`/`rowAddr` must be distinct per cell — this is the #1 cause of "blank document in Hancom" for hand-written tables.** Every `<hp:tc>` needs its own `(colAddr, rowAddr)` matching its actual grid position; copy-pasting the first cell's block for the remaining cells without updating these two values leaves every cell at `(0,0)`, which is structurally valid XML (passes ZIP/well-formed/ID-ref checks) but renders as an empty document. `validate.py` checks that every `rowCnt × colCnt` grid cell is covered exactly once — run it before opening in Hancom.

## Table placement patterns

`treatAsChar` controls placement behavior:

| Value | DOM position | Behavior |
|-------|-------------|----------|
| `1` (inline) | `<hp:p>` is a normal sibling of other paragraphs inside `<hs:sec>` | Flows with surrounding text |
| `0` (floating) | Same `<hp:p><hp:run>` anchor structure, but table is position-independent | Hancom ignores surrounding text flow |

**Critical**: both inline and floating tables live inside `<hp:p><hp:run>`. Floating tables placed as bare siblings of `<hs:sec>` are invisible in Hancom.

Inline table (`treatAsChar="1"`) — standard form shown in the template above.

Floating table (`treatAsChar="0"`) — same anchor structure, different attribute:

```xml
<!-- hs:sec > hp:p > hp:run > hp:tbl (floating) -->
<hp:p id="고유ID" paraPrIDRef="1" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="29">
    <hp:tbl id="고유ID" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM"
            textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL"
            repeatHeader="0" rowCnt="행수" colCnt="열수" cellSpacing="0"
            borderFillIDRef="3" noAdjust="0">
      <hp:sz width="42520" widthRelTo="ABSOLUTE" height="전체높이" heightRelTo="ABSOLUTE" protect="0"/>
      <hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="0"
              holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP"
              horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
      <!-- rows ... -->
    </hp:tbl>
  </hp:run>
</hp:p>
```

**WRONG** — bare sibling of `<hs:sec>` (Hancom does not render):

```xml
<hs:sec>
  <hp:tbl treatAsChar="0">...</hp:tbl>  <!-- ← never do this -->
</hs:sec>
```

## Table size calculation

- **A4 body width**: 42520 HWPUNIT = 59528 (paper) - 8504×2 (left/right margins)
- **Column widths sum = body width** (42520)
- e.g. 3 equal columns → 14173 + 14173 + 14174 = 42520
- e.g. 2 columns (label:content = 1:4) → 8504 + 34016 = 42520
- **Row height**: usually 2400–3600 HWPUNIT per cell
- Use `calc_col_widths.py` for ratio-based width calc

## ID rules

- Paragraph id: sequential from `1000000001`
- Table id: same sequential namespace as paragraphs — use `next_id.py` to get the next available ID. No two elements (paragraph or table) may share an ID.
- Every id unique within document
- Use `next_id.py` to get next safe ID before inserting paragraphs or tables