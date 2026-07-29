# Backlog

## Harness

- [ ] **[HARNESS] Resync generated agent instances against the role template** — `harness-init`
  Step 4b writes `.claude/agents/{role}.md` once and never revisits it, so template improvements
  never reach existing repos. The reconcile boundary is already settled: *presence of the four
  spine sections only* (Objective / Spawn Prompt Contract / Effort Tier / Exit Criteria) — added
  repo-specific sections and repo-local wording inside shared sections are intentional and must
  not be touched. See **Common spine vs repo-specific additions** in
  `dev/skills/harness-init/references/teammate-role-template.md`. Likely shape: a
  `validate-harness.sh` check that reports missing spine sections rather than a rewriter.
