---
name: start-task
version: 1.0.0
description: >-
  Trigger: "start a task", "pick the next task", "work the backlog", "next task",
  "start work", "다음 작업 시작", "백로그에서 작업 골라", "작업 하나 돌려줘", "백로그 시작",
  "작업 시작", "백로그 작업". Picks an open item from backlog.md/tasks.md, drives the full
  code cycle (branch → Sprint Contract → implement → qa-verifier → version bump), and hands
  off to dev-review-cycle --auto for review, CI, and merge. NOT for: resuming mid-flight work
  that already has a branch with uncommitted changes (→ invoke dev-review-cycle directly),
  review-only requests, or exploring backlog without intent to implement+merge this session.
---

# Start Task

Thin orchestration spine over the `code` cycle in `docs/workflows.md`. Picks work, runs
the cycle, hands off to `dev-review-cycle --auto`. The heavy lifting is delegated — this skill
is the **decision and sequencing layer**, not the implementation engine.

## Prerequisites

The repo must have `backlog.md`, `tasks.md`, and `docs/workflows.md` (harness-init artifacts).
If any are missing, stop and point the user to `dev-tools:harness-init`. A clean working tree
is expected; commit or stash uncommitted changes first.

## Step 1 — Gather candidates

Read both files:

- **backlog.md** → collect every `- [ ]` item under `## Now` and `## Next` only. Exclude `## Someday` and `## History`.
- **tasks.md** → collect every `- [ ]` item. Carry priority label (P0–P3) and `file:line` reference.

Order: tasks.md P0→P1→P2→P3 first, then backlog `## Now`, then backlog `## Next`. Within each tier, preserve file order.

## Step 2 — Select

| Candidates found | Action |
|-----------------|--------|
| 0 | Report "backlog and tasks are clear — nothing open to start." Stop. |
| 1 | Announce the item (type tag + short text + file:line), proceed immediately. |
| ≥2 | Present top candidates (cap at 4) with `AskUserQuestion`. Each option: type tag, first ~80 chars, file:line. Wait for selection. |

If the user picks a tasks.md finding, the item's `file:line` is the natural scope anchor.

## Step 3 — Run the code cycle

Execute `docs/workflows.md` → `code` cycle (Steps 0–6) with these start-task-specific
overrides and decisions:

**Branch (Step 0 override)**
Derive `git checkout -b <type>/<slug>` from the chosen item's `[type]` tag + a short slug.

**Mark active**
If the item came from `backlog.md`, flip its checkbox `[ ]` → `[>]` to signal in-flight.
Leave `tasks.md` items as `[ ]` (resolved via dev-review-cycle's Step 5 commit later).

**Plan mode gate (before Step 2)**
Decide scope:
- **Trivial** (1–2 files, bounded change): skip plan mode, go straight to Sprint Contract.
- **Non-trivial** (≥3 files touched, OR any new public API/schema introduced, OR task tag is `[FEAT]` or `[REFACTOR]`): fetch plan-mode tools via `ToolSearch` (`query: "select:EnterPlanMode,ExitPlanMode"`), call `EnterPlanMode`, design the approach, call `ExitPlanMode` for user approval before coding.

**Sprint Contract (Step 2)**
Per `docs/eval-criteria.md` template: **Scope** (files) / **Acceptance criteria** / **Out of scope** / **Lint/test command**.

**Implement (Step 3 override)**
- ≤2 files and straightforward: inline edit.
- Otherwise: spawn `implementer` agent. Brief must include: Sprint Contract + absolute paths of all in-scope files + the lint/test command from the contract. `implementer` must NOT verify its own output.

**QA (Step 4 — mandatory)**
ALWAYS spawn `qa-verifier` as a separate agent. The agent that implemented must not verify.

**Version bump (Step 5)**
Per `docs/conventions.md` — AFTER all changes, BEFORE handoff. In this repo: bump BOTH `dev-tools/.claude-plugin/plugin.json` and `dev-tools/.codex-plugin/plugin.json` (keep in sync).

**Do NOT commit.** Leave all changes (code + version bump) uncommitted. `dev-review-cycle`
Step 1 commits everything so there is one clean commit per review/merge cycle.

## Step 4 — Hand off

Invoke `Skill(dev-tools:dev-review-cycle)` with `args: --auto`.

`dev-review-cycle --auto` commits, creates PR, collects reviews, applies all in-scope findings
(skipping the manual approval pause), records out-of-scope items to `tasks.md`, waits CI,
and merges. If CI fails or a hard blocker surfaces, `dev-review-cycle` handles it per its
own error-handling table.

## Edge cases

**Work already in flight** — feature branch with uncommitted changes from a previous session.
Offer: "I see uncommitted changes on `<branch>`. Skip to `dev-review-cycle --auto`?" If yes,
hand off directly.

**Deferred backlog item** — item has `*(deferred: ...)*`. Surface the deferral reason before
proceeding so the user can confirm the blocker is resolved.

**tasks.md finding spans multiple PRs** — scope narrowly to the specific `file:line` ref.
Record broader related items back to `tasks.md` via the normal out-of-scope path.
