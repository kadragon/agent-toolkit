# Delegation

The orchestrator plans and routes. Sub-agents do the heavy lifting. Broad work inline is a harness defect.

## Pattern Selection

```
Q1. Does the task decompose into >1 genuinely parallel subtask?
    No  → single session. No delegation. Stop.
    Yes → Q2.
Q2. Do subtasks need to share findings mid-flight?
    Yes → Agent Team (TeamCreate + SendMessage)
    No  → Sub-agent (Agent tool, run_in_background ok)
```

Most work in this repo is sequential: explore → implement → verify. Default to sub-agent mode.

## Routing Table

All triggers are objective and measurable — no subjective conditions.

### Mandatory Gates (blocking — skipping is a golden principle violation)

| Trigger | Delegate to | Model | Context to pass |
|---------|-------------|-------|-----------------|
| Target plugin area not explored this session AND has >3 files | `explorer` | sonnet | Plugin dir path |
| Implementation task from `backlog.md` | `implementer` | sonnet | Backlog item, conventions, target files |
| After any source edit (always) | `qa-verifier` | sonnet | Modified files, test/lint commands |
| Skill quality assessment requested | `skill-evaluator` | opus | Skill path, eval-criteria.md |

### Background Gates (non-blocking)

| Trigger | Delegate to | Context |
|---------|-------------|---------|
| Every PR | `dev-tools:dev-review-cycle` skill | PR number or current branch |
| Harness check request | `dev-tools:harness-curator` skill | — |

### Escalation

| Trigger | Action |
|---------|--------|
| Same failure ×2 | Call `advisor` tool — full context forwarded automatically |
| Advisor unresolved | `codex:rescue` with explicit brief |

## Spawn Prompt Contract (all 4 fields mandatory)

Every `Agent(...)` call must include:

```
- Objective: {what specifically to accomplish}
- Output format: {diff / report / table / verdict}
- Tools to use: {subset of role's allowlist}
- Boundaries: {files/modules this spawn must NOT touch}
```

Missing any field → reject and rewrite the spawn prompt.

## Effort Tier

Embed in every spawn prompt:

| Tier | Use for | Tool calls | Model |
|------|---------|------------|-------|
| Simple | Known-answer lookup, single-file edit, mechanical check | 3–10 | haiku/sonnet |
| Comparison | Weighing options, multi-file review, cross-module check | 10–15 | sonnet |
| Complex | Root cause unknown, architectural decision | 15+ | opus |

## Data Transfer Protocols

| Strategy | Mechanism | Use when |
|----------|-----------|----------|
| Return value | Agent tool result | Sub-agent reports to orchestrator |
| File-based | `_workspace/{phase:02d}_{agent}_{artifact}.{ext}` | Large artifacts, cross-phase handoff |
| Task-based | `TaskCreate`/`TaskUpdate` | Progress tracking, dependency gates |

`_workspace/` naming: `{phase:02d}_{agent}_{artifact}.{ext}` — e.g. `01_explorer_map.md`, `02_implementer_diff.md`.

Preserve `_workspace/` across sessions (enables partial re-run). Remove only on explicit "reset".
