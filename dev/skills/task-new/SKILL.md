---
name: task-new
version: 1.0.1
description: >-
  Intake for a NEW concrete task the user's prompt itself DESCRIBES — the request spells out
  the work to build or fix (a feature, bug, or change), not a reference to the existing queue.
  e.g. "add a logout button", "refactor the auth module", "fix the timezone bug in reports",
  "이거 만들어줘", "새 기능 추가해줘", "X 리팩터링해줘", "이 버그 고쳐줘". Classifies the request,
  resolves ambiguity via task-grill, and for larger work breaks it into a spec (task-spec) and tickets
  (task-tickets); then runs the full code cycle (branch → Sprint Contract → implement →
  qa-verifier → version bump → task-review --auto) on it. Trivial requests get a lite-path
  offer (direct merge, no PR/CI). Discriminator vs `task-next`: use task-new when the prompt
  states WHAT to do; use `task-next` when the prompt asks to pull the next item FROM
  `backlog.md`/`tasks.md` without naming specific new work.
---

# New Task

Intake and drive a **fresh, free-text request** — a feature, refactor, or fix the user just
described that is not yet an item in `backlog.md`/`tasks.md`. Sibling to `task-next`: that skill
picks work already on the queue; this one turns a spoken request into work and runs it through
the same `code` cycle in `docs/workflows.md`. Delegate the heavy lifting — this skill is the
**intake, sizing, and sequencing layer**, not the implementation engine.

Boundary vs `task-next`: if the request is already a `backlog.md`/`tasks.md` item, stop and use
`task-next` — do not re-enter it here. This skill runs when the request has no tracking entry yet.

## Prerequisites

The repo must have `backlog.md`, `docs/workflows.md`, `docs/eval-criteria.md`, and
`docs/conventions.md` (harness-init artifacts). If any is missing, stop and point the user to
`dev:harness-init`.

**Working tree gate:** Run `git status --porcelain`. If the output is non-empty, stop and list
the dirty files — do NOT proceed. Ask the user to commit, stash, or discard first. (This gate is
checked once, here. Later steps deliberately dirty `tasks.md`/`backlog.md` as part of the cycle;
that is expected and rides into the feature branch.)

## Step 1 — Classify & size-gate

Free text carries no `[type]` tag yet, so infer one from what the request describes before
gating — adds/changes user-visible behavior → `[FEAT]`; restructures existing behavior without
changing it → `[REFACTOR]`; fixes broken behavior → `[FIX]`; anything else → leave untagged.

Then judge **trivial**: trivial iff ALL hold — inferred/explicit tag is NOT `[FEAT]`/`[REFACTOR]`,
total in-scope files ≤2, no new public API/schema. An untagged one-file typo fix stays trivial;
an untagged one-file behavioral addition ("로그인 버튼 추가해줘") is not, because it infers to
`[FEAT]`.

If the file count isn't obvious from the request text, run a quick scoped scan (or spawn
`explorer` per the `docs/delegation.md` >3-file gate) to estimate it before classifying.

## Step 2 — Route by size

**Trivial** → skip task-grill/`task-spec`/`task-tickets` entirely. Build the Sprint Contract directly from
the request and go to Step 3. The Step 3 lite-path offer still applies.

**Non-trivial and ambiguous** (scope, requirements, or a design decision is not already clear from
the request) → `Skill(dev:task-grill)` to resolve scope. Do not proceed until task-grill reports the
open questions resolved.

**After resolution, judge size:**

- **Single-session-sized** → build the Sprint Contract directly from the task-grill output (or directly
  from the request, if task-grill was skipped because it was unambiguous but not trivial) and go to
  Step 3.
- **Multi-session or architecturally significant** → `Skill(dev:task-spec)` to write
  `docs/design/{slug}.md`, then `Skill(dev:task-tickets)` to break the approved spec into
  ordered `backlog.md` items. Once `task-tickets` has written the tickets, **pick the first
  ready ticket** (the topologically-first item with no unresolved `*(blocked by: ...)*` marker) and
  run Step 3 on that single ticket. The remaining tickets stay in `backlog.md` for future
  `task-next` runs — do NOT try to implement more than one ticket in this invocation.

Either way, Step 3 runs **exactly one** code cycle before handoff.

## Step 3 — Run the code cycle

Execute `docs/workflows.md` → `code` cycle (Steps 0–6). This skill is a thin front-end over that
cycle; the overrides below are what differ for a **request-sourced** task. Standard steps apply
where not overridden.

**Branch (Step 0)**
`git checkout -b <type>/<slug>` — derive from the `[type]` inferred in Step 1 + a short slug. If the
tag was left untagged, emit a warning ("Request has no clear [type] — defaulting branch prefix to
`fix/`") and use `fix/`.

**Scope check (Step 1)**
If the target area has >3 files AND was not explored this session → spawn `explorer` before writing
the Sprint Contract.

**Plan mode gate (before Step 2)**
- **Non-trivial** (tag is `[FEAT]`/`[REFACTOR]`, OR ≥3 files, OR new public API/schema): use
  `ToolSearch` (`query: "select:EnterPlanMode,ExitPlanMode"`) to load plan-mode tools, call
  `EnterPlanMode`, design the approach, call `ExitPlanMode` for user approval. If `ToolSearch`
  returns no results, present the plan as a numbered list and wait for explicit "proceed".
- **Trivial**: skip plan mode.

**Sprint Contract (Step 2)**
Write a `tasks.md` Sprint Contract per `docs/eval-criteria.md`:
- `# heading` = a short title for the request
- `status: active`
- **Scope** / **Acceptance criteria** / **Out of scope** / **Lint/test command**
- If this cycle is running a `task-tickets`-generated backlog ticket (the multi-session path), add a
  `## Covers` line with that ticket's `- [ ]` item copied **verbatim** from `backlog.md` — this is
  the deletion target for cleanup.

**Implement (Step 3)**
- 1–2 files AND not `[FEAT]`/`[REFACTOR]`: inline edit.
- Otherwise: spawn `implementer` (brief per `docs/delegation.md` four-field format: Objective /
  Output format / Tools to use / Boundaries — include the Sprint Contract, absolute paths of all
  in-scope files, and the lint/test command). `implementer` must NOT verify its own output.
- **Stuck-fix stop condition:** if the same fix is attempted 3+ times on one file without the
  lint/test command passing, stop and report instead of retrying.
- **Destructive-command guard:** never run `git push --force`/`--force-with-lease`,
  `git reset --hard`, `git clean -f`/`-fd`, or `git branch -D` while implementing. If a fix seems to
  require one, stop and ask.
- **If `implementer` fails or returns unusable output:** stop and report; do not proceed to QA.

**QA (Step 4 — mandatory)**
ALWAYS spawn `qa-verifier` as a separate agent. If it reports blocking issues: surface them, spawn
`implementer` to fix, re-run `qa-verifier` **once**. If still blocking after one retry: stop and
report — do NOT hand off with unresolved blockers.

**Version bump (Step 5)**
Per `docs/conventions.md` — determine which plugin directory the changed files belong to and bump
its manifests (keep `.claude-plugin` and `.codex-plugin` in sync; patch for modify, minor for new
skill, major for remove/rename). Do this AFTER all changes, BEFORE handoff. (If the target repo is
not this plugin marketplace, skip when no `plugin.json` applies.)

**Do NOT commit.** Leave everything uncommitted — `task-review` Step 1 makes the single commit.

**Pre-merge cleanup (before handoff)**
Leave these uncommitted so they land in the initial PR commit:
1. In `tasks.md`: delete the Sprint Contract block written above. If `tasks.md` has no remaining
   content, delete the file.
2. If a `## Covers` ticket was set (multi-session path): delete that item's `- [ ]` line from
   `backlog.md`. Also delete any now-empty h2/h3 heading left behind.
3. Append to `CHANGELOG.md` under `## Unreleased`: `- [done] <title> (<date>)` (create the section
   if absent).

## Step 4 — Hand off

Invoke `Skill(dev:task-review)` with `args: --auto`. It commits (including the cleanup
above), creates the PR, collects reviews, applies in-scope findings, records out-of-scope items to
`tasks.md`, waits for CI, and merges.

If `task-review` reports CI failure and the PR must be abandoned: close the PR and delete the
feature branch — `main` retains its pre-cleanup state, no rollback needed.

## Lite path

For a **trivial** request only. The lite path changes **only the handoff** — everything in Step 3
(branch, Sprint Contract, implement, QA, version bump, cleanup) runs identically; only Step 4
differs. Present the choice when entering Step 3 (before branching) so the user isn't surprised:

```
[1] 라이트 패스 — 구현+QA 후 main에 직접 머지 (PR·CI 없음)
[2] 풀 사이클 — task-review (PR, CI, 코드리뷰 포함)
```

- User picks **1** → run Step 3 (branch, Sprint Contract, implement, QA, version bump, cleanup) then
  skip `task-review` and merge directly:

```bash
git add <changed files>
git commit -m "[TYPE] <description>

Co-Authored-By: Claude <noreply@anthropic.com>"
git checkout main
git pull origin main
git merge --no-ff <type>/<slug> -m "Merge branch '<type>/<slug>'"
git push origin main
git branch -d <type>/<slug>
```

  **Branch-protection caveat:** if `git push origin main` is rejected (PR-only rule), reset local
  main (`git reset --hard origin/main`), check out the feature branch, and fall back to
  `Skill(dev:task-review)` with `args: --auto`.

  Report: "라이트 패스 완료 — main에 직접 병합 및 푸시됨. PR·CI 없음."
- User picks **2** → proceed to Step 3 / Step 4 normally.

## Edge cases

**Request is already tracked** — if the described work matches an existing `backlog.md`/`tasks.md`
item, stop and route the user to `task-next` instead of duplicating the entry.

**Batch of unrelated requests** — this skill runs one request per invocation. If the user lists
several independent tasks, handle the first and tell them to re-invoke for the rest (or add them to
`backlog.md` and point at `task-next --all`).

**Work already in flight** — if `git status` shows an in-flight feature branch rather than a fresh
request, this is `task-next` territory (its "Work already in flight" edge case). Route there.
