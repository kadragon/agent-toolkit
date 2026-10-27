# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## 8 — task-next lean pass

- [ ] [HARNESS] task-next lean pass: replace repeated Git-authority and delegation-threshold restatements (cycle.md, SKILL.md, batch A2, tree.md, edge-cases.md) with one-line pointers to `git-authorization.md` / `docs/delegation.md`; drop the 0-count `--full-scan` row; `.worktrees/` ignore via `info/exclude` replaces the `.gitignore` snapshot/restore and dead `GITIGNORE_ADDED`; state that `--tree` is the user's explicit direction to delegate
  - Source: 2026-10-26 review, stage 2
  - Done when: `test_cycle_state.py` green; `grep GITIGNORE_ADDED` empty; net line count down

## 13 — test-prune ledger drop

- [ ] [HARNESS] test-prune ledger drop: remove the run ledger (`scripts/prune_ledger.py`, `references/run-ledger.md`, SKILL *Run ledger*) — 4 recorded runs, zero `carried_from` units; keep the clean-HEAD precondition as one inline `git status` check
  - Source: 2026-10-26 review, stage 4
  - Done when: `grep -rn prune_ledger dev .github` empty; SKILL.md still refuses a dirty tracked tree

## 14 — ci-wait stale-head strike

- [ ] [FIX] ci-wait.sh counts a stale head's failure as a strike: right after a push, while the new run is still queued, `hub.sh ci-status` (GitHub path: `gh pr checks`, not pinned to a SHA) returns the previous commit's `failure`, so one real failure is struck twice and the 3-strike `rework-cap` fires a round early; pin the status read to the pushed head SHA (the Forgejo path already reads `head.sha`) and treat checks for any other SHA as `pending`
  - Source: PR #362 review cycle — strike count 2 after 1 real CI failure
  - Done when: a `ci-wait.sh` regression test with a stale-SHA `failure` followed by a head-SHA `success` leaves the strike file unincremented and passes

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
