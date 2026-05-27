# Orchestrator Template

An orchestrator is a **skill** (`.claude/skills/{domain}-orchestrator/SKILL.md`) that wires agents into an executable workflow. It is not a doc — it runs.

Copy and adapt one of the three templates below based on coordination needs.

## Choosing an Execution Mode

```
Q1. Are there ≥2 agents that need to share findings mid-flight?
    Yes → Team Mode (Template A)
    No  → Q2
Q2. Are subtasks truly independent (results reported at the end only)?
    Yes → Sub-agent Mode (Template B)
    No  → reconsider whether multi-agent is needed
Q3. Does the workflow have phases with fundamentally different coordination needs?
    Yes → Hybrid Mode (Template C)
```

Cost note: Team mode carries 3–5× token overhead vs a single session. Default to team only when the inter-agent communication pays for itself — shared discoveries, contradiction resolution, incremental QA.

---

## Template A — Agent Team Mode (default for ≥2 collaborative agents)

```markdown
---
name: {domain}-orchestrator
description: |
  Orchestrates {domain} workflow using an agent team. Trigger when:
  - "{domain} 실행해줘", "{domain} 시작", "{domain} 다시 실행"
  - 부분 수정: "{domain}의 {부분} 수정", "이전 결과 기반으로 {수정}"
  - 점검: "{domain} 검증", "{domain} 상태 확인"
---

## Phase 0: Context Detection

Check `_workspace/` before anything else.

- `_workspace/` missing → **Initial run** — proceed to Phase 1
- `_workspace/` exists + user gave new input → **New run** — clear `_workspace/`, proceed to Phase 1
- `_workspace/` exists + user asked to revise/fix → **Partial re-run** — skip completed phases, re-run only requested scope

## Phase 1: Preparation

Read inputs, validate preconditions, create `_workspace/`:

```bash
mkdir -p _workspace
```

File naming convention: `{phase:02d}_{agent}_{artifact}.{ext}`
Examples: `01_analyst_requirements.md`, `02_architect_design.json`

## Phase 2: Team Assembly

```
TeamCreate(
  team_name: "{domain}-team",
  members: ["{agent-1}", "{agent-2}", "{agent-3}"]
)
```

Assign tasks with dependencies:

```
TaskCreate([
  {id: "task-1", agent: "{agent-1}", description: "...", dependencies: []},
  {id: "task-2", agent: "{agent-2}", description: "...", dependencies: ["task-1"]},
  {id: "task-3", agent: "{agent-3}", description: "...", dependencies: ["task-1"]}
])
```

## Phase 3: Parallel Execution

Agents run and coordinate via SendMessage. The orchestrator monitors via TaskGet.

Data transfer between agents:
- **Coordination**: `SendMessage` (real-time findings, blocking questions)
- **Progress**: `TaskUpdate` with status (in_progress → completed)
- **Artifacts**: Write to `_workspace/{phase}_{agent}_{artifact}.{ext}`

## Phase 4: Integration

Read agent artifacts from `_workspace/`, synthesize, produce final output.

Error policy:
- 1 agent fails → retry once
- Retry fails → proceed without that agent's output; note omission in report
- Majority fail → stop, report to user with `_workspace/` state preserved

## Phase 5: Cleanup

```
TeamDelete(team_name: "{domain}-team")
```

Preserve `_workspace/` for partial re-run support. Remove only on explicit "reset" request.
```

---

## Template B — Sub-agent Mode (independent parallel tasks)

```markdown
---
name: {domain}-orchestrator
description: |
  Orchestrates {domain} via parallel sub-agents. Trigger on: "{domain} 실행".
---

## Phase 0: Context Detection

(Same as Template A)

## Phase 1: Spawn Sub-agents

Launch independent agents in parallel in a single turn:

```
Agent(subagent_type: "{agent-1}", prompt: """
  Objective: {specific task}
  Output format: {format}
  Tools to use: {subset}
  Boundaries: {must not touch}
  Save output to: _workspace/01_{agent-1}_result.md
""", run_in_background: true)

Agent(subagent_type: "{agent-2}", prompt: """
  Objective: {specific task}
  ...
  Save output to: _workspace/01_{agent-2}_result.md
""", run_in_background: true)
```

All four Spawn Prompt Contract fields are mandatory (Objective / Output format / Tools to use / Boundaries).

## Phase 2: Collect and Integrate

Read artifacts from `_workspace/`, produce final output.

Error policy: (same as Template A Phase 4)
```

---

## Template C — Hybrid Mode (phase-dependent coordination)

Use when phases have distinct coordination needs. Common combinations:

| Pattern | Phase A | Phase B |
|---------|---------|---------|
| Gather → Decide | Sub-agent (parallel collection) | Team (consensus synthesis) |
| Design → Verify | Team (collaborative design) | Sub-agent (independent verification) |
| Explore → Build → QA | Sub-agent | Sub-agent | Sub-agent |

Between phases, save artifacts to `_workspace/`, then switch mode:

```markdown
## Phase 2: Parallel Gathering (sub-agent)
[spawn sub-agents, collect to _workspace/]

## Phase 3: Team Synthesis (team)
TeamCreate(...)
[read _workspace/ artifacts, coordinate via SendMessage]
TeamDelete(...)

## Phase 4: Independent Verification (sub-agent)
[spawn verifier sub-agent reading _workspace/ artifacts]
```

---

## _workspace/ Convention

```
_workspace/
  {phase:02d}_{agent}_{artifact}.{ext}
  01_analyst_requirements.md
  02_architect_design.json
  03_implementer_diff.patch
```

Rules:
- All paths use `_workspace/` as root
- Never use relative paths without `_workspace/` prefix
- Final deliverables go to user-specified path; intermediates stay in `_workspace/`
- Preserve across sessions for partial re-run support

---

## CLAUDE.md Pointer (register after orchestrator created)

Add to project `CLAUDE.md`:

```markdown
## Harness: {Domain}

**Goal:** {one line}

**Trigger:** For {domain} work, use the `{domain}-orchestrator` skill.

**Change History:**
| Date | Change | Scope | Reason |
|------|--------|-------|--------|
| {YYYY-MM-DD} | Initial setup | all | - |
```

Keep CLAUDE.md as a thin pointer — trigger rule + change history only. Agent list, skill list, directory structure → do NOT put here.
