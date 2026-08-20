---
name: task-next
version: 1.6.10
description: >-
  Pull the next queued item from backlog.md/tasks.md and run the full code cycle: branch,
  Sprint Contract, implement, verify, version bump, review. Flags: --all (parallel batch),
  --tree (worktree isolation). New work you just described → task-new.
disable-model-invocation: true
---

# Next Tasks

Act as the thin orchestration layer over the `code` cycle in `docs/workflows.md`. Pick work,
run the cycle, and hand off to the review cycle (Step 4 makes that call). Delegate the heavy lifting — this
skill is the **decision and sequencing layer**, not the implementation engine.

**Mode routing:** default = single-pick (Steps 1–4 below). If the invocation carries `--all`
(or "전부 처리", "모두 돌려", "다 처리", "batch all"), run **Batch mode** instead — see the
`## Batch mode (--all)` section. If the invocation carries `--tree`, run single-pick but route
the code cycle through a git worktree — see `## --tree mode`. A NEW free-text request not yet in
`backlog.md`/`tasks.md` is out of scope here — that is `task-new`'s job; this skill only picks
work already on the queue. Prerequisites and the working-tree gate apply to all modes.

## Prerequisites

**Required:** `backlog.md`, `docs/workflows.md`, `docs/eval-criteria.md` — the queue and the two
docs this skill executes. If any is missing, stop and point the user to `dev:harness-init`.

**Conditional:** `docs/conventions.md` is generated at init only when rules exist that the linter
does not already own, so a repo whose linter owns every rule correctly has none. Read and follow it
when present; when absent, proceed and take the linter as the authority. Never stop on its absence.

**Working tree gate:** Capture the tree state before deciding whether dirty files are stray:

```bash
dirty=$(git status --porcelain)
if [[ -n "$dirty" ]]; then
  current_branch=$(git branch --show-current)
  task_contract_dirty=$(git status --porcelain -- tasks.md)
  task_worktree=$(git worktree list --porcelain | grep -E '^worktree .*/\.worktrees/' || true)
fi
```

If `dirty` is non-empty and `current_branch` is not `main`/`master`, route directly to the "Work
already in flight" edge case (`references/edge-cases.md`) and inspect the matching feature
branch, even when the default single-item path has no `tasks.md`. Include all captured dirty paths in the diagnosis: source edits
are expected while resuming a feature-branch sprint. On `main`/`master`, route only when
`task_contract_dirty` and `task_worktree` are both non-empty; this is the `--tree` exception, whose
main checkout stays on `main` while the file-backed Sprint Contract (and optionally release
bookkeeping or the ignore rule) is intentionally dirty. If `dirty` is non-empty and none of those
conditions match, list the dirty files — do NOT proceed — and ask the user to commit, stash, or
discard first.

`tasks.md` is optional in default mode: it holds the Sprint Contract and nothing else, so it is
present only when `## Covers` is needed — a pre-existing `status: open` h1 block, or a backlog.md
group with ≥2 in-scope items — and absent otherwise, including a single-item cycle, which keeps
the contract inline (see **Mark active** below) and never writes the file. `--tree` is the
exception: it always writes the file-backed Sprint Contract, including for one item, so the main
checkout's dirty tracking state exposes the in-flight run to a second invocation. Every persistent
item — queued work, review findings, security findings — lives in `backlog.md`, which is why
`backlog.md` is a prerequisite and `tasks.md` is not. If `backlog_candidates.py` warns that `tasks.md` still holds a
`## Review Backlog` / `## Security Fixes` section, move it to `backlog.md` verbatim before
proceeding: those items are not selectable, and `prune-tasks` refuses to run until they move.

## Step 1 — Gather candidate groups

**Fast path (single-pick only):** Read a minimal slice of each file to surface the top candidates — do NOT scan the full backlog unless the user explicitly asks for more.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
CANDIDATES="$SKILL_DIR/scripts/backlog_candidates.py"
[[ -r "$CANDIDATES" ]] || { echo "Bundled script missing or unreadable: $CANDIDATES" >&2; exit 1; }
python3 "$CANDIDATES" --tasks tasks.md --backlog backlog.md
rc=$?
[[ $rc -eq 0 ]] || { echo "backlog_candidates.py exited $rc — see its stderr above" >&2; exit 1; }
```

The guard tests the **script**, not `scripts/`: a present directory holding a missing, unreadable
or non-running script is the failure this catches. Exit status is checked separately because a
`python3` crash or an unreadable `backlog.md` also produces no candidates — **an empty candidate
list at exit 0 is meaningful and must not be swallowed** (see the zero-candidate diagnosis below).
A missing `backlog.md` is a non-zero exit by design: it is a Prerequisite above, so the run stops
and the user goes to `dev:harness-init`. Only `tasks.md` is optional.

Prints one line per candidate — `[N] <source>: <heading> (<M> items)`; h1 sprint blocks omit the
item count. The script owns the selection algorithm end to end: source order (tasks.md `status:
open` h1 sprint blocks → backlog.md h2/h3 groups, capped at 2 groups), combined fast-path cap 3,
skipping items marked `[x]`/`[>]`/`*(deferred: …)*`/`*(blocked by: …)*` and blocks marked
`status: active`/`done`, and discarding headings and items buried in `<!-- ... -->` comments or
fenced code blocks. Read the script if you need the exact rule.

**Read stderr on every run, not just empty ones.** Four orchestrator decisions depend on it:

- `Warning: unbalanced fence opened at line N in <file>` — a stray odd fence blanks everything
  after it, so part of the queue can be hidden while other groups still surface. Relay the
  warning and treat that file as untrustworthy: do NOT present the candidate list as complete.
- `Warning: <file> holds N persistent section(s) that belong in backlog.md` — a `tasks.md` still
  carrying `## Review Backlog` / `## Security Fixes`. Those items are real queued work that no
  rule can select, and `prune-tasks` will refuse at pre-merge cleanup. Move the section to
  `backlog.md` verbatim (the item syntax is identical) before continuing, and say so.
- On zero candidates the script writes a diagnosis naming *which kind* of empty this is. Relay it
  verbatim; **never report "queue clear" on an empty stdout alone.**
- `Note: fast path is showing N of M candidate group(s) — ...` — the fast path's cap hid real
  candidates. Relay the note, say how many more groups exist when offering **"더 많은 항목
  보기"**, and never present the truncated list as the whole queue.

**Fast-path selection (cap = 3):**

| Count | Action |
|-------|--------|
| 0 | Follow the stderr diagnosis above, then fall through to the full scan |
| 1 | Announce the group and proceed directly to Step 3 |
| 2–3 | On Claude Code use **one** `AskUserQuestion` carrying the batched gate below; on Codex print a plain numbered list. Always append **"더 많은 항목 보기"** as the last option of the pick question. User picks a group → proceed to Step 2.5, which consumes the answers already collected. User picks "더 많은 항목 보기" → run full scan below, then go to Step 2. Non-interactive run: do **not** pick from this capped, document-ordered list — run the full scan below, then take its candidate `[1]` and announce it. |

**Batched pre-implementation gate — ask once, not three times.** A trivial pick otherwise stops
the cycle three separate times (the pick here, then Step 2.5's batch nudge, then its lite-path
offer), each a full round trip of idle wall clock. Before asking, judge each candidate's
**apparent** triviality from its item text alone — tag is not `[FEAT]`, names ≤2 files, no new
public API/schema — then issue a single `AskUserQuestion` with up to three questions:

| # | Question | Emit when | Shape |
|---|----------|-----------|-------|
| Q1 | 처리할 그룹 | always | single-select; the candidates plus **"더 많은 항목 보기"** — the fast path's cap of 3 keeps this inside the 4-option limit |
| Q2 | 함께 묶을 추가 항목 | ≥2 candidates look trivial | `multiSelect: true`; the trivial candidates. Selecting the Q1 group too is harmless — dedupe it |
| Q3 | 라이트 패스 / 풀 사이클 | ≥1 candidate looks trivial | single-select, wording per Step 2.5's *Lite path offer* |

Emit Q2/Q3 only under those conditions — a pick list with no trivial-looking candidate must not
carry them, or the user is answering about a path that cannot apply.

**Apparent triviality is a pre-filter, never the authority.** It is judged from item text, before
any scoping; Step 2.5 re-judges the *selected* group properly. If the pick turns out non-trivial
once scoped, discard the Q2/Q3 answers, say so in one line, and run the full cycle.

**Discard the Q2/Q3 answers whenever the selection is re-made**, not only on that non-trivial
outcome. Picking **"더 많은 항목 보기"** re-opens the choice, so the batch and lite-path answers
now describe a task the user is no longer running — carrying them into Step 2.5 would merge a
*different* item straight to `main` with no PR and no CI on the strength of an answer given about
something else. Re-ask after any re-pick.

Non-interactive run: ask nothing — the full-scan `[1]` default applies, no batching, full cycle.

**Full scan (fast path found nothing, or `--all` batch mode):** Run the script in full-scan mode to build the complete candidate list:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
CANDIDATES="$SKILL_DIR/scripts/backlog_candidates.py"
[[ -r "$CANDIDATES" ]] || { echo "Bundled script missing or unreadable: $CANDIDATES" >&2; exit 1; }
python3 "$CANDIDATES" --tasks tasks.md --backlog backlog.md --full-scan
rc=$?
[[ $rc -eq 0 ]] || { echo "backlog_candidates.py exited $rc — see its stderr above" >&2; exit 1; }
```

Uncapped, and one difference from the fast path: the backlog.md sources use type priority (all
qualifying h3 headings before any h2 heading) instead of the fast path's document order. Both
algorithms qualify a heading by the same test, so a fast-path zero **is** proof the queue is
empty — the full scan is for ordering and completeness, not reachability. Every h2/h3 with an open
`- [ ]` qualifies — including `## Ideas` or `## Someday`; park an item with
`[>]`/`[x]`/a `*(deferred: ...)*` marker, not by choosing a section name.

## Step 2 — Select

| Groups found | Action |
|-------------|--------|
| 0 | Read the script's stderr before saying anything. **Do NOT report an empty queue** if it names work the rules could not reach — prose bullets under a heading, items above the first heading, items attributed but selected by no phase, a `tasks.md` findings section pending migration — or if it warned about an unbalanced fence, which can hide the rest of the file. Relay the diagnosis per Step 1 instead. Otherwise the queue really is clear (everything parked, no open items, or no headings at all): report "backlog and tasks are clear — nothing open", point the user to `task-new` for new work, and stop. |
| 1 | Announce the group and proceed to Step 3. *(Full-scan path only; the fast path handles the 1-sprint case directly.)* |
| ≥2 | Print a numbered list of all groups (user explicitly requested full list): `[N] <source>: <heading title> (<M> items)`. Wait for the user to reply with a number. Non-interactive run: take candidate `[1]` and announce it — no wait. |

Non-interactive default (both tables above) and the rest of this section's gates: see
`dev:harness-init` → `references/harness-invariants.md` → *Non-Interactive Gate Defaults*.

**Large-group guard:** if the selected group has >8 open items, confirm with the user before proceeding — list the items numbered and ask whether to process all or a subset. This guard does **not** auto-default in a non-interactive run — abort and report instead.

**Deferred/blocked items:** a group where every open item has `*(deferred: ...)*` or `*(blocked by: ...)*` is not a candidate. Skip it and surface the blocker. If all groups are deferred/blocked with unresolved blockers, report and stop. Any item you *newly* judge blocked this run (no marker yet) — or whose marker you find is now stale — is persisted at pre-merge cleanup (see **Blocked-analysis sync** in Step 3) so you don't re-analyze it next run. That sync rides the selected task's cleanup commit; in the all-blocked → stop case there is no task to ride, so it does not run.

Do NOT use `AskUserQuestion` in this step — a plain numbered list handles any list size without the 4-option cap.

## Step 2.5 — Size gate (batch nudge + lite path offer)

Run after selecting a group, before Step 3. Evaluate whether the selected group is **trivial**:
ALL must hold: tag is NOT `[FEAT]`, total in-scope files ≤2, no new public API/schema. This is the
authoritative judgement — Step 1's apparent-triviality pre-filter only decided which questions to
ask.

If **not trivial** OR **`--tree` is active** → skip this section entirely, proceed to Step 3
normally. Discard any Q2/Q3 answers Step 1 collected and say in one line that they no longer
apply; do not silently drop a batch the user asked for.

If **trivial** (and `--tree` is NOT active): **the answers are usually already in hand.** When
Step 1 emitted Q2/Q3, read them and do not ask again — the whole point of the batched gate is that
this section costs zero further round trips. Ask only for a question Step 1 did not emit (the
full-scan path, the Codex numbered-list path, or a condition that was not met at pick time).

**Batch nudge** — Q2's answer, or, when Q2 was not emitted, scan for other trivial open groups
(re-use the candidate list from Step 1; re-grep only if the list is no longer in context). If ≥1
other trivial groups exist and no answer is in hand, surface them:

```
선택한 태스크가 작습니다. 아래 항목들과 묶으면 PR·CI 오버헤드를 공유할 수 있습니다:
  [1] <group title> (<M> items)
  [2] <group title> (<M> items)
  ...
같이 처리할 항목을 번호로 선택하세요 (복수 가능). 건너뛰려면 N.
```

Non-interactive run: decline the nudge — no batching — and announce.

If the user selects ≥1 additional groups → treat the combined selection as a **Batch mode
(`--all`)** run: skip A1–A3 (selection already done), proceed directly to **A4** with this
confirmed unit list. End Step 2.5 here.

**Lite path offer** — Q3's answer, when Step 1 emitted it. Otherwise, if the user declines the
nudge (or no other trivial groups exist), offer:

```
[1] 라이트 패스 — 구현+QA 후 main에 직접 머지 (PR·CI 없음)
[2] 풀 사이클 — task-review (PR, CI, 코드리뷰 포함)
```

- User picks **1** → proceed to Step 3 with the **lite path** active (see `## Lite path` section).
- User picks **2** → proceed to Step 3 normally.
- Non-interactive run: resolve to **2** (full cycle) and announce — no wait.

## Step 3 — Run the code cycle

Execute `docs/workflows.md` → `code` cycle (workflows.md Steps 0–5; workflows.md Step 6 is this skill's Step 4).
Overrides below; standard steps apply where not overridden.

**Branch (workflows.md Step 0)**
The script applies the shared-`[type]`-else-`fix/` rule; surface its stderr warning when it falls back.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
NODES="$SKILL_DIR/scripts/task_nodes.py"
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }
BRANCH=$(printf '%s\n' "<each selected item line, verbatim>" \
  | python3 "$NODES" branch --title "<selected heading title>")
git checkout -b "$BRANCH"
```

**Roster check — run before the first agent spawn in this step or the ones below.** A role exists
only if `.claude/agents/{role}.md` or `~/.claude/agents/{role}.md` is present; an absent role is
never a reason to stop, and never a reason to create the role mid-task.

```bash
role=implementer  # the role to probe
if [[ -f ".claude/agents/$role.md" || -f "$HOME/.claude/agents/$role.md" ]]; then
  echo present
else
  echo absent
fi
```

A role can also arrive from an installed plugin, which no path check finds — if the runtime lists
it as an available agent type, treat it as present regardless of the probe. Route around an absent
role per `dev:harness-init` → `references/harness-invariants.md` → *Absent-Role Fallbacks*, and say
in one line which fallback you took.

**Result-handoff rule (applies to every agent this skill spawns).** Any agent launched with a
`name` — and, as cheap insurance, any launched with `run_in_background: true` — must be told
**in its initial prompt** to report via `SendMessage(to: "main")`. For a named agent, messaging
is the delivery channel: it finishes the work and the result is silently dropped otherwise.
There is no way to add the instruction after the spawn. Full rule: *Result-handoff rule* in
`delegation-template.md` (bundled with `dev:harness-curate`). Covers every spawn point below —
`explorer`, `implementer`, `qa-verifier`, and the batch/tree fan-outs in `references/tree.md`
and `references/batch.md` — including when the result is empty.

**Scope check (workflows.md Step 1)**
If the target area has >3 files AND was not explored this session → spawn `explorer` before
writing the Sprint Contract. **`explorer` absent from the roster:** see
`references/harness-invariants.md` → *Absent-Role Fallbacks*.

**Plan mode gate (before workflows.md Step 2)**
Check tag first, then file count:
- **Non-trivial** (tag is `[FEAT]` or `[REFACTOR]`, OR ≥3 files, OR new public API/schema):
  use `ToolSearch` (`query: "select:EnterPlanMode,ExitPlanMode"`) to load plan mode tools,
  call `EnterPlanMode`, design the approach, call `ExitPlanMode` for user approval. If
  ToolSearch returns no results, present the plan as a numbered list and wait for explicit
  "proceed" before coding.
  **Write the drafted Sprint Contract into the plan body**, in the shape the *Sprint Contract*
  step below specifies (Tag / Scope / Acceptance criteria / Out of scope / Lint/test command).
  One approval then covers approach *and* contract, and **Mark active** below follows with no
  second round trip. Drafting it here costs nothing: the contract has to exist before implement
  either way, and an acceptance criterion the user disagrees with is far cheaper to catch at
  approval than after the code lands.
- **Trivial** (tag is NOT `[FEAT]`/`[REFACTOR]` AND 1–2 files AND no new public API/schema):
  skip plan mode.
- **Non-interactive run** (no live user reachable — see `dev:harness-init` →
  `references/harness-invariants.md` → *Non-Interactive Gate Defaults*): skip
  `EnterPlanMode`/`ExitPlanMode` even when the item is non-trivial; record the plan in the
  transcript and the PR body instead, announce, and proceed. Same gate, same default as
  `task-new` Step 3 — the two must not diverge.

**Mark active — after scope is confirmed**
Once plan is approved (or trivial gate passed), derive action from the selected group's source:

*tasks.md h1 block (`status: open`):* flip `status: open` → `status: active` in tasks.md.
  The existing h1 block IS the Sprint Contract — do not write a new one. Read the h1 block's
  body (especially `## Acceptance criteria` if present) for implementation scope.

*backlog.md group (h2 or h3) — including a `### PR #N` findings group under `## Review Backlog`:*
  Do NOT flip items to `[>]` — leave them as `[ ]` in backlog.md until deletion at pre-merge cleanup.

  - **≥2 in-scope items:** write a `tasks.md` Sprint Contract with:
    - `# heading` = the selected heading title (verbatim from backlog.md)
    - `status: active`
    - `## Covers` listing each in-scope item copied **verbatim** from backlog.md — full line including the `- [ ]` prefix (e.g., `- [ ] fix thing`). This is the deletion list; exact match required so cleanup can locate and remove the right lines.
  - **Exactly 1 in-scope item:** in default mode, write no file. Author the Sprint Contract inline
    in the conversation (same Scope / Acceptance criteria / Out of scope / Lint/test command shape
    as below) and carry the item's verbatim `- [ ] ...` line forward yourself — it goes straight
    into the `prune-backlog` call at pre-merge cleanup, with no `tasks.md` round-trip. In `--tree`
    mode, write the same contract to `tasks.md` with `status: active` and a `## Covers` section
    containing the item's full `- [ ] ...` line; tree mode is file-backed even for one item.

**Sprint Contract (workflows.md Step 2)**
Per `docs/eval-criteria.md` template: **Tag** / **Scope** / **Acceptance criteria** /
**Out of scope** / **Lint/test command**. The **Tag** is the `[TYPE]` this change will commit
under, and it must be written into the contract — the verifier grades the contract alone, so a tag
it cannot see gates nothing. Do not recover it from the branch prefix: `task_nodes.py` falls back
to `fix/` for untagged and mixed-tag groups alike, so the prefix cannot distinguish a real `[FIX]`.

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
- **`implementer` absent from the roster:** see `references/harness-invariants.md` →
  *Absent-Role Fallbacks* — implement inline on the main thread. It covers every implementer spawn this skill owns, `--tree` mode and batch mode's
  per-unit fan-out (`references/tree.md`, `references/batch.md`) included; there the main thread
  works the units itself, sequentially, one worktree at a time, since the parallelism came from
  the fan-out that is no longer available.
- **Per-item checkpoint (≥2-item group, default mode):** work the `## Covers` items one at a time
  and run the Sprint Contract's lint/test command after each one, before starting the next — a
  failure in the first item must surface at that item, not be discovered at handoff. Applies to the
  inline path and the `implementer` brief alike; when delegating, the brief must state the per-item
  order and require the checkpoint result for each item in the returned report. Do **not** commit
  per item — committing stays with `task-review-cycle` Step 1 (or the lite path's single commit). Fix a
  failing checkpoint before starting the next item, under the stuck-fix stop condition below. This
  does not replace the end-of-sprint QA pass: the checkpoint is the implementing agent's own gate,
  and independent verification still runs once at the end per the QA step. Out of scope: a
  single-item cycle has nothing to interleave, and batch mode already spawns a verifier per unit
  (`references/batch.md` A5).
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

**QA (workflows.md Step 4)**
QA is always a separate agent, and the implementing agent must not verify — a deliberate exception
to the volume half of the repo's delegation gate, argued once in `docs/delegation.md` → *Role
Routing*. The exception covers every QA spawn this skill owns, batch mode's per-unit verifiers
included; every non-QA delegation still needs both conditions.

**Where it runs depends on the path.** On the **default full-cycle path** — single-pick, not lite,
not `--tree`, not `--all` — do **not** spawn `qa-verifier` here. Hand off with `--qa-pending` (Step 4
below) and contract QA runs inside `task-review-cycle` as review-panel source 2-4, concurrently with
the three review engines instead of as its own blocking wave in front of them. Everything below —
the adversarial brief, the absent-role fallback, the blocking-issue retry — then belongs to that
slot, and `task-review-cycle` → *2-4: Contract QA* states it; do not also run it here, or the diff
is verified twice and the latency this buys is spent again.

The **lite path**, **`--tree`** and **`--all`** batch mode keep QA here, before handoff or
integration, exactly as written below: the lite path never opens a PR, so there is no panel to ride,
and tree/batch verify per worktree before their units are collapsed onto one branch.

**Brief the verifier adversarially.** The objective in the brief is *find violations*, not *confirm
compliance*: tell it to hunt for each way the change could fail a criterion and to record a pass
only where it has evidence. Do **not** include the orchestrator's own reasoning about why the
implementation is correct — the verifier grades the diff against the contract, and a supplied
conclusion is what it will confirm. Applies to every QA spawn this skill owns, the
`general-purpose` fallback and batch mode's per-unit verifiers included.

**`qa-verifier` absent from the roster:** see `harness-init` → `references/harness-invariants.md`
→ *Absent-Role Fallbacks* — spawn `general-purpose` with the same four-field brief. **Carry the
standing-checks floor in it**, taken from `references/harness-invariants.md` → *Verifier
Standing-Checks Floor*; do not reconstruct that list from memory. Independence is what must not be
dropped, not the role name; the fallback applies to every QA spawn this skill owns, batch mode's
per-unit verifiers included.

If the verifier reports blocking issues:
1. Surface findings to user.
2. **Classify each blocking finding before fixing.** A finding caused by an unclear, incomplete or
   wrong Sprint Contract is a *contract* defect: correct the contract and re-brief from it. Only a
   finding that survives a correct contract goes to `implementer` — sending a contract defect there
   re-litigates it as an implementation defect and burns the one allowed retry. This covers every
   retry path this skill owns — `references/batch.md` A5's per-unit implementer→qa-verifier retry
   and `references/tree.md`'s included — so classify there too rather than fanning out blind.
3. Spawn `implementer` with the surviving findings as its brief to fix them (or fix inline, when
   `implementer` is absent).
4. Re-run the verifier once, against the corrected contract.
5. If still blocking after one retry: stop and report — do NOT hand off with unresolved blockers.

**Version bump (workflows.md Step 5)**
The judgment is *which* plugin and *which* bump level; the rewrite itself is scripted. Do this
AFTER all changes, BEFORE handoff.

```bash
[[ -f scripts/bump-version.sh ]] && bash scripts/bump-version.sh <plugin> <major|minor|patch> \
  [--skill <name> <major|minor|patch>]
```

Pass `--skill` when the changed files include that skill's own `SKILL.md`, so its `version:`
frontmatter does not go stale. The script takes **one** `--skill` per run and bumps the plugin on
every run, so a change touching two skills needs the second skill's `version:` edited by hand —
re-running would bump the plugin twice for one change.

`bump-version.sh` keeps both platform manifests in sync and states the semver table in its own
header; `docs/conventions.md` → *Plugin Version Bump Rules* is the prose copy where that doc exists.
Read one of them rather than recalling the rules — the script header suffices on its own when the
repo has no `docs/conventions.md`. If the repo has no `scripts/bump-version.sh` (it ships with this
marketplace, not with the skill), edit the manifests by hand per the same rules; if the repo
has no `plugin.json` at all, skip this step. With **neither** the script nor `docs/conventions.md`
present, the repo has stated no release policy — ask the user for the bump level instead of
inventing one. This gate never auto-defaults: in a non-interactive run, abort and report rather
than picking a level (`references/harness-invariants.md` → *Non-Interactive Gate Defaults*).

**Do NOT commit.** Leave all changes uncommitted. `task-review-cycle` Step 1 commits everything
so there is one clean commit per review/merge cycle.

**Pre-merge cleanup (do before Step 4)**

Mark the sprint done and sync tracking files — leave as uncommitted so they land in the
initial PR commit alongside the code.

Your judgment is *which* lines are done; deletion, heading cascade and entry placement are
scripted. Run the lines that apply to this task's source:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
NODES="$SKILL_DIR/scripts/task_nodes.py"
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }

# only if a sprint block exists in tasks.md — a pre-existing h1, a ≥2-item Sprint Contract, or any
# `--tree` run (tree mode is file-backed even for one item)
python3 "$NODES" prune-tasks --file tasks.md --block "<h1 title>"
# backlog.md lines listed verbatim in the Sprint Contract's ## Covers
printf '%s\n' "<each ## Covers line>" | python3 "$NODES" prune-backlog --file backlog.md
# one CHANGELOG entry; drop --plugin/--version in a repo with no versioned plugin
python3 "$NODES" changelog --file CHANGELOG.md --title "<sprint or finding-group title>" \
  --plugin <plugin> --version <X.Y.Z> [--link docs/<owning-doc>.md]
```

`prune-*` refuses (exit 1) and changes nothing when a line matches no line verbatim, or matches
more than one — an ambiguous target is the dangerous case, since two sections can hold identically
worded items and only one is done. Re-read and re-run rather than loosening the input. A heading is
dropped only where this sprint left its whole section blank, so `[x]`/`[>]` history, prose and
surviving child headings all keep their ancestors alive. **This is deliberately stricter than the
rule it replaced** ("no open `- [ ]` items left"), which would strand surviving `[x]` lines under a
deleted heading. `tasks.md` goes once empty — safe because it holds the Sprint Contract and
nothing else, which `prune-tasks` verifies before touching it — and `backlog.md` never does.
`changelog` runs the repo's own `scripts/ci/check_changelog_entries.py` over the composed line and
refuses (exit 1, nothing written) when the decidable subset fails — over the cap, a second `→`
link, a link that does not resolve — so those surface at authorship instead of in CI. What no
script can decide — the ban on explanatory clauses, file lists and narration — lives in
`harness-invariants.md` → *CHANGELOG Entry Contract*. Read it before choosing the title; do not
reconstruct the limits from memory.

*Blocked-analysis sync (runs for every source type):*

While selecting (Step 1/2) you inspect items and judge some blocked. Persist that judgment so
the next run's `backlog_candidates.py` filters them deterministically instead of you
re-analyzing them each run. **Scope: only items you actually inspected this run** — do NOT
force a full scan just to annotate. Sync **both** directions:

- **Mark newly-found blocked items.** An open `- [ ]` item you confirmed this run is blocked by
  an unresolved dependency (or otherwise non-actionable) and that carries NO
  `*(blocked by: ...)*`/`*(deferred: ...)*` marker → append a marker to that line:
  `*(blocked by: <slug>)*` when the blocker is another queue item, else
  `*(deferred: <short reason>)*`. Write the slug alone — the `<n>-` prefix on older markers is
  authoring residue this skill never invents (`dev:task-tickets` step 6). Only when you verified
  the blocker is unresolved this session — verify, never guess.
- **Clear stale markers.** An item carrying `*(blocked by: ...)*` whose referenced blocker is no
  longer an open item (it landed or was removed), or a `*(deferred: ...)*` whose reason you
  confirmed resolved this run → delete the marker so the item becomes a candidate again next run.
  Only when the resolution is verifiable from files/command output read this session — never guess.
  Three rules govern the match, and the last is the one that keeps this safe:
  - **Match on the slug, never on any `<n>-` prefix.** The number is authoring residue that nothing
    renumbers, so a number matching no heading position is expected (`dev:task-tickets` step 6).
  - **The slug is abbreviated, so match it by judgment against the blocker's heading and item
    text** — not by string equality. `user-invoked-descriptions` is the marker for
    `## Invocation axis — user-invoked descriptions`; a literal comparison would find nothing.
  - **Failing to find a match is never evidence the blocker landed.** Clear a marker only on
    positive evidence — the blocker's item now reads `[x]`, or its removal is visible in git.
    When you cannot resolve the slug at all, leave the marker and say so.

These edits ride the same cleanup commit. Disclose them in the PR body (or lite-path commit
message), e.g. "synced N blocked markers in backlog.md", so review does not read them as scope
creep. If nothing was synced, skip silently.

Post-merge, verify `backlog.md` and `tasks.md` are clean — no `[x]`, `[>]`, or stale sprint markers.

## Step 4 — Hand off

Call the Skill tool with "dev:task-review-cycle" and:

- **default full-cycle path** — `args: --from task-next --auto --qa-pending`. `--qa-pending` says
  contract QA is still owed, so the review cycle runs it as source 2-4 alongside the panel. **State
  the Sprint Contract verbatim in the handoff** — Tag / Scope / Acceptance criteria / Out of scope /
  Lint-test command. Pre-merge cleanup has already pruned `tasks.md`, so this restatement is the
  only copy 2-4's brief can be built from; hand off without it and the review cycle stops and asks.
- **`--tree` and `--all`** — `args: --from task-next --auto`, no `--qa-pending`: those paths already
  verified per worktree/unit before collapsing onto the branch.

`task-review-cycle` commits (including the cleanup changes above), creates PR, collects
reviews, applies in-scope findings, records out-of-scope items to `backlog.md`, waits CI, and merges.

**If task-review reports CI failure and the PR must be abandoned:** close the PR and delete
the feature branch without merging — `main` retains the pre-cleanup state and no rollback is needed.
If you continue on the same branch after fixing CI, the cleanup commit is already correct and
no further action is required.

## Lite path

Active when the user chose "라이트 패스" in Step 2.5. Runs the code cycle without PR or CI —
implement, QA, then merge directly to `main` in the same session.

Run Step 3 sub-steps normally (branch, Sprint Contract — file-backed only for a ≥2-item group,
inline otherwise, per **Mark active** above — Implement, QA, version bump, pre-merge cleanup)
with these overrides. **QA runs here**, before the merge — the deferral to review-panel source 2-4
is a full-cycle-only move and there is no PR on this path to carry it.

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

**Branch-protection caveat:** if `git push origin main` is rejected (branch protection rule requires PRs), reset local main (`git reset --hard origin/main`), check out the feature branch (`git checkout <type>/<slug>`), and fall back to calling the Skill tool with "dev:task-review-cycle" and `args: --from task-next --auto`.

Report on completion: "라이트 패스 완료 — main에 직접 병합 및 푸시됨. PR·CI 없음."

## `--tree` mode (single task, worktree isolation)

Runs single-pick through an isolated git worktree so the main checkout stays on `main` throughout implementation and QA. QA stays in the worktree, before handoff — no `--qa-pending`. See `references/tree.md` for full detail.

## Batch mode (`--all`)

Implements multiple units in parallel worktrees, then collapses them onto one integration branch for a single version bump, cleanup pass, and one `task-review-cycle --from task-next --auto` run. Each unit is QA'd in its own worktree before integration, so the run carries no `--qa-pending`. See `references/batch.md` for full detail.

## Edge cases

Five branches a normal run never reaches. Recognise them by name here; open
`references/edge-cases.md` for the full handling before acting on one.

- **Work already in flight** — a feature branch (or a `--tree` worktree) carrying uncommitted work
  from a previous session. The Prerequisites working-tree gate routes here. Three ordered checks
  produce a specific diagnosis; always still ask yes/no before resuming.
- **Whether QA is still owed** — a resumed run must decide this before handing off. Commits ahead
  of `main` do not prove QA ran.
- **Deferred backlog item (≥2 candidates)** — surface the blocker, confirm it is resolved.
- **Deferred item in a group** — warn and continue with the group's non-deferred items.
- **Review finding spans multiple PRs** — scope narrowly to the specific `file:line` ref.
