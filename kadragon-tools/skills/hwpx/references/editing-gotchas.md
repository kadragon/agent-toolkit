# HWPX Editing Gotchas

Traps causing silent failures and no-op edits in existing HWPX. Read before modifying text/tables in Workflow 2.

## 1. FORMULA fields — editing cached value is no-op

Table sum/calc cell may be **FORMULA field**, not plain text. Structure:

```xml
<hp:run charPrIDRef="0">
  <hp:ctrl><hp:fieldBegin id="1000000099" type="FORMULA" ... fieldid="2000000001">
    <hp:parameters cnt="5" name="">
      <hp:stringParam name="Command">=SUM(?2:?N)??%g,;;N</hp:stringParam>
      <hp:stringParam name="Formula">=SUM(?2:?N)</hp:stringParam>
      <hp:stringParam name="LastResult">N</hp:stringParam>
    </hp:parameters>
  </hp:fieldBegin></hp:ctrl>
  <hp:t>N+1</hp:t>                                        <!-- 표시값 (캐시) -->
  <hp:ctrl><hp:fieldEnd beginIDRef="1000000099" fieldid="2000000001"/></hp:ctrl>
  <hp:t/>
</hp:run>
```

`<hp:t>N+1</hp:t>` = **cached formula result**. Change only this → Hancom recalculates on open, **overwrites** → no-op.

**Detection**: `type="FORMULA"` nearby = field. `Command`/`Formula`/`LastResult` params = clue. Display value ≠ `LastResult` = formula/range already broken.

**Two fixes**:

- **Convert to static (recommended when answer fixed)**: replace whole span from `fieldBegin` ctrl through `fieldEnd` ctrl + cached `<hp:t>` with static text. Use `id`/`fieldid` as regex anchors for uniqueness.
  ```python
  import re
  # actual id/fieldid values — read from the document
  FIELD_ID = "1000000099"
  FIELDID  = "2000000001"
  pat = (rf'<hp:ctrl><hp:fieldBegin id="{FIELD_ID}".*?'
         rf'<hp:fieldEnd beginIDRef="{FIELD_ID}" fieldid="{FIELDID}"/></hp:ctrl><hp:t/>')
  assert len(re.findall(pat, s, re.DOTALL)) == 1
  s = re.sub(pat, "<hp:t>새 값</hp:t>", s, flags=re.DOTALL)
  ```
- **Edit input cell**: if sum is SUM of other cells, fix input cell → Hancom recalculates. Verify formula range (`?2:?N` etc.) points at input cell — wrong range = wrong sum even with correct input.

## 2. Substring collision

`str.replace()` target is **part of longer string** → replaced in unintended places.

Example: changing `"조직"` to `"조직의 구성"`, document already has `"조직의 구성"` 3 places → `s.replace("조직", "조직의 구성")` → `"조직의 구성의 구성"`.

**Fix — match full `<hp:t>` element**:

```python
# ❌ 위험: 부분 문자열
s = s.replace("조직", "조직의 구성")
# ✅ 안전: hp:t 전체 요소 — "...조직의 구성" 안의 부분 매칭 회피
s = s.replace("<hp:t>조직</hp:t>", "<hp:t>조직의 구성</hp:t>")
```

`<hp:t>X</hp:t>` matches only when X is exactly full text of one paragraph/cell → no substring collision.

## 3. Assert count on every replacement

`str.replace()` passes silently on 0 matches. Splitting, substring collision, encoding corruption → silent failure. **Always assert expected count before replacing.**

```python
def rep(s, old, new, n):
    c = s.count(old)
    assert c == n, f"FAIL {old!r}: expected {n}, got {c}"
    return s.replace(old, new)
```

Count differs → abort immediately. Essential for bulk edits.

## 4. Documents without linesegarray

Some HWPX have no `<hp:linesegarray>` cache (varies by Hancom version/save method). Strip is no-op — normal. Removing linesegarray = idempotent "remove if present, leave if absent". Absence not error.

## 5. Non-ASCII match strings go in script file

Non-ASCII like `■`, `○`, Korean in `python -c "..."` via Bash → corrupt in transit through shell/encoding. Corruption → `str.index()`/`rfind()` can't find target, returns `-1` → silent failure. Any check/replace with non-ASCII must be written to `.py` file via `Write`, run via `python script.py` (file is UTF-8, no corruption).

## 6. Deleting paragraphs/spans — dump and verify

Don't hand-build string when deleting multiple paragraphs. Use inspection script to dump target span, confirm paragraph count, then delete.

```python
a = s.rfind("<hp:p ", 0, s.index(first_needle))
b = s.index("</hp:p>", s.index(last_needle)) + len("</hp:p>")
seg = s[a:b]
assert seg.count("<hp:p ") == 기대단락수      # 구간이 정확한지 검증
s = s[:a] + s[b:]
```

Deleting paragraph inside cell → confirm at least 1 paragraph remains — empty cell needs 1 `<hp:p>` (empty run).