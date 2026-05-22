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
- **Edit the input cell**: if the sum is a SUM of other cells, fixing the input cell value makes Hancom recalculate the sum. Verify the formula range (`?2:?N` etc.) points exactly at the input cell — a wrong range gives a wrong sum even with a correct input.

## 2. Substring collision

If a `str.replace()` target is **part of a longer string**, it gets replaced in unintended places too.

Example: changing `"조직"` to `"조직의 구성"`, but the document already has `"조직의 구성"` in 3 places — `s.replace("조직", "조직의 구성")` turns those 3 into `"조직의 구성의 구성"`.

**Avoid — match the full `<hp:t>` element**: if the target is the entire content of one hp:t, match including the tags.

```python
# ❌ 위험: 부분 문자열
s = s.replace("조직", "조직의 구성")
# ✅ 안전: hp:t 전체 요소 — "...조직의 구성" 안의 부분 매칭 회피
s = s.replace("<hp:t>조직</hp:t>", "<hp:t>조직의 구성</hp:t>")
```

`<hp:t>X</hp:t>` form matches only when X is exactly the full text of one paragraph/cell, so there is no substring collision.

**Run-split case**: visible text may be split across multiple `<hp:run>` elements (format boundaries, standalone punctuation runs, etc.). If the target text spans runs, `locate.py` output will show multiple `<hp:t>` elements inside separate `<hp:run>` blocks. Fix each run separately — do not concatenate runs. Example: "홍길동 과장" stored as `<hp:run><hp:t>홍길동 </hp:t></hp:run><hp:run charPrIDRef="1"><hp:t>과장</hp:t></hp:run>` — replace each `<hp:t>` independently.

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

Putting non-ASCII like `■`, `○`, or Korean into `python -c "..."` source and running it via the Bash tool can corrupt characters in transit through the shell and encoding. On corruption, `str.index()`/`rfind()` can't find the target and returns `-1` — a silent failure. Any check/replace logic containing non-ASCII must be written to a `.py` file with `Write` and run via `python script.py` (file is UTF-8, so no corruption).

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