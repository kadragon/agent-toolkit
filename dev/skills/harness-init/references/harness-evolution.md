# Harness Evolution

A harness is a living system, not a one-time setup. This document describes how to evolve the harness based on usage feedback.

## When to Evolve

Trigger a harness evolution pass in any of these conditions:

| Signal | Interpretation | Action |
|--------|---------------|--------|
| Same feedback appears 2×+ | Structural gap in skill/agent | Update skill or agent definition |
| Agent bypasses orchestrator manually | Orchestrator trigger description missing | Expand orchestrator description |
| Same agent failure pattern 2×+ | Agent definition defect | Fix principles / exit criteria in agent file |
| User manually redoes a step | Agent output not matching expectation | Update skill output format spec |

**Don't wait for explicit "update the harness" request.** When the above signals appear, propose the evolution and apply with user confirmation.

## Feedback → Fix Target Mapping

| Feedback type | Fix target | Example |
|---------------|-----------|---------|
| Output quality too low | Agent's skill (`skills/{name}/SKILL.md`) | "분석이 너무 얕아" → 스킬에 깊이 기준 추가 |
| Wrong role doing the work | Agent definition (`agents/{name}.md`) | "보안 검토도 필요해" → 새 에이전트 추가 |
| Phase order wrong | Orchestrator skill | "검증을 먼저 해야 해" → Phase 순서 변경 |
| Two agents doing the same thing | Orchestrator + agent merge | "이 둘은 합쳐도 될 듯" → 에이전트 병합 |
| Skill doesn't trigger | Skill description | "이 표현으로는 안 돼" → description 확장 |
| Too many tokens wasted | Scratchpad/`.claude/tmp/` bloat, agent scope | Tighten Boundaries in spawn prompt |

## Change History

Record every harness change in the pointer block's change history table in `docs/harness-log.md` (never CLAUDE.md — it stays a pure `@AGENTS.md` pointer):

```markdown
**Change History:**
| Date | Change | Scope | Reason |
|------|--------|-------|--------|
| 2026-05-01 | Initial setup | all | - |
| 2026-05-03 | Add security-reviewer agent | agents/security-reviewer.md | Output missed auth issues |
| 2026-05-07 | Expand orchestrator description | skills/domain-orchestrator | "재실행" keyword not triggering |
```

Changes without a history entry are invisible to future sessions — this record IS the harness memory.

## Evolution Protocol

1. **Identify**: which signal triggered the evolution (see table above)
2. **Diagnose**: read the failing agent/skill definition to find the gap
3. **Fix**: apply the minimal change (don't rewrite everything)
4. **Verify**: re-run the failing case or dry-run the changed flow
5. **Record**: add entry to the `docs/harness-log.md` change history

Changes to golden principles or enforcement layers are high risk — always confirm with user before applying.

## Periodic Audit (optional)

On explicit "harness audit" request, run this checklist:

- [ ] Each agent's description still matches what it actually does
- [ ] Orchestrator description covers all known user phrasings
- [ ] Scratchpad naming convention followed consistently
- [ ] `docs/harness-log.md` change history is up to date
- [ ] No stale agent files for roles that are no longer used
- [ ] Team size still appropriate for current workload

Delete stale agents. Shrink over-specified skills. A lean harness beats a comprehensive one.
