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

### PR #391 — task_nodes branch exits 3 on an in-flight checkout; cycle.md runs that cycle in a worktree (2026-11-14)

- [ ] [harness] a squash-landed feature branch exits 0, so cycle.md's `git checkout -b` starts the new cycle from that stale HEAD and misses later base commits; branch from the confirmed base, or route it through the worktree (source: codex panel, claude review) (introduced here) — dev/skills/task-next/scripts/task_nodes.py `in_flight_status`
- [ ] [harness] `in_flight_status` is now a gate but still fails open: a failed or timed-out `rev-list`/`status` (e.g. origin/HEAD pointing at a pruned origin/master) returns 0 and `checkout -b` runs in place; fail closed once a base resolves (source: claude review) (introduced here) — dev/skills/task-next/scripts/task_nodes.py `in_flight_status`
- [ ] [harness] tree.md ignores `branch`'s exit status: on exit 3 it continues and then tells the agent to switch to main, contradicting the warning; handle rc (stop with the cycle.md pointer) (source: claude review) (introduced here) — dev/skills/task-next/references/tree.md → *Modified Branch step*
- [ ] [harness] the exit-3 worktree flow depends on `merge-and-cleanup.sh` running from inside the worktree; issued from the in-flight checkout it checks out the base there; say the call must be `cd`-prefixed, or make the script refuse a non-worktree cwd when `worktree_path` is given (source: claude review) (introduced here) — dev/skills/task-next/references/cycle.md → *Branch*
- [ ] [debt] in-flight follow-ups: (a) on the base name, unpushed commits ahead of origin/<base> read as safe and ride into the new branch; (b) the exit-3 block has no recovery when `$BRANCH` already exists from a partial run (tree.md's delete-first note); (c) untracked files alone count as dirty — use `--untracked-files=no`; (d) the squash self-test assumes `merge-tree --write-tree` (git ≥2.38) — skip it on older git; (e) CHANGELOG entry names dev only, not mods v0.9.2 (source: claude review, agy panel) (introduced here) — dev/skills/task-next/scripts/task_nodes.py, dev/skills/task-next/references/cycle.md, CHANGELOG.md

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
