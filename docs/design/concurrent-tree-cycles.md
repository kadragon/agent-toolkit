# Concurrent `--tree` cycles

## Problem Statement

`task-next --tree` isolates only the code change in `.worktrees/<slug>`. The Sprint Contract
(`tasks.md`), version bump, `CHANGELOG.md`, and cleanup stay uncommitted in the main checkout,
and the collapse step runs `git checkout $BRANCH` there. That design assumes one run at a time,
so several sessions cannot each work one PR in the same repo at once:

1. The working tree gate (`task-next/SKILL.md` → *Working tree gate*) routes to *Work already in
   flight* whenever any `.worktrees/` entry exists, even with a clean base checkout.
2. There is one uncommitted `tasks.md` in the main checkout, so it can hold only one contract.
3. Collapse switches the main checkout to `$BRANCH`, which pulls the floor out from under every
   other run that assumes the main checkout sits on base.
4. Every run bumps the same `plugin.json` pair and inserts at the top of `CHANGELOG.md` →
   `## Unreleased`, so concurrent PRs always conflict. The CI `version-bump` job compares
   against `origin/main`, so the second PR to land also fails CI unless its bump is redone.
5. `backlog_candidates.py` reads only the main checkout's `tasks.md`/`backlog.md`, so a second
   session picks the same item another worktree is already working.
6. `task-new` has no `--tree`.

## Solution

Make `--tree` a collapse-free worktree cycle, the same shape `task-next/references/cycle.md` →
*Branch* already uses for exit 3: everything a cycle writes — `tasks.md`, contract archive,
edits, version bump, `CHANGELOG.md`, cleanup, commits, PR, merge — happens inside
`.worktrees/<slug>`, and the main checkout is never edited or switched. The gate treats other
worktrees as other sessions' work when the main checkout is clean on base. Candidate selection
skips items other worktrees have claimed. Just before merge, the review cycle resyncs a branch
that fell behind base and recomputes the bump number. `task-new --tree` uses the same path.

## User Stories

- As a user running three sessions in one repo, I want each `task-next --tree` to pick a
  different backlog item and open its own PR, so that work proceeds in parallel without me
  sequencing it.
- As a user, I want my main checkout to stay on a clean base while `--tree` runs, so that I can
  start another session from it at any time.
- As a user whose PR lands second, I want the bump and CHANGELOG conflict resolved
  mechanically before merge, so that I do not hand-fix `plugin.json` every time.
- As a user with a stopped run, I want to resume it only when I name it, so that a new session
  never adopts another session's live worktree by accident.
- As a user with a free-text request, I want `task-new --tree` to run it in a worktree, so that
  it can run beside queue work.

## Implementation Decisions

- **Collapse-free `--tree`.** `tree.md`'s Branch step stops requiring the main checkout to be on
  base for correctness of later steps; it creates `.worktrees/<slug>` from `origin/<base>` (the
  `git merge --ff-only` leveling of the local base stays when this checkout holds base, as
  today). *Mark active* writes `tasks.md` (`status: active`, `## Covers`) **in the worktree**.
  Version bump, `CHANGELOG.md`, `prune-tasks`/`prune-backlog` run in the worktree. The collapse
  block is deleted. The review cycle runs from the worktree and passes the absolute worktree
  path as `merge-and-cleanup.sh`'s fifth argument, `worktree_path`, issued per cycle.md exit 3's
  rules (`cd` as its own Bash call, merge command unprefixed). `tree.md` and cycle.md exit 3
  should end up sharing one description of "a cycle in its own worktree" rather than two.
- **`--tree` always takes the hub (PR) path.** The lite path's local `git checkout <base>` +
  `git merge` cannot run inside a linked worktree (base is checked out in the main worktree) and
  would edit the main checkout. One task, one PR.
- **Implementer/QA boundary.** The implementer still must not touch manifests, `backlog.md`,
  `tasks.md`, or `CHANGELOG.md`; the parent does those edits in the same worktree after QA.
- **Gate relaxation.** The row "on base branch, `task_worktree` non-empty, whatever is dirty"
  splits: clean base checkout + other worktrees → **proceed without asking**, announcing the
  skipped worktrees in one line (e.g. `skipping 2 in-flight worktrees: .worktrees/foo,
  .worktrees/bar`). A dirty main checkout still follows the existing rows. The
  `task_contract_dirty` row (a collapse that stopped) becomes legacy-only, since `--tree` no
  longer leaves `tasks.md` in the main checkout.
- **Explicit resume.** A preserved worktree is resumed only on explicit request: `--resume
  <slug>`, or the user naming the worktree. *Work already in flight* (`edge-cases.md`) is
  rewritten to that rule for worktrees; a feature branch checked out in the main checkout keeps
  today's handling.
- **Claimed items.** `backlog_candidates.py` gains awareness of other worktrees (enumerated via
  `git worktree list --porcelain`, `.worktrees/` entries only). An item is claimed when either
  (a) its line appears under `## Covers` in that worktree's `tasks.md`, or (b) that worktree's
  `backlog.md` deleted it relative to the worktree's merge-base with base — (b) keeps the claim
  alive after cleanup has pruned both `tasks.md` and the backlog line but before merge. Claimed
  items are dropped from candidates, and the output names how many were skipped and by which
  worktree. The `cycle_state` archive is not used for claims: its contract text is not
  guaranteed to carry the verbatim item lines.
- **Pre-merge resync (decision d).** In `task-review-cycle`, before the hub merge: fetch; if the
  branch is behind `origin/<base>`, rebase onto it. For the version-bearing files — both
  manifests of the bumped plugin, the `version:` line of any `SKILL.md` bumped with `--skill`,
  and `CHANGELOG.md` — take base's side, re-run `bump-version.sh` with the level chosen in the
  original cycle (recorded in the contract archive or PR body so the resync can read it), and
  re-insert the CHANGELOG entry with the new version via `task_nodes.py changelog`. Any other
  conflict stops the resync and is reported — never auto-resolved. Then `git push
  --force-with-lease`, wait for CI again, merge. Force-push needs its own Git authority check
  (`git-authorization.md`). Where the scripted part lives (new script vs. `task_nodes.py`
  subcommand) is an implementation choice for the ticket.
- **`task-new --tree`.** `task-new` accepts `--tree` and runs cycle.md's worktree path even from
  base. It writes no `tasks.md` (no queue line), so it claims nothing under the claimed-items
  rule; that is acceptable because a free-text request is not in the queue.

## Alternatives rejected

- Bump after merge (a follow-up commit on base) — the CI `version-bump` job fails every PR that
  touches `dev/`/`prod/` without a bump against `origin/main`; Golden Principle 1 would break.
- Keep collapse but serialize runs with a lock file — still one run at a time; does not meet
  the goal.
- Ask the user before proceeding past other worktrees — every new parallel session would stop
  on a question, defeating concurrency; the announcement line plus explicit resume covers the
  "forgot my stopped run" risk.
- Claims from the `cycle_state` archive — the archive is keyed by branch and holds contract
  text, not guaranteed verbatim backlog lines; worktree files are the direct source.
- Lite (local merge) path inside the worktree — base is checked out in the main worktree, so
  the merge would have to edit the main checkout.

## Testing Decisions

- `backlog_candidates.py --test`: fixtures with a temp repo holding linked `.worktrees/` entries —
  claim via `## Covers`, claim via a backlog line deleted relative to merge-base, a line added to
  base after the worktree branched (must **not** count as claimed), and non-`.worktrees/`
  worktrees ignored.
- Resync script: a regression test (CI step in `harness-check.yml` per AGENTS.md) on a temp repo
  where two branches bump the same plugin — the second resyncs to the next patch number, its
  CHANGELOG entry carries the new version, and a non-version conflict stops with no push.
- Prose changes (gate table, `tree.md`, `edge-cases.md`, `task-new`): `bash
  dev/skills/harness-init/scripts/validate-harness.sh`, plus a manual dry run with two
  concurrent `--tree` sessions in this repo.

## Out of Scope

- Redesigning `--all` batch mode beyond the shared gate rows.
- Changing `--tree`'s delegation of implementation and QA to `implementer`/`qa-verifier`.
- GitHub merge queue or any server-side merge automation.

## Further Notes

- Each slice touches `dev/`, so every ticket bumps the dev plugin pair (both manifests).
- Until this feature has landed, these tickets run one at a time: each is still bound by the
  current `--tree` constraints (one in-flight run, collapse into the main checkout). Order puts
  the foundations first — claimed items, collapse-free `--tree`, pre-merge resync — then the
  gate relaxation, which is safe only once collapse no longer switches the main checkout.
- `merge-and-cleanup.sh` already accepts `worktree_path` and already avoids switching the main
  worktree's branch; no change is expected there beyond being called from the new path.
