# Workflows

Six workflows. Pick the primary one per cycle. The `code` cycle's step-by-step procedure ships with `dev:task-next` (`references/cycle.md`); this page states the contract. See `docs/delegation.md` for how to brief a sub-agent once you have decided to delegate.

## `plan` — Spec Generation

Expand a short prompt into a concrete spec.

1. Expand into `docs/design/{feature}.md`: user stories, high-level design. No granular implementation details.
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

Primary cycle for behavioral changes. The procedure — branch (`task_nodes.py branch`), scope,
Sprint Contract (template and approval), implement, version bump, validation evidence, hand-off —
is `dev:task-next` → `references/cycle.md`. Repo-specific points:

- **Delegation** — default inline; thresholds in AGENTS.md → *Delegation*, briefs in
  `docs/delegation.md`. Eligibility never mandates a spawn.
- **Version bump** — per `docs/conventions.md`, after all skill changes, before committing.
- **Review** — call the Skill tool with "dev:task-review-cycle" and `args: --from <your skill
  name> --auto`, restating the Sprint Contract verbatim. `/task-review` is the human entry point;
  no skill calls it. Do not inline-manage the cycle.

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

## Cross-session resume

The code cycle archives its approved Sprint Contract under the common Git directory via `cycle_state.py`; recover that contract and its validation evidence to resume in a new session.

## Permitted Side-Effects

| Primary workflow | Permitted |
|-----------------|-----------|
| `code` | Add `[doc]` or `[constraint]` item to `backlog.md` |
| `code` | Update relevant docs after implementation |
| `draft` | Add `backlog.md` item when doc reveals missing behavior |
| `sweep` | Fix trivial `[doc]` items inline |

Not permitted: writing production code during `draft` or `sweep`.

Git effects follow the original contract's approval source/actions/limits, not `--from` or
`--auto`; read `dev:task-next` → `references/git-authorization.md` before writes.
