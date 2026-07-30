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
  {Directive. Start with "Use this agent when ...". State the measurable
  triggers that make this role the right fit — the delegation router reads this
  verbatim to decide when to spawn. Source for directive phrasing: Anthropic
  skill-creator docs — directive descriptions improved auto-trigger rate on
  5 of 6 public skills vs descriptive ("triggers on …") phrasing. Reserve
  "ALWAYS invoke" / "do NOT inline" for roles the delegation table marks
  "Mandatory, blocking" — see the rule below the anti-pattern table.}
tools: {comma-separated allowlist or omit for all tools}
model: {haiku | sonnet | opus}
---

{Role system prompt — goes here as markdown body.}
```

**Description anti-patterns** (rejected at validate time once the harness lint
catches them):

| Bad | Good |
|---|---|
| `description: Reviews code for issues.` | `description: Use this agent when reviewing a diff that touches auth, billing, or migrations, or that spans >N files.` |
| `description: Triggered on explore commands.` | `description: Use this agent to map a module before editing it — when the target has >N files or >M LOC, per this repo's delegation table.` |
| `description: Considers test verification.` | `description: Use this agent to verify an implementation against its Sprint Contract after a separate agent implemented it. Never the agent that wrote the code.` |

Note what the "Good" column does *not* do: it states measurable fit, not an
unconditional mandate. A description that reads `ALWAYS … do NOT inline` makes
the role fire on every superficially matching turn regardless of whether the
delegation bar is met, which is the drift the next rule bounds.

`>N` / `>M` are placeholders — substitute the thresholds from this repo's own
delegation table, and keep them at or above what the platform's global
instruction layer requires, never below. Do not replace them with a subjective
condition ("unfamiliar module", "if unsure") or with a self-assessment that
defers to "the caller's delegation bar": `delegation-template.md` →
*Trigger Anti-patterns* rejects all three, and a description is read by the
router before any caller judgment exists to defer to.

If — and only if — a role appears in the AGENTS.md delegation table as
"Mandatory, blocking", its description MUST contain `ALWAYS` and an explicit
"do NOT inline" or "do NOT skip" clause — for that role the directive
description is the primary trigger. A role that is merely *available* for
delegation gets a fit-description instead; the caller's own bar decides. Only
if the repo runs the trigger-router *fallback* (Step 7b — installed on a
measured miss-rate, not by default), also register the role in
`.claude/trigger-routes.json` (see `references/trigger-router-template.md`) so
the hook emits an explicit `Spawn Agent(subagent_type={role}) ...` on match.

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

### Exemption: deliberately lean roles

One class of role is exempt: a **pure role-play or single-shot worker spawned in bulk**, where the
whole prompt arrives per call and four stub sections would buy nothing but per-spawn tokens.
Declare it in the frontmatter:

```markdown
spine-exempt: true
```

`validate-harness.sh` §11 then waives the four section checks for that file and reports it as a
`PASS`. The frontmatter fields stay required — the router reads them regardless.

The marker exists so the intent is **mechanical rather than tribal**: without it, a lean role is
indistinguishable from a stale one, and a permanent WARN the repo has already ruled correct-by-
design trains the operator to skim past §11 entirely. Reach for it only when the leanness is the
point; a role that merely *has not been written yet* is stale, not exempt.

### Common spine vs repo-specific additions

Nothing *regenerates* a role file when this template changes — the paths that revisit one are all
repo-driven (Extend mode's `Architecture change` row in `SKILL.md`, the feedback signals plus
Periodic Audit in `references/harness-evolution.md`), never template-driven. What closes that gap
is `scripts/validate-harness.sh` §11, which reports drift on every validate run. It is a reporting
check, not a rewriter: resyncing a flagged file stays a human decision.

Not all drift is equal — before treating a difference as staleness, classify it:

| Layer | Owner | Drift means |
|---|---|---|
| Frontmatter schema (required fields present, `model` from the Model Selection table) | this template | stale instance — the template is the source of truth |
| The four spine sections above (Objective, Spawn Prompt Contract, Effort Tier, Exit Criteria) | this template | stale instance — the template is the source of truth |
| Non-spine sections this template ships (`## Multi-pass Rule`, `## Team Communication Protocol`) | this template, but **opt-in per role** | absence is not staleness — they apply only to roles that need them |
| Sections a repo *adds* (e.g. `## Checks (always run)`, `## Domain-safety pass`) | the repo | intended specialization — never overwrite |
| Wording inside any shared section (test/lint commands, path globs, thresholds) | the repo | intended — the section is common, its contents are local |

Measured 2026-07-29 across four repos generated from this template (`qa-verifier.md`, 27–36 lines,
four distinct hashes): every instance carried all four spine sections; every difference was either
an added repo-specific section or repo-local wording inside a shared one. No instance was missing
spine structure. Note none carried `## Multi-pass Rule` either — which is why row 3 exists: a
differ that treated every template section as required would report four false positives here.

`validate-harness.sh` §11 implements exactly that boundary: it reconciles **frontmatter-field
presence** (`name`, `description`, `model`; `tools` is optional per the schema above) **and
spine-section presence** — the latter waived by `spine-exempt: true` — and emits `WARN`, never
`FAIL`, never an edit. Section contents, repo-added sections, and the opt-in non-spine sections
are out of its remit. Any future resync tool inherits the same limits.

## Team Communication Protocol (add when role runs in Agent Teams)

When a role participates in a team, add this section to the body:

```markdown
## Team Communication Protocol

**Receives from:** {agent name(s)} via SendMessage — {what data/signal to expect}
**Sends to:** {agent name(s)} via SendMessage — {what data/signal to emit}
**Task updates:** Call `TaskUpdate(taskId, status: "in_progress")` when starting;
  `TaskUpdate(taskId, status: "completed")` when done.
**Artifact path:** Write output to `{scratchpad}/{phase:02d}_{this-role}_{artifact}.{ext}` — the orchestrator passes `{scratchpad}` explicitly in the Spawn Prompt Contract; do not derive it yourself.

Block on input from {upstream agent} before proceeding. If no message within
{N} tool calls, write partial output to `{scratchpad}` and notify orchestrator.
```

**When to include:** Step 4b creates this section for every role that participates
in a team-mode orchestration (spawned by the lead as a named teammate, not via any
team-creation call — see `orchestrator-template.md` → Phase 2). Omit for purely sub-agent roles that
only return values to the orchestrator.

## Role Templates (create the reachable ones on `harness-init`)

These are templates, not a mandatory set. Create a role only if its delegation
trigger is reachable in the target repo — see the reachability gate in
`SKILL.md` Step 4b. Most repos keep 1–3.

### `implementer.md`

```markdown
---
name: implementer
description: |
  Use this agent for an implementation task that already has a Sprint Contract
  and a listed set of files to edit — when that list spans >N files or ≥3
  independent units. Does NOT self-evaluate; hands off to qa-verifier
  afterwards.
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
  Use this agent to map a module before editing it — when the target has >N
  files or >M LOC, per this repo's delegation table. Read-only: produces a map,
  not a change.
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
  Use this agent to verify an implementation a *different* agent produced.
  NEVER the same agent instance that implemented — that constraint holds
  whenever verification is delegated at all. Verifies against Sprint Contract
  criteria, not impressions.
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
  Use this agent at feature completion when the quality question is subjective
  — does this actually solve the user's problem? Opus-level judgment,
  independent from implementer and qa-verifier.
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
