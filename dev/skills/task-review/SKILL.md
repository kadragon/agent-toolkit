---
name: task-review
description: >-
  Post-dev review cycle for this branch — commit, collect reviews, then apply findings and merge (lite or PR+CI
  by risk and required checks). Flags: --no-hub (local only), --auto (skip confirmation), --pr / --lite
  (request the merge path), --panel (force agy + Codex).
disable-model-invocation: true
version: 1.0.4
---

# Dev Review Cycle

## Phase index

Read *Arguments* here for a direct invocation. The remaining sections are in
`../task-review-cycle/SKILL.md`. Locate headings with `rg -n '^#{1,3} ' <file>` and read the current
range through its next peer heading.

| Phase | Sections to open |
|---|---|
| Recover the contract and open the PR if required | *Caller gate*, *Arguments*, *Prerequisites and Setup*, *Step 1: Commit, route, PR* |
| Review and address findings | *Step 2: Review*, then *Step 3: Consolidate and confirm*, *Step 4: Apply*, and *Step 5: Commit* as reached |
| Verify and finish | *Step 6: Merge* (also covers the PR-only stop). Open *Error handling* on failure |

## Arguments

The flags in the description are defined once, in `dev:task-review-cycle` → *Arguments*; pass
them through unchanged. The description's `--auto` skips only the review-fix confirmation; it
grants no Git effect (one definition, not two that drift:
`cursor/plugins@9b93e81:pstack/skills/poteto-mode/playbooks/authoring-a-skill.md`).

Restate the Sprint Contract in the same invocation when the implementation was not yet verified
against it; the reviewer grades it (on lite, the orchestrator grades it inline — not independent).

With no original contract, create a feature branch first when on the base branch, then
archive a diff-review contract with the verified authority fields and concrete checks.
Authority itself is the callee's *Caller gate*; `--from` is never approval.

Call the Skill tool with "dev:task-review-cycle", passing `--from task-review` **plus** this
invocation's `args` unchanged — e.g. `--from task-review --auto`. Forward it on every path,
including a bare `/task-review`. The whole workflow lives in `dev:task-review-cycle`.
