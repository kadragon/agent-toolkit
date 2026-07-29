# Delegation

**This file does not decide *whether* to delegate — it defines *how*, once that decision is made.**
The threshold lives in `~/.claude/CLAUDE.md`: default inline; delegate only when the user asks, a
skill directs, or a global gate applies (10+ files to read/summarize · 3+ truly independent units ·
output would flood main context). Coupled, sequential, or judgment-heavy work stays inline. This
repo imposes no lower bar.

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

## Role Routing

No row below is a gate. When the threshold above is met, match the job to the role:

| Job | Delegate to | Model | Context to pass |
|-----|-------------|-------|-----------------|
| Read-only map of an unexplored plugin area | `explorer` | sonnet | Plugin dir path |
| Implementation task from `backlog.md` | `implementer` | sonnet | Backlog item, conventions, target files |
| Verifying an implementation | `qa-verifier` | sonnet | Modified files, test/lint commands |
| Skill quality assessment requested | `skill-evaluator` | opus | Skill path, eval-criteria.md |

`qa-verifier` never runs on its own output — whoever implemented must not be the one who verifies.
That constraint holds whenever a verifier runs; it does not by itself mandate spawning one.

### Background Gates (non-blocking)

| Trigger | Delegate to | Context |
|---------|-------------|---------|
| Every PR | `dev:task-review` skill | PR number or current branch |
| Harness check request | `dev:harness-curate` skill | — |

### Escalation

| Trigger | Action |
|---------|--------|
| Same failure ×2 | Encode the fix mechanically (hook/lint/test) per the global harness-ratchet rule |
| Root cause still unknown after that | `codex:rescue` with an explicit brief |

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
| File-based | Session scratchpad dir, `{phase:02d}_{agent}_{artifact}.{ext}` | Large artifacts, cross-phase handoff |
| Task-based | `TaskCreate`/`TaskUpdate` | Progress tracking, dependency gates |

Naming: `{phase:02d}_{agent}_{artifact}.{ext}` — e.g. `01_explorer_map.md`, `02_implementer_diff.md`.

The orchestrator determines its scratchpad path once (from its own system prompt) and embeds the full path explicitly in every spawn prompt — sub-agents must not guess or reconstruct it. Scratchpad is ephemeral: gone when the session ends, no cross-session resume.
