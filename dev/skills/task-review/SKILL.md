---
name: task-review
description: >-
  Post-dev review cycle for this branch — commit, collect reviews, then apply findings and merge (lite or PR+CI
  by risk and required checks). Flags: --no-hub (local only), --auto (skip confirmation), --pr / --lite
  (request the merge path), --panel (force agy + Codex; default on every non-lite route).
disable-model-invocation: true
version: 1.0.2
---

# Dev Review Cycle

## Arguments

The flags in the description are defined once, in `dev:task-review-cycle` → *Arguments*; pass
them through unchanged. The description's `--auto` skips only the review-fix confirmation; it
grants no Git effect (one definition, not two that drift:
`cursor/plugins@9b93e81:pstack/skills/poteto-mode/playbooks/authoring-a-skill.md`).

Restate the Sprint Contract in the same invocation when the implementation was not yet verified
against it; the reviewer grades it (on lite, the orchestrator grades it inline — not independent).

Before handoff, verify this actual human invocation and any narrower Git instructions per
`../task-next/references/git-authorization.md`. Carry the originating instruction and the
contract's approval source/actions/limits verbatim; archive any explicitly approved revision.
With no original contract, create a feature branch first when on the base branch, then
archive a diff-review contract with those fields and concrete checks;
this does not pretend to recover implementation criteria. Never use `--from` as approval.

Call the Skill tool with "dev:task-review-cycle", passing `--from task-review` **plus** this
invocation's `args` unchanged — e.g. `--from task-review --auto`. Forward it on every path,
including a bare `/task-review`. The whole workflow lives in `dev:task-review-cycle`.
