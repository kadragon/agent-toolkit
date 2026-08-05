---
name: harness-init
description: >-
  Set up or validate a repo's agent infrastructure — AGENTS.md, docs/ index,
  harness audit. Does NOT modify ~/.claude/CLAUDE.md.
---

# Harness Init

Set up complete harness for repo so Claude Code (and other AI agents) do reliable, consistent work. Harness = full environment of scaffolding, constraints, feedback loops, docs surrounding agent.

## Core Philosophy

**If the agent struggles, that's a harness defect** — fix the environment, not the prompt. And find the simplest solution that works: every component encodes an assumption about what the model can't do alone, so start minimal and add scaffolding only on concrete failures. A harness built for the weakest model slows a stronger one down.

That second rule is why this skill creates **nothing speculative**: no agent roles, no orchestrator, no sweep, no lint rewrite, and only the docs the repo has content for. Each has an evidence trigger instead, watched by `dev:harness-curate`.

Sources, evidence, and the failure modes behind each rule: `references/design-rationale.md`. Read it before deviating from a step.

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

> **Relation to the platform's own `/init`.** It complements this skill rather than duplicating it — if the repo already ran `/init`, treat its CLAUDE.md as Step 1 input and migrate/extend it, don't overwrite blindly. Detail: `references/design-rationale.md`.

**Init ships no orchestration infrastructure — no agent roles (Step 4b), no orchestrator skill (Step 4c).** This is the default, not a gap to apologize for: at init there is no working history, so any roster is a guess, and the built-in `Explore` / `general-purpose` subagents already cover ad-hoc fan-out.

Roles arrive **on evidence, not on setup**: `dev:harness-curate` mines the transcripts for work repeatedly done inline that a missing agent should have owned (its *triggering-miss* signal), and routes to `plugin-dev:agent-creator`. Adding one afterwards is Extend mode, not a re-init. Zero roles is a legitimate steady state — many repos never need one.

**Create a role or orchestrator during init only if the user explicitly asks for it in this session.** Then it is their call, not the skill's guess: build exactly what they named, apply the reachability check in Step 4b to that candidate, and skip the rest.

**Second sizing input — the operator's own instruction layer.** Read the invoking platform's global instruction file — `~/.claude/CLAUDE.md` (Claude Code) or `~/.codex/AGENTS.md` (Codex) — (and note what the platform's base instructions say) before writing any delegation wording. If that layer says *default inline, delegate only above N files*, or forbids spawning agents unless the user asks, the generated docs must not read stricter than it. A blocking gate that contradicts a higher-precedence file does not win — it gets ignored, and teaches the operator the harness is noise. See `examples/agents-md-example.md` → Delegation for the calibration note to carry into the generated file.

Delegation is only the axis where narrowing is a safe automatic fix. Every other axis goes through Step 0b.

**Mode selection:**

| Condition | Mode | Action |
|-----------|------|--------|
| No `AGENTS.md`, no `docs/` | **New setup** | Run Step 0b, then Steps 1–10 |
| Existing harness, user adds agent/skill/area | **Extend** | Run only affected steps (see matrix below) |
| User asks "harness 점검", "validate", "audit" | **Audit** | Run `scripts/validate-harness.sh`, report maturity level, stop. Structure only — for an instruction-conflict/duplication audit of the existing files, route to `dev:harness-curate` (Signal 7) |

**Maturity assessment (for New setup and Extend mode):**

Run `scripts/validate-harness.sh` against the target repo (if it exists). Classify as Level 1 / 2 / 3 per `references/maturity-levels.md`. Report the current level and which level to target.

- **Default target: Level 1.** Do not treat it as a waypoint to pass through in the same session. Levels 2–3 add CI gates and hooks, and every one of those guards a rule that has not yet been broken in this repo — enforcement built on a guess is the same defect as a roster built on a guess. Report the Level 2/3 upgrade path; let the repo earn it.
- **Level 2 in the same session:** only when CI already exists and adding the validate step costs one file. Never stand up CI *for* the harness at init.
- **Level 3:** propose only on demonstrated risk — a destructive surface (`permissions.deny` at Layer 0 is cheap and model-independent, so it is the one exception worth taking early) or a violation that already happened.
- **Existing repo, partial harness:** start from current level, advance at most one level per session.

**Extend mode — step selection matrix:**

| Change type | Steps to run |
|-------------|-------------|
| Add agent role | 4b (new role file) → 4c (update orchestrator) → 9 (validate) |
| Add/modify skill | 4c (skill update) → 9 |
| Add new domain with orchestrator | 4b + 4c → 9 |
| Architecture change | Affected docs → 4b (impacted roles) → 4c → 9 |

**Every row above still runs Step 0b and the Step 1 language resolution first.** Both are preconditions for writing anything, not New-setup-only steps — an Extend run that skips Step 1 falls back to the chat language (the exact failure Step 1 exists to prevent), and one that skips Step 0b can add a single role or gate that contradicts the operator's global layer.

Report mode + current maturity level + target level before proceeding.

### Step 0b: Reconcile With Higher-Precedence Instruction Layers

The global instruction file read in Step 0 is not just a sizing input — it is a **higher-precedence layer this skill must not contradict**. Before writing any artifact, pair each rule you intend to generate against that layer (and against the platform's base instructions, already in front of you this session) and classify the pair:

| Pair shape | Action |
|---|---|
| Repo rule **specializes** the upper layer (narrower scope, stricter threshold, repo value filling a placeholder) | Write it. Refinement, not conflict. |
| Repo rule uses an **opt-out the upper layer itself grants** (e.g. a global "Exception: repo AGENTS.md/CLAUDE.md opts in") | Write it, and label it inline (`Overrides global: …`) so the next agent doesn't re-derive the exemption. |
| Repo rule **restates** an upper-layer rule with no delta | Multi-tool repo → keep it (the repo copy is that rule's only reach on Codex/Cursor/Copilot). Verified single-tool repo → trim the redundant *items*, keeping the repo-specific ones, exactly as Step 3 prescribes for `## Token Economy` — never swap a whole mandated block for a pointer. "Verified" means positive evidence that Claude is the only intended reader, not the mere absence of another tool's config (same bar as `dev:harness-curate` → `references/signal-taxonomy.md` §7). |
| Repo rule **contradicts** the upper layer — incompatible instructions for the same situation | **Stop and ask the user.** Do not write either version, and do not silently pick one. |

**On a real conflict:** quote both sides verbatim, recommend a side with reasons, ask which is authoritative — batched into one prompt, before generating the affected file. Never assert a precedence winner you cannot quote a source for.

**Asking never halts the run.** Generate every artifact the conflict does not touch first, then ask, then write the affected ones. With **no user to ask** (running as a subagent/teammate): skip the conflicting rule rather than guessing, state the assumption, and surface both quoted sides in the return value — that satisfies the Step 9 checklist item.

**Two bounds, so the gate doesn't become noise:** it fires on *contradiction*, not resemblance (reuse the non-findings list in `dev:harness-curate` → `references/signal-taxonomy.md` §7), and it covers only rules **this run is about to write** — auditing conflicts already sitting in an existing `AGENTS.md` / `docs/` / `.claude/rules/` is `dev:harness-curate`'s Signal 7.

Quoting format, the operator hard-stop wording this mirrors, and the full bounds: `references/design-rationale.md` → Instruction-layer reconciliation.

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

**Settle the docs language here, before writing anything.** Every artifact this skill produces — AGENTS.md prose, `docs/*.md` bodies, role and skill files — goes in that language, *not* the language of the conversation you are having. The two are unrelated; defaulting to the chat language is the observed failure (`references/design-rationale.md` → Docs language). Resolve in order:

1. **Existing repo Language Policy** (AGENTS.md, README, CONTRIBUTING) — it wins outright.
2. Else the invoking platform's global instruction file, already read in Step 0 — `~/.claude/CLAUDE.md` (Claude Code) or `~/.codex/AGENTS.md` (Codex) (e.g. "User-facing Korean; code/commits/comments/docs English").
3. Neither settles it → ask. One question, then proceed.

Domain terms with no real equivalent in the target language (a proper name, a regulatory term, a framework's own field labels) stay in the source language. State the resolved language before Step 3 so the user can correct it once instead of after every file.

**Two carve-outs — the docs language governs prose bodies only.**

- **Matcher text follows the operator's prompt language.** Trigger phrases, skill/agent `description:` fields, and router route patterns are matched against what the operator actually types: keep the English lines always, and keep or translate the other-language alternates to whatever the operator prompts in.
- **`harness:verbatim` blocks stay verbatim.** The two mandated AGENTS.md blocks (Step 3) are copied unchanged in English no matter what language resolves here.

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

**Non-inferability filter — the primary anti-bloat gate.** Before writing a *descriptive* line, ask "would the agent already know this from the repo?" — if yes, delete it. The target is prose restating what the agent discovers by reading the code: architecture summaries, style rules the linter owns, a paraphrase of the README. Measured effect, not taste — LLM-generated context files *reduced* task success in 5 of 8 settings in an ETH Zurich study, while human-curated non-inferable ones gained (`references/design-rationale.md` → Non-inferability filter).

It does **not** prune navigational pointers (the `## Docs Index`, "read `docs/x.md` when …") or a concrete non-obvious command/example — those earn their tokens by cutting discovery cost.

**Two limits, both places it has actually misfired:** a `<!-- harness:verbatim … -->` block is out of scope, and "a higher-precedence file already says this" is a different claim than "the repo already shows this" — quote the covering text or keep the line, and note that a quote only settles it on a single-tool repo. Full reasoning in the rationale doc.

Three patterns make the map earn its tokens:
- **Code example > prose.** One real snippet of the convention beats three sentences describing it — show the pattern, don't narrate it.
- **Critical rules first.** Order sections so load-bearing invariants (golden principles, hard stops) sit near the top; long-context models drop middle content ("lost in the middle").
- **Tiered boundaries.** Where the agent needs permission cues, a compact table reads faster than prose — ✅ Allowed / ⚠️ Ask first / 🚫 Never. Reserve it for genuinely non-obvious boundaries; obvious ones are inferable and fail the filter above.

See `examples/agents-md-example.md` for complete reference.

**Required sections:** `## Docs Index`, `## Golden Principles`, `## Delegation`, `## Token Economy`, `## Working with Existing Code`, `## Language Policy`, `## Maintenance`. Full structure in `examples/agents-md-example.md`. Write this file's own prose in the language resolved in Step 1 — a `## Language Policy` the surrounding file violates teaches every later reader that the policy is decorative. The two `harness:verbatim` blocks below are the exception: copy them in English unchanged (Step 1 carve-out).

**Index only the docs this run actually creates.** The `## Docs Index` is a table of contents for files on disk, not a wishlist: a row pointing at a doc that does not exist sends the next agent to a dead path, and `sweep.sh`/`validate-harness.sh` correctly report it as drift. Write one row per file Step 4 produced — `docs/runbook.md` always, each conditional doc only if its "Create when" fired, and **never `docs/delegation.md`**, which init does not create (Step 4 table). The six-row index in `examples/agents-md-example.md` is the mature-repo case; a default init typically emits one to three rows. When a later session adds a doc, it adds the row in the same commit. The same applies to `docs/*.md` mentions in the *body* — `sweep.sh`/`validate-harness.sh` scan every reference in AGENTS.md, not just index rows, so prose copied from the example must drop the paths whose files this run did not create.

**Two embedded blocks mandatory in AGENTS.md** — copy verbatim from `examples/agents-md-example.md` (do not paraphrase): the `## Maintenance` edit policy and the `## Token Economy` rules. Copy the `<!-- harness:verbatim … -->` comment preceding each one too — it is what makes the block defend itself against later trimming passes (~8 tokens, invisible in Markdown).

**Token Economy overlaps Claude's base instructions — keep it anyway on a multi-tool repo.** On a **Claude-Code-only** repo, trim the items the base instructions already impose and keep only the repo-specific ones. On a multi-tool repo the block stays whole. Reasoning: `references/design-rationale.md` → Token Economy overlap.

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

Each doc is read **on demand**, not loaded every session. Each template file is self-describing — read it before writing the doc. Bodies go in the Step 1 language, not the chat language — the templates ship in English as scaffolding, which is not itself the language decision.

**One doc is unconditional. The rest have to earn it.** Apply Step 3's non-inferability filter here too — it is the same failure mode at a different path, and generating a doc whose content the agent would read from the code anyway is what the ETH result measured as *harmful*, not merely wasteful. Ask per file: does this repo have the thing the doc documents, and is that thing non-inferable from the code?

| File | Create when | Template |
|------|-------------|----------|
| `docs/runbook.md` | **always** — build/test/deploy commands, env setup, and failure modes are never inferable from source | `references/runbook-template.md` |
| `docs/architecture.md` | the repo has real module boundaries, layer rules, or dependency directions that the directory tree does not already show | `references/architecture-template.md` |
| `docs/conventions.md` | rules exist that agents get wrong **and the linter does not already own** — if the linter enforces it, the linter is the doc | `references/conventions-template.md` |
| `docs/workflows.md` | the repo runs a defined work cycle worth writing down. Write only the workflows actually used — not all six | `references/workflows-template.md` |
| `docs/eval-criteria.md` | the repo runs the Sprint Contract flow (paired with `backlog.md` below) | `references/eval-criteria-template.md` |
| `docs/delegation.md` | **not at init** — it documents routing to agents, and init creates none. Created with the repo's first role (`dev:harness-curate`) | `dev:harness-curate` → `references/delegation-template.md` |

For each doc you skip, say so in the Step 10 summary with its one-line trigger, so the next session knows the gap is a decision with a condition attached rather than an omission. `scripts/validate-harness.sh` reports these as `INFO`, not `WARN`, for the same reason.

**When `docs/delegation.md` is eventually written:** triggers in its routing table must be objective and measurable — never subjective conditions ("unfamiliar module") an agent can rationalize away.

**Steps 4b–4c (roles, orchestrator) produce nothing on a default init** — read them for the one case that does apply: the user asked for a specific role or orchestrator this session.

### Step 4a: Sprint / Backlog Files — only if the repo runs sprints

**Do not create `backlog.md` merely so `scripts/reconcile-harness.py` has a file to operate on.** That inverts the dependency: the script exists to serve the sprint flow, so a repo that does not run sprints needs neither. `reconcile-harness.py` is a no-op without them, not a failure, and `validate-harness.sh` reports the absence as `INFO`.

If the repo does adopt the backlog/sprint flow — now or later — create at repo root:

- **`backlog.md`** — queue of work not yet in flight. Copy the minimal template from `references/backlog-template.md`. Empty sections are fine.
- **`tasks.md`** — never at init. It exists only during an active sprint, holds the Sprint Contract and nothing else, and is deleted whole at close; every persistent item (queue, review findings, security findings) belongs in `backlog.md`. Record the template path (`references/tasks-template.md`) in `docs/workflows.md` so the first sprint starter knows the schema.

Both files follow the **Reconciliation Contract** in `references/harness-invariants.md`.

### Step 4b: Reusable Roles — none by default

**Create no `.claude/agents/*.md` at init.** The repo starts with an empty roster and the main thread does the work inline, using the built-in `Explore` / `general-purpose` subagents when it wants ad-hoc fan-out. Rationale in Step 0: before the repo has a working history there is no evidence about which delegations recur, and a guessed role is dead weight that discredits the harness.

Say so explicitly in the Step 10 summary — "no agent roles created; `dev:harness-curate` adds them when the transcripts show a delegation actually recurring" — so the empty roster reads as a decision rather than an omission.

**The one exception: the user asked for a specific role in this session.** Then create that role and only that role, after a reachability check — does its trigger fire in this repo's normal work?

| Role | Trigger | Reachable when |
|------|---------|----------------|
| `qa-verifier` | after any source edit | any repo with editable source |
| `explorer` | unexplored area >3 files | repo has real modules/dirs, not one flat file |
| `implementer` | backlog item w/ Sprint Contract | repo actually runs a `backlog.md` sprint flow |
| `product-evaluator` | subjective quality judgment | repo ships a user-facing artifact that gets judged |

If the requested role fails its own reachability check, say so and let the user decide — do not silently create it, and do not silently skip it. Swap in a domain-specific role when it matches the request better than the generic one (this marketplace uses `skill-evaluator` in place of `product-evaluator`).

Role-file prose goes in the Step 1 language; the `description:` field follows the matcher carve-out there, not the docs language. Omit `model:` — the role inherits the session model and the caller overrides per spawn (`dev:harness-curate` → `references/delegation-template.md` → "Model Selection — inherited by default").

**Keep the generated docs consistent with the empty roster.** `docs/workflows.md` and `docs/delegation.md` (from `references/workflows-template.md` and `dev:harness-curate` → `references/delegation-template.md`) must not name an agent this repo does not have: generate the delegation section headers and trigger-design rules, leave the routing-table rows out, and write the workflow's QA/eval steps as inline checks against the written criteria. Both templates carry the wording for this. Never leave a mandatory gate pointing at an agent that does not exist.

Read `dev:harness-curate` → `references/teammate-role-template.md` for the full schema and per-role templates — they are starting points for the later evidence-driven creation, not an init checklist.

**Team communication protocol:** If a role is created and will be spawned as a named teammate in team-mode orchestration, add the `## Team Communication Protocol` section (template in `dev:harness-curate` → `references/teammate-role-template.md`). This section specifies which agents to receive from/send to, task update calls, and scratchpad artifact path. Without it, inter-agent coordination degrades to guessing.

Regardless of roster, write `references/handoff-template.md`-style `handoff-{feature}.md` schema reference into `docs/workflows.md` for within-session continuity (context anxiety, subagent handoff — not cross-session resume). Handoff files are deferred Spawn Prompt Contracts.

### Step 4c: Orchestrator Skill — not at init

**Create no orchestrator skill during init** (default-off per Step 0). An orchestrator exists to route work to agents; with the Step 4b roster empty there is nothing to route to, so what gets generated is a skill that describes coordination the repo cannot perform. Its cost is not zero either — it loads on matching prompts and tells the model to spawn agents that do not exist.

The same evidence path applies: once `dev:harness-curate` has produced one or more roles and the transcripts show the *same multi-step domain workflow* recurring, an orchestrator is worth building — and by then its phases can be written from what actually happened instead of guessed. That is Extend mode (`Add new domain with orchestrator` in the Step 0 matrix), and it routes to `skill-creator`.

**Build one during init only if the user explicitly asks.** In that case follow the rest of this step as written.

When it is built — here on explicit request, or later via Extend mode — the whole procedure lives in one place: `dev:harness-curate` → `references/orchestrator-template.md` → **Build checklist**. It covers the file path, mode selection (team / sub-agent / hybrid), the four mandatory contents, the directive `description:`, frontmatter fields, registration in AGENTS.md + `docs/harness-log.md`, and the scratchpad convention to copy into `docs/runbook.md`. Do not re-derive any of it here.

Two constraints this skill owns: skill-body prose follows the Step 1 docs language while trigger phrases and `description:` follow the matcher carve-out, and CLAUDE.md stays a pure `@AGENTS.md` pointer (Step 8) — the registration goes in AGENTS.md or `docs/`, never there.

### Step 5: Sweep Automation — deferred, not installed

**Do not copy `scripts/sweep.sh` at init.** Sweep audits harness *drift* — docs that fell behind code, golden principles quietly violated, components that stopped being load-bearing. A harness created minutes ago has no drift, so what init would install is a check whose findings are guaranteed empty plus a cadence decision made before anyone knows the cadence.

Mention it in the Step 10 summary as available-on-demand, and install it on the first real signal: a doc found stale, a principle found violated, or a model upgrade that makes the load-bearing assessment worth running.

**When it is installed** (later session, or now if the user asks): copy `scripts/sweep.sh` into the project's `tools/`, adapt the `# ADAPT:` sections, and read `references/sweep-template.md` for ecosystem-specific guidance. It performs five checks — lint scan, doc drift, golden principle violations, harness freshness, finding report — plus the periodic **load-bearing assessment** (`references/sweep-template.md` → "Load-Bearing Assessment").

A trigger policy is required at that point, because sweep is deliberately not in the session-start loop. Pick one and record it in `docs/runbook.md` and in `references/harness-invariants.md` → "Sweep Trigger Policy":

- **Manual** (default) — run `bash tools/sweep.sh` between features
- **SessionStart hook** — `.claude/settings.json` hook with a staleness guard (skip if `tools/.sweep-stamp` <7 days old)
- **Cron / CI** — weekly GitHub Actions job or `CronCreate` schedule

### Step 6: Lint Message Readability — on evidence only

**Do not rewrite the project's lint messages at init.** This step edits the user's own lint configuration on the theory that an agent will one day misread an error. That is a speculative change to their code, and the anti-generation ladder rules it out until the failure is observed.

Do it when an agent actually stalls on a lint error — then the rewrite targets the message that really failed. Append a `FIX:` line (what to change and how) and a `REF:` line (the doc or config explaining the rule) to the existing message, turning it into a micro-instruction.

### Step 7: Build the Enforcement Chain

**At a Level 1 target this step ships Layer 0 only.** Every other layer guards a rule that has not yet been broken here; Layer 0 is the exception because it is model-independent, costs a few lines of `.claude/settings.json`, and the thing it prevents (a destructive command, a write outside the repo) is not something you want to learn about from evidence. Add Layers 1–3 as the repo advances a level, or immediately for a demonstrated risk.

Read `references/enforcement-template.md` for detailed templates per layer.

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

Match enforcement depth to maturity level target: Level 1 (the init default) → Layer 0 only, no hooks; Level 2 → add Layers 1 + 3; Level 3 → all layers + circuit breaker. Layer 0 deny rules apply at every level and are mandatory for a high-risk repo (auth/billing/migrations/infra). Read `references/enforcement-template.md` for templates and Agent Teams hook wiring.

### Step 7b: Make Delegation Non-Optional

**Why this step exists.** A delegation table fires only if the model reads it and chooses to delegate; auto-invocation is description-driven and lands well below 100% even with good descriptions (evidence: `references/design-rationale.md` → Auto-delegation). The failure mode is a beautiful delegation harness the agent then works around inline.

**Applies only once orchestrators or roles exist.** A freshly initialized repo has neither (Steps 4b/4c), so there is nothing to auto-delegate *to* and this whole step is a no-op — do not install a router to compensate for an empty roster. Run it when `dev:harness-curate` adds the first role or orchestrator, and apply it to that asset.

**Primary mechanism — directive descriptions (always, for each asset that exists).** Write the `description:` field of every orchestrator skill and high-leverage role directively ("ALWAYS invoke when X — do NOT inline-execute"); it measurably out-triggers descriptive phrasing. This is where auto-delegation is won or lost — template: `dev:harness-curate` → `references/orchestrator-template.md` → "Description writing rule".

**Fallback — trigger router (only on a measured miss-rate).** If a specific high-value delegation still misfires after the descriptions are right, add a mechanical backstop. Never preemptively — a stale router is worse than none.

1. **UserPromptSubmit trigger router** — pattern-matches each prompt, emits an explicit `Use Skill(X)` / `Spawn Agent(subagent_type=X)` instruction when a registered phrase matches. Read `dev:harness-curate` → `references/trigger-router-template.md` and install for the routes that actually miss:
   - `.claude/hooks/trigger-router.sh`
   - `.claude/trigger-routes.json` (one route per delegation you watched misfire)
   - Add `UserPromptSubmit` hook to `.claude/settings.json`

2. **PreToolUse delegation gate** (critical-path repos only) — blocks `Edit|Write` on critical paths (auth/billing/migrations) unless a delegation evidence file exists in `.claude/tmp/`. This is a hard block justified wherever an inline edit is genuinely dangerous — independent of the router, install it on evidence of risk, not of miss-rate. **Prerequisite: a role the gate can be satisfied by.** Installing it with an empty roster makes those paths simply un-editable, which is a broken repo, not a safe one. Read `references/enforcement-template.md` → "Delegation Gate (Layer 1 Extension)" and install:
   - `.claude/hooks/delegation-gate.sh`
   - Add `PreToolUse` matcher to `.claude/settings.json`

**Default:** directive descriptions for every orchestrator/agent that exists — at init, typically none. Router or gate only on evidence: a route you watched misfire, or a critical path that must never be touched inline. This repo's own harness ships no router.

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

Read `dev:harness-curate` → `references/agent-teams-onboarding.md` for tooling prerequisites and environment check.

Add adversarial debugging playbook as on-demand workflow: `dev:harness-curate` → `references/competing-hypotheses-playbook.md`. Maps to `debate` workflow in `docs/workflows.md`.

**Skip entirely if:** Step 4c chose Template B (sub-agent only). Agent Teams carries 3–5× token cost — don't enable it without an orchestrator that actually spawns named teammates and coordinates them mid-flight.

Token cost note: Team mode is not free. The orchestrator template enforces the decision gate (Q2 in Pattern Selection) so teams only activate when mid-flight coordination genuinely pays off.

### Step 9: Validate

Run `scripts/validate-harness.sh` against target project to verify all artifacts complete and consistent. **If validation exits non-zero, halt immediately. Show the full validation report to the user. Do NOT auto-fix — user must review and decide. Re-run validation after user addresses issues.**

Script checks:

- Required files exist (`AGENTS.md`, `CLAUDE.md`, `docs/runbook.md`); conditional docs and `backlog.md` are reported as `INFO` when absent, not `WARN`
- AGENTS.md size within policy band (see `references/harness-invariants.md`)
- `CLAUDE.md` is exactly `@AGENTS.md`
- `.agents/skills` points to `../.claude/skills`
- `backlog.md` schema (checkbox items under `##` headings)
- AGENTS.md `## Maintenance` section contains edit-policy rules
- Golden Principles, Delegation, enforcement layers present

Clean validate run at Level 2+ means enforcement is active and drift is mechanically prevented.

Manual checklist for items script cannot verify:
- [ ] No generated rule contradicts the operator's global layer or the platform's base instructions — every conflict Step 0b found was surfaced to the user and resolved by them (never resolved silently)
- [ ] Golden principles enforceable (each has lint rule, test, or hook)
- [ ] No generated doc names an agent role or orchestrator that does not exist in this repo
- [ ] No role file or delegation table pins a model — spawns inherit, callers override (`dev:harness-curate` → `references/delegation-template.md`)
- [ ] Every skipped doc was named in the Step 10 summary with the condition that would create it
- [ ] Eval criteria concrete and gradeable (not vague) — if `docs/eval-criteria.md` was generated
- [ ] `docs/` files don't duplicate each other

### Step 10: Explain to the User

Show the user all five of the following — this is the exit criterion for Step 10:

1. **Full AGENTS.md content** — paste or display the entire file so the user can confirm it looks right.
2. **List of all created files with one-line purpose each** — every file produced during init, so nothing is invisible.
3. **What was deliberately not created, and what would create it.** One line each, covering everything this run skipped: agent roles and orchestrator (→ `dev:harness-curate` when transcripts show a delegation recurring), each skipped doc with its trigger from the Step 4 table, `backlog.md` if the repo does not run sprints, `tools/sweep.sh` (→ on the first drift signal), lint-message rewrites (→ when an agent actually stalls on one), and Layers 1–3 of enforcement (→ on the maturity upgrade or a demonstrated risk). Without this list the user reads a minimal harness as an incomplete one.
4. **The maturity level reached and the next level's cost** — Level 1 is the expected outcome; state plainly what Level 2 would add and that it is not needed yet.
5. **How to update AGENTS.md when tasks change** — point to the `## Maintenance` rules embedded in AGENTS.md; emphasize: only add when all 4 conditions are met.

Drift prevention scales with level: at Level 1 it is convention, and only Level 3 makes it mechanical. Do not describe a fresh init as drift-proof. A violation after a clean init is a signal for the *next* level, not operator error — trace it to the missing hook or CI check.

## Harness Evolution

After a harness is in use, it should evolve based on feedback. Trigger evolution when:
- Same feedback appears ≥2× (structural gap signal)
- Agent bypasses orchestrator (description trigger missing)
- Repeated agent failure pattern (definition defect)

Read `references/harness-evolution.md` for feedback → fix target mapping and change history protocol. Record every change in the orchestrator's pointer block in `docs/harness-log.md` (see Step 4c) — never CLAUDE.md.

## Ongoing Maintenance

At Level 1 the routine below is manual and worth running periodically. Only at Level 3 do hooks and CI prevent drift mechanically, retiring the manual pass. See `references/maintenance.md` for the full routine.

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
| `scripts/sweep.sh` | Five-check harness audit: lint scan, doc drift, golden principle violations, freshness, finding report (not installed at init — copy and adapt on the first drift signal, Step 5) |
| `scripts/sync-claude-md.sh` | Repair CLAUDE.md → @AGENTS.md (if manually broken) |
| `scripts/symlink-guard.sh` | Repair .agents/skills symlink (if manually broken) |
| `scripts/check-context-size.sh` | Warn if AGENTS.md > 200 lines |

The last three scripts are repair tools, not routine ops. At Level 3, they should rarely be needed. The `dev` plugin's SessionStart hook runs sync-claude-md (CLAUDE.md pointer check), symlink-guard (.agents/skills symlink check), and check-context-size (AGENTS.md size check) daily as a lightweight safety net; at Level 3 it should always be silent.

## Additional Resources

All `references/*.md` files are cited inline at point of use — consult them there. Optional / surfaced on request:

- **`references/design-rationale.md`** — evidence and failure modes behind the rules: why init creates nothing speculative, the non-inferability study, instruction-layer precedence, docs-language carve-outs, auto-delegation trigger rates. **Read before deviating from a step.**

**Delegation-asset templates live in `dev:harness-curate/references/`, not here** — `teammate-role-template.md`, `delegation-template.md`, `orchestrator-template.md`, `coordination-patterns.md`, `agent-teams-onboarding.md`, `competing-hypotheses-playbook.md`, `trigger-router-template.md`. They moved when init stopped creating agents (Steps 4b/4c): every one of them is read *after* a delegation has proven itself, which is `harness-curate`'s decision, not init's. Read them from there in the one init case that needs them — the user asked for a specific role or orchestrator this session.

- **`references/harness-evolution.md`** — Feedback-driven evolution: signal → fix target mapping, change history protocol. **Read when harness needs evolution.**
- **`references/path-scoped-rules.md`** — `.claude/rules/*.md` with `paths:` frontmatter: mechanical just-in-time rules that load only when matching files are touched, home-selection table, fat-AGENTS.md migration. **Read at Step 3a.**
- **`references/maturity-levels.md`** — 3-level progression (Basic/Verified/Enforced), checklist per level, upgrade path. **Read at Step 0 for existing repos.**
- **`references/power-user-settings.md`** — Optional env vars (AUTOCOMPACT threshold, extended thinking) and output-style customization. Informational; surface to user after Step 10 if asked.

### Examples

- **`examples/agents-md-example.md`** — Complete AGENTS.md for Next.js SaaS project with both mandatory embedded blocks
