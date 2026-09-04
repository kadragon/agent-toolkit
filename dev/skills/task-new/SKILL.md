---
name: task-new
version: 2.0.0
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

**Required:** `backlog.md`. Missing → stop and point to `dev:harness-init`. Read
`docs/conventions.md` when present; when absent the linter is the authority.

**Working tree gate** — the same rule as `task-next`'s: a clean tree proceeds; a tree where only
`backlog.md` is dirty proceeds with the edit announced and carried; a dirty feature branch is
`task-next`'s *Work already in flight* case — route there; anything else stops and asks the user
to commit, stash, or discard.

## Step 1 — Classify and size

Infer the tag: adds or changes user-visible behavior → `[FEAT]`; restructures without changing
behavior → `[REFACTOR]`; fixes broken behavior → `[FIX]`; otherwise untagged.

**Trivial** iff all hold: tag is not `[FEAT]`/`[REFACTOR]`, in-scope files ≤ 2, no new public
API/schema. An untagged one-file typo fix is trivial; "로그인 버튼 추가해줘" is `[FEAT]` and is
not. Unsure of the file count → one scoped scan first.

## Step 2 — Route by size

- **Trivial** → build the Sprint Contract from the request, go to Step 3.
- **Non-trivial and ambiguous** (scope, requirement, or a design decision unclear) → call the
  Skill tool with "dev:task-grill"; continue only when it reports the open questions resolved.
- **Single-session-sized** → contract from the request (or the grill output), Step 3.
- **Multi-session or architecturally significant** → call the Skill tool twice, for
  "dev:task-spec" and then "dev:task-tickets"; then pick the first ready ticket (topologically
  first, no unresolved `*(blocked by: …)*`) and run Step 3 on that one ticket. The rest stay in
  `backlog.md` for `task-next`.

Exactly one cycle runs per invocation. Several unrelated requests → handle the first, tell the
user to re-invoke (or queue them for `task-next --all`).

## Step 3 — Run the cycle

Follow `../task-next/references/cycle.md` end to end (its `CYCLE_DIR` is that references
directory) with these overrides:

- **Branch** — no stdin; pass `--tag <TYPE>` from Step 1, or omit it when untagged and accept the
  `fix/` fallback.
- **Sprint Contract** — inline, no file, on every path except a `task-tickets` ticket: that one
  writes `tasks.md` with `status: active` and a `## Covers` line holding the ticket's `- [ ]`
  item verbatim, the deletion target for cleanup.
- **Cleanup** — `prune-tasks` and `prune-backlog` only on the ticket path; `changelog` always.

## Step 4 — Hand off

Per `cycle.md` → *Hand off*: `args: --from task-new --auto`, Sprint Contract restated verbatim.
