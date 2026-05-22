# HWPX XML Integrity — Prevent HWP Parser Crashes

The HWP parser is sensitive to XML serialization. Violating the patterns below makes the file **exit immediately (crash)** in Hancom.

## No lxml re-serialization (fatal risk)

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

## Safe text modification — use `str.replace()`

```python
# ✅ 안전
xml_str = raw.decode("utf-8")
xml_str = xml_str.replace('기존 텍스트', '새 텍스트', 1)
```

> **Run-split caution**: a sentence that looks like one on screen is often split across multiple `<hp:run>`/`<hp:t>` (format boundaries, standalone comma/parenthesis runs, etc.). If the replace target crosses a run boundary, `str.replace()`/`patch_section.py` **silently fails with 0 matches**. If count is 0, suspect run splitting — extract the element with `locate.py`, check the structure, then replace only a **substring that fits within a single `<hp:t>`**.

> **Substring-collision caution**: if the replace target is part of a longer string, it replaces unintended places too (e.g. `"조직"` inside `"조직의 구성"`). **Put `assert s.count(old) == expected` on every `str.replace()`**, and when the target is the full text of a paragraph/cell, match with the tags like `<hp:t>X</hp:t>`. Detail — `editing-gotchas.md` §2·§3.

## Safe new-paragraph insertion — compact then string-insert

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

## Compute insertion position after all str.replace() are done

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

## No duplicate `hp:p` IDs

Every `<hp:p id="...">` value in the document must be unique. Duplicate ID → HWP crash.

- Exceptions: `id="0"`, `id="2147483648"` (placeholders)
- When copying/inserting a paragraph from a modified copy, check for ID collision
- Verify: `re.findall(r'<hp:p\s[^>]*\bid="(\d+)"', xml_str)` then check with `Counter`

## linesegarray removal

When modifying text in an existing section0.xml, remove `<hp:linesegarray>` elements.
`linesegarray` is the layout engine's line-break cache; stale values after a text edit trigger a "document corrupted or modified" warning.

```python
import re
xml_str = re.sub(r'<hp:linesegarray>.*?</hp:linesegarray>', '', xml_str, flags=re.DOTALL)
```

HWP automatically recalculates linesegarray on open. Documents with no `<hp:linesegarray>` at all are also valid — removal is a no-op.

## Workflow 2 (unpack → Edit → pack) caution

`unpack.py` extracts raw bytes as-is (no lxml re-serialization). Editing must be done by direct text modification:

```
✅ unpack.py → Read/Edit 도구로 텍스트 직접 수정 → pack.py
❌ unpack.py → lxml parse → etree.tostring() → pack.py  (크래시)
```

**Same rule applies to `content.hpf`** — it contains 14 Hancom namespace declarations; lxml re-serialization corrupts it.
