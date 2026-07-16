---
name: to-spec
description: >-
  Use for multi-session or architecturally significant work to synthesize what's already
  known — conversation context plus any `Skill(dev-tools:grill)` output — into
  `docs/design/{slug}.md`. Does NOT interview the user; if scope is still ambiguous, call
  `Skill(dev-tools:grill)` first. Automates `docs/workflows.md` `plan` workflow steps 1-2.
  Trigger: "spec this out", "write a design doc", "스펙 문서 만들어줘", "설계 문서 작성해줘".
  NOT for trivial or single-session work — skip straight to a Sprint Contract
  (`docs/eval-criteria.md`) instead.
version: 1.0.0
---

# To Spec

> Inspired by mattpocock/skills (https://github.com/mattpocock/skills) — adapted for this repo's markdown-only backlog (no issue tracker, no CONTEXT.md/ADR pipeline).

Synthesizes an approved scope into a spec document. This skill does **not** ask the user
questions — if scope is still ambiguous when this skill is invoked, call
`Skill(dev-tools:grill)` first (or let the caller, e.g. `new-task`, do so) and only
invoke `to-spec` once the open questions are resolved.

## When to use

Only for work that is **multi-session or architecturally significant** — new subsystem,
cross-cutting change, or anything that won't fit in one Sprint Contract. Trivial or
single-session work skips this skill entirely and goes straight to a Sprint Contract.

This skill automates `docs/workflows.md` `plan` workflow **steps 1-2** ("Expand into
`docs/design/{feature}.md`" + "Review with user"). Step 3 (generate `backlog.md` items) is
`Skill(dev-tools:to-tickets)`'s job, not this skill's.

## Flow

1. **Determine the slug.** Derive a short kebab-case slug from the feature/change name
   (matches the branch-naming convention in `docs/conventions.md`).
   ```bash
   SLUG="<short-kebab-case-slug derived from the feature name>"
   DESIGN_DIR="docs/design"
   [[ -d "$DESIGN_DIR" ]] || mkdir -p "$DESIGN_DIR"
   ```
2. **Synthesize, do not interview.** Gather everything already known: the conversation so
   far, any resolved `Skill(dev-tools:grill)` output, and relevant existing code/docs. If a
   genuine open question surfaces during synthesis, stop and call `Skill(dev-tools:grill)` —
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
   {key design/architecture choices and why, resolved via grill or conversation}

   ## Testing Decisions
   {how correctness will be verified — test type, lint/test command, manual verification}

   ## Out of Scope
   {explicit exclusions}

   ## Further Notes
   {anything else worth recording — open risks, follow-ups}
   ```

4. **Review with user.** Present the written spec (or a summary + file path) and wait for
   explicit approval before any downstream skill (`to-tickets`, or direct implementation)
   proceeds. This mirrors `plan` workflow step 2 — do not skip it.
5. **Hand off.** Once approved, the caller (typically `new-task`) proceeds to
   `Skill(dev-tools:to-tickets)` to break the spec into backlog items.

## Boundaries

- Do not write production code from this skill.
- Do not create any file other than `docs/design/{slug}.md` — no `CONTEXT.md`, no ADRs, no
  glossary.
- Do not skip user review of the written spec.
