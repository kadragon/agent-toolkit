---
name: task-grill
description: >-
  Resolve material ambiguity before a spec, tickets, or a Sprint Contract by
  interviewing the user one question at a time, each with a recommended answer +
  rationale. Callable from other skills via `Skill(dev:task-grill)`. Not for
  facts discoverable from the repo — look those up instead of asking.
version: 1.1.1
---

# Grill

> Inspired by mattpocock/skills (https://github.com/mattpocock/skills) — adapted for this repo's markdown-only backlog (no issue tracker, no CONTEXT.md/ADR pipeline).

Formalizes this repo's existing "Grill" hard-stop convention (`~/.claude/CLAUDE.md`) into a
reusable skill: **material ambiguity affecting scope, irreversible effects, external
communication, or expected output → grill, don't guess.** Unlike mattpocock's `grilling`+`domain-modeling` pair, this skill does not
produce a separate `CONTEXT.md` or ADR artifact — this repo has no such convention. Its output
feeds directly into whichever document is being built next: a Sprint Contract
(`docs/eval-criteria.md` template) or a `task-spec` document.

## When to use

Use this skill — whether fired directly, or by `task-new`/`task-spec` calling the Skill tool
with "dev:task-grill" — only when there is **genuine, non-trivial ambiguity** — not to rubber-stamp already-clear scope.
If the answer is discoverable by reading a file, running a command, or checking a manifest,
look it up instead of asking.

## Rules

1. **One question at a time.** Never batch multiple open questions into a single message —
   the user can't hold five decisions in flight at once.
2. **Every question carries a recommended answer + rationale.** Format:
   ```
   Q: <question>
   Recommended: <answer> — <one-line rationale>
   ```
   This lets the user answer with a single "yes" / "그렇게 해" instead of composing from scratch.
3. **Look it up before asking.** If a fact is discoverable from the repo (code, config,
   `git log`, existing docs) or environment (installed tools, running services), read it —
   do not ask the user to restate something you can verify yourself.
4. **Never act until the user confirms shared understanding.** Do not start implementing,
   writing a spec, or writing tickets mid-interview. The interview ends when the user has
   answered every open question, or declared the question itself irrelevant — not merely
   deferred it back to you. "알아서 해줘", "좋아 보여", or silence do **not** close the
   interview — none of them confirms a specific answer to the open question on the table.
   Re-ask **one** narrower version of the question; if that reply still pins down no choice,
   adopt the stated `Recommended:` answer, announce it as an assumption, and move on.
   **Non-interactive run** (no live user reachable — see `dev:harness-init` →
   `references/harness-invariants.md` → *Non-Interactive Gate Defaults* for the trigger list):
   skip the wait — adopt every open question's `Recommended:` answer immediately, mark each as
   an assumption in the four-field summary, announce per that section, and list any question the
   interview could not resolve even with a default in the handoff.
5. **No ADR/glossary machinery.** Do not create `CONTEXT.md`, a glossary file, or any
   standalone artifact. Hold the resolved answers in conversation context and hand them
   directly to the caller (Sprint Contract author, or `task-spec`).

## Flow

1. Identify the open questions blocking scope/design (from the current conversation or the
   caller's brief).
2. Ask the first one, per the `Q:` / `Recommended:` format above.
3. Wait for the user's reply. Accept a direct answer, an edit to the recommendation, or a
   confirmation of the recommendation. In a non-interactive run there is no reply to wait
   for — take Rule 4's non-interactive branch and go straight to step 5.
4. Repeat for each remaining question, one at a time, until none are open.
5. Summarize the resolved decisions in a fixed four-field block and hand control back to the
   caller (or continue inline if invoked standalone) — this summary is the only output; there
   is no file to write. Fields, in order:
   ```
   Outcome: <what changes, in one line — feeds Sprint Contract's Scope>
   Success: <how it's verified — feeds Sprint Contract's Acceptance criteria>
   Constraint: <non-negotiable limits surfaced during the interview — feeds Sprint Contract's
     Acceptance criteria as a must-not-violate condition>
   Out of scope: <explicit exclusions — feeds Sprint Contract's Out of scope>
   ```
   Omit a field only if the interview genuinely surfaced nothing for it — do not leave it
   blank silently.

## Exit

Stop and hand off once every open question is resolved. Do not continue grilling once scope
is clear — proceeding to ask more questions than the ambiguity warrants is itself a failure
mode (over-interviewing trivial decisions).
