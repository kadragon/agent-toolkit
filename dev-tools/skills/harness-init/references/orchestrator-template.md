# Orchestrator Template

An orchestrator is a **skill** (`.claude/skills/{domain}-orchestrator/SKILL.md`) that wires agents into an executable workflow. It is not a doc — it runs.

Copy and adapt one of the three templates below based on coordination needs.

## Choosing an Execution Mode

```
Q1. Are there ≥2 agents that need to share findings mid-flight?
    Yes → Team Mode (Template A)
    No  → Q2
Q2. Are subtasks truly independent (results reported at the end only)?
    Yes → Q3
    No  → reconsider: heavy inter-agent deps → single session is cheaper
Q3. Does the workflow have phases with fundamentally different coordination needs?
    Yes → Hybrid Mode (Template C)
    No  → Sub-agent Mode (Template B)
```

Cost note: Team mode carries 3–5× token overhead vs a single session. Default to team only when the inter-agent communication pays for itself — shared discoveries, contradiction resolution, incremental QA.

---

## Description writing rule (applies to all three templates)

The `description:` field is the **primary discovery mechanism** for skill auto-invocation. Anthropic's own skill-creator testing reports directive phrasing ("ALWAYS invoke when …") improves trigger rate on 5 of 6 public skills compared to descriptive phrasing ("Triggers on …"). Combined with the UserPromptSubmit router (`references/trigger-router-template.md`), this raises observed auto-invocation from the ~50% baseline ([Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)", 2025-11-06](https://scottspence.com/posts/claude-code-skills-dont-auto-activate)) toward deterministic on matched prompts.

**Localization note.** Templates below include Korean trigger phrases (e.g. `"{domain} 실행해줘"`) because this harness is authored for a bilingual KO/EN user. For **English-only repos, drop the Korean lines** when copying the template — leaving them in pollutes the description with unused tokens and may confuse the model's matcher. For other-language repos, translate the trigger phrases to the target language. Keep the English lines in every case (they're the lingua franca for Claude's auto-invocation).

**Required pattern for orchestrator descriptions:**

```yaml
description: |
  ALWAYS invoke this skill when the user asks for {domain} work. Do NOT inline-execute {domain} tasks.
  Trigger phrases (Korean + English):
  - "{domain} 실행해줘", "{domain} 시작", "{domain} 다시 실행"
  - "run {domain}", "start {domain}", "{domain} again"
  Resume / partial: "{domain}의 {부분} 수정", "based on previous results, redo {부분}"
  Validation: "{domain} 검증", "{domain} 상태", "validate {domain}"
  Skip only if user explicitly says "inline" / "직접" / "without orchestrator".
```

Also register the orchestrator in `.claude/trigger-routes.json` so the UserPromptSubmit hook emits an explicit `Use Skill(...)` instruction on match — descriptions handle the long tail, the router handles the high-leverage phrases.

---

## Template A — Agent Team Mode (default for ≥2 collaborative agents)

```markdown
---
name: {domain}-orchestrator
description: |
  ALWAYS invoke this skill when the user asks for {domain} work. Do NOT inline-execute {domain} tasks.
  Trigger phrases (Korean + English):
  - "{domain} 실행해줘", "{domain} 시작", "{domain} 다시 실행"
  - "run {domain}", "start {domain}", "{domain} again"
  Resume / partial: "{domain}의 {부분} 수정", "based on previous results, redo {부분}"
  Validation: "{domain} 검증", "{domain} 상태", "validate {domain}"
  Skip only if user says "inline" / "직접" / "without orchestrator".
---

## Phase 0: Context Detection

Check `_workspace/campaign-state.json` before anything else.

```
campaign-state.json missing → Initial run — proceed to Phase 1
campaign-state.json exists + new-run signal (--new flag OR input hash changed) →
  New run — rename _workspace/ to _workspace_archive-{timestamp}/ (outside _workspace/
  to avoid "cannot move to a subdirectory of itself"), write fresh campaign-state.json,
  proceed to Phase 1
campaign-state.json exists + no new-run signal → Resume — read next_entry_point,
  skip completed_phases, continue from current_phase
```

Read `current_phase` and `tasks` from the state file. Report to user: "Resuming {domain} campaign from Phase {N} — tasks {completed} done, {in_progress} in progress."

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
  ALWAYS invoke this skill when the user asks for {domain} work — coordinates parallel sub-agents.
  Trigger phrases: "{domain} 실행", "{domain} 시작", "run {domain}", "start {domain}".
  Skip only if user says "inline" / "직접" / "without orchestrator".
---

## Phase 0: Context Detection

Same as Template A — read `_workspace/campaign-state.json`.

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

| Pattern | Phase A | Phase B | Phase C |
|---------|---------|---------|---------|
| Gather → Decide | Sub-agent (parallel collection) | Team (consensus synthesis) | — |
| Design → Verify | Team (collaborative design) | Sub-agent (independent verification) | — |
| Explore → Build → QA | Sub-agent (explore) | Sub-agent (build) | Sub-agent (QA) |

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
  campaign-state.json                                  ← session-persistent campaign state
  {phase:02d}_{agent}_{area}_{session_id}_{artifact}.{ext}
  01_analyst_auth_sess-abc123_requirements.md
  02_architect_auth_sess-abc123_design.json
  03_implementer_billing_sess-abc123_diff.patch
```

Rules:
- All paths use `_workspace/` as root
- Never use relative paths without `_workspace/` prefix
- Final deliverables go to user-specified path; intermediates stay in `_workspace/`
- Preserve across sessions for partial re-run support
- **Include `{area}` and `{session_id}` in the filename** when the delegation gate (`references/enforcement-template.md`) is installed. The gate's evidence glob is `_workspace/*_{area}_{session_id}_*.md`; omitting either field will leave the gate unable to verify your delegation and block the next edit. If you omit them deliberately, also relax the gate's glob.

### Campaign State File (`_workspace/campaign-state.json`)

Write this file at the end of every phase. Phase 0 reads it to determine resume point.

```json
{
  "domain": "{domain}",
  "started_at": "{ISO-8601}",
  "last_updated": "{ISO-8601}",
  "current_phase": 3,
  "completed_phases": [1, 2],
  "tasks": {
    "task-1": "completed",
    "task-2": "completed",
    "task-3": "in_progress"
  },
  "next_entry_point": "Phase 3 — resume from task-3",
  "artifacts": [
    "_workspace/01_analyst_requirements.md",
    "_workspace/02_architect_design.json"
  ],
  "notes": "{anything blocking or worth preserving across sessions}"
}
```

**Phase 0 reads this file.** If `campaign-state.json` exists and `current_phase > 0`, it's a resume — skip completed phases, jump to `next_entry_point`. If the file is absent or malformed, treat as initial run.

Update `campaign-state.json` atomically at the end of each phase (write to a temp file, rename). Never update mid-phase — a partial write corrupts resume state.

---

## Task Claim Protocol

For team mode with multiple agents that could race to claim tasks, use an explicit claim step to prevent duplicate work.

**Agent-side claim sequence:**

```
1. TaskGet(task_id) → check status
2. If status != "pending": skip — claimed by another agent
3. TaskUpdate(task_id, status: "in_progress", claimed_by: "{this-agent}")
4. Do the work
5. TaskUpdate(task_id, status: "completed")
6. Write artifact to _workspace/
7. SendMessage to orchestrator: "task-{id} done, artifact: _workspace/..."
```

**If agent stops unexpectedly:**

```
TaskUpdate(task_id, status: "blocked", notes: "{last known state}")
SendMessage to orchestrator: "task-{id} blocked — {reason}"
```

This prevents the second most common multi-agent failure: two agents writing to the same artifact path simultaneously. The orchestrator should not assign the same task to multiple agents, but the claim check is a safety net.

**In the orchestrator, after TaskCreate:** monitor via `TaskGet` in a polling loop or wait for `SendMessage` notifications. Don't assume tasks complete in order.

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
