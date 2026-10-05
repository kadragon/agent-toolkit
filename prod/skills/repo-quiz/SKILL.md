---
name: repo-quiz
description: >-
  Interactive spaced-repetition quiz on THIS repository — architecture,
  conventions, data flow, gotchas — plus the wrong-answer log and XP/streak
  progress persisted in `.repo-quiz/`. NOT for writing docs or an onboarding
  guide, NOT for general programming trivia.
version: 1.1.3
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

## Language

Ask in **Korean**. Everything you present to the user — question stems, `mc` options,
free-recall prompts, the reveal, and the post-answer explanation — is user-facing text, so
write it in Korean. Keep code, identifiers, file paths, and quoted snippets verbatim in their
original language (English): a `fill-blank` cloze or a `code-trace` still shows the real code
untranslated; only the surrounding prose is Korean. Internal state stays English — the
`--concept` concept slug, the `--type` question-type slug (`mc`/`code-trace`/…, never a concept
slug), and the other `record`/`config` flag values are never shown to the user. The one
exception is the human-readable text you pass to `--title` and `--note`: it lands in
`mistakes.md`, which the user rereads, so write it in Korean too (keeping any code, paths, and
identifiers inside it verbatim). The illustrative examples below are written in Korean for this
reason; mirror that.

Design credits (CodebaseQA, py-fsrs, Duolingo, Understand-Anything, retrieval-practice literature): `references/credits.md`.

## The state manager does the bookkeeping

`scripts/quiz_state.py` owns everything that must be exact — scheduling (FSRS when
installed, SM-2 fallback otherwise), XP, level, streak (with streak-freeze), achievements,
persona/goal config, the question log, and the mistakes note. Resolve it relative to *this*
SKILL.md (its parent dir), and always pass `--repo` pointing at the repo being quizzed:

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> <subcommand> [flags]
```

Use **`python3`**, not bare `python` (many systems, current macOS included, ship only
`python3`). **Each tool call runs in a fresh shell**: re-capture `Q` at the top of *every*
shell block that calls the script (capture-before-use).

Never do the date math or scheduler arithmetic yourself — call the script (`--test`
self-checks it). FSRS is used when `py-fsrs` is importable; otherwise (or on a review error)
the script falls back to SM-2 for that review.

Subcommands: `init` (first run, idempotent) · `status` (dashboard JSON incl. due[], config, achievements, scheduler, fsrs flags) · `due --count N` · `record --concept SLUG --correct true|false [--grade again|hard|good|easy] [--type TYPE] [--title T] [--note N] [--session ID]` · `config [--get] [--set-persona junior|mid|senior] [--set-daily-goal N] [--seen-fsrs-notice]`. Full table, flag semantics, state files under `.repo-quiz/` (gitignored, personal progress), recording examples, difficulty, and gamification rules: `references/state-reference.md`.

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

`record --type <slug>` (default `mc`) feeds both the schedule and XP, so pass the type you
actually asked — never label a free-recall question `mc` for convenience.

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

**Offer the FSRS upgrade once.** If `status` shows `fsrs_available: false` and `fsrs_notice_seen: false`, follow `references/fsrs-offer.md` — tell the user once, ask before installing (installing is their call), then `config --seen-fsrs-notice` whether they install or decline. If `fsrs_available` is `true`, skip it.

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

Hold the drafted set as a scratch list (stem / type / options / correct / concept-slug) — don't
persist it; `record` in step 3 captures each result as it's answered.

### 3. Ask the pre-built questions, one at a time

Now that the set is ready, present them sequentially. Use `AskUserQuestion` for `mc`
(single-select); for `bug-hunt`/`code-trace`/`why`, ask directly and let the user respond in
free text, then grade yourself against the grounded answer; for `free-recall`, withhold any
options, let the user answer unaided, reveal the grounded answer, and ask the user to
self-rate 1–4 (map 1→again, 2→hard, 3→good, 4→easy). Keep the stem short and concrete; for
`mc`, make options parallel in form and vary which position is correct.

```
[Q2/5]  이 레포에서 dev/ 아래 파일을 수정하면 반드시 무엇을 함께 바꿔야 하나요?
  A  dev/.claude-plugin/plugin.json 버전만
  B  .claude-plugin과 .codex-plugin의 plugin.json 버전 둘 다   ← correct
  C  루트 AGENTS.md의 버전 헤더
  D  아무것도 — CI가 자동으로 올려줌
```

After each answer, record it immediately — don't batch, so an interruption still saves progress:

```sh
Q=<dir-of-this-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> record \
  --concept version-bump-rule --correct true --type mc \
  --title "dev 수정 시 버전 범프" --session <round-id>
```

On a **wrong** answer, pass a `--note` (lands in `mistakes.md`): the correct answer, *why*, and a
file pointer — that note is what the user rereads, so make it teach. For self-graded free-recall,
pass the user's 1–4 rating as `--grade` and still pass `--correct` (`true` unless they say they got
it flatly wrong). Examples of both: `references/state-reference.md` § "Recording examples". Use
one `--session` id for the whole round (e.g. `2026-07-16a`) so the history groups cleanly.

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

Example spoken follow-up: `references/state-reference.md` § "Explanation example".

Deliver this out loud between questions; the wrong-answer `--note` is the *persisted* short form for
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
