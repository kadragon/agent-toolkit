---
name: task-spec
description: >-
  Synthesize known context into a `docs/design/{slug}.md` design doc for
  multi-session or architecturally significant work. Does NOT interview — run
  `Skill(dev:task-grill)` first if scope is still ambiguous. NOT for splitting
  an already-approved spec into queue items → task-tickets. Trivial work skips
  straight to a Sprint Contract.
# notation-exempt: description text, rewritten only under a separate decision
version: 1.1.0
---

# To Spec

> Inspired by mattpocock/skills (https://github.com/mattpocock/skills) — adapted for this repo's markdown-only backlog (no issue tracker, no CONTEXT.md/ADR pipeline).

Synthesizes an approved scope into a spec document. This skill does **not** ask the user
questions — if scope is still ambiguous when this skill is invoked, call the Skill tool with
"dev:task-grill" first (or let the caller, e.g. `task-new`, do so) and only
invoke `task-spec` once the open questions are resolved.

## When to use

Only for work that is **multi-session or architecturally significant** — new subsystem,
cross-cutting change, or anything that won't fit in one Sprint Contract. Trivial or
single-session work skips this skill entirely and goes straight to a Sprint Contract.

This skill automates `docs/workflows.md` `plan` workflow **steps 1-2** ("Expand into
`docs/design/{feature}.md`" + "Review with user"). Step 3 (generate `backlog.md` items) is
`task-tickets`'s job, not this skill's.

## Flow

1. **Determine the slug.** Derive a short kebab-case slug from the feature/change name
   (matches the branch-naming convention in `docs/conventions.md`).
   ```bash
   SLUG="<short-kebab-case-slug derived from the feature name>"
   DESIGN_DIR="docs/design"
   [[ -d "$DESIGN_DIR" ]] || mkdir -p "$DESIGN_DIR"
   ```
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

   ## Testing Decisions
   {how correctness will be verified — test type, lint/test command, manual verification}

   ## Out of Scope
   {explicit exclusions}

   ## Not yet specified
   {in-scope areas you cannot yet phrase as a sharp question — omit the section when empty}

   ## Further Notes
   {anything else worth recording — open risks, follow-ups}
   ```

3a. **Split what stays foggy.** An area is in scope but not yet answerable when you cannot
   state its question precisely *now* — not merely when you cannot answer it. Write those
   into `## Not yet specified`, one line each: the suspected question plus the area to
   revisit. The test is sharpness, not certainty — a question you can phrase but not answer
   belongs in `## Implementation Decisions` as an open decision (or goes back to
   `dev:task-grill`), not here. Something ruled beyond the destination goes to
   `## Out of Scope`, which never graduates. Omit the section entirely when nothing is foggy;
   a spec that is foggier than it is decided is a signal the scope is too large for one
   spec, so say so instead of filling the section.

4. **Review with user.** Present the written spec (or a summary + file path) and wait for
   explicit approval before any downstream skill (`task-tickets`, or direct implementation)
   proceeds. This mirrors `plan` workflow step 2 — do not skip it.
5. **Hand off.** Once approved, the caller (typically `task-new`) proceeds by calling the Skill
   tool with "dev:task-tickets" to break the spec into backlog items.

## Boundaries

- Do not write production code from this skill.
- Do not create any file other than `docs/design/{slug}.md` — no `CONTEXT.md`, no ADRs, no
  glossary.
- Do not skip user review of the written spec.
