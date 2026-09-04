---
name: harness-init
description: >-
  Set up or validate a repo's agent infrastructure — AGENTS.md, the docs/ index, harness
  audit. Proposing or pruning individual assets from session evidence instead → harness-
  curate.
disable-model-invocation: true
---

# Harness Init

Set up the harness — scaffolding, constraints, feedback loops, docs — so agents do reliable,
consistent work in this repo.

## Core Philosophy

**If the agent struggles, that's a harness defect** — fix the environment, not the prompt. And
find the simplest thing that works: every component encodes an assumption about what the model
cannot do alone, so start minimal and add scaffolding only on a concrete failure. A harness built
for the weakest model slows a stronger one down.

So this skill creates **nothing speculative**: no agent roles, no orchestrator, no sweep, no
lint rewrite, and only the docs the repo has content for. Each has an evidence trigger instead,
watched by `dev:harness-curate`. Evidence and failure modes behind each rule:
`references/design-rationale.md` — read it before deviating from a step.

## Prerequisites

Scan the repo first (Step 1); ask the user only what code does not reveal — team size, sprint
cadence, pain points ("what goes wrong when agents work here?").

## Step 0: Classify the request

| Condition | Mode | Action |
|-----------|------|--------|
| No `AGENTS.md`, no `docs/` | **New setup** | Step 0b, then Steps 1–10 |
| Existing harness, user adds an area, doc, or asset | **Extend** | Step 0b + Step 1 language resolution, then only the affected steps, then Step 9 |
| "harness 점검", "validate", "audit" | **Audit** | run `scripts/validate-harness.sh`, report the maturity level, stop. Instruction-conflict audits belong to `dev:harness-curate` |

If the repo already ran the platform's `/init`, treat its `CLAUDE.md` as Step 1 input and
migrate it — do not overwrite blindly.

**Maturity:** run `scripts/validate-harness.sh`; classify per `references/maturity-levels.md`.
Default target is **Level 1**. Levels 2–3 add CI gates and hooks that each guard a rule not yet
broken here — report the upgrade path, let the repo earn it (Level 2 same-session only when CI
already exists; Level 3 only on demonstrated risk; existing repo: one level per session).

**The operator's own instruction layer is a sizing input.** Read `~/.claude/CLAUDE.md` (Claude
Code) or `~/.codex/AGENTS.md` (Codex) before writing any delegation wording; never write to it. If
it says *default inline, delegate only above N files*, the generated docs must not read stricter —
a gate that contradicts a higher-precedence file gets ignored and teaches the operator the harness
is noise. Roles and orchestrators are created at init only on an explicit request (Steps 4b/4c).

## Step 0b: Reconcile with higher-precedence layers

Pair every rule you are about to write against the global file and the platform's base
instructions:

| Pair shape | Action |
|---|---|
| Repo rule **specializes** the upper layer (narrower scope, stricter threshold, a repo value filling a placeholder) | Write it |
| Repo rule uses an **opt-out the upper layer grants** | Write it, labeled inline (`Overrides global: …`) |
| Repo rule **restates** an upper-layer rule with no delta | Multi-tool repo → keep (the copy is that rule's only reach on Codex/Cursor). Verified single-tool repo → trim the redundant items, never a whole mandated block |
| Repo rule **contradicts** the upper layer | **Stop and ask.** Quote both sides, recommend one, ask which wins — batched into one prompt |

Asking never halts the run: generate everything the conflict does not touch first; with no user
to ask, skip the rule, state the assumption, surface both sides in the return value. Fires on
contradiction, not resemblance; covers only rules this run writes. Report mode, current level and
target level before proceeding.

## Step 1: Analyze the repository

Read `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/`, build/CI config, lint config, test
infrastructure, source layout, and git history (commit patterns, branch strategy). Decide what to
keep versus replace.

**Settle the docs language now.** Every artifact goes in that language, not the chat language.
Resolve in order: an existing repo Language Policy → the global instruction file's policy → ask
once. Domain terms with no real equivalent stay in the source language. Two carve-outs: matcher
text (trigger phrases, `description:` fields) follows what the operator types, and
`harness:verbatim` blocks stay in English unchanged.

## Step 2: Define golden principles

Three to seven invariants that, if violated, cause the most damage. Each must be **mechanically
enforceable** (lint, test, or hook), **specific to this project**, and **grounded in real pain**.
Ask: "What rules, if broken, cause the most pain here?" Examples per stack:
`references/golden-principles-guide.md`. Add the **Agent Integrity Principle** everywhere — an
unread value is written `[unknown — read {source}]`, never guessed.

## Step 3: Create AGENTS.md

A map, not an encyclopedia: target ≤100 lines, hard warn >200. The primary anti-bloat gate is the
**non-inferability filter** — before writing a descriptive line ask "would the agent already know
this from the repo?" and delete it if yes. Architecture summaries, linter-owned style, README
paraphrases all fail it; navigational pointers (the Docs Index) and a non-obvious command pass.

**Required sections:** `## Docs Index`, `## Golden Principles`, `## Delegation`, `## Token
Economy`, `## Working with Existing Code`, `## Language Policy`, `## Maintenance`. Structure:
`examples/agents-md-example.md`. Two blocks are copied **verbatim** with their
`<!-- harness:verbatim … -->` comment — `## Maintenance` (the edit policy) and `## Token Economy`
(on a Claude-Code-only repo, trim the items the base instructions already impose).

**Index only the docs this run creates.** One row per file Step 4 produced; never
`docs/delegation.md`, which init does not create. The same applies to `docs/*.md` mentions in the
body — `validate-harness.sh` flags every reference whose file is missing.

A code example beats prose; critical rules first; workflow and delegation detail, evaluation
criteria, and architecture deep dives belong in `docs/`, not here.

## Step 3a: Path-scoped rules (`.claude/rules/`) — conditional

Multi-tool repo (Claude Code + Codex/Cursor/Copilot) → keep area rules in `docs/*.md`; do not
split into `.claude/rules/`, which only Claude reads. Claude-only repo → `.claude/rules/{area}.md`
with a `paths:` glob loads mechanically when a matching file is touched. Hybrid: content in
`docs/`, a two-line `.claude/rules/` pointer. `@`-imports do not save context. Skip entirely on a
repo with no area boundaries. Layout and migration: `references/path-scoped-rules.md`.

## Step 4: Create the docs/ knowledge base

Each doc is read on demand. Apply the non-inferability filter per file: does the repo have the
thing, and is it non-inferable from the code? A doc that restates the README is the filter
failing. Templates are self-describing scaffolds in English; bodies go in the Step 1 language.

| File | Create when | Template |
|------|-------------|----------|
| `docs/runbook.md` | **always** — build/test/deploy commands, env setup, failure modes are never inferable | `references/runbook-template.md` |
| `docs/architecture.md` | real module boundaries or dependency directions the tree does not show | `references/architecture-template.md` |
| `docs/conventions.md` | rules agents get wrong **that the linter does not own** | `references/conventions-template.md` |
| `docs/workflows.md` | the repo runs a defined work cycle worth writing down; only the workflows actually used | `references/workflows-template.md` |
| `docs/eval-criteria.md` | the repo grades its own skills or artifacts against rubrics | `references/eval-criteria-template.md` |
| `docs/delegation.md` | **not at init** — created with the repo's first role by `dev:harness-curate` | this marketplace's own `docs/delegation.md` is the reference shape |

Name every skipped doc in the Step 10 summary with its trigger (`validate-harness.sh`: `INFO`).

### Step 4a: Sprint / backlog files — only if the repo runs sprints

`backlog.md` from `references/backlog-template.md` when the repo adopts the queue flow — it is
the only file `dev:task-next` / `dev:task-new` require. `tasks.md` never at init: it exists only
during an active sprint, holds the Sprint Contract and nothing else, and is deleted at close
(`references/tasks-template.md`). Both follow the *Reconciliation Contract* in
`references/harness-invariants.md`.

### Step 4b: Reusable roles — none by default

Create no `.claude/agents/*.md`. The main thread works inline and uses the built-in `Explore` /
`general-purpose` subagents for ad-hoc fan-out. Say so in the Step 10 summary: roles arrive via
`dev:harness-curate` when the transcripts show a delegation recurring.

The one exception: the user asked for a specific role this session. Create that role only, after
a reachability check — does its trigger fire in this repo's normal work? (`qa-verifier` needs
editable source; `explorer` needs real modules; `implementer` needs a `backlog.md` flow.) Role
files carry the spine in `references/harness-invariants.md` → *File Layout Invariants*; omit
`model:` so spawns inherit the session model. Keep generated docs consistent with the roster —
never a mandatory gate pointing at an agent that does not exist.

### Step 4c: Orchestrator skill — not at init

An orchestrator routes work to agents; with an empty roster it describes coordination the repo
cannot perform, and it loads on matching prompts. Build one only on explicit request, or later in
Extend mode once roles exist and the transcripts show the same multi-step workflow recurring —
that routes to `skill-creator`. Its body follows the Step 1 language; `CLAUDE.md` stays a pure
`@AGENTS.md` pointer.

## Step 5: Sweep automation — deferred

Do not copy `scripts/sweep.sh` at init; a harness created minutes ago has no drift. Install on
the first real signal (a stale doc, a violated principle, a model upgrade): copy it into the
project's `tools/`, adapt the `# ADAPT:` sections per `references/sweep-template.md`, and record
a trigger policy (manual / SessionStart with a 7-day stamp / weekly CI) in `docs/runbook.md`.

## Step 6: Lint message readability — on evidence only

Rewrite a lint message only after an agent stalls on it: append `FIX:` and `REF:` lines to it.

## Step 7: Build the enforcement chain

At Level 1 ship **Layer 0 only** — `permissions.deny` / `sandbox.enabled` in
`.claude/settings.json` block destructive actions regardless of what the model decides. Layers
1–3 (real-time hooks, pre-commit, CI gate; PR template optional) arrive with the maturity level
or a demonstrated risk. Ladder: must always run → hook; must be blocked no matter what →
settings-level deny; everything else → `AGENTS.md` or a path-scoped rule. Templates per layer,
plus the circuit breaker and consent gates: `references/enforcement-template.md`.

### Step 7b: Make delegation non-optional

Applies only once a role or orchestrator exists. Write its `description:` directively ("ALWAYS
invoke when X — do NOT inline-execute"); that is where auto-delegation is won. A
`UserPromptSubmit` router or a `PreToolUse` delegation gate (`references/enforcement-template.md`
→ *Delegation Gate*) is a fallback installed only on a measured miss or a critical path — never
preemptively, and never with an empty roster.

## Step 8: Repo root configs

- **`CLAUDE.md`** — exactly `@AGENTS.md`. A validated invariant; repair with
  `scripts/sync-claude-md.sh`. Claude-specific guidance goes in `.claude/rules/` or `AGENTS.md`.
- **Memory boundary** — harness files hold durable repo facts; auto-memory holds the model's
  discovered preferences. State it once in `## Maintenance`. Env vars:
  `references/power-user-settings.md`.
- **`.claudeignore`** — compose from `references/claudeignore-template.md` for the Step 1 stack.
- **`.agents/skills` symlink** → `../.claude/skills`:

  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -f "$SKILL_DIR/scripts/symlink-guard.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/symlink-guard.sh" >&2; exit 1; }
  bash "$SKILL_DIR/scripts/symlink-guard.sh"
  ```

  Fallback: `mkdir -p .agents && ln -s ../.claude/skills .agents/skills`. Accepted forms:
  `references/harness-invariants.md` → *File Layout Invariants*.

## Step 9: Validate

Run `scripts/validate-harness.sh`. Non-zero → halt, show the full report, do not auto-fix. It
checks required files, the AGENTS.md size band, the `CLAUDE.md` pointer, the symlink, the
`backlog.md` schema, the `## Maintenance` block, golden principles, delegation, and enforcement.
Manual checklist: no generated rule contradicts the operator's global layer (every Step 0b
conflict was resolved by the user); each golden principle has a check; no doc names a role that
does not exist; no role pins a model; every skipped doc is named with its trigger; `docs/` files
do not duplicate each other.

## Step 10: Explain to the user

Show all five: the full `AGENTS.md`; every created file with a one-line purpose; **what was
deliberately not created and what would create it** (roles/orchestrator → `harness-curate`
evidence; each skipped doc → its trigger; `backlog.md` → adopting sprints; sweep → the first
drift signal; Layers 1–3 → a level upgrade or a demonstrated risk); the maturity level reached
and the next level's cost; how to update `AGENTS.md` (the four `## Maintenance` conditions).
Do not describe a fresh init as drift-proof — only Level 3 makes drift prevention mechanical.

## Ongoing maintenance

| When | Action |
|------|--------|
| Periodically, or "harness 점검" | `bash scripts/validate-harness.sh` |
| A sprint finishes outside the task cycle | `python scripts/reconcile-harness.py` — close the `tasks.md` block |
| Feedback from harness usage | `dev:harness-curate` — detect, route to the creator with a named acceptance check |

Repair tools: `scripts/sync-claude-md.sh`, `scripts/symlink-guard.sh`, `scripts/check-context-size.sh`
— the `dev` plugin's SessionStart hook runs all three daily as a safety net. Full routine:
`references/maintenance.md`.

## Additional Resources

- **`references/design-rationale.md`** — evidence behind every rule above. Read before deviating.
- **`references/harness-invariants.md`** — file layout, size policy, spawn contract, verifier
  floor, absent-role fallbacks, non-interactive defaults, reconciliation and CHANGELOG contracts.
- **`references/maturity-levels.md`** — the three-level progression; other references are read at
  the step that cites them. **`examples/agents-md-example.md`** — a complete AGENTS.md.
