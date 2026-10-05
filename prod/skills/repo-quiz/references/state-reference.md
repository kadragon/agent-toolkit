# State Manager Reference

Moved out of SKILL.md. `$Q` below is `<dir-of-the-repo-quiz-SKILL.md>/scripts/quiz_state.py`; re-capture it at the top of every shell block (capture-before-use), and always pass `--repo`.

## Commands

| Command | Use |
|---------|-----|
| `init` | First run: creates `.repo-quiz/` and adds it to `.gitignore`. Idempotent. |
| `status` | Dashboard JSON: xp, level, xp_to_next, streak, freezes, total_concepts, due_count, due[], `config` (persona, daily_goal), `achievements`, `scheduler` (`fsrs`\|`sm2`), `fsrs_available`, `fsrs_notice_seen`. |
| `due --count N` | Concepts due for review today, most-overdue first (JSON). |
| `record --concept SLUG --correct true\|false [--grade again\|hard\|good\|easy] [--type TYPE] [--title T] [--note N] [--session ID]` | Apply one answer: schedule + XP + streak + achievements + logs. Prints the new schedule/score. |
| `config [--get] [--set-persona junior\|mid\|senior] [--set-daily-goal N] [--seen-fsrs-notice]` | Read or update persona/daily goal, or mark the one-time FSRS install notice as shown. With no flags, prints current config. |

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

On a **wrong** answer, pass a `--note` that will land in `mistakes.md`: state the correct
answer, *why*, and a file pointer — that note is what the user rereads later, so make it
teach.

```sh
Q=<dir-of-the-repo-quiz-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct false --type mc \
  --title "dev 수정 시 버전 범프" \
  --note "정답: **B**. dev/ 아래 파일을 수정하면 dev/.claude-plugin/plugin.json 과 dev/.codex-plugin/plugin.json 버전을 **둘 다** 올려야 합니다(동기화 유지). AGENTS.md 'Golden Principles' #1 참고 — 안 그러면 CI가 머지를 막습니다." \
  --session <round-id>
```

For a self-graded free-recall question, pass the user's self-rating as `--grade` (still pass
`--correct` too — `true` unless the user says they got it flatly wrong):

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

- **Type-weighted XP.** Correct answers pay more for higher-demand types, so grinding easy MC
  yields little: `mc`=1.0×, `fill-blank`=1.2×, `code-trace`/`bug-hunt`/`why`=1.5×,
  `free-recall`=2.0× (× 10 XP, rounded). Wrong answers always pay a flat 3 XP
  (participation credit). Level = 1 + xp // 100. (Duolingo gamification case study.)
- **Streak-freeze.** The user starts with 1 freeze. Missing exactly one day auto-consumes a
  freeze and preserves the streak instead of resetting it; missing more than one day resets it
  regardless. `status.freezes` shows the remaining count.
- **Achievements.** Modest, difficulty-tiered milestones tracked in `status.achievements`
  (e.g. `first-correct`, `first-bug-hunt`, `streak-3`/`streak-7`/`streak-30`). Call out a new
  one in the round recap — that's the whole point of tracking it.

## Explanation example

Spoken follow-up after a correct answer (SKILL.md step 3):

> ✅ 정답 — **B**. `plugin.json` 두 파일이 함께 올라가는 이유는, 마켓플레이스가 하나의
> 릴리스로 스킬을 Claude Code *와* Codex 양쪽에 배포하기 때문입니다. 버전이 어긋나면 둘이
> desync되죠 (`AGENTS.md` Golden Principle #1; CI의 `harness-check.yml`가 강제).
> **Broader context:** 이건 "릴리스 버전의 단일 진실 공급원(single source of truth)"이라는
> 표준 관행입니다 — 배포 타깃이 여럿인 모노레포(npm workspaces, Cargo workspaces)도 같은
> 부류의 버그를 겪고, 그래서 Changesets 같은 도구가 형제 버전을 lockstep으로 유지합니다.
> 나중에 자동 버전 범프를 붙일 일이 있으면 한 번 볼 만합니다.
