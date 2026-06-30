---
name: next-tasks
version: 1.3.0
description: >-
  Use when user says "start a task", "next task", "work the backlog", "start work", "태스크
  시작", "태스크 골라줘", "다음 작업 시작", "백로그 작업", "작업 시작", or similar. Runs full
  code cycle: pick → branch → Sprint Contract → implement → qa-verifier → version bump →
  dev-review-cycle --auto. Flags: --all (parallel batch), --tree (worktree isolation).
  Trivial tasks auto-offer lite path (direct merge, no PR/CI). Not for review-only or
  backlog browsing without intent to implement.
---

# Next Tasks

Act as the thin orchestration layer over the `code` cycle in `docs/workflows.md`. Pick work,
run the cycle, and hand off to `dev-review-cycle --auto`. Delegate the heavy lifting — this
skill is the **decision and sequencing layer**, not the implementation engine.

**Mode routing:** default = single-pick (Steps 1–4 below). If the invocation carries `--all`
(or "전부 처리", "모두 돌려", "다 처리", "batch all"), run **Batch mode** instead — see the
`## Batch mode (--all)` section. If the invocation carries `--tree`, run single-pick but route
the code cycle through a git worktree — see `## --tree mode`. Prerequisites and the
working-tree gate apply to all modes.

## Prerequisites

The repo must have `backlog.md`, `docs/workflows.md`, `docs/eval-criteria.md`, and
`docs/conventions.md` (harness-init artifacts). If any is missing, stop and point the user
to `dev-tools:harness-init`.

**Working tree gate:** Run `git status --porcelain`. If the output is non-empty, stop and
list the dirty files — do NOT proceed. Ask the user to commit, stash, or discard first.

`tasks.md` is optional: present in an active sprint or as a review-backlog accumulator; absent
in the idle state. If absent, only `backlog.md` candidates are offered.

## Step 1 — Gather candidate groups

**Fast path (single-pick only):** Read a minimal slice of each file to surface the top candidates — do NOT scan the full backlog unless the user explicitly asks for more.

**Phase A — h1 sprint blocks (tasks.md):**

```bash
grep -En "^# |^status:" tasks.md 2>/dev/null
```

For each `# ` heading, check if the immediately following `status:` line reads `open`. Collect all matching h1 titles in document order.

**Phase B — top Review Backlog h3 groups (tasks.md):** *(skip if Phase A already has 5 candidates)*

```bash
grep -n "^## Review Backlog\|^### \|^- \[ \]" tasks.md 2>/dev/null | head -80
```

Locate the `## Review Backlog` line in the output; collect up to **3** h3 sub-headings (in document order) that directly own ≥1 open `- [ ]`.

**Phase C — top backlog.md groups:** *(skip if Phases A+B already have 5 candidates)*

```bash
grep -n "^## \|^### \|^- \[ \]" backlog.md 2>/dev/null | head -40
```

Collect up to **2** h2 or h3 groups (in document order) that directly own ≥1 open `- [ ]`, skipping groups where every item is `[x]` or `[>]`.

**Fast-path selection (A+B+C combined, cap = 5):**

| Count | Action |
|-------|--------|
| 0 | No fast-path hits — fall through to full scan below |
| 1 | Announce the group and proceed directly to Step 3 |
| 2–5 | On Claude Code use `AskUserQuestion` (single-select); on Codex print a plain numbered list. Always append **"더 많은 항목 보기"** as the last option. User picks a number → proceed to Step 3. User picks "더 많은 항목 보기" → run full scan below, then go to Step 2. |

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
| 1 | Announce the group and proceed to Step 3. *(Full-scan path only; the fast path handles the 1-sprint case directly.)* |
| ≥2 | Print a numbered list of all groups (user explicitly requested full list): `[N] <source>: <heading title> (<M> items)`. Wait for the user to reply with a number. |

**Large-group guard:** if the selected group has >8 open items, confirm with the user before proceeding — list the items numbered and ask whether to process all or a subset.

**Deferred items:** a group where every open item has `*(deferred: ...)*` is not a candidate. Skip it and surface the blocker. If all groups are deferred with unresolved blockers, report and stop.

Do NOT use `AskUserQuestion` in this step — a plain numbered list handles any list size without the 4-option cap.

## Step 2.5 — Size gate (batch nudge + lite path offer)

Run after selecting a group, before Step 3. Evaluate whether the selected group is **trivial**:
ALL must hold: tag is NOT `[FEAT]`, total in-scope files ≤2, no new public API/schema.

If **not trivial** OR **`--tree` is active** → skip this section entirely, proceed to Step 3 normally.

If **trivial** (and `--tree` is NOT active):

**Batch nudge** — scan for other trivial open groups (re-use the candidate list from Step 1;
re-grep only if the list is no longer in context). If ≥1 other trivial groups exist, surface them:

```
선택한 태스크가 작습니다. 아래 항목들과 묶으면 PR·CI 오버헤드를 공유할 수 있습니다:
  [1] <group title> (<M> items)
  [2] <group title> (<M> items)
  ...
같이 처리할 항목을 번호로 선택하세요 (복수 가능). 건너뛰려면 N.
```

If the user selects ≥1 additional groups → treat the combined selection as a **Batch mode
(`--all`)** run: skip A1–A3 (selection already done), proceed directly to **A4** with this
confirmed unit list. End Step 2.5 here.

**Lite path offer** — if the user declines the nudge (or no other trivial groups exist), offer:

```
[1] 라이트 패스 — 구현+QA 후 main에 직접 머지 (PR·CI 없음)
[2] 풀 사이클 — dev-review-cycle (PR, CI, 코드리뷰 포함)
```

- User picks **1** → proceed to Step 3 with the **lite path** active (see `## Lite path` section).
- User picks **2** → proceed to Step 3 normally.

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

*backlog.md group (h2 or h3):* Write a `tasks.md` Sprint Contract with:
  - `# heading` = the selected heading title (verbatim from backlog.md)
  - `status: active`
  - `## Covers` listing each in-scope item copied **verbatim** from backlog.md — full line including the `- [ ]` prefix (e.g., `- [ ] fix thing`). This is the deletion list; exact match required so cleanup can locate and remove the right lines.
  Do NOT flip items to `[>]` — leave them as `[ ]` in backlog.md until deletion at pre-merge cleanup.

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
1. Delete the entire h1 block from `tasks.md` (the `# heading`, `status:` line, and all body content). If `tasks.md` has no remaining content after deletion, delete the file.
2. Append to `CHANGELOG.md`: `- [done] <sprint title> (<date>)` under `## Unreleased`.

*Task came from tasks.md finding group (h3/h2):*
- In `tasks.md`: **delete** each completed finding line (the `- [ ]` items that were fixed). If the h3 heading has no remaining open `- [ ]` items after deletion, delete the heading line too. If `## Review Backlog` becomes empty, delete that section header as well. If `tasks.md` is now entirely empty, delete the file.

*Task came from backlog.md group:*
1. In `tasks.md`: delete the Sprint Contract block (the entire h1 block with `status: active`). If `tasks.md` has no remaining content, delete the file.
2. In `backlog.md`: **delete** each item line listed in `## Covers` of the Sprint Contract. Also delete any h2/h3 heading that has no remaining open `- [ ]` items after the deletion.
3. Append to `CHANGELOG.md`: `- [done] <sprint title> (<date>)` under `## Unreleased` (create the section if absent).

Post-merge, verify `backlog.md` and `tasks.md` are clean — no `[x]`, `[>]`, or stale sprint markers.

## Step 4 — Hand off

Invoke `Skill(dev-tools:dev-review-cycle)` with `args: --auto`.

`dev-review-cycle --auto` commits (including the cleanup changes above), creates PR, collects
reviews, applies in-scope findings, records out-of-scope items to `tasks.md`, waits CI, and merges.

**If dev-review-cycle reports CI failure and the PR must be abandoned:** close the PR and delete
the feature branch without merging — `main` retains the pre-cleanup state and no rollback is needed.
If you continue on the same branch after fixing CI, the cleanup commit is already correct and
no further action is required.

## Lite path

Active when the user chose "라이트 패스" in Step 2.5. Runs the code cycle without PR or CI —
implement, QA, then merge directly to `main` in the same session.

Run Step 3 sub-steps normally (branch, Sprint Contract, Implement, QA, version bump, pre-merge
cleanup) with these overrides:

**Branch:** `git checkout -b <type>/<slug>` as normal — never commit directly to `main`.

**Skip dev-review-cycle entirely.** After QA passes and version bump + pre-merge cleanup are done:

```bash
# commit all staged changes (code + cleanup + version bump together)
git add <changed files>
git commit -m "[TYPE] <description>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# merge and push
git checkout main
git pull origin main
git merge --no-ff <type>/<slug> -m "Merge branch '<type>/<slug>'"
git push origin main
git branch -d <type>/<slug>
```

**Branch-protection caveat:** if `git push origin main` is rejected (branch protection rule requires PRs), reset local main (`git reset --hard origin/main`), check out the feature branch (`git checkout <type>/<slug>`), and fall back to `Skill(dev-tools:dev-review-cycle)` with `args: --auto`.

Report on completion: "라이트 패스 완료 — main에 직접 병합 및 푸시됨. PR·CI 없음."

## `--tree` mode (single task, worktree isolation)

Triggered by `--tree`. Runs Steps 1–2 identically to default single-pick. The code cycle (Step
3) is modified so implementation and QA run in an isolated git worktree, keeping the main
checkout on `main` throughout — useful when the user wants to preserve a clean working tree
while a task is in flight.

**Modified Branch step (replaces `git checkout -b` under `--tree`):**

```bash
SLUG=<slug>            # short slug derived from item title
BRANCH=<type>/<slug>   # derived as normal from item [type] tag + slug
git fetch
# ensure .worktrees/ is git-ignored — add to .gitignore if missing (edit main checkout, uncommitted)
# if $BRANCH already exists locally (prior failed run), delete it first: git branch -D "$BRANCH" (confirm with user)
git worktree add ".worktrees/$SLUG" -b "$BRANCH" origin/main
```

**Implement (workflows.md Step 3):** spawn `implementer` agent. Brief must include the **absolute
worktree path** AND these explicit CWD instructions (the Bash tool is stateless — CWD resets
to the main checkout on every call; a standalone `cd` has no persistent effect):

> "Your spawn CWD is the main checkout. The Bash tool is stateless — CWD resets each call.
> Every Bash command must begin with `cd <absolute-worktree-path> &&`
> (e.g. `cd /path/to/worktree && git status`, `cd /path/to/worktree && npm test`).
> Read/Edit/Write tool calls must use absolute paths under `<absolute-worktree-path>/`.
> Do NOT read or edit any file in the main checkout."

The agent works entirely inside the worktree — it must NOT touch `plugin.json` manifests,
`backlog.md`, `tasks.md`, or `CHANGELOG.md` anywhere (those are main-checkout edits done after QA).

**QA (workflows.md Step 4):** spawn `qa-verifier` pointed at the worktree path, verifying
against the Sprint Contract. Include the same CWD instructions in the brief: every Bash command
must begin with `cd <absolute-worktree-path> &&`; Read/Edit/Write use absolute paths under the
worktree. Same retry policy as Step 3 (one fix-and-re-verify cycle).

**If QA fails after one retry:** clean up and stop.
```bash
git worktree remove --force ".worktrees/$SLUG"
git branch -D "$BRANCH"
```
Report the failure; main checkout remains on `main`.

**Version bump (workflows.md Step 5):** performed in the **main checkout** only — do NOT edit manifests inside the worktree. Read which files changed inside the worktree to determine which plugin directory to bump, then edit the manifests in the main checkout. Leave uncommitted (carries through to `$BRANCH` on `git checkout` since there is no conflict — implementer cannot touch manifests per the constraint above).

**Collapse after QA passes:**

Ensure the worktree is clean (implementer committed all changes to `$BRANCH`). If `git status` inside the worktree shows dirty files, commit them before proceeding — `git worktree remove` refuses on a dirty worktree.

```bash
git worktree remove ".worktrees/$SLUG"   # worktree gone; branch $BRANCH still exists
git checkout "$BRANCH"                   # switch main checkout onto the feature branch
```

Now run **pre-merge cleanup** (backlog / tasks.md / CHANGELOG edits) in the main checkout on
`$BRANCH`, then hand off: `Skill(dev-tools:dev-review-cycle)` with `args: --auto` (Step 4).

## Batch mode (`--all`)

Triggered by `--all`. Implements **multiple** units in parallel (each in its own git worktree),
then collapses them onto **one integration branch** that goes through a **single** version bump,
cleanup pass, and `dev-review-cycle --auto` → one PR, one CI run, one merge.

**Why one integration branch, not N PRs.** The shared single-copy files — `plugin.json` manifests,
`backlog.md`, `tasks.md`, `CHANGELOG.md` — cannot be edited per-unit in parallel without collision.
`dev-review-cycle` also detects its branch from the session's current checkout and cannot be aimed
at a worktree. So worktrees do **code only**; every shared-file edit happens once, serially, on
the integration branch in the main checkout. This sidesteps the whole class of cross-worktree
merge/CWD failures.

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
agent's brief (four-field per `docs/delegation.md`) gives the **absolute worktree path** and
these explicit CWD instructions (agents spawn in the main checkout CWD, not the worktree):

> "Your spawn CWD is the main checkout. The Bash tool is stateless — CWD resets each call.
> Every Bash command must begin with `cd <absolute-worktree-path> &&`
> (e.g. `cd /path/to/worktree && git commit -m '...'`).
> Read/Edit/Write tool calls must use absolute paths under `<absolute-worktree-path>/`.
> Do NOT read or edit any file in the main checkout."

Then the brief continues:
1. Implement the unit's **code only**. Do NOT touch `backlog.md`, `tasks.md`, `plugin.json`,
   or `CHANGELOG.md` — all cleanup edits happen once in A6.
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
unit returned in A4. Include the same CWD instructions in each brief: every Bash command must
begin with `cd <absolute-worktree-path> &&`; Read/Edit/Write use absolute paths under the
worktree. Fan out all QA agents in one message.

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
3. **Collect cleanup targets — once.** For each merged unit, record what to delete:
   - **backlog units** → all open `- [ ]` lines directly under the unit's heading group in `backlog.md` (read the heading section; every `- [ ]` item under it is a deletion target)
   - **finding groups** → the completed `- [ ]` lines in the relevant h3/h2 block in `tasks.md`
4. **Version bump — once.** Per `docs/conventions.md`, bump each touched plugin's manifests a
   single time for the whole batch (both `.claude-plugin` and `.codex-plugin`).
5. **Pre-merge cleanup — once.**
   - **tasks.md findings**: delete each completed `- [ ]` line. Remove the h3/h2 heading if no open items remain. Remove `## Review Backlog` if it becomes empty. If `tasks.md` is now entirely empty, delete the file.
   - **backlog.md**: delete each completed item line. Remove h2/h3 headings that have no remaining open `- [ ]` items.
   - **CHANGELOG.md**: append one entry under `## Unreleased`: `- [done] <batch-slug> (<N> units) (<date>)`.

   Leave all edits uncommitted — `dev-review-cycle` Step 1 commits them.
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
