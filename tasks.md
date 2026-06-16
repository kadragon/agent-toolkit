## Review Backlog

### PR #54 — start-task skill (2026-06-14)

- [ ] [debt] `.claude/trigger-routes.json:4` — `start.*work` pattern can match "start implementing a skill"; no guard for `implement|구현` to skip to skill-dev-orchestrator route instead (source: review) — P2
- [ ] [debt] `.claude/trigger-routes.json:4` — route instruction "Do NOT inline-pick or inline-implement" conflicts with SKILL.md line 66 which allows "inline edit" for ≤2 files. Reword route to "Do NOT skip the skill" (source: pr-review-toolkit, conf 70) — P3
