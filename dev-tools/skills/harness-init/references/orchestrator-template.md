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

The `description:` field is the **primary discovery mechanism** for skill auto-invocation — get it right first; everything else is a fallback. Anthropic's own skill-creator testing reports directive phrasing ("ALWAYS invoke when …") improves trigger rate on 5 of 6 public skills compared to descriptive phrasing ("Triggers on …"). Description discovery is imperfect (~50% baseline for weak descriptions, [Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)", 2025-11-06](https://scottspence.com/posts/claude-code-skills-dont-auto-activate)); the UserPromptSubmit router (`references/trigger-router-template.md`) is the **optional fallback** for a specific delegation that still measurably misfires after the description is directive — not a default companion.

**Localization note.** Templates below include Korean trigger phrases (e.g. `"{domain} 실행해줘"`) because this harness is authored for a bilingual KO/EN user. For **English-only repos, drop the Korean lines** when copying the template — leaving them in pollutes the description with unused tokens and may confuse the model's matcher. For other-language repos, translate the trigger phrases to the target language. Keep the English lines in every case (they're the lingua franca for Claude's auto-invocation).

**Required pattern for orchestrator descriptions:**

```yaml
description: |
  ALWAYS invoke this skill when the user asks for {domain} work. Do NOT inline-execute {domain} tasks.
  Trigger phrases (Korean + English):
  - "{domain} 실행해줘", "{domain} 시작", "{domain} 다시 실행"
  - "run {domain}", "start {domain}", "{domain} again"
  No cross-session resume — scratchpad artifacts are gone once the session ends.
  Validation: "{domain} 검증", "{domain} 상태", "validate {domain}"
  Skip only if user explicitly says "inline" / "직접" / "without orchestrator".
```

Only if you are running the trigger-router *fallback* (Step 7b — installed on a measured miss-rate, not by default), also register the orchestrator in `.claude/trigger-routes.json` so the UserPromptSubmit hook emits an explicit `Use Skill(...)` instruction on match. Absent that, the directive description above is the whole mechanism.

## Skill frontmatter reference (2026)

Only `description` is required (defaults aside). Per the Agent Skills standard plus Claude Code extensions, these fields are available on any `SKILL.md` you generate:

| Field | Use |
|-------|-----|
| `description` (+ `when_to_use`) | What + when. **Combined budget ~1,536 chars — front-load the key use case**; everything past the cap is truncated and never seen. |
| `name` | Display name; defaults to the directory name. |
| `model` | Per-skill model override (e.g. force `opus` for a judgment-heavy orchestrator, `haiku` for a mechanical one). |
| `effort` | Per-skill reasoning effort (`low`…`max`). |
| `disable-model-invocation: true` | Manual-only (`/name`); also keeps it out of subagent preload. Use for destructive or expensive skills that must not auto-fire. |
| `user-invocable: false` | Hide from the `/` menu — background knowledge the model consults but the user never calls directly. |
| `allowed-tools` / `disallowed-tools` | Gate which tools are usable while the skill is active. |
| `paths` | Glob-gate auto-activation — the skill surfaces only when matching files are in play (same mechanism as path-scoped rules). |
| `context: fork` + `agent` | Run the skill body in a forked subagent so its work doesn't pollute the lead context. |
| `hooks` | Skill-scoped lifecycle hooks, active only while the skill runs. |

**Progressive-disclosure reminder:** only `description`/`when_to_use` sit in the always-loaded listing; the SKILL.md **body loads only on invocation and then persists across turns** — so keep the body concise and push long material to `references/` (loaded on demand, near-zero cost until needed).

**Dynamic context injection:** `` !`command` `` in the body runs the command and inlines its output before the model sees the skill (e.g. `` !`git diff --stat HEAD` ``) — useful for an orchestrator that needs live repo state at invocation.

Custom slash commands and skills are unified — `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` both expose `/deploy`. Prefer the skill form for anything with supporting files or progressive disclosure.

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
  No cross-session resume — artifacts live in the scratchpad and are gone once the session ends.
  Skip only if user says "inline" / "직접" / "without orchestrator".
---

## Phase 1: Preparation

Determine your scratchpad path from your own system prompt (never guess or reconstruct it). Read inputs, validate preconditions.

File naming convention: `{phase:02d}_{agent}_{artifact}.{ext}`
Examples: `01_analyst_requirements.md`, `02_architect_design.json`

Embed the full scratchpad path explicitly in every spawn prompt below — sub-agents/teammates must not derive it independently.

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
- **Artifacts**: Write to `{scratchpad}/{phase}_{agent}_{artifact}.{ext}`

## Phase 4: Integration

Read agent artifacts from the scratchpad, synthesize, produce final output.

Error policy:
- 1 agent fails → retry once
- Retry fails → proceed without that agent's output; note omission in report
- Majority fail → stop, report to user with scratchpad artifact paths

## Phase 5: Cleanup

```
TeamDelete(team_name: "{domain}-team")
```

No cleanup needed — the scratchpad is session-scoped and self-cleaning.
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

## Phase 1: Spawn Sub-agents

Determine your scratchpad path from your own system prompt. Launch independent agents in parallel in a single turn, embedding the full scratchpad path in each spawn prompt:

```
Agent(subagent_type: "{agent-1}", prompt: """
  Objective: {specific task}
  Output format: {format}
  Tools to use: {subset}
  Boundaries: {must not touch}
  Save output to: {scratchpad}/01_{agent-1}_result.md
""", run_in_background: true)

Agent(subagent_type: "{agent-2}", prompt: """
  Objective: {specific task}
  ...
  Save output to: {scratchpad}/01_{agent-2}_result.md
""", run_in_background: true)
```

All four Spawn Prompt Contract fields are mandatory (Objective / Output format / Tools to use / Boundaries).

## Phase 2: Collect and Integrate

Read artifacts from the scratchpad, produce final output.

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

Between phases, save artifacts to the scratchpad, then switch mode:

```markdown
## Phase 2: Parallel Gathering (sub-agent)
[spawn sub-agents, collect to {scratchpad}]

## Phase 3: Team Synthesis (team)
TeamCreate(...)
[read {scratchpad} artifacts, coordinate via SendMessage]
TeamDelete(...)

## Phase 4: Independent Verification (sub-agent)
[spawn verifier sub-agent reading {scratchpad} artifacts]
```

---

## Scratchpad Convention

```
{scratchpad}/
  {phase:02d}_{agent}_{artifact}.{ext}
  01_analyst_requirements.md
  02_architect_design.json
  03_implementer_billing_diff.patch
```

Rules:
- All agent-artifact paths under the session scratchpad dir (path from the system prompt — never guess it)
- The orchestrator determines the path once and embeds it explicitly in every spawn prompt; sub-agents/teammates must not derive it themselves
- Final deliverables go to user-specified path; intermediates stay in the scratchpad
- Ephemeral by design — gone when the session ends, no cross-session resume
- **This is a different mechanism from the delegation gate's evidence files.** If `references/enforcement-template.md`'s PreToolUse gate is installed, its evidence files live in the repo-local `.claude/tmp/` (not the scratchpad) and still require `{area}_{session_id}` stamping — see that file for the naming convention. Do not conflate the two.

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
6. Write artifact to {scratchpad}
7. SendMessage to orchestrator: "task-{id} done, artifact: {scratchpad}/..."
```

**If agent stops unexpectedly:**

```
TaskUpdate(task_id, status: "blocked", notes: "{last known state}")
SendMessage to orchestrator: "task-{id} blocked — {reason}"
```

This prevents the second most common multi-agent failure: two agents writing to the same artifact path simultaneously. The orchestrator should not assign the same task to multiple agents, but the claim check is a safety net.

**In the orchestrator, after TaskCreate:** monitor via `TaskGet` in a polling loop or wait for `SendMessage` notifications. Don't assume tasks complete in order.

---

## docs/harness-log.md Pointer (register after orchestrator created)

Add to `docs/harness-log.md` (and register the file as a Docs Index row in AGENTS.md — never CLAUDE.md, which stays a pure `@AGENTS.md` pointer):

```markdown
## Harness: {Domain}

**Goal:** {one line}

**Trigger:** For {domain} work, use the `{domain}-orchestrator` skill.

**Change History:**
| Date | Change | Scope | Reason |
|------|--------|-------|--------|
| {YYYY-MM-DD} | Initial setup | all | - |
```

Keep `docs/harness-log.md` as a thin pointer — trigger rule + change history only. Agent list, skill list, directory structure → do NOT put here.
