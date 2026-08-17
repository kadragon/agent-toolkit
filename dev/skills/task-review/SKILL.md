---
name: task-review
description: >-
  Post-dev review cycle for this branch — commit, collect reviews, apply findings, retrospect,
  wait for CI, merge. Flags: --no-hub (local only), --auto (skip confirmation).
disable-model-invocation: true
---

# Dev Review Cycle

## Arguments

- `--no-hub` — no push, no PR, no CI, no merge. Commits locally, reviews from local diff.
- `--auto` — skip the consolidation confirmation gate. Apply all in-scope findings automatically. Verifier and contest-round verdicts still apply (refuted = not applied).

Call the Skill tool with "dev:task-review-cycle", passing `--from task-review` **plus** this
invocation's `args` unchanged — e.g. `--from task-review --auto`. That token is the caller
argument the primitive checks; a call without it is not a wrapper call. Forward it on every
path, including a bare `/task-review` with no other flags.

The whole workflow — Setup, Steps 0–6, error handling, script reference — lives in `dev:task-review-cycle`.
