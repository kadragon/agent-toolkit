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

## 7. 빈 셀 self-closing run → full run 패턴

템플릿의 빈 셀은 종종 self-closing `<hp:run>` 형태:

```xml
<!-- 빈 셀 (텍스트 없음) -->
<hp:run charPrIDRef="3"/>
```

이 형태에 텍스트를 직접 str.replace로 넣을 수 없음. 먼저 full run으로 전개한 뒤 `<hp:t>` 삽입:

```xml
<!-- 전환 후 -->
<hp:run charPrIDRef="3"><hp:t>채울 텍스트</hp:t></hp:run>
```

```python
old = '<hp:run charPrIDRef="3"/>'
new = '<hp:run charPrIDRef="3"><hp:t>채울 텍스트</hp:t></hp:run>'
assert s.count(old) == 1
s = s.replace(old, new)
```

**Detection**: `locate.py --tag hp:tc --contains ""` 또는 `--extract-dir`로 추출 후 self-closing run 확인. `replace_cell.py` 사용 시에는 이 변환이 자동 처리됨.

## 8. `<hp:t>` 정규식 — `<hp:t[^>]*>` 오매칭 함정

`<hp:t[^>]*>` 패턴은 `<hp:tc>`, `<hp:tbl>`, `<hp:tr>` 도 매칭됨:

```python
# ❌ 위험: hp:tc, hp:tbl, hp:tr 모두 매칭
re.findall(r"<hp:t[^>]*>", xml)

# ✅ 안전: hp:t 단독 (속성 없는 형태)
re.findall(r"<hp:t>", xml)

# ✅ 안전: hp:t 뒤에 공백/속성이 올 수 있는 경우
re.findall(r"<hp:t(?:\s[^>]*)?>", xml)

# ✅ 텍스트 추출용
re.findall(r"<hp:t>(.*?)</hp:t>", xml, re.DOTALL)
```

closing 태그도 동일: `</hp:t>` 는 안전, `</hp:t[^>]*>` 불필요.

## 9. paraPrIDRef로 빈 셀 타겟팅

템플릿에서 빈 셀이 여러 개일 때 `<hp:t>` 내용이 모두 비어 있어 텍스트 기반 식별 불가. `paraPrIDRef`를 고유 식별자로 활용:

```python
# 1. 문서 내 유일성 먼저 확인
target = 'paraPrIDRef="42"'
assert s.count(target) == 1, f"not unique: {s.count(target)} occurrences"

# 2. paraPrIDRef 포함 run 교체
old = '<hp:p id="1000000005" paraPrIDRef="42" ...'
# → locate.py --tag hp:p 로 exact 스팬 추출 후 교체
```

`paraPrIDRef`는 단락 스타일 ID — 같은 스타일을 공유하는 단락이 여러 개면 유일하지 않음. **count 확인 선행 필수**. 불유일 시 위치 기반(rfind/index 앵커) 또는 `locate.py --tag hp:tc` 로 상위 셀 먼저 특정 후 내부 탐색.

## 10. 단일 빈 paragraph → 복수 paragraph 교체

`replace_cell.py` 대신 raw str.replace로 빈 paragraph 1개를 2개로 늘려야 할 때:

```python
# 원본: 빈 단락 1개 (paraPrIDRef="5"로 특정)
old = '<hp:p id="1000000010" paraPrIDRef="5" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:t/></hp:run></hp:p>'

# 교체: 2개 단락 (두 번째 id는 next_id.py로 확보)
new = (
    '<hp:p id="1000000010" paraPrIDRef="5" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
    '<hp:run charPrIDRef="0"><hp:t>첫 번째 내용</hp:t></hp:run></hp:p>'
    '<hp:p id="1000000099" paraPrIDRef="5" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
    '<hp:run charPrIDRef="0"><hp:t>두 번째 내용</hp:t></hp:run></hp:p>'
)

assert s.count(old) == 1
s = s.replace(old, new)
```

**주의**: 새 ID(`1000000099`)는 `next_id.py`로 충돌 없는 값 확보. 표 셀 내부라면 `replace_cell.py --content-file`로 처리하는 것이 더 안전 (linesegarray 자동 처리).

## 11. 스크립트 재실행 안전성 (idempotency)

`assert s.count(old) == N` 패턴은 재실행 시 AssertionError 발생 — 이미 채워진 셀에서 empty run 패턴 0개.

**옵션 A: skip 패턴** (이미 적용됨 → 스킵):

```python
count = s.count(old)
if count == 0:
    print(f"SKIP: already applied or pattern changed — {old!r}")
elif count == expected:
    s = s.replace(old, new)
else:
    raise AssertionError(f"unexpected count {count} (expected 0 or {expected})")
```

**옵션 B: 상태 기반 old 패턴** (재실행 시 현재 상태를 old로):

```python
# 첫 실행: empty → filled
old_empty = '<hp:run charPrIDRef="3"/>'
old_filled = '<hp:run charPrIDRef="3"><hp:t>값</hp:t></hp:run>'
assert s.count(old_empty) + s.count(old_filled) == 1  # 어느 상태든 정확히 1개
```

배치 처리 스크립트에서는 옵션 A를 기본으로 사용 — 부분 실패 후 재실행 가능.

## 12. linesegarray 스트립 타이밍

`<hp:linesegarray>` 제거는 **편집 완료 후 파일 전체에 한 번** 실행이 원칙:

```bash
# 편집 완료 후 pack → strip
python3 "$SKILL_DIR/scripts/office/pack.py" ./unpacked/ tmp.hwpx
python3 "$SKILL_DIR/scripts/strip_linesegarray.py" tmp.hwpx --output result.hwpx
python3 "$SKILL_DIR/scripts/validate.py" result.hwpx --baseline original.hwpx
```

셀 단위로 수동 제거하면 다른 셀의 stale lineseg가 남을 수 있음. `replace_cell.py` 사용 시에는 해당 셀만 자동 처리 — 다른 셀에 직접 str.replace 편집이 있다면 마지막에 `strip_linesegarray.py` 한 번 더 실행.

**strip은 idempotent** — 여러 번 실행해도 안전. `<hp:linesegarray>` 없는 문서에 실행해도 no-op.