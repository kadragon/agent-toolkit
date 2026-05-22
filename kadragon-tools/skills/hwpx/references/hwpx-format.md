# HWPX (OWPML) File Format Reference

## Overview

HWPX is Hancom Office's next-generation document format, following the **OWPML** (Open Word-Processor Markup Language) standard (KS X 6101:2024). It is a ZIP-based XML container, using an OPC (Open Packaging Conventions) structure similar to DOCX/XLSX.

## Internal file structure

```
document.hwpx (ZIP archive)
├── mimetype                    # "application/hwp+zip" (첫 번째 엔트리, 비압축)
├── META-INF/
│   ├── container.xml           # 패키지 루트 파일 위치
│   ├── container.rdf           # 관계 정보
│   └── manifest.xml            # 파일 목록
├── Contents/
│   ├── content.hpf             # 매니페스트 (OPF 형식, 섹션/헤더 목록)
│   ├── header.xml              # 문서 헤더 (스타일, 폰트, CharShape, ParaShape 정의)
│   ├── section0.xml            # 본문 섹션 (문단, 표, 그림 등)
│   ├── section1.xml            # 추가 섹션 (있는 경우)
│   └── ...
├── Preview/
│   ├── PrvImage.png            # 미리보기 이미지
│   └── PrvText.txt             # 미리보기 텍스트
├── settings.xml                # 편집 설정
└── version.xml                 # 버전 정보
```

### Core rules

- **mimetype**: must be the **first entry** of the ZIP archive, stored as **ZIP_STORED** (uncompressed)
- **content.hpf**: OPF-format manifest. References all content files
- **header.xml**: document-global style definitions (CharShape, ParaShape, BorderFill, etc.)
- **section*.xml**: actual document content

## XML namespaces

| Prefix | URI | Use |
|--------|-----|------|
| `hp` | `http://www.hancom.co.kr/hwpml/2011/paragraph` | Paragraph, run, text, table, control |
| `hs` | `http://www.hancom.co.kr/hwpml/2011/section` | Section root |
| `hc` | `http://www.hancom.co.kr/hwpml/2011/core` | Core data types |
| `hh` | `http://www.hancom.co.kr/hwpml/2011/head` | Header (style/property definitions) |
| `ha` | `http://www.hancom.co.kr/hwpml/2011/app` | App metadata |
| `hp10` | `http://www.hancom.co.kr/hwpml/2016/paragraph` | Extended paragraph elements |
| `hpf` | `http://www.hancom.co.kr/schema/2011/hpf` | Manifest (content.hpf) |
| `opf` | `http://www.idpf.org/2007/opf/` | OPF package |

## Main XML elements

### Section (section*.xml)

```xml
<hs:sec xmlns:hp="..." xmlns:hs="...">
  <hp:p>...</hp:p>     <!-- 문단 -->
  <hp:p>...</hp:p>     <!-- 문단 -->
</hs:sec>
```

### Paragraph

```xml
<hp:p id="..." paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0">
    <hp:t>텍스트 내용</hp:t>
  </hp:run>
</hp:p>
```

- `paraPrIDRef`: ParaShape reference ID in header.xml
- `styleIDRef`: Style reference ID in header.xml
- `charPrIDRef`: CharShape reference ID in header.xml (run level)

### Text run

```xml
<hp:run charPrIDRef="2">
  <hp:t>볼드 텍스트</hp:t>
</hp:run>
```

- One paragraph can hold multiple runs (text with different formatting)
- `charPrIDRef` references the character format

### Table

```xml
<hp:tbl id="..." rowCnt="2" colCnt="3" cellSpacing="0" borderFillIDRef="3">
  <hp:sz width="21600" height="7200" />
  <hp:pos treatAsChar="1" />
  <hp:tr>                           <!-- 행 -->
    <hp:tc borderFillIDRef="3">     <!-- 셀 -->
      <hp:cellAddr colAddr="0" rowAddr="0" colSpan="1" rowSpan="1"/>
      <hp:cellSz width="7200" height="3600"/>
      <hp:cellMargin left="510" right="510" top="142" bottom="142"/>
      <hp:subList>
        <hp:p ...>
          <hp:run ...>
            <hp:t>셀 내용</hp:t>
          </hp:run>
        </hp:p>
      </hp:subList>
    </hp:tc>
  </hp:tr>
</hp:tbl>
```

### Section properties

Held in the first run of the first paragraph:

```xml
<hp:secPr textDirection="HORIZONTAL" ...>
  <hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">
    <hp:margin header="4252" footer="4252" gutter="0"
               left="8504" right="8504" top="5668" bottom="4252"/>
  </hp:pagePr>
</hp:secPr>
```

- Unit: HWPUNIT (1/7200 inch). e.g. 59528 ≈ A4 width (210mm)
- `width="59528"` = A4 portrait width, `height="84186"` = A4 height
- Margins: `left/right/top/bottom` values (HWPUNIT)

### Inline controls

```xml
<hp:run>
  <hp:ctrl>
    <hp:colPr type="NEWSPAPER" colCount="1" />
  </hp:ctrl>
</hp:run>
```

```xml
<hp:run>
  <hp:lineBreak/>    <!-- 줄바꿈 -->
  <hp:tab/>          <!-- 탭 -->
</hp:run>
```

## header.xml main structure

### CharShape (character format)

```xml
<hh:charProperties itemCnt="...">
  <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none"
             useFontSpace="0" useKerning="0" symMark="NONE"
             borderFillIDRef="0">
    <hh:fontRef hangul="한양신명조" latin="Times New Roman" .../>
    <hh:ratio hangul="100" latin="100" .../>
    <hh:spacing hangul="0" latin="0" .../>
    <hh:relSz hangul="100" latin="100" .../>
    <hh:offset hangul="0" latin="0" .../>
    <hh:bold/>          <!-- 볼드 (요소 존재 시 활성) -->
    <hh:italic/>        <!-- 이탤릭 -->
    <hh:underline type="BOTTOM" shape="SOLID" color="#000000"/>
    <hh:strikeout type="NONE"/>
    <hh:outline type="NONE"/>
    <hh:shadow type="NONE"/>
    <hh:emboss type="NONE"/>
    <hh:engrave type="NONE"/>
    <hh:supscript type="NONE"/>
  </hh:charPr>
</hh:charProperties>
```

- `height`: font size (HWPUNIT, 1000 = 10pt)
- `textColor`: font color (#RRGGBB)
- Bold/italic: determined by presence of the element

### ParaShape (paragraph format)

```xml
<hh:paraProperties itemCnt="...">
  <hh:paraPr id="0" align="JUSTIFY" vertalign="BASELINE"
             headingType="NONE" level="0" tabPrIDRef="0"
             condense="0" fontLineHeight="0" snapToGrid="1"
             suppressLineNumbers="0" checked="0">
    <hh:margin indent="0" left="0" right="0"/>
    <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
    <hh:heading type="NONE" idRef="0" level="0"/>
    <hh:border borderFillIDRef="0" offsetLeft="0" offsetRight="0"
               offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
    <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
  </hh:paraPr>
</hh:paraProperties>
```

- `align`: `JUSTIFY`, `LEFT`, `RIGHT`, `CENTER`
- `lineSpacing`: `type="PERCENT"`, `value="160"` = 160% line spacing

## Unit conversion

| Unit | Description | Conversion |
|------|------|------|
| HWPUNIT | Hancom internal unit | 1 HWPUNIT = 1/7200 inch |
| pt (point) | Font size | 1pt = 100 HWPUNIT |
| mm (millimeter) | Paper/margin | 1mm ≈ 283.46 HWPUNIT |

### Common values

- A4 paper: width=59528, height=84186
- 10pt font: height=1000
- 12pt font: height=1200
- Default margin (left/right): 8504 (≈ 30mm)
- Default margin (top): 5668 (≈ 20mm)
- Default margin (bottom): 4252 (≈ 15mm)

## python-hwpx API mapping

| Operation | python-hwpx method | Note |
|------|---------------------|------|
| New document | `HwpxDocument.new()` | Uses empty Skeleton template |
| Open file | `HwpxDocument.open(path)` | Accepts path, bytes, BinaryIO |
| Add paragraph | `doc.add_paragraph(text, section=)` | Format settable via charPrIDRef |
| Add table | `doc.add_table(rows, cols, section=)` | borderFillIDRef auto-generated |
| Cell text | `table.set_cell_text(row, col, text)` | 0-indexed |
| Header | `doc.set_header_text(text, section=)` | |
| Footer | `doc.set_footer_text(text, section=)` | |
| Memo | `doc.add_memo_with_anchor(text, ...)` | MEMO field auto-generated |
| Bold/italic run style | `doc.ensure_run_style(bold=True)` | Returns charPrIDRef |
| Text extraction | `TextExtractor(path).extract_text()` | Table-include option |
| Save | `doc.save_to_path(path)` | |
| Return bytes | `doc.to_bytes()` | |

## Low-level XML access

When python-hwpx's high-level API can't handle it:

1. Use the **unpack** → edit XML directly → **pack** workflow
2. Access the low-level XML tree via the `doc.oxml` property
3. Manipulate lxml Element directly via `doc.sections[0].element`

### Example: change paper size (A4 → B5)

```python
# unpack 후 section0.xml 편집
# <hp:pagePr> 의 width, height 속성 변경
# B5: width=51592, height=72850
```

### Example: change font (header.xml)

```python
# <hh:charPr id="0"> 의 <hh:fontRef> 속성 변경
# hangul="맑은 고딕" latin="Arial"
```

---

## header.xml Editing Guide

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
