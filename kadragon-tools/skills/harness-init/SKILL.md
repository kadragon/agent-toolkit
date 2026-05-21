---
name: harness-init
version: 0.4.1
description: |
  This skill should be used when the user asks to "set up a harness", "initialize agent infrastructure", "bootstrap AGENTS.md", "bootstrap a repo without a harness", "create agent rules", "set up Claude Code for a new repo", "make this repo agent-ready", "하네스 초기화", "에이전트 설정", or when a repo has no AGENTS.md / docs/ structure and needs one. Also trigger when the user mentions wanting consistent AI-assisted development, delegation to sub-agents, automated code quality checks, or structured agent workflows. Produces: AGENTS.md (map), CLAUDE.md pointer, docs/ knowledge base, backlog.md, sweep automation, .claudeignore, .agents/skills symlink, and optional enforcement hooks. Repo-scoped — does NOT modify global ~/.claude/CLAUDE.md.
---

# Harness Init

Set up complete harness for repo so Claude Code (and other AI agents) do reliable, consistent work. Harness = full environment of scaffolding, constraints, feedback loops, docs surrounding agent.

## Core Philosophy

Three sources inform harness design:

1. **Anthropic** — Generator-Evaluator separation, context reset over compaction, every harness component encodes model-limitation assumption for periodic re-examination
2. **OpenAI** — AGENTS.md is map not encyclopedia (~100 lines), repo is system of record, golden principles enforced mechanically, automated garbage collection
3. **Practical experience** — Progressive disclosure (INDEX -> detail), agent-readable lint errors, sub-agent context manifests

Key insight: **if agent struggles, that's harness defect**, not agent defect. Fix environment, not prompt.

**Simplification principle:** Find simplest solution, increase complexity only when needed. Every harness component encodes assumption about what model can't do alone — start minimal, add scaffolding only on concrete failures. Harness built for weakest model slows stronger model.

## When to Use

- Setting up new repo for AI-assisted development
- Retrofitting existing codebase with agent infrastructure
- After cloning repo with no AGENTS.md or docs/ structure
- When user reports agents keep making mistakes or forgetting context

## Prerequisites

Before starting, gather project info (ask user if not obvious from repo):

1. **Tech stack** — Language(s), framework(s), database, frontend
2. **Project type** — Greenfield, legacy, monorepo, library
3. **Team size** — Solo dev, small team, large org
4. **Existing tooling** — Linters, CI, test frameworks, build tools
5. **Pain points** — What goes wrong when agents work on this repo?

## Execution Steps

Work through steps in order. Each produces concrete artifacts.

### Step 1: Analyze the Repository

Before creating anything, understand what exists.

```
Scan the repo for:
- README.md, CLAUDE.md, AGENTS.md (existing agent config)
- docs/ directory (existing documentation)
- Build/CI config (package.json, Cargo.toml, pom.xml, Makefile, etc.)
- Lint config (.eslintrc, checkstyle, rustfmt, etc.)
- Test infrastructure (test directories, test config)
- Source structure (how code is organized)
- Git history (commit message patterns, branch strategy)
```

Record findings — these shape every artifact created downstream. If existing AGENTS.md or docs/ exist, read them, decide what to keep vs. replace.

### Step 2: Define Golden Principles

Golden principles = 3-7 invariants that, if violated, cause most damage. Must be:
- **Mechanically enforceable** (via lint, test, or hook — not verbal agreement)
- **Specific to this project** (not generic "write clean code")
- **Grounded in real pain** (past bugs, security issues, consistency problems)

Read `references/golden-principles-guide.md` for examples across tech stacks.

**Delegation is golden principle candidate.** Agents overestimate understanding, skip delegation when "merely recommended." If project uses sub-agents, include delegation discipline principle with objective, measurable triggers — not subjective ones like "unfamiliar module." See "Delegation Discipline" section in `references/golden-principles-guide.md`.

Ask user: "What rules, if broken, cause most pain in this codebase?" Answer seeds golden principles.

### Step 3: Create AGENTS.md

AGENTS.md is **map, not encyclopedia**. See `references/harness-invariants.md` → "AGENTS.md Size Policy" for thresholds (target ≤100, hard warn >200). Must fit in agent's context window without crowding actual work.

See `examples/agents-md-example.md` for complete reference.

**Structure:**

```markdown
# {Project Name} Agent Rules

{One-line description of the project and its tech stack.}

## Docs Index (read on demand)

| File | When to read |
|------|--------------|
| `docs/architecture.md` | {when} |
| `docs/conventions.md` | {when} |
| `docs/workflows.md` | {when} |
| `docs/delegation.md` | {when} |
| `docs/eval-criteria.md` | {when} |
| `docs/runbook.md` | {when} |

## Golden Principles

## Delegation

## Token Economy

## Working with Existing Code

## Language Policy

## Maintenance

{embed the AGENTS.md Edit Policy — see below}
```

**Three embedded blocks mandatory in AGENTS.md**, all shown verbatim in `examples/agents-md-example.md`:
1. `## Maintenance` — 4-rule edit policy from `references/harness-invariants.md` → "AGENTS.md Edit Policy"
2. `## Token Economy` — 5-rule block (biggest lever for long-session context)
3. Context-anxiety note — prefer context resets over compaction; write `handoff-{feature}.md` at start of multi-session work, not after context degrades. See `references/workflows-template.md` → "Context Anxiety".

**What NOT to put in AGENTS.md:** workflow details, delegation details, evaluation criteria, architecture deep dives, API references. These belong in `docs/`.

### Step 4: Create docs/ Knowledge Base

Create these files. Each read **on demand**, not loaded every session. Each template file is self-describing — read before writing doc.

| File | Purpose | Template |
|------|---------|----------|
| `docs/architecture.md` | Project structure, layer rules, module boundaries, dependency directions | `references/architecture-template.md` |
| `docs/conventions.md` | Naming, code style, framework rules agents frequently get wrong (don't duplicate linter) | `references/conventions-template.md` |
| `docs/workflows.md` | Six standard workflows (plan/code/draft/constrain/sweep/explore) with delegation gates embedded | `references/workflows-template.md` |
| `docs/delegation.md` | Pattern-selection flowchart, Spawn Prompt Contract, Effort Tier, routing table, per-role model | `references/delegation-template.md` (+ `coordination-patterns.md`) |
| `docs/eval-criteria.md` | Generator-Evaluator separation, Sprint Contract, calibration methodology | `references/eval-criteria-template.md` |
| `docs/runbook.md` | Build/test/deploy commands, failure modes, env setup | `references/runbook-template.md` |

**Non-negotiable for `docs/delegation.md`:** triggers in routing table must be objective and measurable — never subjective conditions ("unfamiliar module") agent can rationalize away.

### Step 4c: Define Reusable Roles (if multi-agent)

Skip if project uses only single session. Otherwise create `.claude/agents/{role}.md` for each recurring role. Claude Code reuses these for both subagent spawns and Agent Teams teammates — define once, use both ways.

Read `references/teammate-role-template.md` for schema and starter pack (implementer, explorer, qa-verifier, product-evaluator). Each role MUST include:

- YAML frontmatter: `name`, `description` (measurable triggers only), `tools` allowlist, `model`
- Body sections: **Objective**, **Spawn Prompt Contract** (4 fields), **Effort Tier**, **Exit Criteria**

Routing table in `docs/delegation.md` cites roles by name — role file body appended to spawn prompt automatically.

Also write `references/handoff-template.md`-style `handoff-{feature}.md` schema reference into `docs/workflows.md` for multi-session work. Handoff files are deferred Spawn Prompt Contracts.

### Step 4b: Create Sprint / Backlog Files

Required so `harness-sync` C (reconciliation) is no-op on first run. Without these, sync silently reports `Backlog clear.` forever (harmless but wasteful) or warns about missing schema.

Create at repo root:

- **`backlog.md`** — queue of work not yet in flight. Copy minimal template from `references/backlog-template.md`. Empty sections fine.
- **`tasks.md`** — DO NOT create at init time. Exists only during active sprint. Include template path (`references/tasks-template.md`) as reference in `docs/workflows.md` so first sprint starter knows schema.

Both files follow **Reconciliation Contract** documented in `references/harness-invariants.md`.

### Step 5: Set Up Sweep Automation

Copy `scripts/sweep.sh` into target project's `tools/` directory, adapt `# ADAPT:` sections. Read `references/sweep-template.md` for ecosystem-specific adaptation guidance.

Sweep script performs five checks: lint scan, doc drift, golden principle violations, harness freshness, finding report. Includes periodic **load-bearing assessment** — stress-testing whether each harness component still compensates for real model limitation. See `references/sweep-template.md` → "Load-Bearing Assessment".

**Trigger policy required** — sweep deliberately NOT part of session-start sync loop (too heavy for every session). Pick one, document in `docs/runbook.md`:

- **Manual** (default) — developer runs `bash tools/sweep.sh` between features
- **SessionStart hook** — `.claude/settings.json` hook with staleness guard (e.g., skip if `tools/.sweep-stamp` <7 days old)
- **Cron / CI** — weekly GitHub Actions job or `CronCreate` schedule

Whichever chosen, record in `references/harness-invariants.md` → "Sweep Trigger Policy" so future sessions know cadence.

### Step 6: Improve Lint for Agent Readability

If project has linters, improve error messages for agent consumption:

**Before (human-oriented):**
```
ERROR: Line 42 — violation of rule X
```

**After (agent-readable):**
```
ERROR: Line 42 — violation of rule X
  FIX: {what to change and how}
  REF: {which doc or config file explains this rule}
```

Each error message becomes micro-instruction telling agent exactly how to fix issue.

### Step 7: Build the Enforcement Chain

Build multi-layer enforcement chain so golden principles are mechanically guaranteed. Read `references/enforcement-template.md` for detailed templates per layer.

**Four layers (defense in depth):**
1. **Real-time hooks** (`.claude/settings.json`) — Catch violations at edit time. If Agent Teams enabled, also wire `TaskCreated` / `TaskCompleted` / `TeammateIdle` hooks — see `references/enforcement-template.md` → "Agent Teams Quality Gates". `TaskCreated` hook mechanically enforces 4-field Spawn Prompt Contract.
2. **Pre-commit checks** — Block commits with unfixed violations
3. **CI gate** — Block merges on failure
4. **PR template** (optional) — Checklist derived from golden principles

Match enforcement depth to team size and risk tolerance. Not every project needs all 4 layers. Two extras from `references/enforcement-template.md`: `[[ =~ ]]` performance rule for hook scripts (§Performance) and Bash Output Truncation PostToolUse hook (§Bash Output Truncation) — zero-judgment win for repos with verbose command output.

### Step 8: Create Repo Root Configs

Three items at repo root. All mechanical wins — "create once, benefits every session."

#### `CLAUDE.md` (pointer)

```markdown
@AGENTS.md
```

Keeps loading chain clean: Claude loads `CLAUDE.md` → `AGENTS.md` (map) → `docs/` (on demand). Invariant enforced by `harness-sync` B.

#### `.claudeignore` (scan exclusions)

Prevents token burn on vendored deps, build outputs, generated artifacts. Compose from `references/claudeignore-template.md` (Common + language sections) based on Step 1 stack analysis.

#### `.agents/skills` symlink

Tooling looks up project-local skills via `.agents/` while files live under `.claude/skills/`. Invariant enforced by `harness-sync` E. Create once at init:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/harness-sync/scripts/symlink-guard.sh
```

Accepted forms (POSIX symlink or Windows text-file fallback) documented in `references/harness-invariants.md` → File Layout Invariants.

### Step 8b: Agent Teams Onboarding (optional)

Enable Claude Code's experimental Agent Teams only if project has real parallel workloads (cross-layer refactors, multi-lens code review, adversarial debugging). Read `references/agent-teams-onboarding.md` for decision checklist and full setup.

If enabled, also add adversarial debugging playbook as on-demand workflow: `references/competing-hypotheses-playbook.md`. Maps to `debate` workflow in `docs/workflows.md` — invoked rarely, high value when stakes justify token cost.

Skip for solo workloads and most CRUD apps. Agent Teams carries 3-5× token cost and meaningful coordination overhead.

### Step 9: Validate

Run `scripts/validate-harness.sh` against target project to verify all artifacts complete and consistent. Script checks:

- Required files exist (`AGENTS.md`, `CLAUDE.md`, `docs/*`, `backlog.md`)
- AGENTS.md size within policy band (see `references/harness-invariants.md`)
- `CLAUDE.md` is exactly `@AGENTS.md`
- `.agents/skills` points to `../.claude/skills`
- `backlog.md` schema (checkbox items under `##` headings)
- AGENTS.md `## Maintenance` section contains edit-policy rules
- Golden Principles, Delegation, enforcement layers present

Clean validate run means `harness-sync` on first invocation is no-op.

Manual checklist for items script cannot verify:
- [ ] Golden principles enforceable (each has lint rule, test, or hook)
- [ ] Delegation table specifies model per role (haiku/sonnet/opus)
- [ ] Eval criteria concrete and gradeable (not vague)
- [ ] `docs/` files don't duplicate each other
- [ ] Sweep trigger policy recorded in `docs/runbook.md`

### Step 10: Explain to the User

After setup, walk user through what was created. Key points:

- AGENTS.md is entry point — keep short, point to docs/
- `## Maintenance` section in AGENTS.md carries edit-policy rules; apply whenever touching AGENTS.md
- Run sweep per chosen trigger (manual / hook / cron)
- Update docs/ after implementing features — stale docs worse than no docs
- Golden principles should evolve — add when new pain points emerge, remove when model capability makes them unnecessary

**Handoff to `harness-sync`:** from this point, `harness-sync` runs silently at session start to keep harness tidy. Maintains these exact invariants (CLAUDE.md pointer, `.agents/skills` symlink, backlog/tasks schemas, AGENTS.md size warnings). If sync reports unexpected drift on first run, treat as init bug — not sync false positive — fix template here.

## Additional Resources

All `references/*.md` files cited inline at point of use — consult there. One file optional, not cited inline:
- **`references/power-user-settings.md`** — Optional env vars (AUTOCOMPACT threshold, extended thinking) and output-style customization. Informational, not auto-applied; surface to user after Step 10 if they ask for further tuning.

### Scripts

- **`scripts/sweep.sh`** — Base sweep script to copy and adapt per project (Step 5)
- **`scripts/validate-harness.sh`** — Validates harness completeness (Step 9)

### Examples

- **`examples/agents-md-example.md`** — Complete AGENTS.md for Next.js SaaS project with all three mandatory embedded blocks