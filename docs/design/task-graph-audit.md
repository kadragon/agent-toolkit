# Design: `task-*` Pipeline Graph + Edge Enforcement Audit

**Status:** analysis (no code change in this doc)
**Branch:** `plan/task-graph-audit`
**Type:** `[PLAN]` — produces backlog items, not behavior.

## Why this exists

Inspired by LangChain's ["3 Years of Graph Engineering with LangGraph"](https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph),
which frames an agentic system as nodes (deterministic code / LLM call / full agent run) joined by
edges, placed along a determinism-to-agency spectrum. Applying that lens here does **not** mean
adopting a graph runtime — this repo is a harness, not an execution engine. It means naming a thing
the existing vocabulary could not name:

> The `task-*` skill family already **is** a cyclic graph. Its nodes are increasingly code. Its
> edges are prose.

Golden Principle 1 says *mechanical enforcement > verbal agreement*. Node outputs are checked
mechanically; transitions between nodes are not checked at all. That asymmetry is what this audit
measures.

Scope note: the lens applies to the `task-*` pipeline only. `harness-init` and `harness-curate` are
judgment-heavy and exploratory — the same article warns against forcing those into fixed paths, and
they stay prose-driven deliberately.

## The graph

```
[task-new] free-text                    [task-next] queue
    │ classify/size                         │ backlog_candidates.py
    ├─ trivial ────────────┐                ├─ Step 2.5 size gate
    ├─ ambiguous → grill ──┤                └──────────┬─ lite path ─┐
    └─ large → spec → tickets ─┘                       │             │
                           ↓                           ↓             │
                      ┌────────────── CODE CYCLE ──────────────┐     │
                      │ branch → scope(explorer) → plan-gate   │     │
                      │   → sprint-contract(tasks.md)          │     │
                      │   → implement ⇄ qa-verifier      (C1)  │     │
                      │        ↑ stuck-fix cap           (C2)  │     │
                      │   → version-bump → pre-merge cleanup   │     │
                      └────────────────┬───────────────────────┘     │
                                       ↓ --auto                      ↓
                      ┌──────────── task-review ──────────┐    direct merge
                      │ commit+PR → reviews (claude/agy/  │    (no PR, no CI)
                      │   codex) → consolidate (+verifier,│
                      │   contest, single pass) → apply   │
                      │   → retrospect → commit           │
                      │   → CI ⇄ fix  (C3) → merge        │
                      └───────────────┬───────────────────┘
                                      ↓ out-of-scope findings
                                  tasks.md ──→ next task-next run   (C4)
                                      ↓ harness-capture
                                  docs/ · auto-memory ──→ harness-curate  (C5)
```

Cycles: **C1** qa retry (1×) · **C2** stuck-fix cap (3×) · **C3** CI failure rework (3×) ·
**C4** out-of-scope re-entry · **C5** harness evolution.

## Edge enforcement audit

| # | Edge | Enforced by | Verdict |
|---|------|-------------|---------|
| 1 | pick → branch (no direct commit to `main`) | `dev/hooks/commit-guard/guard.py`, PreToolUse(Bash), exit 2 | mechanical |
| 2 | commit message `[TYPE] ` prefix | same hook, `TYPE_PATTERN` | mechanical |
| 3 | changed files → plugin version bump | `.github/workflows/harness-check.yml` → `version-bump` job, `exit 1` | mechanical (at merge, not at the edge) |
| 4 | skill/agent/command frontmatter valid | `harness-check.yml` → `skill-frontmatter` job | mechanical |
| 5 | plugin-root portability + capture-before-use | `harness-check.yml` → `harness-drift` job | mechanical |
| 6 | **implement → qa-verifier (mandatory, no self-verification)** | nothing — SKILL.md prose only | **gap (P0)** |
| 7 | **review slot → orchestrator (`SendMessage(to: "main")`)** | nothing — a line in the spawn prompt | **gap (P0)** |
| 8 | **loop bounds C1 (1×), C2 (3×), C3 (3×)** | nothing. `task-next/SKILL.md` states it outright: *"This is a prompted constraint, not a mechanically enforced cap — no loop-counter tooling exists for implementer sub-agents."* | **gap (P1)** |
| 9 | Sprint Contract exists before implement | nothing | gap (P2) |
| 10 | pre-merge cleanup contract (CHANGELOG ≤160 chars, backlog line deletion) | nothing | gap (P2) |
| 11 | working-tree gate, plan-mode gate | nothing — the model runs `git status` and decides | gap (P2) |
| 12 | `task-new` ↔ `task-next` boundary (no double entry) | nothing | gap (P3) |

**5 of 12 edges are mechanical.** All five check a *node's output* (a commit, a version, a
frontmatter block). **Zero check a transition.** The pipeline verifies what was produced and never
verifies which path produced it.

## Primary finding

`dev/skills/harness-init/references/enforcement-template.md` already ships the two mechanisms that
close the worst gaps:

- **Delegation Gate** — PreToolUse `Edit|Write` block unless a delegation evidence file exists under
  `.claude/tmp/`. This is the shape that enforces edge #6.
- **Circuit Breaker** — halt after N consecutive failures. This is the shape that enforces edge #8.

Neither is installed in this repo. The harness we ship to other repos is not applied to the repo
that authors it.

## Secondary finding — node determinism placement

| Skill | Bundled scripts | Consequence |
|-------|-----------------|-------------|
| `task-review` | 11 (`preflight`, `commit-and-push`, `ci-wait`, `merge-and-cleanup`, …) | nodes are code; behavior is reproducible |
| `task-next` | 1 (`backlog_candidates.py`) | branch creation, version bump, CHANGELOG insertion, backlog line deletion are prose instructions |
| `task-new` | 0 | same, plus Sprint Contract authoring |

Branch derivation, version bump, CHANGELOG insertion and backlog-line deletion are deterministic
transforms where model judgment adds nothing. They belong on the code side of the spectrum. This is
the same direction as the global anti-generation ladder, reached from a different premise.

## Resulting backlog items

Filed under `## Harness — task-* graph enforcement` in `backlog.md`, in priority order:

1. `[CONSTRAINT]` qa-verifier gate (edge #6)
2. `[CONSTRAINT]` review-slot handoff accounting (edge #7)
3. `[HARNESS]` shared loop-counter / circuit breaker for C1–C3 (edge #8)
4. `[HARNESS]` script out the deterministic `task-next` / `task-new` nodes
5. `[CONSTRAINT]` CHANGELOG Entry Contract lint (edge #10)

## Explicitly out of scope

- Adopting LangGraph or building a graph execution runtime.
- Adding node/edge vocabulary to `AGENTS.md` — it fails the repo's own bloat test.
- Converting `harness-init` / `harness-curate` into fixed pipelines.
