# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Review Backlog

### PR #408 — task-next candidates skip items claimed by other .worktrees/ runs (2026-11-19)

- [ ] [harness] Phase A `status: open` tasks.md sprint blocks are not claim-checked; a block another worktree marked active stays a candidate (source: code-review) — dev/skills/task-next/scripts/backlog_candidates.py:phase_a_candidates
- [ ] [harness] Two sessions selecting before either writes `## Covers` can both take the same item; claims need an atomic commit-or-reselect step (source: codex) — docs/design/concurrent-tree-cycles.md → Claimed items
- [ ] [debt] Claim keys are the item's first-line text, so identical item text in two groups is indistinguishable (one claim hides both; a deletion is masked by the surviving twin) (source: codex) (introduced here) — dev/skills/task-next/scripts/backlog_candidates.py:item_keys

### PR #412 — task-next proceeds past other .worktrees/ on a clean base (2026-11-19)

- [ ] [harness] A preserved `--all` unit (`.worktrees/<slug>` on `wt/<slug>`) writes no `## Covers` and prunes no backlog line, so the clean-base gate skips past it while Step 1 still offers its item (source: code-review) (introduced here) — dev/skills/task-next/references/batch.md → unit worktrees
- [ ] [harness] A default run routed through exit 3's *Worktree cycle* claims nothing until cleanup (one item writes no `tasks.md`; a group writes `## Covers` after the plan gate), so a clean-base session can pick the same item (source: code-review) — dev/skills/task-next/references/cycle.md → Worktree cycle

### PR #413 — task-next --tree selects from origin/HEAD whatever the main checkout holds (2026-11-19)

- [ ] [harness] Under `--tree`, *Prerequisites* stops on a `backlog.md` missing from this checkout before looking at the base commit, which may still hold one (source: codex) (introduced here) — dev/skills/task-next/SKILL.md → Prerequisites
- [ ] [harness] Under `--tree`, an all-blocked Step 2 deletes a landed blocked marker in this checkout and re-runs Step 1, which reads the base commit, so the item stays blocked (source: codex) (introduced here) — dev/skills/task-next/SKILL.md → Step 2
- [ ] [harness] merge-and-cleanup.sh fast-forwards a main checkout on base after a worktree merge without a clean check, so a dirty checkout `--tree` announced as left as is can still move (source: codex) — dev/skills/task-review-cycle/scripts/merge-and-cleanup.sh:116
- [ ] [debt] `--ref` maps the queue path through `realpath`, so a symlinked backlog.md/tasks.md is looked up at the ref as its link target (source: codex) (introduced here) — dev/skills/task-next/scripts/backlog_candidates.py:_read_at_ref
- [ ] [constraint] No test pins utf-8 decoding of `git show` queue output; Linux CI's utf-8 locale cannot catch a cp949 regression (source: codex) (introduced here) — dev/skills/task-next/scripts/backlog_candidates.py:_git

### PR #415 — pre_merge_resync EOLs/suffixes/CWD; comment rules (2026-11-20)

- [ ] [debt] Script-dir resolution `$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)` prints two paths under an exported `CDPATH` when run by a relative path; clear `CDPATH` for that `cd` in every task-review-cycle script (source: codex) — dev/skills/task-review-cycle/scripts/claude-review.sh:44

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
