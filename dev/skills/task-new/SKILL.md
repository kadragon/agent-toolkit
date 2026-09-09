---
name: task-new
version: 2.1.0
description: >-
  Intake for new work you just described — classify, size, then run the full code cycle:
  branch, Sprint Contract, implement, version bump, review. Already on the queue
  instead → task-next.
disable-model-invocation: true
---

# New Task

Turn a fresh free-text request — not yet an item in `backlog.md`/`tasks.md` — into a Sprint
Contract, then run the same code cycle `task-next` runs. If the request already matches a queue
item, stop and route to `task-next`.

## Prerequisites

Read `backlog.md` and `docs/conventions.md` when present. A standalone task needs neither backlog
nor harness initialization. Require/create `backlog.md` only when this run writes queue tickets
or deferred findings; a missing queue is not a blocker for a self-contained code cycle.

**Working tree gate** — apply `task-next`'s gate in the same order: inspect any feature branch
for in-flight work, even when clean, via `../task-next/references/edge-cases.md`. On the base
branch, a clean tree proceeds; backlog-only edits proceed with the delta announced and carried.
Other dirty base state requires ownership/recovery diagnosis before new work.

## Step 1 — Classify and size

Infer the tag: adds or changes user-visible behavior → `[FEAT]`; restructures without changing
behavior → `[REFACTOR]`; fixes broken behavior → `[FIX]`; otherwise untagged.

Size by independently testable outcome and unresolved decisions. A small feature or mechanical
multi-file edit may fit one contract. Use `../task-next/references/cycle.md` → *Plan gate* for
approval; tags and file counts are context, not gates. Inspect the relevant area before sizing.

## Step 2 — Route

First match wins, so read the rows in order and check the last one against the request first:
"clear" is not "small", and a fully specified request can still be too large for one contract.

- **Ambiguous** (scope, requirement, or a design decision unclear) → call the
  Skill tool with "dev:task-grill"; continue only when it reports the open questions resolved,
  then re-route on the rows below.
- **Multi-session or architecturally significant** → call the Skill tool twice, for
  "dev:task-spec" and then "dev:task-tickets"; then pick the first ready ticket (topologically
  first, no unresolved `*(blocked by: …)*`) and run Step 3 on that one ticket. The rest stay in
  `backlog.md` for `task-next`.
- **Clear, bounded, and single-session-sized** → build the Sprint Contract from the request (or
  the grill output), go to Step 3.

Exactly one cycle runs per invocation. Several unrelated requests → handle the first, tell the
user to re-invoke (or queue them for `task-next --all`).

## Step 3 — Run the cycle

Follow `../task-next/references/cycle.md` end to end (its `CYCLE_DIR` is that references
directory) with these overrides:

- **Branch** — no stdin; pass `--tag <TYPE>` from Step 1, or omit it when untagged and accept the
  `fix/` fallback.
- **Sprint Contract** — archive on every path per the shared cycle. Only a `task-tickets` ticket
  also writes `tasks.md` with `status: active` and a `## Covers` line holding the ticket's `- [ ]`
  item verbatim, the deletion target for cleanup.
- **Cleanup** — `prune-tasks` and `prune-backlog` only on the ticket path; update `CHANGELOG.md`
  when the repo maintains one. Do not scaffold a harness to finish standalone work.

## Step 4 — Hand off

Per `cycle.md` → *Hand off*: `args: --from task-new --auto`, Sprint Contract restated verbatim.
