# Tasks

## Review Backlog

### PR #182 — gate dangling cross-asset section refs; state hook version-bump rule (2026-07-31)

- [ ] [doc] Shipped skills still carry the coarse bump rule `(patch for modify, minor for new skill, major for remove/rename)`, which no longer states the by-name carve-out PR #182 wrote into `AGENTS.md` and `docs/conventions.md`. Deferred out of #182 because editing either file forces the `dev/` version bump that PR deliberately had no need for — fold into the next `dev/` change (source: review) — `dev/skills/task-next/SKILL.md:286`, `dev/skills/task-new/SKILL.md:121`
- [ ] [doc] `AGENTS.md` says "Agent roles in `.claude/agents/*.md` — used both as subagent and Agent Teams teammate" and the Delegation table names `explorer` / `implementer` / `qa-verifier` / `skill-evaluator`, but `.claude/agents/` does not exist in this repo, so none of those roles resolve as a `subagent_type`. Either ship the role files or restate the table as guidance about *which* brief to write rather than which agent type to spawn (source: retrospect) — `AGENTS.md` Delegation section
