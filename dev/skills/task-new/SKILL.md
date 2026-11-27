---
name: task-new
version: 2.8.0
description: >-
  Intake for new work you just described — classify, size, then run the full code cycle:
  branch, Sprint Contract, implement, version bump, review, commit, push, PR and merge
  (possibly direct base-branch merge/push). Flag: --tree (worktree isolation). Multi-session
  work goes to a spec plus queue tickets instead. Already on the queue instead → task-next.
disable-model-invocation: true
---

# New Task

Turn a fresh free-text request into a Sprint Contract, then run the same code cycle
`task-next` runs. If the request already matches an item in the resolved queue, stop and
route to `task-next`.

## Prerequisites

Resolve the checkout's queue backend with `queue_backend.py describe` using
`../task-next/SKILL.md` → *Prerequisites* (set `SKILL_DIR` to the task-next skill directory and
leave `REF` empty for intake, including `--tree`). Use the resolved queue to check whether the
request is already tracked. Read `docs/conventions.md` when present. On `backlog`, read
`backlog.md` when present and create it only if writing tickets or findings. A standalone
task needs neither a backlog file nor harness initialization.

**Working tree gate** — apply `../task-next/SKILL.md` → *Working tree gate* with the
resolved `BACKEND`: its capture block, then its table rows in order.

## Step 1 — Classify and size

For `Dispatch mode: parallel-worktree`, classify and size only the assigned unit.

Infer the tag from the **Tag:** list in `../task-next/references/cycle.md` → *Sprint Contract* —
the one that names the change (a docs-only request is `[DOCS]`, a harness change `[HARNESS]`).

Size by independently testable outcome and unresolved decisions. For a record-only request,
size the queue edit itself. A small feature or mechanical multi-file edit may fit one contract.
Use `../task-next/references/cycle.md` → *Plan gate* for
approval; tags and file counts are context, not gates. Inspect the relevant area before sizing.

## Step 2 — Route

For a `--tree` handoff with `Dispatch mode: parallel-worktree`, classify only the assigned
unit. If the assignment is missing, already queued, unclear, larger than one contract, or
requires shared planning, report the blocker to the home session and stop before writing.
Keep planning-only work in one session. On `backlog`, report any assignment requiring queue
edits and stop, except when the home session assigned an already scoped queue-only edit
as the wave's sole write to that backlog. A queue-only assignment that passes these checks
follows **Queue without implementing** below. For implementation, verify the original request
and Git limits per `../task-next/references/git-authorization.md`, then proceed to Step 3.

For other runs, first match wins. Size comes before clarity: a fully specified request
can still be too large for one contract.
- **Queue without implementing** (the user asks only to record it):
  - Issues backend → call the Skill tool with "dev:task-tickets" to file the issues under the
    standing `queue-write` grant, then stop and report the ticketing result. This route skips
    the commit-authority check and *Queue documentation cycle*, including on a parallel dispatch.
  - Dispatched `--tree` on `backlog` → verify commit authority for the queue edit from the
    forwarded human request and Git limits per `../task-next/references/git-authorization.md`.
    If established, take *Queue documentation cycle* below. Otherwise report the blocker and
    stop before writing.
  - Other runs on `backlog` → call the Skill tool with "dev:task-tickets" on the request,
    then stop after writing the tickets.
- **Multi-session or architecturally significant** → call the Skill tool twice, for
  "dev:task-spec" (after "dev:task-grill" when its scope is still ambiguous) and then
  "dev:task-tickets"; then **stop** — no cycle runs this invocation.
  Implementation starts in a fresh session that holds the written spec, not the interview that
  produced it: tell the user to `/clear` and run `/dev:task-next`, which picks the first ready
  ticket (in Codex, the `task-next` skill-picker entry in a new session). The working-tree gate
  carries the uncommitted `docs/design/` spec on both backends and `backlog.md` on `backlog`.
- **Ambiguous** (scope, requirement, or a design decision unclear) → call the
  Skill tool with "dev:task-grill"; continue only when it reports the open questions resolved,
  then re-route on these rows.
- **Clear, bounded, and single-session-sized** → build the Sprint Contract from the request (or
  the grill output), go to Step 3.

At most one cycle runs per invocation. Several unrelated requests → handle the first, tell the
user to re-invoke (or queue them for `task-next --all`).

### Queue documentation cycle

On `backlog`, use Steps 3–4 for the queue edit. Archive a Sprint Contract scoped to recording the assigned
tickets, with the verified Git authority and limits. Apply `--tree` for checkout isolation
only. At *Implement*, call the Skill tool with "dev:task-tickets" from the cycle's checkout.
Keep the selected backend for that call by setting `AGENT_QUEUE_BACKEND=backlog` on its queue
commands if the cycle uses a separate checkout.
After writing the approved tickets, return to this cycle with the ticket list in place of the
ticket skill's standalone handoff. If ticketing is blocked or leaves no queue delta, report
that outcome and the saved branch and contract, then stop before review. Verify the ticket
entries and continue through applicable release steps, *Validation evidence*, and Step 4.
The tickets remain open for a later implementation cycle.

At handoff, pass `--pr` when feature push and PR write are authorized. The review cycle owns
commit, PR and merge within the saved limits. Report the result at the applicable limit,
such as a reviewed local commit under `no-push`. For a parallel dispatch with a PR, honor its
pre-merge stop and report `ready` after review and required CI, with the checkout, archived
contract and PR. When the home session explicitly releases that PR's pre-merge stop for
serial merge, recover the archive from the same checkout and re-enter Step 4 for the existing
PR. Recheck the saved merge permission and final head at the review cycle's merge gate.
Report `merged` only after confirmation.

## Step 3 — Run the cycle

Follow `../task-next/references/cycle.md` end to end (its `CYCLE_DIR` is that references
directory) with these overrides. Verify the originating user invocation and preserve its
Git limits per `../task-next/references/git-authorization.md` before writes:

- **Branch** — no stdin; pass `--tag <TYPE>` from Step 1. `--tree` → replace the block with
  `../task-next/references/tree.md` → *Branch*, swapping its piped item lines for `--tag <TYPE>`
  and an empty `BASE_SHA` (it pins `origin/HEAD`'s commit, levels the local base only when this checkout is clean
  on it, and leaves this checkout's branch and uncommitted edits untouched), then run the whole
  cycle as a `cycle.md` → *Worktree cycle* from any branch or dirty state (the gate's `--tree` row). Nothing is claimed: no `tasks.md`, and a free-text request is not on the queue.
- **Sprint Contract** — archive per the shared cycle. No `tasks.md`: a free-text request has no
  queue line to delete.
- **Cleanup** — skip `prune-tasks` and `prune-backlog`; this cycle claims no queue items.
  When the repo maintains a `CHANGELOG.md`, record the completed scoped change. In a queue
  documentation cycle, title the entry for the act of recording the tickets. Do not scaffold
  a harness to finish standalone work.

## Step 4 — Hand off

Per `cycle.md` → *Hand off*: `args: --from task-new --auto`, Sprint Contract restated verbatim.
`--tree` → hand off from the worktree and state its absolute path, so the review cycle runs
there, takes the hub path, and passes the path to `merge-and-cleanup.sh` (*Worktree cycle* →
*Route*, *Merge*).
