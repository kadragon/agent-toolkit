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
- `--qa-pending` — contract QA is still owed, so the cycle runs it as review-panel source 2-4. Pass it when resuming a `task-next`/`task-new` cycle that handed off after implement without verifying, and restate the Sprint Contract verbatim in the same invocation — without the contract the cycle stops and asks. Omit it when QA already ran, or the diff is verified twice.

Call the Skill tool with "dev:task-review-cycle", passing `--from task-review` **plus** this
invocation's `args` unchanged — e.g. `--from task-review --auto`. That token is the caller
argument the primitive checks; a call without it is not a wrapper call. Forward it on every
path, including a bare `/task-review` with no other flags.

The whole workflow — Setup, Steps 0–6, error handling, script reference — lives in `dev:task-review-cycle`.
