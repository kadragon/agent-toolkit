---
name: grill
description: >-
  Use when there is material ambiguity in scope, requirements, or a design decision that
  blocks non-trivial work — before writing a Sprint Contract, a `docs/design/{slug}.md` spec,
  or backlog tickets. Interviews the user one question at a time, each with a recommended
  answer + rationale, and waits for confirmation before proceeding. Trigger: "grill me on
  this", "clarify scope", "resolve ambiguity", "질문해줘", "범위 확인해줘", "모호한 부분
  물어봐줘". Reusable from other skills via `Skill(dev-tools:grill)`. NOT for facts
  discoverable from the repo/environment (look those up instead of asking) — NOT for trivial,
  already-specified, or single-obvious-answer decisions.
version: 1.0.0
---

# Grill

> Inspired by mattpocock/skills (https://github.com/mattpocock/skills) — adapted for this repo's markdown-only backlog (no issue tracker, no CONTEXT.md/ADR pipeline).

Formalizes this repo's existing "Grill" hard-stop convention (`~/.claude/CLAUDE.md`,
`team-standards/standards/AGENT-STANDARDS.md`) into a reusable skill: **material ambiguity
affecting scope, irreversible effects, external communication, or expected output → grill,
don't guess.** Unlike mattpocock's `grilling`+`domain-modeling` pair, this skill does not
produce a separate `CONTEXT.md` or ADR artifact — this repo has no such convention. Its output
feeds directly into whichever document is being built next: a Sprint Contract
(`docs/eval-criteria.md` template) or a `to-spec` document.

## When to use

Call this skill (directly, or via `Skill(dev-tools:grill)` from `next-tasks`/`to-spec`) only
when there is **genuine, non-trivial ambiguity** — not to rubber-stamp already-clear scope.
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
   answered (or explicitly waved off) every open question.
5. **No ADR/glossary machinery.** Do not create `CONTEXT.md`, a glossary file, or any
   standalone artifact. Hold the resolved answers in conversation context and hand them
   directly to the caller (Sprint Contract author, or `to-spec`).

## Flow

1. Identify the open questions blocking scope/design (from the current conversation or the
   caller's brief).
2. Ask the first one, per the `Q:` / `Recommended:` format above.
3. Wait for the user's reply. Accept a direct answer, an edit to the recommendation, or a
   confirmation of the recommendation.
4. Repeat for each remaining question, one at a time, until none are open.
5. Summarize the resolved decisions in one short block and hand control back to the caller
   (or continue inline if invoked standalone) — this summary is the only output; there is no
   file to write.

## Exit

Stop and hand off once every open question is resolved. Do not continue grilling once scope
is clear — proceeding to ask more questions than the ambiguity warrants is itself a failure
mode (over-interviewing trivial decisions).
