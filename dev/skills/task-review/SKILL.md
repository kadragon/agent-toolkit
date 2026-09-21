---
name: task-review
description: >-
  Post-dev review cycle for this branch — commit, review, apply findings, merge (lite or PR+CI
  by risk and required checks). Flags: --no-hub (local only), --auto (skip confirmation), --pr / --lite
  (request the merge path), --panel (force agy + Codex; default on every non-lite route).
disable-model-invocation: true
---

# Dev Review Cycle

## Arguments

- `--no-hub` — commit locally, review, apply, stop. No push, PR, CI, or merge.
- `--auto` — skip the consolidation confirmation; apply every in-scope finding.
- `--pr` / `--lite` — request PR+CI or direct merge; risk and mandatory CI gates still apply.
- `--panel` — force the agy + Codex panel, which also forces PR+CI unless `--no-hub`. Without it the panel runs on
  every PR+CI and `--no-hub` route and stays off on the lite path (`dev:task-review-cycle`).

Restate the Sprint Contract in the same invocation when the implementation was not yet verified
against it; the reviewer grades it.

Call the Skill tool with "dev:task-review-cycle", passing `--from task-review` **plus** this
invocation's `args` unchanged — e.g. `--from task-review --auto`. Forward it on every path,
including a bare `/task-review`. The whole workflow lives in `dev:task-review-cycle`.
