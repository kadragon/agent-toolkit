---
name: repo-quiz
description: >-
  ALWAYS invoke when the user wants to test, build, or track their understanding of THIS
  repository through questions — an interactive quiz about the codebase's architecture,
  conventions, data flow, entry points, or gotchas, with progress that persists across
  sessions. Triggers: "quiz me on this repo", "test my understanding", "레포 퀴즈",
  "코드베이스 퀴즈 내줘", "이 repo 이해도 테스트", "오답노트 보여줘", "복습 문제",
  "내 XP/스트릭 보여줘", "onboard me with questions", "review what I got wrong".
  Runs a 5-question round by default (user can ask for more), mixing multiple-choice,
  bug-hunt, code-trace, fill-in-the-blank, free-recall, and elaborative-why questions,
  scheduled via FSRS (SM-2 fallback), with XP/level/streak/achievements in a gitignored
  .repo-quiz/ folder.
  NOT for generating docs or a written onboarding guide (that is a summary task, not a
  quiz) — and NOT for quizzing on general programming trivia unrelated to the current repo.
version: 1.1.0
allowed-tools: Bash AskUserQuestion Read Grep Glob Edit
---

# Repo Quiz

Turn the current repository into a spaced-repetition quiz. The user answers questions drawn
from the *actual code*, and their progress — what they've been asked, what they got wrong,
and a running XP/streak/achievements — persists in `.repo-quiz/` so understanding compounds
over sessions instead of resetting every time.

The point is **retrieval practice against ground truth**: every question must be answerable
by reading files in this repo, and every answer is checked against what the code actually
says — never against your own assumptions. A quiz that rewards plausible-but-wrong answers
teaches the wrong thing, so grounding each question in a file you've read is the whole game.

## Credits

Design in this skill borrows from, and credits:

- **[CodebaseQA](https://github.com/context-labs/codebase-qa)** — the multi-type question
  bank (bug hunt, code trace, cloze, free recall, "why") and the gamification-plus-retrieval
  framing generally.
- **[open-spaced-repetition/py-fsrs](https://github.com/open-spaced-repetition/py-fsrs)** —
  the FSRS scheduler (Free Spaced Repetition Scheduler), used in place of hand-rolled SM-2
  when the package is installed.
- **Duolingo's gamification case study** — streak-freeze, type-weighted XP, and tiered
  achievements as motivation mechanics.
- **[Understand-Anything](https://github.com/understand-anything/understand-anything)** —
  dependency-ordered codebase tours (teach boundaries/entry points before their dependents)
  and persona-scaled depth (junior/mid/senior).
- **Retrieval-practice literature** (e.g. Roediger & Karpicke on the testing effect) — free
  recall produces stronger retention than recognition (multiple-choice), which is why
  free-recall questions are weighted higher and preferred as a concept matures.

## The state manager does the bookkeeping

`scripts/quiz_state.py` owns everything that must be exact — scheduling (FSRS when
installed, SM-2 fallback otherwise), XP, level, streak (with streak-freeze), achievements,
persona/goal config, the question log, and the mistakes note. Resolve it relative to *this*
SKILL.md (its parent dir), and always pass `--repo` pointing at the repo being quizzed:

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> <subcommand> [flags]
```

Use **`python3`**, not bare `python` — many systems (current macOS included) ship only
`python3`, and `python` there exits "command not found" before the script ever runs. Also
note that **each tool call runs in a fresh shell**, so a `Q=...` assignment does not persist
across blocks: re-capture `Q` (or inline the absolute path) at the top of *every* shell block
that calls the script — the `python3 "$Q" …` lines below assume `Q` is defined in that same
block. This is the repo's capture-before-use convention.

Never do the date math or scheduler arithmetic yourself — call the script. Its `--test` flag
self-checks the logic if you ever suspect it's misbehaving. FSRS is used automatically when
`py-fsrs` is importable; if it isn't (or a review call errors for any reason), the script
falls back to SM-2 for that review — scheduling still works, just less optimally. When
`py-fsrs` is missing entirely, surface the one-time install offer described in *Running a
round → step 1* so the user can opt into the better scheduler.

| Command | Use |
|---------|-----|
| `init` | First run: creates `.repo-quiz/` and adds it to `.gitignore`. Idempotent. |
| `status` | Dashboard JSON: xp, level, xp_to_next, streak, freezes, total_concepts, due_count, due[], `config` (persona, daily_goal), `achievements`, `scheduler` (`fsrs`\|`sm2`), `fsrs_available`, `fsrs_notice_seen`. |
| `due --count N` | Concepts due for review today, most-overdue first (JSON). |
| `record --concept SLUG --correct true\|false [--grade again\|hard\|good\|easy] [--type TYPE] [--title T] [--note N] [--session ID]` | Apply one answer: schedule + XP + streak + achievements + logs. Prints the new schedule/score. |
| `config [--get] [--set-persona junior\|mid\|senior] [--set-daily-goal N] [--seen-fsrs-notice]` | Read or update persona/daily goal, or mark the one-time FSRS install notice as shown. With no flags, prints current config. |

`--type` is the question-type slug (see below); defaults to `mc` if omitted. `--grade`
overrides the correct/wrong → schedule-quality mapping for self-graded free-recall answers
(the user picks 1–4 after seeing the revealed answer); omit it for auto-graded types
(MC/fill-blank), where correct → `good` and wrong → `again` are inferred automatically.

State written under `<repo-root>/.repo-quiz/` (gitignored — it's the user's personal
progress, not a team artifact):
- `progress.json` — xp, level, streak, freezes, achievements, config, and per-concept
  schedule (FSRS fields or SM-2 `ef`/`interval`/`reps`, whichever scheduler produced it)
- `history.jsonl` — append-only log, one line per question asked (includes `type`, `grade`)
- `mistakes.md` — human-readable wrong-answer notes, so the user can skim what tripped them up

### Concepts and slugs

The scheduler tracks *concepts*, not literal questions — so you can ask a fresh question about
the same idea each time it comes due. A concept is one checkable fact about the repo, keyed by
a stable kebab-case slug you assign and reuse:

- `auth-token-verify` — "where/how are auth tokens verified?"
- `version-bump-rule` — "what must change when you edit a plugin?"
- `hook-plugin-root-var` — "which env var locates the plugin root in a hook?"

Reuse the same slug whenever you quiz the same fact, so its schedule accumulates. Pick slugs
by what the fact *is*, not by the wording of one question.

## Question types

Vary the type per question — mixing types (CodebaseQA) exercises different depths of
understanding than multiple-choice alone, and free recall in particular produces stronger
retention than recognition-based formats (retrieval-practice literature: the "testing
effect"). Every type still requires the grounding rule below — no exceptions.

| Type (`--type`) | What it asks | When to use |
|---|---|---|
| `mc` | Multiple-choice: stem + 4 options, one correct. | Default for new/unfamiliar concepts; cheapest to answer, good for first exposure. |
| `bug-hunt` | Show a snippet with one planted bug (subtly wrong vs. the real file); user spots/names it. | Once a concept has been seen once — tests whether the user notices deviations, not just recognizes text. |
| `code-trace` | Show real code; ask what it returns/prints/does for a given input. | Concepts involving control flow, data transforms, or non-obvious behavior. |
| `fill-blank` | Cloze: a key line/identifier from the real file blanked out. | Naming/convention facts (function names, config keys, env vars). |
| `free-recall` | No options offered — ask the open question, let the user answer unaided, *then* reveal the grounded answer and have the user self-rate 1–4 (feeds `--grade again|hard|good|easy`). | Concepts the user has already gotten right at least once via a recognition-based type — this is the highest-demand type, so prefer it as a concept matures. |
| `why` | Elaborative: "why is it this way?" — asks for the *reasoning*, not just the fact. | Design decisions and invariants (e.g. why plugin.json bumps both `.claude-plugin` and `.codex-plugin`) — pairs well with senior-persona depth. |

`record --type <slug>` writes the type into `history.jsonl`; if omitted, it defaults to `mc`.
Grading feeds directly into both the schedule and XP (see below), so pick the type that
actually matches what you asked — don't label a free-recall question `mc` just because it's
convenient.

## Running a round

### 1. Set up and read the state

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> init      # first time only; harmless to repeat
python3 "$Q" --repo <repo-root> status
```

`status` tells you the streak (and freezes), XP/level, config (persona/daily_goal),
achievements, and — crucially — which concepts are **due** for review. Default round size is
**`daily_goal` from config** (5 by default); honor any count the user asks for ("10문제",
"quiz me on 3 things") and honor an explicit `config --set-daily-goal N` if the user wants a
different standing default.

**Offer the FSRS upgrade once.** `status` also reports `fsrs_available`. If it's `false` and
`fsrs_notice_seen` is `false`, the script is running on the SM-2 fallback — tell the user, one
time, that installing FSRS gives measurably better scheduling (fewer reviews for the same
retention) and offer to install it before the round:

> 📈 지금은 SM-2 스케줄러로 진행 중입니다. FSRS(`py-fsrs`)를 설치하면 같은 암기 효과에
> 리뷰 횟수가 줄어듭니다. 설치할까요? — `python3 -m pip install --user fsrs`

Install into **the same interpreter that runs the quiz** so `import fsrs` will resolve —
derive it from the `python`/`python3` you invoke `$Q` with (e.g. `<that-python> -m pip install
--user fsrs`; on an externally-managed environment add `--break-system-packages`, or use the
user's venv/`uv pip install fsrs`). This needs the user's go-ahead — installing a package is
their call, so ask, don't run it silently. After they install, no code change is needed: the
next `status`/`record` picks FSRS up automatically. Whether they install or decline, mark the
notice so you don't nag next time, then proceed with the round either way:

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> config --seen-fsrs-notice
```

If `fsrs_available` is already `true`, skip all of this — FSRS is in use.

### 2. Build the whole round up front — all N questions before asking any

Do **all** the exploration and question-writing first, in one batch, and only then start
asking. Don't interleave "explore → ask → explore → ask": that stalls the user between every
question while you go read another file. Read what you need, draft the full set of N
questions (stem, type, options-if-any, correct answer, concept slug for each), *then* move to
step 3 and fire them one at a time with no research gaps in between.

Fill the round in this order so spaced repetition actually works:

1. **Due concepts first.** For each concept from `due`, generate a *fresh* question testing
   that same fact — prefer a higher-demand type (bug-hunt/code-trace/why/free-recall) over
   plain MC as the concept matures, since it's already been seen before. Re-read the relevant
   file so the question reflects the code as it is now, not as it was when first asked.
2. **New concepts for the remaining slots.** Explore parts of the repo the user hasn't been
   quizzed on. Start from the repo's own map — `AGENTS.md` / `README` / `docs/` / entry
   points / config — and pull one checkable fact per question. **Sequence new concepts
   dependency-first, not session-read order**: ask about foundational modules, entry points,
   and shared config *before* the things that depend on them (teach the boundary before the
   leaf implementation that calls it) — this is a dependency-ordered tour, borrowed from
   Understand-Anything, and it makes later questions build on established context instead of
   arriving cold. Prefer things that matter for working in the repo (architecture,
   invariants, conventions, where-does-X-live, gotchas) over trivia (exact line numbers,
   cosmetic naming).

If `status` shows this is a brand-new repo with no history, all N are new concepts, so the
dependency-ordering rule governs the whole round.

**Ground every question in a file you actually read this session.** Before writing a
question, open the source (Read/Grep/Glob) and confirm the correct answer there. For `mc`,
the three distractors should be *plausible* — real files, real patterns from this repo — not
obviously silly, or the question tests nothing. For `bug-hunt`, plant a bug that's a
realistic mistake (swapped condition, off-by-one, wrong variable) — not something silly.

#### Scale depth to persona

Read `config.persona` from `status` (default `mid`) and scale question depth accordingly:

- **junior** — concrete, function-level: "what does this function return?", "where is X
  defined?" Stick mostly to `mc`/`fill-blank`/`code-trace`.
- **mid** (default) — as above, plus some cross-file interaction and "why does this exist"
  at a local scope.
- **senior** — architectural trade-offs and invariants: "why is the script the single writer
  of state?", "what would break if two plugins bumped independently?" Lean on `why` and
  free-recall more heavily.

If the user hasn't set a persona and their answers suggest a mismatch (breezing through
junior-level questions, or struggling badly with senior-level ones), suggest
`config --set-persona <level>` rather than silently guessing every round.

Hold the drafted set in your working context (a short scratch list of stem / type / options /
correct / concept-slug per question is enough) — you don't persist it; `record` in step 3
captures each result as it's answered.

### 3. Ask the pre-built questions, one at a time

Now that the set is ready, present them sequentially. Use `AskUserQuestion` for `mc`
(single-select); for `bug-hunt`/`code-trace`/`why`, ask directly and let the user respond in
free text, then grade yourself against the grounded answer; for `free-recall`, withhold any
options, let the user answer unaided, reveal the grounded answer, and ask the user to
self-rate 1–4 (map 1→again, 2→hard, 3→good, 4→easy). Keep the stem short and concrete; for
`mc`, make options parallel in form and vary which position is correct.

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
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct true --type mc \
  --title "Version bump on dev-tools edit" --session <round-id>
```

On a **wrong** answer, pass a `--note` that will land in `mistakes.md`: state the correct
answer, *why*, and a file pointer — that note is what the user rereads later, so make it
teach.

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct false --type mc \
  --title "Version bump on dev-tools edit" \
  --note "Correct: **B**. Editing anything under dev-tools/ requires bumping BOTH dev-tools/.claude-plugin/plugin.json AND dev-tools/.codex-plugin/plugin.json (kept in sync). See AGENTS.md 'Golden Principles' #1 — CI blocks the merge otherwise." \
  --session <round-id>
```

For a self-graded free-recall question, pass the user's self-rating as `--grade` (still pass
`--correct` too — `true` unless the user says they got it flatly wrong):

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct true --type free-recall --grade hard \
  --title "Version bump on dev-tools edit" --session <round-id>
```

Use one `--session` id for the whole round (a short label like `2026-07-16a`) so the history
groups cleanly.

#### Give a real explanation after every answer — right *or* wrong

Don't stop at "Correct, it's B." After **each** question spend two or three sentences
teaching, so a right answer still adds something and a wrong one doesn't just sting. Aim for:

1. **The grounded why** — restate the correct answer and *why the code is that way*, with the
   file/line pointer you verified it against. This part stays strictly inside this repo (see
   Guardrails) — it's the thing you're grading.
2. **A widen-the-lens tip** — one concrete pointer to something worth knowing beyond the bare
   fact: a related file or pattern elsewhere in the repo, the doc/ADR that explains the
   decision, *why* the convention exists industry-wide, a common pitfall it prevents, or how
   current tooling/practice handles the same problem. This is where a recent-trend or
   best-practice note belongs.

Keep the tip **honest and separable** from the graded fact. If it's general knowledge rather
than something this repo settles, mark it as such ("Broader context: …") so the user can tell
repo-ground-truth from your added color — and if you're not sure a claim is current, say so
rather than asserting it. One good pointer beats a paragraph of filler; don't pad.

Example spoken follow-up (correct answer):

> ✅ Right — **B**. Both `plugin.json` files bump together because the marketplace ships the
> skill to Claude Code *and* Codex from one release, so a drifted version would desync them
> (`AGENTS.md` Golden Principle #1; CI's `harness-check.yml` enforces it).
> **Broader context:** this is the standard "single source of truth for release version"
> practice — monorepos with multiple publish targets (npm workspaces, Cargo workspaces) hit
> the same class of bug, which is why tools like Changesets exist to keep sibling versions in
> lockstep. Worth a look if you ever wire up automated version bumps here.

Deliver this out loud between questions; the `--note` above is the *persisted* short form for
`mistakes.md`, the spoken version is the fuller teach. If the extra tip is genuinely useful to
reread later, fold a one-line version of it into `--note` too.

### 4. Close the round

Read `status` again and give a short, upbeat recap — the gamification only motivates if the
user sees it:

- Score this round (e.g. "4/5")
- XP gained and current level (+ xp_to_next), and the streak ("🔥 3-day streak", noting if a
  freeze was consumed to preserve it)
- Any newly unlocked achievements (`status.achievements` — call out ones not mentioned last
  time)
- What comes back for review and roughly when
- One-line pointer to `.repo-quiz/mistakes.md` if they missed anything

Keep it encouraging and specific. Missing a question is the mechanism, not a failure — it's
what schedules the concept to come back until it sticks.

## Difficulty

Let it ride on the schedule rather than a manual dial. A concept the user keeps getting right
reappears less often (its interval grows under FSRS or SM-2 alike); a missed one comes back
soon. If the user explicitly wants harder questions, go deeper — ask *why* a design choice was
made or how two parts interact, and prefer `why`/free-recall — but keep every answer checkable
against the code. `config.persona` (see above) is the standing version of "make it harder":
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

## Guardrails

- **Never invent facts.** If you haven't read the file that settles a question this session,
  don't ask it. A quiz graded against a guess is worse than no quiz.
- **Stay in this repo — for the graded fact.** Questions and their correct answers are about
  the code at `<repo-root>`, not general trivia. The post-answer *widen-the-lens tip* may
  reach beyond the repo (industry practice, recent tooling/trends), but keep it clearly
  labeled as broader context and honest about certainty — never let outside color get graded
  or blur into the repo ground truth.
- **The script is the single writer of state.** Don't hand-edit `progress.json` or
  `history.jsonl`. You may append richer prose to `mistakes.md` with `Edit` if the user wants
  fuller notes, but routine wrong-answer capture goes through `record --note`.
- **Respect the count.** `daily_goal` (5 by default) unless the user asks for more.
