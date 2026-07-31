# Tasks

## Review Backlog

### PR #181 — retire failure-log/delegation-log hooks; consolidate SessionStart into one dispatcher (2026-07-31)

- [ ] [doc] Version-bump table scopes "remove/rename → major" to skills/agents only — hook removal/rename is uncovered, and the two reviewers split on major vs patch for this PR. Decide and state the rule (source: review, codex) — `AGENTS.md` Golden Principle 1, `docs/conventions.md:117-123`
- [ ] [harness] Add a CI gate for dangling cross-asset section references (`§N`, `Signal N`) — this PR renumbered signal-taxonomy 8→7 and shipped 4 dangling refs in `harness-init/SKILL.md` plus 1 in `harness-curate/SKILL.md`; nothing mechanical caught it (source: retrospect) — `scripts/ci/check_harness_drift.py`
