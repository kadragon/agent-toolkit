---
name: repo-quiz
description: >-
  ALWAYS invoke when the user wants to test, build, or track their understanding of THIS
  repository through questions — an interactive quiz about the codebase's architecture,
  conventions, data flow, entry points, or gotchas, with progress that persists across
  sessions. Triggers: "quiz me on this repo", "test my understanding", "레포 퀴즈",
  "코드베이스 퀴즈 내줘", "이 repo 이해도 테스트", "오답노트 보여줘", "복습 문제",
  "내 XP/스트릭 보여줘", "onboard me with questions", "review what I got wrong".
  Runs a 5-question round by default (user can ask for more), grades via multiple choice,
  keeps an SM-2 spaced-repetition schedule, a wrong-answer note, and XP/level/streak in a
  gitignored .repo-quiz/ folder. NOT for generating docs or a written onboarding guide
  (that is a summary task, not a quiz) — and NOT for quizzing on general programming
  trivia unrelated to the current repo.
version: 1.0.0
allowed-tools: Bash AskUserQuestion Read Grep Glob Edit
---

# Repo Quiz

Turn the current repository into a spaced-repetition quiz. The user answers multiple-choice
questions drawn from the *actual code*, and their progress — what they've been asked, what
they got wrong, and a running XP/streak — persists in `.repo-quiz/` so understanding
compounds over sessions instead of resetting every time.

The point is **retrieval practice against ground truth**: every question must be answerable
by reading files in this repo, and every answer is checked against what the code actually
says — never against your own assumptions. A quiz that rewards plausible-but-wrong answers
teaches the wrong thing, so grounding each question in a file you've read is the whole game.

## The state manager does the bookkeeping

`scripts/quiz_state.py` owns everything that must be exact — SM-2 scheduling, XP, level,
streak, the question log, and the mistakes note. Resolve it relative to *this* SKILL.md
(its parent dir), and always pass `--repo` pointing at the repo being quizzed:

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python "$Q" --repo <repo-root> <subcommand> [flags]
```

Never do the date math or SM-2 arithmetic yourself — call the script. Its `--test` flag
self-checks the logic if you ever suspect it's misbehaving.

| Command | Use |
|---------|-----|
| `init` | First run: creates `.repo-quiz/` and adds it to `.gitignore`. Idempotent. |
| `status` | Dashboard JSON: xp, level, xp_to_next, streak, total_concepts, due_count, due[]. |
| `due --count N` | Concepts due for review today, most-overdue first (JSON). |
| `record --concept SLUG --correct true\|false [--title T] [--note N] [--session ID]` | Apply one answer: SM-2 + XP + streak + logs. Prints the new schedule/score. |

State written under `<repo-root>/.repo-quiz/` (gitignored — it's the user's personal
progress, not a team artifact):
- `progress.json` — xp, level, streak, and per-concept SM-2 schedule
- `history.jsonl` — append-only log, one line per question asked
- `mistakes.md` — human-readable wrong-answer notes, so the user can skim what tripped them up

### Concepts and slugs

SM-2 schedules *concepts*, not literal questions — so you can ask a fresh question about the
same idea each time it comes due. A concept is one checkable fact about the repo, keyed by a
stable kebab-case slug you assign and reuse:

- `auth-token-verify` — "where/how are auth tokens verified?"
- `version-bump-rule` — "what must change when you edit a plugin?"
- `hook-plugin-root-var` — "which env var locates the plugin root in a hook?"

Reuse the same slug whenever you quiz the same fact, so its schedule accumulates. Pick slugs
by what the fact *is*, not by the wording of one question.

## Running a round

### 1. Set up and read the state

```sh
python "$Q" --repo <repo-root> init      # first time only; harmless to repeat
python "$Q" --repo <repo-root> status
```

`status` tells you the streak, XP/level, and — crucially — which concepts are **due** for
review. Default round size is **5 questions**; honor any count the user asks for ("10문제",
"quiz me on 3 things").

### 2. Decide what to ask — due reviews first, then new ground

Fill the round in this order so spaced repetition actually works:

1. **Due concepts first.** For each concept from `due`, generate a *fresh* multiple-choice
   question testing that same fact. Re-read the relevant file so the question reflects the
   code as it is now, not as it was when first asked.
2. **New concepts for the remaining slots.** Explore parts of the repo the user hasn't been
   quizzed on. Start from the repo's own map — `AGENTS.md` / `README` / `docs/` / entry
   points / config — and pull one checkable fact per question. Prefer things that matter for
   working in the repo (architecture, invariants, conventions, where-does-X-live, gotchas)
   over trivia (exact line numbers, cosmetic naming).

If `status` shows this is a brand-new repo with no history, all 5 are new concepts.

**Ground every question in a file you actually read this session.** Before writing options,
open the source (Read/Grep/Glob) and confirm the correct answer there. The three distractors
should be *plausible* — real files, real patterns from this repo — not obviously silly, or
the question tests nothing.

### 3. Ask, one question at a time

Use `AskUserQuestion` per question (single-select). Keep the stem short and concrete; make
options parallel in form. Vary which position is correct.

```
[Q2/5]  In this repo, what must change whenever you edit a file under dev-tools/?
  A  Only dev-tools/.claude-plugin/plugin.json version
  B  Both .claude-plugin and .codex-plugin plugin.json versions   ← correct
  C  The root AGENTS.md version header
  D  Nothing — CI bumps it automatically
```

After each answer, immediately record it — don't batch, so a mid-round interruption still
saves progress:

```sh
python "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct true \
  --title "Version bump on dev-tools edit" --session <round-id>
```

On a **wrong** answer, pass a `--note` that will land in `mistakes.md`: state the correct
answer, *why*, and a file pointer — that note is what the user rereads later, so make it
teach. Then give a brief spoken correction before the next question.

```sh
python "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct false \
  --title "Version bump on dev-tools edit" \
  --note "Correct: **B**. Editing anything under dev-tools/ requires bumping BOTH dev-tools/.claude-plugin/plugin.json AND dev-tools/.codex-plugin/plugin.json (kept in sync). See AGENTS.md 'Golden Principles' #1 — CI blocks the merge otherwise." \
  --session <round-id>
```

Use one `--session` id for the whole round (a short label like `2026-07-16a`) so the history
groups cleanly.

### 4. Close the round

Read `status` again and give a short, upbeat recap — the gamification only motivates if the
user sees it:

- Score this round (e.g. "4/5")
- XP gained and current level (+ xp_to_next), and the streak ("🔥 3-day streak")
- What comes back for review and roughly when
- One-line pointer to `.repo-quiz/mistakes.md` if they missed anything

Keep it encouraging and specific. Missing a question is the mechanism, not a failure — it's
what schedules the concept to come back until it sticks.

## Difficulty

Let it ride on the SM-2 schedule rather than a manual dial. A concept the user keeps getting
right reappears less often (its interval grows); a missed one comes back tomorrow. If the
user explicitly wants harder questions, go deeper — ask *why* a design choice was made or how
two parts interact, rather than *where* something lives — but keep every answer checkable
against the code.

## Guardrails

- **Never invent facts.** If you haven't read the file that settles a question this session,
  don't ask it. A quiz graded against a guess is worse than no quiz.
- **Stay in this repo.** Questions are about the code at `<repo-root>`, not general trivia.
- **The script is the single writer of state.** Don't hand-edit `progress.json` or
  `history.jsonl`. You may append richer prose to `mistakes.md` with `Edit` if the user wants
  fuller notes, but routine wrong-answer capture goes through `record --note`.
- **Respect the count.** 5 by default; more only if asked.
