---
name: next-tasks
version: 1.1.2
description: >-
  This skill should be used when the user says "start a task", "pick the next task",
  "work the backlog", "next task", "start work", "다음 작업 시작", "백로그에서 작업 골라",
  "작업 하나 돌려줘", "백로그 시작", "작업 시작", "백로그 작업", "태스크 시작", or
  "태스크 골라줘". Picks an open item from backlog.md or tasks.md, drives the full code
  cycle (branch → Sprint Contract → implement → qa-verifier → version bump), and hands off
  to dev-review-cycle --auto for review, CI, and merge. With the `--all` flag (also "전부
  처리", "모두 돌려", "다 처리", "batch all", "all tasks") it batches: the user multi-selects
  bounded items, each implemented + QA'd in its own git worktree in parallel, then all merged
  into one integration branch for a single version bump → reconcile → dev-review-cycle --auto
  (one PR). Not for review-only requests or backlog browsing without intent to implement.
---

# Next Tasks

Act as the thin orchestration layer over the `code` cycle in `docs/workflows.md`. Pick work,
run the cycle, and hand off to `dev-review-cycle --auto`. Delegate the heavy lifting — this
skill is the **decision and sequencing layer**, not the implementation engine.

**Mode routing:** default = single-pick (Steps 1–4 below). If the invocation carries `--all`
(or "전부 처리", "모두 돌려", "다 처리", "batch all"), run **Batch mode** instead — see the
`## Batch mode (--all)` section. Prerequisites and the working-tree gate apply to both modes.

## Prerequisites

The repo must have `backlog.md`, `docs/workflows.md`, `docs/eval-criteria.md`, and
`docs/conventions.md` (harness-init artifacts). If any is missing, stop and point the user
to `dev-tools:harness-init`.

**Working tree gate:** Run `git status --porcelain`. If the output is non-empty, stop and
list the dirty files — do NOT proceed. Ask the user to commit, stash, or discard first.

`tasks.md` is optional: present in an active sprint or as a review-backlog accumulator; absent
in the idle state. If absent, only `backlog.md` candidates are offered.

## Step 1 — Gather candidate groups

**Fast path (single-pick only):** Check `tasks.md` for open h1 sprint blocks first:

```bash
grep -En "^# |^status:" tasks.md 2>/dev/null
```

For each `# ` heading, check if the immediately following `status:` line reads `open`. Collect all matching h1 titles in document order.

If ≥1 found: present up to the **first 3** using `AskUserQuestion` (single-select) so the user gets a proper selection UI. Include a "더 많은 항목 보기" option as the last choice to trigger the full scan. Do not run the backlog.md grep or build the full candidate list — open sprint items are the obvious next work.

**Full scan (fast path found nothing, or `--all` batch mode):** Run both greps to build the complete candidate list:

```bash
grep -En "^#{1,3} |^- \[ \]|^status:" tasks.md 2>/dev/null
grep -En "^#{1,3} |^- \[ \]" backlog.md 2>/dev/null
```

From the output, group each `- [ ]` line under its nearest preceding heading. A group is **candidate** if it directly contains ≥1 open `- [ ]` line ("directly" means no narrower sub-heading sits between the item and this heading).

**tasks.md candidates (in order):**
1. h1 (`# `) blocks with `status: open` — the `tasks.md` grep above captures `status:` lines; match each h1 heading to the `status:` line that immediately follows it. The h1 title is the sprint scope; do not expand item list here.
2. h3 (`### `) sub-headings under `## Review Backlog` that directly own ≥1 open `- [ ]`.
3. h2 (`## `) headings outside Review Backlog that directly own ≥1 open `- [ ]`.

Skip h1 blocks with `status: active` (already in flight) or `status: done`.

**backlog.md candidates (after tasks.md):**
4. h3 (`### `) sub-headings under any h2 container that directly own ≥1 open `- [ ]`.
5. h2 (`## `) headings that directly own ≥1 open `- [ ]` (domain groups, `## Now`, `## Next`).

Skip headings where every item is `[x]` or `[>]`. Note: all h2/h3 headings with open checkboxes are candidates — including `## Ideas` or `## Someday` sections left unscheduled. Authors must use `[>]` or `[x]` to park items intentionally; the old `## Now`/`## Next` allowlist is removed.

## Step 2 — Select

| Groups found | Action |
|-------------|--------|
| 0 | Report "backlog and tasks are clear — nothing open." Stop. |
| 1 | Announce the group and proceed to Step 3. |
| ≥2 | Print a numbered list of all groups (no cap): `[N] <source>: <heading title> (<M> items)`. Wait for the user to reply with a number. |

**Large-group guard:** if the selected group has >8 open items, confirm with the user before proceeding — list the items numbered and ask whether to process all or a subset.

**Deferred items:** a group where every open item has `*(deferred: ...)*` is not a candidate. Skip it and surface the blocker. If all groups are deferred with unresolved blockers, report and stop.

Do NOT use `AskUserQuestion` — a plain numbered list handles any list size without the 4-option cap.

## Step 3 — Run the code cycle

Execute `docs/workflows.md` → `code` cycle (workflows.md Steps 0–5; workflows.md Step 6 is this skill's Step 4).
Overrides below; standard steps apply where not overridden.

**Branch (workflows.md Step 0)**
`git checkout -b <type>/<slug>` — derive from the item's `[type]` tag + short slug.
For a heading group: use the common `[type]` if all items share one (e.g. all `[FIX]` →
`fix/<slug>`); otherwise default to `fix/`. If the item has no `[type]` tag (common
for tasks.md findings), emit a warning ("Item has no [type] tag — defaulting branch prefix
to `fix/`") and use `fix/` prefix.

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
Once plan is approved (or trivial gate passed), derive action from the selected group's source:

*tasks.md h1 block (`status: open`):* flip `status: open` → `status: active` in tasks.md.
  The existing h1 block IS the Sprint Contract — do not write a new one. Read the h1 block's
  body (especially `## Acceptance criteria` if present) for implementation scope.

*tasks.md finding group (h3 under Review Backlog, or h2 grab-bag):* leave `[ ]` checkboxes
  as-is — findings resolve when the fix is committed and verified. No `[>]` flip; no
  `## Covers` section needed.

*backlog.md group (h2 or h3):* flip each open `- [ ]` under the heading → `[>]`. Write a
  `tasks.md` Sprint Contract with:
  - `# heading` = the selected heading title (verbatim from backlog.md)
  - `status: active`
  - `## Covers` listing each `[>]`-flipped item's **exact text** as a bullet.
  `reconcile-harness.py` reads `## Covers` at completion and archives/reverts each listed
  `[>]` anchor — no orphans.

**Sprint Contract (workflows.md Step 2)**
Per `docs/eval-criteria.md` template: **Scope** / **Acceptance criteria** / **Out of scope** /
**Lint/test command**.

For a multi-item group: Acceptance criteria has **one concrete checkbox per item** — do not
merge them into a single vague criterion. Scope lists all in-scope files/areas.

**Implement (workflows.md Step 3)**
- 1–2 files AND not `[FEAT]`/`[REFACTOR]` (including small bundles that still touch ≤2
  files in total): inline edit.
- Otherwise: spawn `implementer` agent. Brief must include: Sprint Contract + absolute paths
  of all in-scope files + lint/test command (follow `docs/delegation.md` four-field format:
  Objective / Output format / Tools to use / Boundaries). List each item's
  file:line in the brief so the implementer works all of them. `implementer` must NOT verify
  its own output.
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

**Pre-merge cleanup (do before Step 4)**

Mark the sprint done and sync tracking files — leave as uncommitted so they land in the
initial PR commit alongside the code.

*Task came from tasks.md h1 block:*
1. In `tasks.md`: change `status: active` → `status: done`
2. Run `reconcile-harness.py` from the project root:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/harness-init/scripts/reconcile-harness.py"
   ```
   This archives the sprint and appends to `CHANGELOG.md`. tasks.md is removed only if the sprint block was its only content; if a `## Review Backlog` section exists, the sprint block is stripped and tasks.md is retained. **Expected:** reconcile-harness.py may print a WARNING about unmatched active markers — normal for h1 block sprints that never flip backlog items to `[>]`; safe to ignore.

*Task came from tasks.md finding group (h3/h2):*
- In `tasks.md`: flip each finding `[ ]` → `[x]`

*Task came from backlog.md group:*
1. In `tasks.md`: change `status: active` → `status: done`
2. Run `reconcile-harness.py` from the project root (same command as above).
   This removes the `[>]` markers from `backlog.md` via `## Covers` and appends to `CHANGELOG.md`.
   Empty headings left after removal are NOT cleaned up here (cleanup only runs when tasks.md is absent);
   they persist until a later reconcile sweep. Do NOT flip `[>]` → `[x]` manually — `remove_active_markers()`
   matches `[>]` specifically; a manual flip to `[x]` breaks that lookup.

Post-merge, `reconcile-harness.py` is a no-op for this sprint (already reconciled) but can
still be run as part of a sweep without side effects.

## Step 4 — Hand off

Invoke `Skill(dev-tools:dev-review-cycle)` with `args: --auto`.

`dev-review-cycle --auto` commits (including the cleanup changes above), creates PR, collects
reviews, applies in-scope findings, records out-of-scope items to `tasks.md`, waits CI, and merges.

**If dev-review-cycle reports CI failure and the PR must be abandoned:** close the PR and delete
the feature branch without merging — `main` retains the pre-cleanup state and no rollback is needed.
If you continue on the same branch after fixing CI, the cleanup commit is already correct and
no further action is required.

## Batch mode (`--all`)

Triggered by `--all`. Implements **multiple** units in parallel (each in its own git worktree),
then collapses them onto **one integration branch** that goes through a **single** version bump,
`reconcile-harness.py`, and `dev-review-cycle --auto` → one PR, one CI run, one merge.

**Why one integration branch, not N PRs.** The shared single-copy files this repo's tooling
mutates — `plugin.json` manifests, `backlog.md`, `tasks.md`, `CHANGELOG.md` — cannot be edited
per-unit in parallel without collision, and the convergence tools can only run on the *main
checkout*: `reconcile-harness.py` writes relative `tasks.md`/`backlog.md` (whatever the CWD is,
and Bash CWD resets to the repo root between calls), and `dev-review-cycle` detects its branch
from the session's current checkout — neither can be aimed at a worktree. So the worktrees do
**code only**; every shared-file edit happens once, serially, on the integration branch in the
main checkout. This sidesteps the whole class of cross-worktree merge/CWD failures.

### A1 — Gather

Run the **full scan** from Step 1 (skip the fast path — batch mode always needs the complete list). The output is a list of **units**: each unit is
one heading group. Heading-based grouping naturally scopes each unit to one logical area, which
minimizes (but does not guarantee) conflicts when units merge into the integration branch in A6
— shared imports/utilities may still collide, which A6 handles.

### A2 — Filter to batch-eligible

A unit is **batch-eligible** only if ALL hold:
- Trivial: tag is NOT `[FEAT]`/`[REFACTOR]`, total in-scope files ≤2 (across the heading group), no new public API/schema. Non-trivial units need interactive plan-mode approval
  (single-pick Step 3) that cannot run N-way in parallel.
- In-scope files do **not** include any convergence-owned shared file (`plugin.json` manifests,
  `backlog.md`, `tasks.md`, `CHANGELOG.md`). Those are edited only in A6; a unit whose actual
  task is to edit them would collide with convergence — run it solo.

List excluded units explicitly: "Excluded from batch (needs solo run): `<unit>` — `<reason>`".
If filtering leaves 0 eligible units, report that and stop.

### A3 — Multi-select

Do NOT use `AskUserQuestion` (4-option cap is too small for a batch). Render a numbered list,
one line per eligible unit: index, type tag, short slug, file:line (bundles list member count
and area). Accept a comma list (`1,3,4`), inclusive ranges (`1-3`), `all`, or a combination.
Map back to units; ignore out-of-range indices and report them. Empty/unparseable reply →
re-prompt once, then stop.

**Cost gate** — each selected unit costs roughly implementer + qa-verifier (the review cycle
runs only **once** for the whole batch, not per unit). If the user selects **more than 6 units**,
state the rough multiplier and ask for explicit confirmation before A4. CLAUDE.md token economy
applies — the parallelism must earn its cost.

### A4 — Parallel implement (worktrees, code only)

The **main session owns worktree lifecycle** — do NOT use the Agent `isolation: "worktree"`
flag (that worktree is scoped to one agent's lifetime; it may not survive the later A5/A6
steps). Derive the repo name once: `REPO=$(basename "$(git rev-parse --show-toplevel)")`. Keep
worktrees **inside** the repo (an external `../` path can fall outside an agent's sandbox);
ensure `.worktrees/` is git-ignored — if it is not yet, add it to `.gitignore` (this edit lands
on the integration branch in A6). `git fetch` first, then base every worktree on the **same**
`origin/main` the A6 integration branch will use — otherwise a stale local base inflates merge
conflicts in A6 and drops units that would have merged cleanly. For each selected unit, before
fan-out:

```bash
git worktree add ".worktrees/<slug>" -b "wt/<slug>" origin/main   # one per unit
```

Then fan out one implementer agent per unit in a single message (concurrency self-caps). Each
agent's brief (four-field per `docs/delegation.md`) gives the **worktree path** and says to,
in that path:
1. Implement the unit's **code only**. Do NOT touch `backlog.md`, `tasks.md`, `plugin.json`,
   or `CHANGELOG.md` — all marking-active, version bump, and reconcile happen once in A6.
2. **Return** the Sprint Contract text (Scope / Acceptance criteria / Out of scope / Lint-test
   command per `docs/eval-criteria.md`; one acceptance checkbox per bundled item) as part of the
   agent's output — it is NOT written to `tasks.md` here. A5 reads it from this return value.
3. **Commit the code to `wt/<slug>`** (e.g. `[WIP] <unit>`), leaving a clean tree. Return the
   worktree path, branch, the Sprint Contract, and a change summary.

The agent must NOT verify its own output. If an agent fails or returns unusable output, drop
that unit: `git worktree remove --force .worktrees/<slug>` and `git branch -D wt/<slug>`, then
record it for the final report — do not abort the others.

### A5 — Parallel QA

For each successfully-implemented unit, spawn a `qa-verifier` agent (separate from the
implementer) pointed at that unit's worktree path, verifying against the Sprint Contract that
unit returned in A4. Fan out all QA agents in one message.

For any unit with blocking findings, fan out **one** implementer→qa-verifier retry per blocking
unit (all retries in one message — they are independent; do not serialize). Still blocking after
one retry → drop the unit (remove its worktree + branch as in A4) and record it. One unit's
failure never blocks the others.

### A6 — Collapse to one integration branch, then converge once

All of this runs in the **main checkout** (correct CWD/branch for the convergence tools), not in
any worktree.

1. **Create the integration branch off latest base** — `git fetch`, then
   `git checkout -b <type>/batch-<slug> origin/main` (pick the dominant `[type]` across units, else
   `fix/`). `<slug>` is a short batch descriptor.
2. **Merge each verified unit branch in** — for each unit, `git merge --no-ff wt/<slug>`.
   Disjoint areas (A1) keep this clean. On conflict: `git merge --abort`, drop that unit (record
   it), and continue with the rest — the integration branch keeps the units that merged cleanly.
   If every unit conflicts/drops, abandon: `git checkout main && git branch -D <type>/batch-<slug>`,
   then jump to A7 cleanup and report (do not leave the checkout stranded on a dead branch).
3. **Mark active — once, only if the batch has ≥1 backlog unit.** Flip each merged backlog item
   `[ ]` → `[>]` and write **one** combined `tasks.md` Sprint Contract: `status: active`, a
   `# heading` describing the batch, and a `## Covers` section listing **every** merged backlog
   item's exact line (per Step 3 "Mark active — backlog group" rules). If the batch is findings-only (no
   backlog units), skip the contract entirely — there is nothing for reconcile to anchor, and
   writing one only to delete it would needlessly trigger the `tasks.md` unlink (see step 5).
4. **Version bump — once.** Per `docs/conventions.md`, bump each touched plugin's manifests a
   single time for the whole batch (both `.claude-plugin` and `.codex-plugin`).
5. **Pre-merge cleanup — once.** Order matters because `reconcile-harness.py` may unlink
   `tasks.md` on completion (only when no content remains after stripping the sprint block):
   - **First** flip every merged `tasks.md`-finding `[ ]` → `[x]`.
   - **Then**, only if a contract was written in step 3, set it `status: done` and run
     `reconcile-harness.py` (removes all `[>]` via `## Covers`, one `CHANGELOG.md` append,
     archives the sprint — unlinks `tasks.md` only if no other content remains). For a
     findings-only batch, run no reconcile; the `[x]` flips stay in `tasks.md`.

   Leave all edits uncommitted — `dev-review-cycle` Step 1 commits them. `strip_sprint_block()`
   preserves unrelated `## Review Backlog` content when stripping the sprint block; `tasks.md`
   is only fully removed when the sprint block was the only content.
6. **Hand off — once.** `Skill(dev-tools:dev-review-cycle)` with `args: --auto`. Running from the
   main checkout on `<type>/batch-<slug>`, it correctly detects the branch, commits the integration
   work, opens **one** PR, collects reviews, applies in-scope findings, records out-of-scope items
   to `tasks.md`, waits CI, and merges.

**If the integration PR fails CI and must be abandoned:** close the PR; the unit branches still
exist, so you can re-run convergence after fixing, or fall back to single-pick per unit.

### A7 — Cleanup & report

The main session removes every worktree it created (`git worktree remove .worktrees/<slug>`;
`--force` for any with leftover changes) and deletes **all** unit branches it created
(`git branch -D wt/<slug>` for each — merged, dropped, or conflicted; none are needed once the
integration branch holds the work). If the batch was abandoned (all units conflicted), the
integration branch was already deleted in A6 step 2. Then emit a summary table: each unit →
merged-into-PR / dropped (reason), plus the single PR link and final merge status. This is the
only place per-unit outcomes are surfaced, so do not skip it.

## Edge cases

**Work already in flight** — feature branch with uncommitted changes from a previous session.
Offer: "I see uncommitted changes on `<branch>`. Skip to `dev-review-cycle --auto`?"
- **Yes:** invoke `dev-review-cycle --auto` directly (skip Steps 1–3).
- **No:** ask whether to (a) stash and start a fresh task, (b) commit the in-flight work
  first, or (c) cancel. Do not proceed until the tree is clean or the user redirects.

**Deferred backlog item (≥2 candidates)** — item has `*(deferred: ...)*`. Surface the blocker
and confirm it is resolved before proceeding. If unresolved, skip to the next candidate.
If all candidates are deferred with unresolved blockers, report that and stop.
(For the single-candidate case, see Step 2 table.)

**Deferred item in a group** — if any item in a heading group is deferred and the blocker
is unresolved, note it as a warning but continue with the non-deferred items in that group.
If all items in the group are deferred, skip the group (see Step 2 deferred-items rule).

**tasks.md finding spans multiple PRs** — scope narrowly to the specific `file:line` ref.
Record broader related items back to `tasks.md` via the out-of-scope path in dev-review-cycle.
