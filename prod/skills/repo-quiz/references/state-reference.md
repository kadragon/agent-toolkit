# State Manager Reference

Moved out of SKILL.md. `$Q` below is `<dir-of-the-repo-quiz-SKILL.md>/scripts/quiz_state.py`; re-capture it at the top of every shell block (capture-before-use), and always pass `--repo`.

## Flags

`--type` is the question-type slug (SKILL.md § "Question types"); defaults to `mc` if omitted. `--grade`
overrides the correct/wrong → schedule-quality mapping for self-graded free-recall answers
(the user picks 1–4 after seeing the revealed answer); omit it for auto-graded types
(MC/fill-blank), where correct → `good` and wrong → `again` are inferred automatically.

State written under `<repo-root>/.repo-quiz/` (gitignored — it's the user's personal
progress, not a team artifact):
- `progress.json` — xp, level, streak, freezes, achievements, config, and per-concept
  schedule (FSRS fields or SM-2 `ef`/`interval`/`reps`, whichever scheduler produced it)
- `history.jsonl` — append-only log, one line per question asked (includes `type`, `grade`)
- `mistakes.md` — human-readable wrong-answer notes, so the user can skim what tripped them up

## Recording examples

Wrong answer, with a teaching `--note`:

```sh
Q=<dir-of-the-repo-quiz-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct false --type mc \
  --title "dev 수정 시 버전 범프" \
  --note "정답: **B**. dev/ 아래 파일을 수정하면 dev/.claude-plugin/plugin.json 과 dev/.codex-plugin/plugin.json 버전을 **둘 다** 올려야 합니다(동기화 유지). AGENTS.md 'Golden Principles' #1 참고 — 안 그러면 CI가 머지를 막습니다." \
  --session <round-id>
```

Self-graded free-recall:

```sh
Q=<dir-of-the-repo-quiz-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct true --type free-recall --grade hard \
  --title "dev 수정 시 버전 범프" --session <round-id>
```

## Difficulty

Let it ride on the schedule rather than a manual dial. A concept the user keeps getting right
reappears less often (its interval grows under FSRS or SM-2 alike); a missed one comes back
soon. If the user explicitly wants harder questions, go deeper — ask *why* a design choice was
made or how two parts interact, and prefer `why`/free-recall — but keep every answer checkable
against the code. `config.persona` (SKILL.md § "Scale depth to persona") is the standing version of "make it harder":
set it once instead of re-asking every round.

## Gamification

XP (type-weighted), level, streak-freeze and achievements are computed by the script; read
them from `status` and call out a newly unlocked achievement in the round recap.

## Explanation example

Spoken follow-up after a correct answer (SKILL.md step 3):

> ✅ 정답 — **B**. `plugin.json` 두 파일이 함께 올라가는 이유는, 마켓플레이스가 하나의
> 릴리스로 스킬을 Claude Code *와* Codex 양쪽에 배포하기 때문입니다. 버전이 어긋나면 둘이
> desync되죠 (`AGENTS.md` Golden Principle #1; CI의 `harness-check.yml`가 강제).
> **Broader context:** 이건 "릴리스 버전의 단일 진실 공급원(single source of truth)"이라는
> 표준 관행입니다 — 배포 타깃이 여럿인 모노레포(npm workspaces, Cargo workspaces)도 같은
> 부류의 버그를 겪고, 그래서 Changesets 같은 도구가 형제 버전을 lockstep으로 유지합니다.
> 나중에 자동 버전 범프를 붙일 일이 있으면 한 번 볼 만합니다.
