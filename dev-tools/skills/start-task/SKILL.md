---
name: start-task
version: 1.0.2
description: >-
  This skill should be used when the user says "start a task", "pick the next task",
  "work the backlog", "next task", "start work", "다음 작업 시작", "백로그에서 작업 골라",
  "작업 하나 돌려줘", "백로그 시작", "작업 시작", "백로그 작업", "태스크 시작", or
  "태스크 골라줘". Picks an open item from backlog.md or tasks.md, drives the full code
  cycle (branch → Sprint Contract → implement → qa-verifier → version bump), and hands off
  to dev-review-cycle --auto for review, CI, and merge. Not for review-only requests or
  backlog browsing without intent to implement and merge this session.
---

# Start Task

Act as the thin orchestration layer over the `code` cycle in `docs/workflows.md`. Pick work,
run the cycle, and hand off to `dev-review-cycle --auto`. Delegate the heavy lifting — this
skill is the **decision and sequencing layer**, not the implementation engine.

## Prerequisites

The repo must have `backlog.md`, `docs/workflows.md`, `docs/eval-criteria.md`, and
`docs/conventions.md` (harness-init artifacts). If any is missing, stop and point the user
to `dev-tools:harness-init`.

**Working tree gate:** Run `git status --porcelain`. If the output is non-empty, stop and
list the dirty files — do NOT proceed. Ask the user to commit, stash, or discard first.

`tasks.md` is optional: present in an active sprint or as a review-backlog accumulator; absent
in the idle state. If absent, only `backlog.md` candidates are offered.

## Step 1 — Gather candidates

Read both files:

- **backlog.md** → every `- [ ]` item under `## Now` and `## Next`. If neither heading exists,
  emit a warning ("No ## Now or ## Next in backlog.md — no backlog candidates included") and
  continue with tasks.md only.
- **tasks.md** (if present) → every `- [ ]` item under `## Review Backlog` sections only.
  Skip acceptance-criteria or sprint-scope checkboxes — those belong to the active sprint, not
  the candidate queue. Carry priority label (P0–P3) and `file:line`.

Order: tasks.md P0→P1→P2→P3 first (unlabelled items sort after P3), then backlog `## Now`,
then backlog `## Next`. Within each tier, preserve file order.

## Step 2 — Select

| Candidates found | Action |
|-----------------|--------|
| 0 | Report "backlog and tasks are clear — nothing open to start." Stop. |
| 1 (not deferred) | Announce the item and proceed to Step 3. |
| 1 (deferred) | The item has `*(deferred: ...)*`. Surface the blocker text and ask the user to confirm it is resolved before proceeding. If unresolved, report and stop. |
| ≥2 | Present top candidates (cap at 4) with `AskUserQuestion`. Each option: type tag, first ~80 chars, file:line. Wait for selection. |

## Step 3 — Run the code cycle

Execute `docs/workflows.md` → `code` cycle (Steps 0, 1, 2–5; Step 6 is this skill's Step 4).
Overrides below; standard steps apply where not overridden.

**Branch (workflows.md Step 0)**
`git checkout -b <type>/<slug>` — derive from the item's `[type]` tag + short slug. If the
item has no `[type]` tag (common for tasks.md findings), emit a warning ("Item has no [type]
tag — defaulting branch prefix to `fix/`") and use `fix/` prefix.

**Scope check (workflows.md Step 1)**
If the target area has >3 files AND was not explored this session → spawn `explorer` before
writing the Sprint Contract.

**Plan mode gate (before workflows.md Step 2)**
Check tag first, then file count:
- **Non-trivial** (tag is `[FEAT]` or `[REFACTOR]`, OR ≥3 files, OR new public API/schema):
  use `ToolSearch` (`query: "select:EnterPlanMode,ExitPlanMode"`) to load plan mode tools,
  call `EnterPlanMode`, design the approach, call `ExitPlanMode` for user approval. If
  ToolSearch returns no results, present the plan as a numbered list and wait for explicit
  "proceed" before coding.
- **Trivial** (tag is NOT `[FEAT]`/`[REFACTOR]` AND 1–2 files AND no new public API/schema):
  skip plan mode.

**Mark active — after scope is confirmed**
Once plan is approved (or trivial gate passed):
- If item came from `backlog.md`: flip `[ ]` → `[>]` AND write a `tasks.md` Sprint Contract
  with a heading matching the backlog line text and `status: active`. This gives
  `reconcile-harness.py` the anchor it needs to archive or revert the sprint at completion.
- If item came from `tasks.md` Review Backlog: leave its checkbox as `[ ]` — the finding
  resolves when the fix is committed and verified in a future review.

**Sprint Contract (workflows.md Step 2)**
Per `docs/eval-criteria.md` template: **Scope** / **Acceptance criteria** / **Out of scope** /
**Lint/test command**.

**Implement (workflows.md Step 3)**
- 1–2 files AND not `[FEAT]`/`[REFACTOR]`: inline edit.
- Otherwise: spawn `implementer` agent. Brief must include: Sprint Contract + absolute paths of
  in-scope files + lint/test command. `implementer` must NOT verify its own output.
- **If `implementer` fails or returns unusable output:** stop and report to user with reason.
  Do not proceed to qa-verifier.

**QA (workflows.md Step 4 — mandatory)**
ALWAYS spawn `qa-verifier` as a separate agent. The implementing agent must not verify.

If qa-verifier reports blocking issues:
1. Surface findings to user.
2. Spawn `implementer` with those findings as its brief to fix them.
3. Re-run `qa-verifier` once.
4. If still blocking after one retry: stop and report — do NOT hand off with unresolved blockers.

**Version bump (workflows.md Step 5)**
Per `docs/conventions.md` — determine which plugin directory contains the changed files and
bump its manifests (patch for modify, minor for new skill, major for remove/rename). Do this
AFTER all changes, BEFORE handoff.

**Do NOT commit.** Leave all changes uncommitted. `dev-review-cycle` Step 1 commits everything
so there is one clean commit per review/merge cycle.

## Step 4 — Hand off

Invoke `Skill(dev-tools:dev-review-cycle)` with `args: --auto`.

`dev-review-cycle --auto` commits, creates PR, collects reviews, applies in-scope findings,
records out-of-scope items to `tasks.md`, waits CI, and merges.

**After merge:** If the task came from `backlog.md`, set `tasks.md` `status: done` (or ask
the user to do so). `reconcile-harness.py` will then flip `[>]` → `[x]` and archive the sprint.
Do NOT mark done until the merge is confirmed — if dev-review-cycle reports CI failure or a
hard blocker, handle it per dev-review-cycle's error table first.

## Edge cases

**Work already in flight** — feature branch with uncommitted changes from a previous session.
Offer: "I see uncommitted changes on `<branch>`. Skip to `dev-review-cycle --auto`?"
- **Yes:** invoke `dev-review-cycle --auto` directly (skip Steps 1–3).
- **No:** ask whether to (a) stash and start a fresh task, (b) commit the in-flight work
  first, or (c) cancel. Do not proceed until the tree is clean or the user redirects.

**Deferred backlog item** — item has `*(deferred: ...)*`. Surface the blocker and confirm it
is resolved before proceeding. If unresolved, skip to the next candidate. If all candidates
are deferred with unresolved blockers, report that and stop.

**tasks.md finding spans multiple PRs** — scope narrowly to the specific `file:line` ref.
Record broader related items back to `tasks.md` via the out-of-scope path in dev-review-cycle.
