# Backlog

## Harness

- [ ] **[HARNESS] Resync generated agent instances against the role template** — nothing re-runs
  `harness-init` Step 4b when the role template changes; existing role files are revisited only on
  repo-driven signals (Extend mode `Architecture change`, `references/harness-evolution.md`
  feedback + Periodic Audit), never on template change — so template improvements never reach
  existing repos. The reconcile boundary is already settled: *frontmatter-field presence + presence
  of the four spine sections* (Objective / Spawn Prompt Contract / Effort Tier / Exit Criteria).
  Repo-added sections, repo-local wording inside shared sections, and the opt-in non-spine template
  sections (`## Multi-pass Rule`, `## Team Communication Protocol`) are intentional and must not be
  touched. See **Common spine vs repo-specific additions** in
  `dev/skills/harness-init/references/teammate-role-template.md`. Likely shape: a reporting check
  rather than a rewriter — evaluate `harness-evolution.md`'s Periodic Audit as its home before
  adding a new surface to `validate-harness.sh`.
