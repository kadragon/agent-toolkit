---
name: harness-init
version: 0.6.0
description: |
  This skill should be used when the user asks to "set up a harness", "initialize agent infrastructure", "bootstrap AGENTS.md", "bootstrap a repo without a harness", "create agent rules", "set up Claude Code for a new repo", "make this repo agent-ready", "하네스 초기화", "에이전트 인프라 초기화", "에이전트가 자꾸 실수해요", "Claude Code 리포지토리 설정", or when a repo has no AGENTS.md / docs/ structure and needs one. Also trigger when the user mentions wanting consistent AI-assisted development, delegation to sub-agents, automated code quality checks, or structured agent workflows. Produces: AGENTS.md (map), CLAUDE.md pointer, docs/ knowledge base, backlog.md, sweep automation, .claudeignore, .agents/skills symlink, and optional enforcement hooks. Repo-scoped — does NOT modify global ~/.claude/CLAUDE.md.
  Also use when the user asks to "sync harness", "harness sync", "harness 동기화", "AGENTS.md 정리", "AGENTS.md 업데이트", "backlog 정리", "tasks 정리", "하네스 유지보수" — load references/maintenance.md for the full A–G routine. Note: B (CLAUDE.md sync), E (symlink guard), F (context size check) run automatically via SessionStart hook — manual sync is primarily for C (reconcile tasks→backlog) and G (validate).
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

> Trigger conditions are in the frontmatter description above.

## Prerequisites

Before starting, gather project info. **Scan repo first (Step 1: read existing files, git log, package.json). Ask user only for answers that code doesn't reveal** (e.g., team size, sprint cadence, external integrations).

1. **Tech stack** — Language(s), framework(s), database, frontend
2. **Project type** — Greenfield, legacy, monorepo, library
3. **Team size** — Solo dev, small team, large org *(ask user — not in code)*
4. **Existing tooling** — Linters, CI, test frameworks, build tools
5. **Pain points** — What goes wrong when agents work on this repo?

## Execution Steps

Work through steps in order. Each produces concrete artifacts.

### Step 0: Classify the Request

Before acting, determine mode AND maturity level.

**Mode selection:**

| Condition | Mode | Action |
|-----------|------|--------|
| No `AGENTS.md`, no `docs/`, no `.claude/agents/` | **New setup** | Run Steps 1–10 |
| Existing harness, user adds agent/skill/area | **Extend** | Run only affected steps (see matrix below) |
| User asks "sync harness", "harness 점검", "update AGENTS.md" | **Maintain** | Load `references/maintenance.md` |

**Maturity assessment (for New setup and Extend mode):**

Run `scripts/validate-harness.sh` against the target repo (if it exists). Classify as Level 1 / 2 / 3 per `references/maturity-levels.md`. Report the current level and which level to target.

- **Default target:** Level 2 (CI-verified). Propose Level 3 only for multi-agent or high-risk repos.
- **Solo dev / greenfield:** Level 1 suffices; offer Level 2 upgrade path.
- **Existing repo, partial harness:** Start from current level, advance one level per session.

**Extend mode — step selection matrix:**

| Change type | Steps to run |
|-------------|-------------|
| Add agent role | 4b (new role file) → 4c (update orchestrator) → 9 (validate) |
| Add/modify skill | 4c (skill update) → 9 |
| Add new domain with orchestrator | 4b + 4c + 4d → 9 |
| Architecture change | Affected docs → 4b (impacted roles) → 4c → 9 |

Report mode + current maturity level + target level before proceeding.

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

**Add the Agent Integrity Principle universally** — include it in every project's golden principles (see `references/golden-principles-guide.md` → "Agent Integrity Principle"). Prevents agents fabricating values not directly observed. Mark unverified values as `[unknown — read {source} to verify]` instead of guessing.

### Step 3: Create AGENTS.md

AGENTS.md is **map, not encyclopedia** (target ≤100 lines; hard warn at >200 — keeps harness within agent context window). Must fit in agent's context window without crowding actual work.

See `examples/agents-md-example.md` for complete reference.

**Required sections:** `## Docs Index`, `## Golden Principles`, `## Delegation`, `## Token Economy`, `## Working with Existing Code`, `## Language Policy`, `## Maintenance`. Full structure in `examples/agents-md-example.md`.

**Three embedded blocks mandatory in AGENTS.md** — copy verbatim from `examples/agents-md-example.md` (do not paraphrase): `## Maintenance` edit policy, `## Token Economy` rules, context-anxiety note.

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

**Complete Step 4a first. If this is a multi-agent project: also complete Step 4b after Step 4a.**

### Step 4a: Create Sprint / Backlog Files

Required so the maintenance routine section C (reconciliation) is no-op on first run. Without these, it silently reports `Backlog clear.` forever (harmless but wasteful) or warns about missing schema.

Create at repo root:

- **`backlog.md`** — queue of work not yet in flight. Copy minimal template from `references/backlog-template.md`. Empty sections fine.
- **`tasks.md`** — DO NOT create at init time. Exists only during active sprint. Include template path (`references/tasks-template.md`) as reference in `docs/workflows.md` so first sprint starter knows schema.

Both files follow **Reconciliation Contract** documented in `references/harness-invariants.md`.

### Step 4b: Define Reusable Roles

Create `.claude/agents/{role}.md` for each recurring role. Claude Code reuses these for both subagent spawns and Agent Teams teammates — define once, use both ways.

Read `references/teammate-role-template.md` for full schema and starter pack (implementer, explorer, qa-verifier, product-evaluator).

**Team communication protocol:** For every role that will participate in `TeamCreate`-based orchestration, add the `## Team Communication Protocol` section (template in `references/teammate-role-template.md`). This section specifies which agents to receive from/send to, task update calls, and `_workspace/` artifact path. Without it, inter-agent coordination degrades to guessing.

Also write `references/handoff-template.md`-style `handoff-{feature}.md` schema reference into `docs/workflows.md` for multi-session work. Handoff files are deferred Spawn Prompt Contracts.

### Step 4c: Create Orchestrator Skill

For any domain with ≥2 coordinating agents, create an orchestrator skill at:
`.claude/skills/{domain}-orchestrator/SKILL.md`

Read `references/orchestrator-template.md` and choose one of:
- **Template A (team)** — agents share findings mid-flight via SendMessage
- **Template B (sub-agent)** — agents return results independently
- **Template C (hybrid)** — phase-dependent: different modes per phase

The orchestrator must include:
1. Phase 0 context detection — read `_workspace/campaign-state.json`; resume from `next_entry_point` if present
2. Explicit data transfer strategy (see `references/delegation-template.md` → Data Transfer Protocols)
3. Error policy (1 retry, graceful degradation, report omissions)
4. `_workspace/` naming: `{phase:02d}_{agent}_{artifact}.{ext}` + `campaign-state.json`
5. Task claim protocol if ≥2 agents share a task pool (see `references/orchestrator-template.md` → Task Claim Protocol)

After creation, register in CLAUDE.md: add `## Harness: {Domain}` pointer block with trigger rule and change history table. Keep CLAUDE.md thin — pointer + history only (no agent list, no skill list).

**Skip if:** project is truly single-agent. The orchestrator is overhead without payoff there.

### Step 4d: _workspace Pattern

If Step 4c created an orchestrator, add a `_workspace/` section to `docs/runbook.md`:

```markdown
## _workspace/ Convention

Intermediate artifacts live under `_workspace/` at repo root.
Naming: `{phase:02d}_{agent}_{artifact}.{ext}`

Preserve across sessions — enables partial re-run without full restart.
Remove only on explicit "reset" request.
```

This makes the convention discoverable to future sessions and new contributors.

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
1. **Real-time hooks** (`.claude/settings.json`) — Catch violations at edit time
2. **Pre-commit checks** — Block commits with unfixed violations
3. **CI gate** — Block merges on failure
4. **PR template** (optional) — Checklist derived from golden principles

**Two Layer 1 extensions (add when appropriate):**
- **Circuit Breaker** — stops failure cascades before token spiral; fires after N consecutive Bash failures (default: 3). See `references/enforcement-template.md` → "Circuit Breaker".
- **Consent Gates** — halts before irreversible external actions (push, PR, deploy) until user confirms. See `references/enforcement-template.md` → "Consent Gates".

Match enforcement depth to maturity level target: Level 1 → no hooks required; Level 2 → Layer 1 + 3; Level 3 → all layers + circuit breaker. Read `references/enforcement-template.md` for templates and Agent Teams hook wiring.

### Step 8: Create Repo Root Configs

Three items at repo root. All mechanical wins — "create once, benefits every session."

#### `CLAUDE.md` (pointer)

```markdown
@AGENTS.md
```

Keeps loading chain clean: Claude loads `CLAUDE.md` → `AGENTS.md` (map) → `docs/` (on demand). Invariant enforced by maintenance routine B (`sync-claude-md.sh`).

#### `.claudeignore` (scan exclusions)

Prevents token burn on vendored deps, build outputs, generated artifacts. Compose from `references/claudeignore-template.md` (Common + language sections) based on Step 1 stack analysis.

#### `.agents/skills` symlink

Tooling looks up project-local skills via `.agents/` while files live under `.claude/skills/`. Invariant enforced by maintenance routine E (`symlink-guard.sh`). Create once at init:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/harness-init/scripts/symlink-guard.sh
```

If skills repo is not cloned or `CLAUDE_PLUGIN_ROOT` is unset, run directly:

```bash
mkdir -p .agents && ln -s ../.claude/skills .agents/skills
```

Accepted forms (POSIX symlink or Windows text-file fallback) documented in `references/harness-invariants.md` → File Layout Invariants.

### Step 8b: Agent Teams Setup (when Step 4c used Template A or C)

If Step 4c created a team-mode orchestrator, complete Agent Teams setup:

Read `references/agent-teams-onboarding.md` for tooling prerequisites and environment check.

Add adversarial debugging playbook as on-demand workflow: `references/competing-hypotheses-playbook.md`. Maps to `debate` workflow in `docs/workflows.md`.

**Skip entirely if:** Step 4c chose Template B (sub-agent only). Agent Teams carries 3–5× token cost — don't enable it without an orchestrator that uses `TeamCreate`.

Token cost note: Team mode is not free. The orchestrator template enforces the decision gate (Q2 in Pattern Selection) so teams only activate when mid-flight coordination genuinely pays off.

### Step 9: Validate

Run `scripts/validate-harness.sh` against target project to verify all artifacts complete and consistent. **If validation exits non-zero, halt immediately. Show the full validation report to the user. Do NOT auto-fix — user must review and decide. Re-run validation after user addresses issues.**

Script checks:

- Required files exist (`AGENTS.md`, `CLAUDE.md`, `docs/*`, `backlog.md`)
- AGENTS.md size within policy band (see `references/harness-invariants.md`)
- `CLAUDE.md` is exactly `@AGENTS.md`
- `.agents/skills` points to `../.claude/skills`
- `backlog.md` schema (checkbox items under `##` headings)
- AGENTS.md `## Maintenance` section contains edit-policy rules
- Golden Principles, Delegation, enforcement layers present

Clean validate run means the maintenance routine is a no-op on first invocation.

Manual checklist for items script cannot verify:
- [ ] Golden principles enforceable (each has lint rule, test, or hook)
- [ ] Delegation table specifies model per role (haiku/sonnet/opus)
- [ ] Eval criteria concrete and gradeable (not vague)
- [ ] `docs/` files don't duplicate each other
- [ ] Sweep trigger policy recorded in `docs/runbook.md`

### Step 10: Explain to the User

After setup, show the user all four of the following — this is the exit criterion for Step 10:

1. **Full AGENTS.md content** — paste or display the entire file so the user can confirm it looks right.
2. **List of all created files with one-line purpose each** — every file produced during init, so nothing is invisible.
3. **How to trigger sweep** — exact command or trigger method chosen in Step 5 (e.g., `bash tools/sweep.sh`).
4. **How to update AGENTS.md when tasks change** — point to the `## Maintenance` rules embedded in AGENTS.md; emphasize: only add when all 4 conditions are met.

After setup, the maintenance routine (`references/maintenance.md`) runs silently at session start to keep harness tidy. Maintains these exact invariants (CLAUDE.md pointer, `.agents/skills` symlink, backlog/tasks schemas, AGENTS.md size warnings). Unexpected drift on first run → treat as init bug — not maintenance false positive — fix template here.

## Harness Evolution

After a harness is in use, it should evolve based on feedback. Trigger evolution when:
- Same feedback appears ≥2× (structural gap signal)
- Agent bypasses orchestrator (description trigger missing)
- Repeated agent failure pattern (definition defect)

Read `references/harness-evolution.md` for feedback → fix target mapping and change history protocol. Record every change in the orchestrator's CLAUDE.md pointer block.

## Ongoing Maintenance

After init completes, B/E/F run automatically via the `toolkit:harness-maintenance` SessionStart hook (daily debounce). Manual sync is for C (reconcile tasks→backlog) and G (validate) — trigger on explicit request ("sync harness", "harness 동기화", etc.). Full A–G procedure in **`references/maintenance.md`** — load only when explicitly needed.

**Scripts (all run from repo root):**

| Script | Maintenance section | Auto? | Purpose |
|--------|---------------------|-------|---------|
| `scripts/sync-claude-md.sh` | B | ✅ hook | Check/fix CLAUDE.md → @AGENTS.md |
| `scripts/reconcile-harness.py` | C | manual | Sync tasks.md status into backlog.md |
| `scripts/symlink-guard.sh` | E | ✅ hook | Ensure .agents/skills symlink |
| `scripts/check-context-size.sh` | F | ✅ hook | Warn when AGENTS.md > 200 lines |
| `scripts/sweep.sh` | post-sync | manual | Archive stale content |
| `scripts/validate-harness.sh` | G / Step 9 | manual | Full structural validation |

## Additional Resources

All `references/*.md` files cited inline at point of use — consult there. Files optional / surfaced on request:
- **`references/orchestrator-template.md`** — 3-mode orchestrator templates (team/sub-agent/hybrid), `_workspace/` convention, CLAUDE.md pointer block. **Read at Step 4c.**
- **`references/harness-evolution.md`** — Feedback-driven evolution: signal → fix target mapping, change history protocol. **Read when harness needs evolution.**
- **`references/maturity-levels.md`** — 3-level progression (Basic/Verified/Enforced), checklist per level, upgrade path. **Read at Step 0 for existing repos.**
- **`references/power-user-settings.md`** — Optional env vars (AUTOCOMPACT threshold, extended thinking) and output-style customization. Informational; surface to user after Step 10 if asked.

### Scripts

- **`scripts/sweep.sh`** — Base sweep script to copy and adapt per project (Step 5)
- **`scripts/validate-harness.sh`** — Validates harness completeness (Step 9)
- **`scripts/sync-claude-md.sh`** — Maintenance B: check/fix CLAUDE.md pointer
- **`scripts/reconcile-harness.py`** — Maintenance C: sync tasks.md → backlog.md
- **`scripts/symlink-guard.sh`** — Maintenance E: ensure .agents/skills symlink
- **`scripts/check-context-size.sh`** — Maintenance F: warn on AGENTS.md size overflow

### Examples

- **`examples/agents-md-example.md`** — Complete AGENTS.md for Next.js SaaS project with all three mandatory embedded blocks