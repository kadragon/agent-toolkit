# Workflows

Six workflows. Pick the primary one per cycle. The `code` cycle's step-by-step procedure ships with `dev:task-next` (`references/cycle.md`); this page states the contract. See `docs/delegation.md` for how to brief a sub-agent once you have decided to delegate.

## `plan` — Spec Generation

Expand a short prompt into a concrete spec.

1. Expand into `docs/design/{feature}.md`: user stories, high-level design, phased list. No granular implementation details.
2. Review with user. Do not proceed until approved.
3. Generate `backlog.md` items from approved spec.

Skip for trivial features (one-line skill fix, comment update).

Steps 1-2 are automated by `dev:task-spec` (synthesizes conversation + `dev:task-grill`
output into `docs/design/{slug}.md`; does not interview the user). Step 3 is automated by
`dev:task-tickets` (breaks an approved spec into vertical-slice `backlog.md` items in
dependency order, using a `*(blocked by: <n>-<slug>)*` marker for blocking). `dev:task-new`
routes multi-session or architecturally significant requests through this chain. Clear bounded
requests go directly to a contract; unresolved material decisions go through `task-grill`.

## `code` — Implementation

Primary cycle for behavioral changes.

**Step 0: Branch**
Ensure you're on a feature branch. `git checkout -b <type>/<slug>` if on `main`.

**Step 1: Scope check**
Establish what the change touches. Look yourself first (1–2 searches). Spawn `explorer` only when
this cycle was directed to (by the user, or by the skill driving it) **and** the survey also clears
the global gate — 10+ files to read, or output that would flood main context.

**Step 2: Sprint Contract**
Before writing, define "done" in concrete, testable terms. Template in `docs/eval-criteria.md`.
Approval reuse and durable contract ownership live in `dev:task-next` → `references/cycle.md`;
intake, tickets, and resume follow that same authority.

**Step 3: Implement**
Implement directly. Delegate to `implementer` (with spec + conventions) only when the global
delegation bar is met — e.g. a backlog batch of independent items.

**Step 4: QA**
Implementers run focused checks; independent review separately grades requirements and
code quality and never replaces required checks; full required checks run on
the completed candidate after version bump and cleanup. Both rules are owned by `dev:task-next` →
`references/cycle.md`, under *Implement* and *Validation evidence*. Sequential `--all` shares one
final review; parallel units also get worktree QA.

**Step 5: Version bump**
Bump `plugin.json` patch/minor/major per `docs/conventions.md`. Do this AFTER all skill changes, BEFORE committing.

**Step 6: PR + review cycle**
Call the Skill tool with "dev:task-review-cycle" and `args: --from <your skill name> --auto`, restating the Sprint Contract verbatim (the model-invoked half; `/task-review` is the human entry point and no skill may call it). The `--from` token is required — see `dev:task-review-cycle` → *Caller gate*. The cycle commits, reviews the diff against the contract, routes by risk and required CI, applies findings, and merges. Do NOT inline-manage it. It runs a signal-gated retrospect (`dev:harness-capture`) only when a correction or gotcha surfaced, so a durable lesson rides into the same commit.

## `draft` — Documentation

Write or update `docs/`. Ground every claim in current code. Never modify production code during draft. If the doc reveals a missing constraint, add to `backlog.md`.

## `constrain` — Architectural Enforcement

1. Write CI check or lint rule first.
2. Run it.
3. If current code violates → add to `backlog.md`, don't fix here.
4. Update `docs/architecture.md`.

## `sweep` — Garbage Collection

Run between features or on schedule (`bash tools/sweep.sh`).

- Run `tools/sweep.sh`
- List findings tagged `[doc]`, `[constraint]`, `[debt]`, or `[harness]`
- Fix trivials inline
- Leave complex items in `backlog.md`
- Assess whether harness components are still load-bearing (see `references/sweep-template.md`)

## `explore` — Research

State the question → research/prototype → report options and tradeoffs → do not commit. Flows into `plan` or `code` if approved.

---

## Handoff Files

To combat context anxiety within a session (including across compaction) or before spawning a fresh subagent/switching teammates, write `handoff-{feature}.md` to your scratchpad dir at the START (when context is fresh). Scratchpad handoffs do not survive a new CLI session. The code cycle separately archives its approved Sprint Contract under the common Git directory via `cycle_state.py`; recover that contract and its validation evidence for cross-session resume.

Schema from `references/handoff-template.md`.

## Context Anxiety

Models prematurely wrap up work as context fills. Countermeasures:

1. Context resets over compaction for large tasks
2. Handoff files — write early, not when degraded
3. Sprint decomposition if quality drops mid-session

## Permitted Side-Effects

| Primary workflow | Permitted |
|-----------------|-----------|
| `code` | Add `[doc]` or `[constraint]` item to `backlog.md` |
| `code` | Update relevant docs after implementation |
| `draft` | Add `backlog.md` item when doc reveals missing behavior |
| `sweep` | Fix trivial `[doc]` items inline |

Not permitted: writing production code during `draft` or `sweep`.
