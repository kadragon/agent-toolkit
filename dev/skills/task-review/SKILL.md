---
name: task-review
description: >-
  Post-dev review cycle for this branch — commit, review, apply findings, merge (lite or PR+CI
  by risk and required checks). Flags: --no-hub (local only), --auto (skip confirmation), --pr / --lite
  (request the merge path), --panel (add agy + Codex).
disable-model-invocation: true
---

# Dev Review Cycle

## Arguments

- `--no-hub` — commit locally, review, apply, stop. No push, PR, CI, or merge.
- `--auto` — skip the consolidation confirmation; apply every in-scope finding.
- `--pr` / `--lite` — request PR+CI or direct merge; risk and mandatory CI gates still apply.
- `--panel` — add agy and Codex engines. Automatic selection follows the concrete risk
  assessment in `dev:task-review-cycle`, not line count.

Restate the Sprint Contract in the same invocation when the implementation was not yet verified
against it; the reviewer grades it.

Call the Skill tool with "dev:task-review-cycle", passing `--from task-review` **plus** this
invocation's `args` unchanged — e.g. `--from task-review --auto`. Forward it on every path,
including a bare `/task-review`. The whole workflow lives in `dev:task-review-cycle`.
