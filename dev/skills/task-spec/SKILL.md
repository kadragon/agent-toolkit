---
name: task-spec
description: >-
  Synthesize known context into a `docs/design/{slug}.md` design doc for
  multi-session or architecturally significant work. Does NOT interview — run
  `Skill(dev:task-grill)` first if scope is still ambiguous. NOT for splitting
  an already-approved spec into queue items → task-tickets. Trivial work skips
  straight to a Sprint Contract.
# notation-exempt: description text, rewritten only under a separate decision
version: 1.2.3
---

# To Spec

> Inspired by mattpocock/skills (https://github.com/mattpocock/skills) — adapted for this repo's markdown-only backlog (no issue tracker, no CONTEXT.md/ADR pipeline).

Synthesizes an approved scope into a spec document. This skill does **not** ask the user
questions — open questions go to `dev:task-grill` (Step 2).

## When to use

Only for work that is **multi-session or architecturally significant** — new subsystem,
cross-cutting change, or anything that won't fit in one Sprint Contract. Trivial or
single-session work skips this skill entirely and goes straight to a Sprint Contract.

This skill automates `docs/workflows.md` `plan` workflow **steps 1-2** ("Expand into
`docs/design/{feature}.md`" + "Review with user"). Step 3 (generate `backlog.md` items) is
`task-tickets`'s job, not this skill's.

## Flow

1. **Determine the slug.** Derive a short kebab-case slug from the feature/change name
   (matches the branch-naming convention in `docs/conventions.md`); create `docs/design/` if
   it is missing.
2. **Synthesize, do not interview.** Gather everything already known: the conversation so
   far, any output already resolved by a Skill tool call with "dev:task-grill", and relevant
   existing code/docs. If a genuine open question surfaces during synthesis, stop and call the
   Skill tool with "dev:task-grill" —
   do not guess and do not ask the user directly from inside this skill.
3. **Write `docs/design/{slug}.md`** using this template, verbatim section order:

   ```markdown
   # {Feature/Change Name}

   ## Problem Statement
   {what's broken or missing, why it matters now}

   ## Solution
   {the approach at a high level — no granular implementation detail}

   ## User Stories
   - As a {role}, I want {capability}, so that {benefit}.
   - ...

   ## Implementation Decisions
   {key design/architecture choices and why, resolved via task-grill or conversation}

   ## Alternatives rejected
   {each structurally different approach weighed, one line each: the approach and why it lost}

   ## Testing Decisions
   {how correctness will be verified — test type, lint/test command, manual verification}

   ## Out of Scope
   {explicit exclusions}

   ## Not yet specified
   {in-scope areas you cannot yet phrase as a sharp question — omit the section when empty}

   ## Further Notes
   {anything else worth recording — open risks, follow-ups}
   ```

   **Split what stays foggy.** An area is in scope but not yet answerable when you cannot
   state its question precisely *now* — not merely when you cannot answer it. Write those
   into `## Not yet specified`, one line each: the suspected question plus the area to
   revisit. The test is sharpness, not certainty: a question you *can* phrase but cannot
   answer is not fog and never gets parked — it goes back to `dev:task-grill` per Step 2, and
   only its resolved answer reaches `## Implementation Decisions`, which holds decided things
   and is read downstream as slice-bearing. Something ruled beyond the destination goes to
   `## Out of Scope`, which never graduates. Omit the section entirely when nothing is foggy;
   a spec that is foggier than it is decided is a signal the scope is too large for one
   spec, so say so instead of filling the section.

   **Record what lost.** Implementation starts in a fresh session that holds only this file, so
   a rejected approach missing here gets proposed again. Name at least one structurally
   different alternative for each architectural decision; write `None weighed — <reason>` when
   the approach was forced (`cursor/plugins@9b93e81:pstack/skills/architect/SKILL.md` Phase B,
   `pstack/skills/poteto-mode/playbooks/multi-phase-plan.md` Appendix B).

   **Skill extraction handoff.** A summary with `Skill slots:` gets `## Skill slots` after
   Further Notes, per `../task-grill/references/skill-extraction.md` → *Carrying the slots*.

4. **Review with user.** Present the written spec (or a summary + file path) and wait for
   explicit approval before any downstream skill (`task-tickets`, or direct implementation)
   proceeds (`plan` workflow step 2).
5. **Hand off.** Once approved, the caller (typically `task-new`) proceeds by calling the Skill
   tool with "dev:task-tickets" to break the spec into backlog items.

## Boundaries

- Do not write production code from this skill.
- Write only `docs/design/{slug}.md`.
