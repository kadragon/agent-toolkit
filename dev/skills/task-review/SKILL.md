---
name: task-review
description: >-
  Post-dev review cycle — commit → reviews (Claude + agy + Codex) → apply →
  retrospect → CI → merge. Flags: --no-hub (local only), --auto (skip
  confirmation).
disable-model-invocation: true
---

# Dev Review Cycle

## Arguments

- `--no-hub` — no push, no PR, no CI, no merge. Commits locally, reviews from local diff.
- `--auto` — skip the consolidation confirmation gate. Apply all in-scope findings automatically. Verifier and contest-round verdicts still apply (refuted = not applied).

Call the Skill tool with "dev:task-review-cycle", forwarding this invocation's `args` unchanged.

The whole workflow — Setup, Steps 0–6, error handling, script reference — lives in `dev:task-review-cycle`.
