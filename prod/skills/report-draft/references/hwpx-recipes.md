# 보고서 hwpx 편집 레시피

prod:hwpx 스킬의 Workflow 2(수정)·5(참조 기반 생성) 위에서 쓰는 보고서 전용 조각이다. 일반 규칙(lineseg 제거, validate, 한글 열기 확인)은 prod:hwpx를 따른다. Call the Skill tool with "prod:hwpx" for document operations below. Resolve its scripts from the loaded hwpx SKILL.md; report-draft makes no assumption about its installation directory.

## 1. 수정 대상 파악

```bash
SKILL_DIR="<absolute parent directory of the loaded report-draft SKILL.md>"
LINT="$SKILL_DIR/scripts/lint_report.py"
[[ -r "$LINT" ]] || { echo "Bundled report linter unavailable: $LINT" >&2; exit 1; }
```

Call the Skill tool with "prod:hwpx" to analyze the original via Workflow 5 (`build.py analyze`).

- 본문 문단은 `" ○ "` 런(charPr 보통체) + 내용 런 여러 개로 나뉜다. 한 줄에 맞추려고 자간·장평을 줄인 charPr이 섞여 있다(analyze 출력의 `spacing=`·`ratio=`).
- 장 제목(Ⅰ~Ⅴ)은 1행 3열 표다. 표 안 텍스트는 건드리지 않는다.
- `□` 소제목은 기존 번호 소제목(`1. …`)과 같은 paraPr·charPr을 쓴다.

## 2. 볼드 글자 모양 추가

본문 보통체와 볼드체가 이미 짝으로 있으면(예: 15pt 보통 / 15pt 볼드) 볼드체 ID를 그대로 쓴다. 압축 charPr(자간·장평 조정)에는 짝이 없으므로 복제한다.

1. `header.xml`에서 `<hh:charPr id="N" …>…</hh:charPr>`를 문자열로 잘라 낸다.
2. `id`를 새 번호(현재 최대 ID + 1)로 바꾸고 `<hh:underline ` 앞에 `<hh:bold/>`를 넣는다.
3. `</hh:charProperties>` 앞에 붙이고 `<hh:charProperties itemCnt="…">`를 개수에 맞게 올린다.
4. XML 파서로 다시 직렬화하지 않는다(문자열 편집만).

## 3. 런 분할로 부분 볼드

```python
def R(cp, t):
    return '<hp:run charPrIDRef="%s"><hp:t>%s</hp:t></hp:run>' % (cp, t)

rep(R(36, "전임교원 190명(1차 149명, 2차 41명)에게"),
    R(51, "전임교원 190명") + R(36, "(1차 149명, 2차 41명)에게"))
```

`rep()`은 치환 전에 `assert s.count(old) == n`을 건다. 옛 런 시퀀스 전체를 old로 잡아야 부분 문자열 충돌이 없다.

## 4. 문단 추가

`□ 현황` 같은 새 문단은 이웃 문단의 여는 태그를 복사해 앵커 문단 앞·뒤에 끼운다. `<hp:linesegarray>`는 넣지 않는다.

```python
P = '<hp:p id="2147483648" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{runs}</hp:p>'
i = s.rfind("<hp:p ", 0, s.index(anchor_run))   # 앵커 문단 시작
s = s[:i] + P.format(pp="52", runs=R(39, "□ 현황")) + s[i:]
```

## 5. 저장 순서

1. Call the Skill tool with "prod:hwpx" for Workflow 2: copy the original to scratch, unpack, apply the approved edits with replacement assertions, and strip stale lineseg caches with `table.py strip-lineseg` before packing.
2. Within the hwpx workflow, pack and run Workflow 4 validation with the original as `--baseline`; require VALID.
3. Run report-draft lint on the result; resolve the linter again in this shell block and require exit 0:

```bash
SKILL_DIR="<absolute parent directory of the loaded report-draft SKILL.md>"
LINT="$SKILL_DIR/scripts/lint_report.py"
[[ -r "$LINT" ]] || { echo "Bundled report linter unavailable: $LINT" >&2; exit 1; }
python3 "$LINT" <결과.hwpx>
```

4. 새 파일명 `<원본명>_수정.hwpx`로 복사, md5 대조. 같은 이름이 있으면 멈추고 묻는다.
5. 한글로 열어 창 제목이 파일명인지 확인(`빈 문서`면 로드 실패).

원본은 덮어쓰지 않는다.
