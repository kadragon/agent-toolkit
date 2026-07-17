---
name: harness-init
description: >-
  Use when setting up or validating repo agent infrastructure — "set up a harness", "initialize agent infrastructure", "bootstrap AGENTS.md", "validate harness", "harness audit", "하네스 초기화", "에이전트가 자꾸 실수해요", "Claude Code 리포지토리 설정", "하네스 점검", or repo has no AGENTS.md/docs/ structure. Does NOT modify ~/.claude/CLAUDE.md.
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

> **Relation to the platform's own `/init`.** Claude Code ships a built-in `/init` (and newer interactive variants) that bootstraps a basic CLAUDE.md plus optional skills/hooks. This skill **complements, not duplicates** it: harness-init produces the full multi-layer harness (AGENTS.md map, docs knowledge base, path-scoped rules, enforcement chain, orchestrator + agents, maturity progression) that platform `/init` does not. If the repo already ran `/init`, treat its CLAUDE.md as Step 1 input and migrate/extend it — don't overwrite blindly.

**Default toward orchestration infrastructure.** When unsure whether a repo "needs" Step 4b/4c (agents + orchestrator), build them. Empirical failure mode: repos initialized without orchestrator + agents never auto-delegate downstream — auto-delegation (Step 7b) has nothing to fire at, and the model does everything inline. The override cost of unused role files is ~50 lines on disk; the cost of skipping is a permanently inline workflow that floods the main context. Skip only for genuinely trivial repos (single script, docs-only, one-file library).

**Mode selection:**

| Condition | Mode | Action |
|-----------|------|--------|
| No `AGENTS.md`, no `docs/`, no `.claude/agents/` | **New setup** | Run Steps 1–10 |
| Existing harness, user adds agent/skill/area | **Extend** | Run only affected steps (see matrix below) |
| User asks "harness 점검", "validate", "audit" | **Audit** | Run `scripts/validate-harness.sh`, report maturity level, stop |

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

**Non-inferability filter — the primary anti-bloat gate.** The target is redundant *description*: prose that restates what the agent would independently discover by reading the code — architecture summaries, style rules the linter already owns, a paraphrase of the README. This is not a style preference: an ETH Zurich study ([arxiv 2602.11988](https://arxiv.org/abs/2602.11988)) found LLM-generated context files *reduced* task success in 5 of 8 settings (+2.45–3.92 steps/task, +20–23% inference cost) precisely because they restated facts the agent already reads from code; human-curated, non-inferable files instead gained ~4pp. So before writing a *descriptive* line, ask "would the agent already know this from the repo?" — if yes, delete it. This does **not** prune navigational pointers (the `## Docs Index`, "read `docs/x.md` when …") or a concrete non-obvious command/example — those name real files but earn their tokens by cutting discovery cost, which is the whole point of the map. It is the empirical backing for "map, not encyclopedia," and applies to the AGENTS.md body even though the Step 0 default still builds out the orchestration scaffolding (that lives in on-demand `docs/`, not the always-loaded map).

Three patterns make the map earn its tokens:
- **Code example > prose.** One real snippet of the convention beats three sentences describing it — show the pattern, don't narrate it.
- **Critical rules first.** Order sections so load-bearing invariants (golden principles, hard stops) sit near the top; long-context models drop middle content ("lost in the middle").
- **Tiered boundaries.** Where the agent needs permission cues, a compact table reads faster than prose — ✅ Allowed / ⚠️ Ask first / 🚫 Never. Reserve it for genuinely non-obvious boundaries; obvious ones are inferable and fail the filter above.

See `examples/agents-md-example.md` for complete reference.

**Required sections:** `## Docs Index`, `## Golden Principles`, `## Delegation`, `## Token Economy`, `## Working with Existing Code`, `## Language Policy`, `## Maintenance`. Full structure in `examples/agents-md-example.md`.

**Three embedded blocks mandatory in AGENTS.md** — copy verbatim from `examples/agents-md-example.md` (do not paraphrase): `## Maintenance` edit policy, `## Token Economy` rules, context-anxiety note.

**What NOT to put in AGENTS.md:** workflow details, delegation details, evaluation criteria, architecture deep dives, API references. These belong in `docs/`.

### Step 3a: Path-Scoped Rules (`.claude/rules/`) — conditional

**First decide by tool setup — this is the deciding factor:**

- **Multi-tool repo (Claude Code + Codex / Cursor / Copilot / …):** keep area-specific rules in `docs/*.md` (cross-tool — every agent reaches them via the AGENTS.md Docs Index). **Do NOT split content into `.claude/rules/`** — it is Claude Code-only, so the other tools would never see it and the source fragments. This is the default for any repo targeting more than one agent (including this `agent-toolkit` repo, which targets Claude + Codex).
- **Claude Code-only repo:** `.claude/rules/{area}.md` with a `paths:` frontmatter glob is worth it. Such rules load **mechanically and only** when Claude touches a matching file — true just-in-time context, zero budget cost elsewhere, and the agent cannot skip them (unlike `docs/`, whose discovery is voluntary).

**Non-fragmenting hybrid (multi-tool repo that still wants Claude's auto-load):** keep the rule *content* in `docs/` (single source both tools read) and add a 2-line `.claude/rules/{area}.md` **pointer** — "When editing `src/billing/**`, read `docs/billing.md`." Claude gets the mechanical trigger-to-read; Codex still reads `docs/billing.md` directly; nothing is duplicated. Use only if the voluntary-read miss rate is actually hurting.

Read `references/path-scoped-rules.md` for layout, the home-selection table (AGENTS.md vs rules vs docs vs settings), loading semantics, and the fat-AGENTS.md migration recipe.

**Important loading fact (applies either way):** `@`-imports do **not** save context — an imported file loads fully at launch. Only **skills, path-scoped rules, and auto-memory** load on demand. So content that bloats AGENTS.md/CLAUDE.md belongs in `docs/` (or, single-tool only, a path-scoped rule) — never an `@`-import.

**Skip entirely if:** the repo has no meaningful area boundaries (single-script / docs-only).

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

Required so `scripts/reconcile-harness.py` has valid files to operate on. Without these, reconciliation has nothing to process and warns about missing schema.

Create at repo root:

- **`backlog.md`** — queue of work not yet in flight. Copy minimal template from `references/backlog-template.md`. Empty sections fine.
- **`tasks.md`** — DO NOT create at init time. Exists only during active sprint. Include template path (`references/tasks-template.md`) as reference in `docs/workflows.md` so first sprint starter knows schema.

Both files follow **Reconciliation Contract** documented in `references/harness-invariants.md`.

### Step 4b: Define Reusable Roles

**Default: create the starter pack** (implementer, explorer, qa-verifier, product-evaluator) for any repo with >1 source file (default-on per Step 0).

**Skip only if** the repo is genuinely trivial: a single-script tool, a docs-only repo, or a one-file library with no meaningful module boundaries. When unsure, create the starter pack — the override cost is low.

Create `.claude/agents/{role}.md` for each recurring role. Claude Code reuses these for both subagent spawns and Agent Teams teammates — define once, use both ways.

Read `references/teammate-role-template.md` for full schema and starter pack (implementer, explorer, qa-verifier, product-evaluator).

**Team communication protocol:** For every role that will participate in `TeamCreate`-based orchestration, add the `## Team Communication Protocol` section (template in `references/teammate-role-template.md`). This section specifies which agents to receive from/send to, task update calls, and scratchpad artifact path. Without it, inter-agent coordination degrades to guessing.

Also write `references/handoff-template.md`-style `handoff-{feature}.md` schema reference into `docs/workflows.md` for within-session continuity (context anxiety, subagent handoff — not cross-session resume). Handoff files are deferred Spawn Prompt Contracts.

### Step 4c: Create Orchestrator Skill

**Default: create at least one orchestrator skill** for the repo's primary work domain (e.g., `code-orchestrator` for an app repo, `release-orchestrator` for a library, `review-orchestrator` for a docs repo) (default-on per Step 0). The threshold is not "≥2 agents collaborating" — it is "the user will repeatedly invoke this kind of work." An orchestrator is the **named target** that auto-delegation (Step 7b — directive description first, router fallback) points at.

If a domain genuinely needs ≥2 coordinating agents, prefer Template A (team) or C (hybrid). For single-agent domains, use Template B with one sub-agent — it is still worth creating because the orchestrator gives auto-delegation a target and the model an explicit "spawn the agent, do not inline" instruction.

Create at:
`.claude/skills/{domain}-orchestrator/SKILL.md`

Read `references/orchestrator-template.md` and choose one of:
- **Template A (team)** — agents share findings mid-flight via SendMessage
- **Template B (sub-agent)** — agents return results independently
- **Template C (hybrid)** — phase-dependent: different modes per phase

The orchestrator must include:
1. Explicit data transfer strategy (see `references/delegation-template.md` → Data Transfer Protocols) — determine the scratchpad path from the system prompt and embed it in every spawn prompt
2. Error policy (1 retry, graceful degradation, report omissions)
3. Scratchpad naming: `{phase:02d}_{agent}_{artifact}.{ext}`
4. Task claim protocol if ≥2 agents share a task pool (see `references/orchestrator-template.md` → Task Claim Protocol)

No cross-session resume — that mechanism was removed; scratchpad artifacts do not survive a new CLI session.

After creation, register in AGENTS.md (or `docs/`), never CLAUDE.md: add a `## Harness: {Domain}` pointer block with trigger rule and change history table to `docs/harness-log.md`, and add one row under AGENTS.md's `## Docs Index` pointing to it. CLAUDE.md must stay a pure `@AGENTS.md` pointer (Step 8, enforced by `scripts/validate-harness.sh`) — do not append anything to it.

**Directive description mandatory.** The skill's `description:` field is the primary auto-invocation mechanism — Claude reads it on every prompt. Anthropic's skill-creator docs report directive descriptions ("ALWAYS invoke when X — do NOT inline-execute") improved auto-invocation on 5 of 6 public skills vs descriptive phrasing ("Triggers on X"). Use the template in `references/orchestrator-template.md` → "Description writing rule". This is Step 7b's primary mechanism — get it right before considering the router fallback.

**Frontmatter fields (2026).** `description` (+ `when_to_use`) is truncated at ~1,536 chars combined — front-load the key use case. Other useful fields when generating the SKILL.md: `model` / `effort` (per-skill override), `disable-model-invocation: true` (manual `/name` only), `allowed-tools` (gate tools while active), `paths` (glob-gate auto-activation), `context: fork` + `agent` (run in a forked subagent). See `references/orchestrator-template.md` → "Skill frontmatter reference".

**Skip only if:** the repo is genuinely trivial (single-script tool, docs-only repo) — the same bar as Step 4b (default-on per Step 0).

### Step 4d: Scratchpad Pattern

If Step 4c created an orchestrator, add a Scratchpad section to `docs/runbook.md`:

```markdown
## Scratchpad Convention

Intermediate artifacts live in the session scratchpad directory (path given in the system prompt).
Naming: `{phase:02d}_{agent}_{artifact}.{ext}`

Ephemeral — gone at session end, no cross-session resume.

Separate mechanism: delegation-gate evidence files live in `.claude/tmp/` (gitignored, session_id-stamped — see `references/enforcement-template.md`).
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

**Five layers (defense in depth):**
0. **Settings-level deny** (`.claude/settings.json` / managed settings) — `permissions.deny` and `sandbox.enabled` block actions *regardless of what the model decides*. This is the only model-independent layer; hooks can be argued with via clever prompts, prose cannot enforce at all. Put hard blocks here (e.g. deny `Bash(rm -rf*)`, deny writes outside the repo). See `references/enforcement-template.md` → "Layer 0".
1. **Real-time hooks** (`.claude/settings.json`) — Catch violations at edit time
2. **Pre-commit checks** — Block commits with unfixed violations
3. **CI gate** — Block merges on failure
4. **PR template** (optional) — Checklist derived from golden principles

**Enforcement ladder (official):** a rule that *must always run* → hook; a rule that *must be blocked no matter what* → settings-level deny / sandbox; everything else → AGENTS.md / path-scoped rule. CLAUDE.md and prose are guidance, not enforcement — "to block an action regardless of what Claude decides, use a PreToolUse hook or `permissions.deny`."

**Two Layer 1 extensions (add when appropriate):**
- **Circuit Breaker** — stops failure cascades before token spiral; fires after N consecutive Bash failures (default: 3). See `references/enforcement-template.md` → "Circuit Breaker".
- **Consent Gates** — halts before irreversible external actions (push, PR, deploy) until user confirms. See `references/enforcement-template.md` → "Consent Gates".

Match enforcement depth to maturity level target: Level 1 → no hooks required; Level 2 → Layer 1 + 3; Level 3 → all layers + circuit breaker, with Layer 0 deny rules for any high-risk repo (auth/billing/migrations/infra) at any level. Read `references/enforcement-template.md` for templates and Agent Teams hook wiring.

### Step 7b: Make Delegation Non-Optional

**Why this step exists.** The AGENTS.md delegation table and orchestrator skill descriptions only fire if Claude voluntarily reads them and chooses to delegate. Auto-invocation is description-driven, and field reports put it well below 100% even with good descriptions ([Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)", 2025-11-06](https://scottspence.com/posts/claude-code-skills-dont-auto-activate)). The failure mode: init produces a beautiful delegation harness, then the agent does the work inline anyway.

**Primary mechanism — directive descriptions (do this always).** The highest-leverage, lowest-cost lever is the `description:` field of every orchestrator skill and high-leverage agent role. Directive phrasing ("ALWAYS invoke when X — do NOT inline-execute") measurably out-triggers descriptive phrasing ("Triggers on X"). This is where auto-delegation is won or lost — get the descriptions right first (template: `references/orchestrator-template.md` → "Description writing rule"). This repo's own harness relies on description-driven invocation with **no router hook** — dogfooded, and sufficient for the large majority of repos.

**Fallback — trigger router (only when you've measured a real miss-rate).** If, after directive descriptions are in place, a specific high-value delegation still misfires often enough to hurt, add a mechanical backstop. Do not install it preemptively — it costs a hook on every prompt plus a routes file to keep in sync, and a stale router is worse than none.

1. **UserPromptSubmit trigger router** — pattern-matches each prompt, emits an explicit `Use Skill(X)` / `Spawn Agent(subagent_type=X)` instruction when a registered phrase matches. Read `references/trigger-router-template.md` and install for the routes that actually miss:
   - `.claude/hooks/trigger-router.sh`
   - `.claude/trigger-routes.json` (one route per delegation you watched misfire)
   - Add `UserPromptSubmit` hook to `.claude/settings.json`

2. **PreToolUse delegation gate** (critical-path repos only) — blocks `Edit|Write` on critical paths (auth/billing/migrations) unless a delegation evidence file exists in `.claude/tmp/`. This is a hard block justified wherever an inline edit is genuinely dangerous — independent of the router, install it on evidence of risk, not of miss-rate. Read `references/enforcement-template.md` → "Delegation Gate (Layer 1 Extension)" and install:
   - `.claude/hooks/delegation-gate.sh`
   - Add `PreToolUse` matcher to `.claude/settings.json`

**Default:** ship directive descriptions for every orchestrator/agent (default-on per Step 0). Add the router or gate only on evidence — a route you watched misfire, or a critical path that must never be touched inline. This mirrors this repo's own conclusion: description-driven first, router only if the miss-rate proves it necessary.

**Validation (if you install the router):** test each route after creation:

```bash
echo '{"prompt": "<sample trigger phrase>", "session_id": "test"}' | bash .claude/hooks/trigger-router.sh
# Expected: "INSTRUCTION (auto-delegation router): Use Skill(...) ..."
```

### Step 8: Create Repo Root Configs

Three items at repo root. All mechanical wins — "create once, benefits every session."

#### `CLAUDE.md` (pointer)

```markdown
@AGENTS.md
```

Keeps loading chain clean: Claude loads `CLAUDE.md` → `AGENTS.md` (map) → `docs/` (on demand). If drifts, repair with `scripts/sync-claude-md.sh`.

Keep `CLAUDE.md` a pure `@AGENTS.md` pointer — this is a validated invariant (`scripts/validate-harness.sh` fails any other content) and keeps one cross-tool source of truth. Claude-specific guidance goes in `.claude/rules/` (path-scoped) or AGENTS.md, not in CLAUDE.md.

#### Memory boundary (auto-memory)

Claude Code's auto-memory (model-authored `MEMORY.md` + topic files under the per-project memory dir) is **separate from the harness you author here**. Draw the boundary explicitly so they don't drift or duplicate:

- **Harness files (AGENTS.md, `.claude/rules/`, `docs/`)** = durable repo facts — architecture, conventions, golden principles. Human-authored, version-controlled, reviewed.
- **Auto-memory (`MEMORY.md`)** = discovered preferences and cross-session learnings the model writes for itself. Machine-local, not a place for code facts.

State this boundary once (a line in AGENTS.md `## Maintenance` or a `docs/` note) so future sessions don't promote a code fact into auto-memory or vice-versa. Toggle/relocation env vars are in `references/power-user-settings.md`.

#### `.claudeignore` (scan exclusions)

Prevents token burn on vendored deps, build outputs, generated artifacts. Compose from `references/claudeignore-template.md` (Common + language sections) based on Step 1 stack analysis.

#### `.agents/skills` symlink

Tooling looks up project-local skills via `.agents/` while files live under `.claude/skills/`. Create once at init; repair with `scripts/symlink-guard.sh` if broken:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/symlink-guard.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/symlink-guard.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/symlink-guard.sh"
```

If the bundled script cannot be resolved from the loaded `SKILL.md`, run directly:

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

Clean validate run at Level 2+ means enforcement is active and drift is mechanically prevented.

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

After setup, Level 3 enforcement mechanically prevents drift (hooks + CI). Unexpected violations after a clean init → treat as enforcement gap, not operator error — trace to the missing hook or CI check and fix the template.

## Harness Evolution

After a harness is in use, it should evolve based on feedback. Trigger evolution when:
- Same feedback appears ≥2× (structural gap signal)
- Agent bypasses orchestrator (description trigger missing)
- Repeated agent failure pattern (definition defect)

Read `references/harness-evolution.md` for feedback → fix target mapping and change history protocol. Record every change in the orchestrator's pointer block in `docs/harness-log.md` (see Step 4c) — never CLAUDE.md.

## Ongoing Maintenance

With Level 3 enforcement active, no manual sync routine is needed — hooks and CI prevent drift mechanically. See `references/maintenance.md` for the full maintenance routine.

**Regular actions:**

| When | Action |
|------|--------|
| Periodically or on "harness 점검" | `bash scripts/validate-harness.sh` — check maturity level |
| Sprint tasks complete | `python scripts/reconcile-harness.py` — sync tasks.md → backlog.md |
| Feedback from harness usage | Read `references/harness-evolution.md` |

**Scripts (utilities, run from repo root):**

| Script | Purpose |
|--------|---------|
| `scripts/validate-harness.sh` | Full structural validation + maturity level report |
| `scripts/reconcile-harness.py` | Sync completed tasks.md items into backlog.md |
| `scripts/sweep.sh` | Five-check harness audit: lint scan, doc drift, golden principle violations, freshness, finding report (copy and adapt per project in Step 5) |
| `scripts/sync-claude-md.sh` | Repair CLAUDE.md → @AGENTS.md (if manually broken) |
| `scripts/symlink-guard.sh` | Repair .agents/skills symlink (if manually broken) |
| `scripts/check-context-size.sh` | Warn if AGENTS.md > 200 lines |

The last three scripts are repair tools, not routine ops. At Level 3, they should rarely be needed. The SessionStart hook (`dev-tools:harness-maintenance`) runs sync-claude-md (CLAUDE.md pointer check), symlink-guard (.agents/skills symlink check), and check-context-size (AGENTS.md size check) daily as a lightweight safety net; at Level 3 it should always be silent.

## Additional Resources

All `references/*.md` files cited inline at point of use — consult there. Files optional / surfaced on request:
- **`references/orchestrator-template.md`** — 3-mode orchestrator templates (team/sub-agent/hybrid), scratchpad convention, `docs/harness-log.md` pointer block, directive-description rule. **Read at Step 4c.**
- **`references/trigger-router-template.md`** — UserPromptSubmit hook that maps prompt phrases → explicit `Use Skill(X)` / `Spawn Agent(X)` instructions. **Fallback only** — Step 7b's primary mechanism is directive skill descriptions; reach for the router when a specific delegation still misfires often enough to hurt ([Scott Spence 2025-11-06](https://scottspence.com/posts/claude-code-skills-dont-auto-activate)). **Read at Step 7b.**
- **`references/harness-evolution.md`** — Feedback-driven evolution: signal → fix target mapping, change history protocol. **Read when harness needs evolution.**
- **`references/path-scoped-rules.md`** — `.claude/rules/*.md` with `paths:` frontmatter: mechanical just-in-time rules that load only when matching files are touched, home-selection table, fat-AGENTS.md migration. **Read at Step 3a.**
- **`references/maturity-levels.md`** — 3-level progression (Basic/Verified/Enforced), checklist per level, upgrade path. **Read at Step 0 for existing repos.**
- **`references/power-user-settings.md`** — Optional env vars (AUTOCOMPACT threshold, extended thinking) and output-style customization. Informational; surface to user after Step 10 if asked.

### Examples

- **`examples/agents-md-example.md`** — Complete AGENTS.md for Next.js SaaS project with all three mandatory embedded blocks
