---
name: task-next
version: 1.4.1
description: >-
  Use when the prompt asks to pull the next item FROM the queue without describing specific new
  work — "start a task", "next task", "work the backlog", "start work", "태스크 시작", "태스크
  골라줘", "다음 작업 시작", "백로그 작업", "작업 시작", or similar. Runs full code cycle: pick →
  branch → Sprint Contract → implement → qa-verifier → version bump → task-review --auto.
  Flags: --all (parallel batch), --tree (worktree isolation). Trivial tasks auto-offer lite path
  (direct merge, no PR/CI). Operates only on work ALREADY in backlog.md/tasks.md; if the queue is
  empty, reports nothing-open and points to `task-new` for describing fresh work. Discriminator vs task-new: task-next
  when the prompt references the queue abstractly; `task-new` when the prompt itself spells out a
  specific new feature/bug/change. Not for review-only or backlog browsing without intent to
  implement.
---

# Next Tasks

Act as the thin orchestration layer over the `code` cycle in `docs/workflows.md`. Pick work,
run the cycle, and hand off to `task-review --auto`. Delegate the heavy lifting — this
skill is the **decision and sequencing layer**, not the implementation engine.

**Mode routing:** default = single-pick (Steps 1–4 below). If the invocation carries `--all`
(or "전부 처리", "모두 돌려", "다 처리", "batch all"), run **Batch mode** instead — see the
`## Batch mode (--all)` section. If the invocation carries `--tree`, run single-pick but route
the code cycle through a git worktree — see `## --tree mode`. A NEW free-text request not yet in
`backlog.md`/`tasks.md` is out of scope here — that is `task-new`'s job; this skill only picks
work already on the queue. Prerequisites and the working-tree gate apply to all modes.

## Prerequisites

The repo must have `backlog.md`, `docs/workflows.md`, `docs/eval-criteria.md`, and
`docs/conventions.md` (harness-init artifacts). If any is missing, stop and point the user
to `dev:harness-init`.

**Working tree gate:** Run `git status --porcelain`. If the output is non-empty, stop and
list the dirty files — do NOT proceed. Ask the user to commit, stash, or discard first. If the
dirty tree turns out to be an in-flight feature branch (not stray dirty files), route to the
"Work already in flight" edge case below instead of hard-stopping.

`tasks.md` is optional: present in an active sprint or as a review-backlog accumulator; absent
in the idle state. If absent, only `backlog.md` candidates are offered.

## Step 1 — Gather candidate groups

**Fast path (single-pick only):** Read a minimal slice of each file to surface the top candidates — do NOT scan the full backlog unless the user explicitly asks for more.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
python3 "$SKILL_DIR/scripts/backlog_candidates.py" --tasks tasks.md --backlog backlog.md
```

Prints one line per candidate — `[N] <source>: <heading> (<M> items)` (h1 sprint blocks omit
the item count) — already applying the Phase A → B → C order, per-phase caps, and the combined
cap-5 truncation described below. **If the script is unavailable or errors, fall back to
hand-grepping per the Phase A/B/C rules below** (kept in this doc for that purpose).

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

Collect up to **2** h2 or h3 groups (in document order) that directly own ≥1 open `- [ ]`, skipping groups where every item is `[x]`, `[>]`, or carries a `*(deferred: ...)*`/`*(blocked by: ...)*` marker.

**Fast-path selection (A+B+C combined, cap = 5):**

| Count | Action |
|-------|--------|
| 0 | No fast-path hits — fall through to full scan below |
| 1 | Announce the group and proceed directly to Step 3 |
| 2–5 | On Claude Code use `AskUserQuestion` (single-select); on Codex print a plain numbered list. Always append **"더 많은 항목 보기"** as the last option. User picks a number → proceed to Step 3. User picks "더 많은 항목 보기" → run full scan below, then go to Step 2. |

**Full scan (fast path found nothing, or `--all` batch mode):** Run the script in full-scan mode to build the complete candidate list:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
python3 "$SKILL_DIR/scripts/backlog_candidates.py" --tasks tasks.md --backlog backlog.md --full-scan
```

This applies rules 1–5 below in order, uncapped — note rules 4+5 use type priority (all
qualifying h3 headings first, then all qualifying h2 headings), which is a different ordering
from Phase C's type-agnostic document-order scan above. **If the script is unavailable or
errors, fall back to hand-grepping** (kept in this doc for that purpose):

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

Skip headings where every item is `[x]`, `[>]`, or carries a `*(deferred: ...)*`/`*(blocked by: ...)*` marker. Note: all h2/h3 headings with open checkboxes are candidates — including `## Ideas` or `## Someday` sections left unscheduled. Authors must use `[>]` or `[x]` to park items intentionally; the old `## Now`/`## Next` allowlist is removed.

## Step 2 — Select

| Groups found | Action |
|-------------|--------|
| 0 | Report "backlog and tasks are clear — nothing open." If the user has specific new work in mind, point them to `task-new` (describe the work and it runs the code cycle). Stop. |
| 1 | Announce the group and proceed to Step 3. *(Full-scan path only; the fast path handles the 1-sprint case directly.)* |
| ≥2 | Print a numbered list of all groups (user explicitly requested full list): `[N] <source>: <heading title> (<M> items)`. Wait for the user to reply with a number. |

**Large-group guard:** if the selected group has >8 open items, confirm with the user before proceeding — list the items numbered and ask whether to process all or a subset.

**Deferred/blocked items:** a group where every open item has `*(deferred: ...)*` or `*(blocked by: ...)*` is not a candidate. Skip it and surface the blocker. If all groups are deferred/blocked with unresolved blockers, report and stop.

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
[2] 풀 사이클 — task-review (PR, CI, 코드리뷰 포함)
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
- **Stuck-fix stop condition:** if the same fix is attempted 3+ times on the same file without
  the lint/test command passing (inline edits or implementer briefs alike), stop and report to
  the user instead of continuing to retry. This is a prompted constraint, not a mechanically
  enforced cap — no loop-counter tooling exists for implementer sub-agents.
- **Destructive-command guard:** never run `git push --force`/`--force-with-lease`,
  `git reset --hard`, `git clean -f`/`-fd`, or `git branch -D` while implementing (inline edits
  or implementer briefs alike). If a fix seems to require one, stop and ask the user instead.
  This does NOT restrict the orchestrator's own documented worktree-cleanup steps in
  `--tree`/`--all` mode (see `references/tree.md`, `references/batch.md`), which already
  deliberately use `-D`/`--force` on failure paths — those are separate, orchestrator-only
  operations, not implementer actions.
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

**Do NOT commit.** Leave all changes uncommitted. `task-review` Step 1 commits everything
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

Invoke `Skill(dev:task-review)` with `args: --auto`.

`task-review --auto` commits (including the cleanup changes above), creates PR, collects
reviews, applies in-scope findings, records out-of-scope items to `tasks.md`, waits CI, and merges.

**If task-review reports CI failure and the PR must be abandoned:** close the PR and delete
the feature branch without merging — `main` retains the pre-cleanup state and no rollback is needed.
If you continue on the same branch after fixing CI, the cleanup commit is already correct and
no further action is required.

## Lite path

Active when the user chose "라이트 패스" in Step 2.5. Runs the code cycle without PR or CI —
implement, QA, then merge directly to `main` in the same session.

Run Step 3 sub-steps normally (branch, Sprint Contract, Implement, QA, version bump, pre-merge
cleanup) with these overrides:

**Branch:** `git checkout -b <type>/<slug>` as normal — never commit directly to `main`.

**Skip task-review entirely.** After QA passes and version bump + pre-merge cleanup are done:

```bash
# commit all staged changes (code + cleanup + version bump together)
git add <changed files>
git commit -m "[TYPE] <description>

Co-Authored-By: Claude <noreply@anthropic.com>"

# merge and push
git checkout main
git pull origin main
git merge --no-ff <type>/<slug> -m "Merge branch '<type>/<slug>'"
git push origin main
git branch -d <type>/<slug>
```

**Branch-protection caveat:** if `git push origin main` is rejected (branch protection rule requires PRs), reset local main (`git reset --hard origin/main`), check out the feature branch (`git checkout <type>/<slug>`), and fall back to `Skill(dev:task-review)` with `args: --auto`.

Report on completion: "라이트 패스 완료 — main에 직접 병합 및 푸시됨. PR·CI 없음."

## `--tree` mode (single task, worktree isolation)

Runs single-pick through an isolated git worktree so the main checkout stays on `main` throughout implementation and QA. See `references/tree.md` for full detail.

## Batch mode (`--all`)

Implements multiple units in parallel worktrees, then collapses them onto one integration branch for a single version bump, cleanup pass, and `task-review --auto` run. See `references/batch.md` for full detail.

## Edge cases

**Work already in flight** — feature branch with uncommitted changes from a previous session.
This is the routing target when the Prerequisites "Working tree gate" finds an in-flight branch
rather than stray dirty files. Run 3 ordered, cheap checks to produce a specific diagnosis
before asking for confirmation — this only automates the *diagnosis* text, not the resume
action itself; always still ask yes/no.

1. **Commits already ahead of `main`?**
   ```bash
   commits=$(git log main..HEAD --oneline 2>/dev/null)
   [[ -n "$commits" ]] && echo "commits exist — task-review Step 1 already ran"
   ```
   If `$commits` is non-empty, `task-review` Step 1 (commit) already ran. Diagnosis:
   offer `task-review --auto` directly.

2. **No commits ahead, but an active Sprint Contract?**
   ```bash
   active_block=$(grep -c "^status: active" tasks.md 2>/dev/null)
   ```
   If `$active_block` is non-zero, check what's already changed to distinguish stage. Include
   untracked files (`git diff --stat` alone misses new files an implementer created but never
   staged — e.g. a brand-new script):
   ```bash
   code_diff=$(git diff --stat -- . ':!tasks.md' ':!backlog.md' ':!CHANGELOG.md' ':!**/plugin.json' 2>/dev/null)
   untracked=$(git ls-files --others --exclude-standard -- . ':!tasks.md' ':!backlog.md' ':!CHANGELOG.md' ':!**/plugin.json' 2>/dev/null)
   bump_diff=$(git diff --stat -- '**/plugin.json' 2>/dev/null)
   ```
   - `$code_diff` and `$untracked` both empty, `$bump_diff` empty → Sprint Contract written, no
     implementation yet. Diagnosis: resume at **Step 3 – Implement**.
   - `$code_diff` or `$untracked` non-empty, `$bump_diff` empty → implementation in progress, no
     version bump yet. Diagnosis: resume at **Step 3 – QA**.
   - `$bump_diff` non-empty → implementation and version bump both done. Diagnosis: resume at
     **Step 4 – Handoff**.

3. **Neither of the above matched** → state is genuinely unclear from these cheap checks; fall
   back to the generic offer: "I see uncommitted changes on `<branch>`. Skip to
   `task-review --auto`?"

Present the diagnosis (or check 3's fallback to the generic offer) and ask for confirmation:
- **Yes:** resume at the diagnosed step (or invoke `task-review --auto` directly for
  check 1 / the generic fallback).
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
Record broader related items back to `tasks.md` via the out-of-scope path in task-review.
