# Workflows Template

Six workflows. Pick the primary one per cycle. Minor side-effects are allowed (see bottom).

Adapt these to the project — not all projects need all six. A small library might only use `code` and `draft`. A large system might use all six.

## `plan` — Spec Generation

Expand a short prompt into a full product spec.

1. Expand into `docs/design/{feature}.md`: user stories, high-level tech design, phased feature list. **No granular implementation details** — errors cascade downstream.
2. Review with user. Don't proceed until approved.
3. Generate `backlog.md` items from approved spec.

Skip for trivial features.

## `code` — Implementation

The primary cycle for behavioral changes. Runs inline unless configured roles exist.

**Step 0: Branch**
Before editing, use a feature branch within the user's Git authorization.

**Step 1: Scope check**
Inspect the relevant code first. Delegate only past this repo's verified thresholds, naming
only roles that exist.

**Step 1.5: File Ownership Declaration (multi-agent only)**
If the sprint will spawn ≥2 parallel subagents, the lead declares file-ownership globs per role before spawning anyone — in `tasks.md`, or inline in the conversation when this cycle wrote no `tasks.md`. Overlapping globs cause silent overwrites; a cross-boundary edit needs the lead's approval.

```markdown
## File Ownership
- implementer-A: `src/api/users/**`, `tests/api/users/**`
- implementer-B: `src/web/users/**`, `tests/web/users/**`
- qa-verifier:   read-only (any path), writes only to `docs/eval/**`
```

Skip this step for single-agent work.

**Step 2: Sprint Contract**
Before writing code, define done in concrete, testable terms and preserve already approved scope,
criteria, and approach. Independent grading later uses that contract; a separate evaluator
approval is not a prerequisite to implementation.

Template: `dev:task-next` → `references/cycle.md` → *Sprint Contract*.

Adapt testing approach to the project:
- **Projects with test frameworks:** Red → Green → Refactor (TDD cycle)
- **Projects without tests:** Reference implementation → Implement → Lint/verify → Manual check
- **Legacy systems:** Read existing patterns → Implement following patterns → Cross-verify consistency

**Step 3: Implement**
Implement inline by default, running focused tests for fast feedback. Delegate only when the
platform delegation rules authorize it and independent work justifies the coordination cost.

**Step 4: Post-implementation QA (mandatory — delegated only if a QA role exists)**
Run full required checks on the completed candidate. Independent QA grades requirements and
code quality; it does not replace implementer checks. For task-cycle runs, approval, contract
persistence, and check reuse are owned by `dev:task-next` → `references/cycle.md`. Without that
skill, preserve the approved contract through completion and reuse checks only for proven
equivalent inputs, commands, and environment; disclose unavailable independent evaluation.

**Step 5: Feature-complete evaluation (mandatory — same rule)**
When the feature is done, grade it against the done-when criteria and `docs/eval-criteria.md`. Delegate to an evaluator role if one exists. Generator-Evaluator separation is the goal wherever a separate evaluator is available; where it is not, the written criteria are what keep the self-grade honest.

**`backlog.md` format:**

```markdown
## Feature Name
> Goal: what and why.
> Design: docs/design/{feature}.md
> Done-when: (concrete acceptance criteria — agreed BEFORE coding)

- [ ] Simplest case
- [ ] Next case builds on previous
```

## `draft` — Documentation

Write or update `docs/`. Ground every claim in current code. Never modify production code. If the doc reveals a missing constraint, add to `backlog.md`.

## `constrain` — Architectural Enforcement

1. Write structural test or lint rule first.
2. Run it.
3. If current code violates → add remediation to `backlog.md`, don't fix here.
4. Update `docs/architecture.md`.

## `sweep` — Garbage Collection

Fight entropy. Run between features or on a schedule.

- Run automated sweep script (`tools/sweep.sh` or equivalent)
- List findings in `backlog.md` tagged as `[doc]`, `[constraint]`, `[debt]`, or `[harness]`
- Fix trivials inline
- Leave complex items for later
- Include harness simplification: "Is this component still compensating for a real model limitation?"

## `explore` — Research

State the question → research/prototype → report options and tradeoffs → **do not commit**. If approved, flows into `plan` or `code`.


## Permitted Side-Effects

While in a primary workflow, these side-effects are allowed without switching:

| Primary workflow | Permitted side-effect |
|------------------|-----------------------|
| `code` | Add `[doc]` or `[constraint]` item to `backlog.md` when discovering issues |
| `code` | Update relevant docs after implementation |
| `draft` | Add `backlog.md` item when doc reveals missing behavior |
| `sweep` | Fix trivial `[doc]` items inline |

**Not permitted:** Writing production code during `draft` or `sweep`.
