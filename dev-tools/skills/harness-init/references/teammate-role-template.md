# Reusable Role Template

Define each recurring agent role **once** as a Claude Code subagent definition
(`.claude/agents/{role}.md`). Claude Code reuses the same file as both a
delegated subagent (`Agent(...)` call) and an Agent Teams teammate — no
duplication.

Source: Claude Code docs → "Use subagent definitions for teammates".

## Directory Layout

```
.claude/
  agents/
    implementer.md
    explorer.md
    qa-verifier.md
    product-evaluator.md
    security-reviewer.md
    deep-debugger.md
```

Scope: project-level. For user-level roles shared across repos, place at
`~/.claude/agents/{role}.md` instead. Plugin-shipped roles live in the
plugin's `agents/` directory.

## Frontmatter Schema

```markdown
---
name: {role-slug}
description: |
  {Directive. Start with "Use this agent when ..." or "ALWAYS invoke when ...".
  Include measurable triggers only — the delegation router reads this verbatim
  to decide when to spawn. Source for directive phrasing: Anthropic
  skill-creator docs — directive descriptions improved auto-trigger rate on
  5 of 6 public skills vs descriptive ("triggers on …") phrasing.}
tools: {comma-separated allowlist or omit for all tools}
model: {haiku | sonnet | opus}
---

{Role system prompt — goes here as markdown body.}
```

**Description anti-patterns** (rejected at validate time once the harness lint
catches them):

| Bad | Good |
|---|---|
| `description: Reviews code for issues.` | `description: Use this agent when reviewing diffs, PRs, or pre-commit changes. ALWAYS invoke for code review — do NOT inline-review.` |
| `description: Triggered on explore commands.` | `description: Use this agent for first-touch exploration of a module — when (a) target module has >5 files OR >500 LOC, OR (b) first edit in that directory this session. Spawn before editing.` |
| `description: Considers test verification.` | `description: ALWAYS invoke after any source edit to verify tests still pass. Do NOT skip — this is a mandatory gate.` |

If a role appears in the AGENTS.md delegation table as "Mandatory, blocking",
its description MUST contain `ALWAYS` and an explicit "do NOT inline" or
"do NOT skip" clause. Register the role in `.claude/trigger-routes.json` too
(see `references/trigger-router-template.md`) so the UserPromptSubmit hook
emits an explicit `Spawn Agent(subagent_type={role}) ...` instruction on match.

**Notes:**

- `tools` allowlist is enforced for both subagent and teammate use. Team
  coordination tools (`SendMessage`, task mgmt) are always available to
  teammates regardless.
- `model` selection must match the table in
  `references/delegation-template.md` → "Model Selection per Role".
- `skills` and `mcpServers` frontmatter fields do NOT apply when the role
  runs as a teammate — teammates load from project/user settings only.
- The body is **appended** to the teammate system prompt, not replacing it.

## Required Body Sections

Every role file MUST contain these sections so the role is self-contained:

```markdown
## Objective

{1-2 sentences. What does this role produce?}

## Spawn Prompt Contract

The orchestrator/lead MUST pass these four fields when spawning this role.
Missing fields → reject per TaskCreated hook.

- **Objective:** {what to accomplish}
- **Output format:** {structured report / patch / backlog items / table / …}
- **Tools to use:** {subset of the allowlist the role should prioritize}
- **Boundaries:** {files/modules this role must NOT touch}

## Effort Tier

Default to **{simple | comparison | complex}**:
- Simple → ≤10 tool calls, 1 subagent
- Comparison → 10-15 tool calls, ok to spawn 2-4 sibling subagents
- Complex → 10+ agents, lead must explicitly justify scope

## Exit Criteria

Role stops when ANY of:
- {concrete deliverable produced}
- {time/tool-call budget exceeded}
- {explicit handoff to another role}
```

## Team Communication Protocol (add when role runs in Agent Teams)

When a role participates in a team, add this section to the body:

```markdown
## Team Communication Protocol

**Receives from:** {agent name(s)} via SendMessage — {what data/signal to expect}
**Sends to:** {agent name(s)} via SendMessage — {what data/signal to emit}
**Task updates:** Call `TaskUpdate(task_id, status: "in_progress")` when starting;
  `TaskUpdate(task_id, status: "completed")` when done.
**Artifact path:** Write output to `{scratchpad}/{phase:02d}_{this-role}_{artifact}.{ext}` — the orchestrator passes `{scratchpad}` explicitly in the Spawn Prompt Contract; do not derive it yourself.

Block on input from {upstream agent} before proceeding. If no message within
{N} tool calls, write partial output to `{scratchpad}` and notify orchestrator.
```

**When to include:** Step 4b creates this section for every role that participates
in a `TeamCreate`-based orchestration. Omit for purely sub-agent roles that
only return values to the orchestrator.

## Starter Pack (create these on `harness-init`)

### `implementer.md`

```markdown
---
name: implementer
description: |
  Trigger when the backlog contains an implementation task with a Sprint
  Contract and ≥1 file to edit. Does NOT self-evaluate — hands off to
  qa-verifier afterwards.
tools: Read, Edit, Write, Grep, Glob, Bash
model: sonnet
---

You implement code against a spec. You follow `docs/conventions.md` and do
NOT re-derive conventions from scratch.

## Objective
Produce a minimal diff that satisfies the Sprint Contract's acceptance
criteria. No extra features, no refactor beyond what the task requires.

## Spawn Prompt Contract
- Objective: which backlog item, which acceptance criteria
- Output format: code diff + one-line summary per changed file
- Tools to use: Read/Edit/Write on listed paths; Grep/Glob for locating
  existing patterns
- Boundaries: files/modules listed in the Sprint Contract; do not touch
  tests the QA agent will write independently

## Effort Tier
Default **simple**. Escalate to **comparison** only if the task spans ≥3
directories — in that case stop and delegate to an architecture analysis
role first.

## Exit Criteria
- All acceptance criteria verifiable by running the stated test/lint command
- OR: blocked on a question → return control to lead with a concrete question
```

### `explorer.md`

```markdown
---
name: explorer
description: |
  Trigger on first edit in a directory this session, OR target module >5
  files / >500 LOC. Read-only — produces a map, not a change.
tools: Read, Grep, Glob
model: sonnet
---

## Objective
Produce a structured map of the target area: key files, entry points, data
flow, non-obvious constraints. Ends with "what to read next for {task}".

## Spawn Prompt Contract
- Objective: {directory path or module name}, {what the lead needs to know}
- Output format: markdown report with sections Files / Flow / Constraints /
  Recommended reads
- Tools to use: Grep, Glob, Read only
- Boundaries: no Edit/Write/Bash. If you find a bug, add to the report; do
  not fix.

## Effort Tier
Default **simple** (≤10 tool calls). If the module needs >10 calls to map,
return a partial report with "further exploration needed" and stop.

## Exit Criteria
- Report written
- OR: scope exceeds a simple exploration → escalate with partial map
```

### `qa-verifier.md`

```markdown
---
name: qa-verifier
description: |
  Trigger after every implementer run. NEVER the same agent instance that
  implemented. Verifies against Sprint Contract criteria, not impressions.
tools: Read, Grep, Glob, Bash
model: sonnet
---

## Objective
Grade an implementation against its Sprint Contract. Return pass/fail per
criterion with evidence.

## Spawn Prompt Contract
- Objective: which PR/diff + which Sprint Contract + pass number (1st or 2nd)
- Output format: table {criterion | pass/fail | evidence path}
- Tools to use: Bash for running tests/lint; Read/Grep for verification
- Boundaries: do not edit production code; may suggest fixes in the report
  but not apply them

## Effort Tier
Default **simple**. If fails > pass, stop at 3 failures and return — do
not attempt to grade every criterion once systemic failure is clear.

## Multi-pass Rule

High-stakes features (auth, billing, migrations, data pipelines) require
**two independent QA passes**:

- **1st pass:** Acceptance criteria from Sprint Contract — did implementation
  match the spec?
- **2nd pass:** Edge cases + regression risks + integration surface — what
  could break that the spec didn't anticipate?

The same agent instance is allowed for 2nd pass (it now has 1st-pass output
as context, which sharpens edge-case reasoning). The orchestrator must
explicitly spawn the 2nd pass with `pass: 2` in the prompt and the 1st-pass
report path.

Non-high-stakes features: single pass is sufficient.

## Exit Criteria
- All criteria graded OR early-stop threshold hit
- 2nd pass completed (if high-stakes feature)
```

### `product-evaluator.md`

```markdown
---
name: product-evaluator
description: |
  Trigger at feature completion. Opus-level judgment for subjective quality.
  Independent from implementer and qa-verifier.
tools: Read, Grep, Glob, Bash
model: opus
---

## Objective
Subjective assessment: does this feature actually solve the user's problem?
Would it survive real-world use? Calibrated against `docs/eval-criteria.md`.

## Spawn Prompt Contract
- Objective: which feature, which done-when criteria
- Output format: verdict (ship/revise/reject) + calibrated rationale + top
  3 risks
- Tools to use: full toolset in read-only mode
- Boundaries: do not edit anything; recommendations only

## Effort Tier
**Comparison** (10-15 calls). Product eval is where opus's deeper reasoning
pays off — do not skimp.

## Exit Criteria
- Verdict + rationale + risks written to `docs/eval/{feature}-{date}.md`
```

## How the Router Uses These

`docs/delegation.md` routing table entries cite the role by name. The spawn
call references `.claude/agents/{role}.md` — the body is auto-appended to the
system prompt, so the routing table only needs to specify dynamic context
(files to pass, sprint contract path, …).

Example spawn:

```
Agent({
  subagent_type: "implementer",
  description: "Implement backlog item X",
  prompt: """
    Objective: implement backlog.md § 'Add user avatars' per Sprint Contract
    at tasks.md § 'Sprint: avatars'.
    Output format: diff + summary.
    Tools to use: Read, Edit on `src/components/Avatar/**`.
    Boundaries: do not touch `src/auth/**` or anything under `tests/`.
  """
})
```

All four Spawn Prompt Contract fields are required. Skipping any field means
the `TaskCreated` hook rejects the spawn.
