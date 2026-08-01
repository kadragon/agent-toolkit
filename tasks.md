# Tasks

## Review Backlog

### Harness gap found while running the cycle (2026-08-01)

- [ ] [debt] `dev:task-next` pre-merge cleanup omits the CHANGELOG step on the *tasks.md finding group* path, while the h1-sprint and backlog.md-group paths both require one. `docs/conventions.md:30-33` states the rule unconditionally ("One line per completed cycle") and PR #176's review-backlog cycle did get an entry, so the skill's per-source branching is wrong — Codex caught the missing entry in this very PR. Add the CHANGELOG step to the finding-group path (source: codex + this cycle) — `dev/skills/task-next/SKILL.md` § "Pre-merge cleanup"
