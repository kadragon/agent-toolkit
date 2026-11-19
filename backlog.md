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

### PR #411 — review cycle merges base into a PR behind it and re-bumps (2026-11-19)

- [ ] [debt] pre_merge_resync rewrites only single-plugin CHANGELOG suffixes; `(dev vX, mods vY)` entries keep the old numbers (source: codex) (introduced here) — dev/skills/task-review-cycle/scripts/pre_merge_resync.py:resync
- [ ] [debt] pre_merge_resync reads and writes via text mode, so a CRLF-tracked manifest or CHANGELOG is rewritten as LF (source: codex) (introduced here) — dev/skills/task-review-cycle/scripts/pre_merge_resync.py:set_version
- [ ] [debt] pre_merge_resync opens repo-relative paths from the CWD; run from a subdirectory it fails before writing (source: agy) (introduced here) — dev/skills/task-review-cycle/scripts/pre_merge_resync.py:resync

### PR #412 — task-next proceeds past other .worktrees/ on a clean base (2026-11-19)

- [ ] [harness] A preserved `--all` unit (`.worktrees/<slug>` on `wt/<slug>`) writes no `## Covers` and prunes no backlog line, so the clean-base gate skips past it while Step 1 still offers its item (source: code-review) (introduced here) — dev/skills/task-next/references/batch.md → unit worktrees
- [ ] [harness] A default run routed through exit 3's *Worktree cycle* claims nothing until cleanup (one item writes no `tasks.md`; a group writes `## Covers` after the plan gate), so a clean-base session can pick the same item (source: code-review) — dev/skills/task-next/references/cycle.md → Worktree cycle

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
