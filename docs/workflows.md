# Workflows

Six workflows. Pick the primary one per cycle. See `docs/delegation.md` for routing details.

## `plan` — Spec Generation

Expand a short prompt into a concrete spec.

1. Expand into `docs/design/{feature}.md`: user stories, high-level design, phased list. No granular implementation details.
2. Review with user. Do not proceed until approved.
3. Generate `backlog.md` items from approved spec.

Skip for trivial features (one-line skill fix, comment update).

Steps 1-2 are automated by `dev-tools:to-spec` (synthesizes conversation + `dev-tools:grill`
output into `docs/design/{slug}.md`; does not interview the user). Step 3 is automated by
`dev-tools:to-tickets` (breaks an approved spec into vertical-slice `backlog.md` items in
dependency order, using a `*(blocked by: <n>-<slug>)*` marker for blocking). `dev-tools:next-tasks`
Step 0.5 routes ad-hoc, non-trivial free-text requests through this same
grill → to-spec → to-tickets chain automatically.

## `code` — Implementation

Primary cycle for behavioral changes.

**Step 0: Branch**
Ensure you're on a feature branch. `git checkout -b <type>/<slug>` if on `main`.

**Step 1: Scope check (delegation gate)**
Check objective triggers in `docs/delegation.md`:
- Target skill/plugin area not explored this session AND has >3 files → spawn `explorer`
- First edit in a directory this session → spawn `explorer` first

**Step 2: Sprint Contract**
Before writing, define "done" in concrete, testable terms. Template in `docs/eval-criteria.md`.

**Step 3: Implement**
For ≤2 files: implement directly. Larger: delegate to `implementer` role with spec + conventions.

**Step 4: QA (mandatory delegation)**
Always delegate to `qa-verifier`. The agent that implemented must NOT verify its own work.

**Step 5: Version bump**
Bump `plugin.json` patch/minor/major per `docs/conventions.md`. Do this AFTER all skill changes, BEFORE committing.

**Step 6: PR + review cycle**
Use `dev-tools:dev-review-cycle` skill. Do NOT inline-manage review cycle.

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

To combat context anxiety within a session (including across compaction) or before spawning a fresh subagent/switching teammates, write `handoff-{feature}.md` to your scratchpad dir at the START (when context is fresh). This does NOT survive a new CLI session — for genuine multi-day continuity there is currently no supported mechanism; say so explicitly rather than implying otherwise.

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
