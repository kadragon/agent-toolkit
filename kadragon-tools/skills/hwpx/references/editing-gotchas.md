# HWPX Editing Gotchas

Traps that cause silent failures and no-op edits when editing an existing HWPX. Read before modifying text or tables in Workflow 2 (content editing).

## 1. FORMULA fields — editing the cached value is a no-op

A table's sum/calculation cell may be a **FORMULA field**, not plain text. Structure:

```xml
<hp:run charPrIDRef="7">
  <hp:ctrl><hp:fieldBegin id="1277099272" type="FORMULA" ... fieldid="627469685">
    <hp:parameters cnt="5" name="">
      <hp:stringParam name="Command">=SUM(?2:?23)??%g,;;23</hp:stringParam>
      <hp:stringParam name="Formula">=SUM(?2:?23)</hp:stringParam>
      <hp:stringParam name="LastResult">23</hp:stringParam>
    </hp:parameters>
  </hp:fieldBegin></hp:ctrl>
  <hp:t>24</hp:t>                                          <!-- 표시값 (캐시) -->
  <hp:ctrl><hp:fieldEnd beginIDRef="1277099272" fieldid="627469685"/></hp:ctrl>
  <hp:t/>
</hp:run>
```

`<hp:t>24</hp:t>` is the **cached formula result**. Changing only this text — Hancom recalculates the formula on open and **overwrites** it → edit is a no-op.

**Detection**: if you want to change a cell value and `type="FORMULA"` is nearby, it's a field. `Command`/`Formula`/`LastResult` params are the clue. Display value ≠ `LastResult` (e.g. display 24, LastResult 23) signals the formula/range is already broken.

**Two fixes**:

- **Convert to static value (recommended when the answer is fixed)**: replace the whole span from the `fieldBegin` ctrl through the `fieldEnd` ctrl + cached `<hp:t>` with static text. Use `id`/`fieldid` as regex anchors to guarantee uniqueness.
  ```python
  import re
  pat = (r'<hp:ctrl><hp:fieldBegin id="1277099272".*?'
         r'<hp:fieldEnd beginIDRef="1277099272" fieldid="627469685"/></hp:ctrl><hp:t/>')
  assert len(re.findall(pat, s, re.DOTALL)) == 1
  s = re.sub(pat, "<hp:t>49</hp:t>", s, flags=re.DOTALL)
  # 결과: <hp:run charPrIDRef="7"><hp:t>49</hp:t></hp:run>
  ```
- **Edit the input cell**: if the sum is a SUM of other cells, fixing the input cell value makes Hancom recalculate the sum. Verify the formula range (`?2:?23` etc.) points exactly at the input cell — a wrong range gives a wrong sum even with a correct input.

## 2. Substring collision

If a `str.replace()` target is **part of a longer string**, it gets replaced in unintended places too.

Example: changing `"사업 수행 조직"` to `"사업 수행 조직의 구성"`, but the document already has `"사업 수행 조직의 구성"` in 3 places — `s.replace("사업 수행 조직", "사업 수행 조직의 구성")` turns those 3 into `"사업 수행 조직의 구성의 구성"`.

**Avoid — match the full `<hp:t>` element**: if the target is the entire content of one hp:t, match including the tags.

```python
# ❌ 위험: 부분 문자열
s = s.replace("사업 수행 조직", "사업 수행 조직의 구성")
# ✅ 안전: hp:t 전체 요소 — "...조직의 구성" 안의 부분 매칭 회피
s = s.replace("<hp:t>사업 수행 조직</hp:t>", "<hp:t>사업 수행 조직의 구성</hp:t>")
```

`<hp:t>X</hp:t>` form matches only when X is exactly the full text of one paragraph/cell, so there is no substring collision.

## 3. Assert a count on every replacement

`str.replace()` passes silently with no exception even on 0 matches. Run splitting, substring collision, and encoding corruption all lead to silent failure. **Always assert the expected count before replacing.**

```python
def rep(s, old, new, n):
    c = s.count(old)
    assert c == n, f"FAIL {old!r}: expected {n}, got {c}"
    return s.replace(old, new)
```

If the count differs from expected, abort immediately — stop before a corrupted file is produced. Essential for bulk edits.

## 4. Documents without linesegarray

Some HWPX documents have no `<hp:linesegarray>` cache at all (varies by Hancom version and save method). Here strip is a no-op and that is normal — removing linesegarray is an idempotent "remove if present, leave if absent" operation. Absence is not an error.

## 5. Non-ASCII match strings go in a script file

Putting non-ASCII like `■`, `○`, or Korean into `python -c "..."` source and running it via the Bash tool can corrupt characters in transit through the shell and encoding. On corruption, `str.index()`/`rfind()` can't find the target and returns `-1` — a silent failure. Any check/replace logic containing non-ASCII must be written to a `.py` file with `Write` and run via `python script.py` (the file is UTF-8, so no corruption).

## 6. Deleting paragraphs/spans — dump and verify

When deleting multiple paragraphs together, do not hand-build the string. Use an inspection script to dump the target span, confirm the paragraph count, then delete.

```python
a = s.rfind("<hp:p ", 0, s.index(first_needle))
b = s.index("</hp:p>", s.index(last_needle)) + len("</hp:p>")
seg = s[a:b]
assert seg.count("<hp:p ") == 기대단락수      # 구간이 정확한지 검증
s = s[:a] + s[b:]
```

When deleting a paragraph inside a cell, confirm at least 1 paragraph remains in that cell — an empty cell needs 1 `<hp:p>` (an empty run).
