# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## 2 — collapse free tree

- [ ] [HARNESS] `--tree` runs the whole cycle in `.worktrees/<slug>` with no collapse; the main checkout is never edited or switched
  Source: docs/design/concurrent-tree-cycles.md → Implementation Decisions → Collapse-free `--tree`; `--tree` always takes the hub (PR) path; Implementer/QA boundary
  Done when: `tree.md` writes `tasks.md`, bump, CHANGELOG and cleanup in the worktree, has no collapse block, routes review to the hub path and passes `worktree_path` to `merge-and-cleanup.sh`; `tree.md` and `cycle.md` exit 3 share one worktree-cycle description → `bash dev/skills/harness-init/scripts/validate-harness.sh` + a manual `--tree` run leaving `git status` clean on base in the main checkout
  Approach: fold `tree.md` onto `cycle.md` → *Branch* exit 3's worktree rules; delete *Collapse after QA passes*

## 3 — pre merge resync

- [ ] [HARNESS] review cycle resyncs a PR behind base before merge: rebase, take base's version files, re-bump at the original level, re-insert CHANGELOG, force-with-lease, re-wait CI *(blocked by: 2-collapse-free-tree)*
  Source: docs/design/concurrent-tree-cycles.md → Implementation Decisions → Pre-merge resync (decision d)
  Done when: two branches bumping the same plugin both merge, the second at the next number with its CHANGELOG entry on that version; a non-version conflict stops with no push; force-push checks Git authority → new regression test wired as a `harness-check.yml` step
  Approach: scripted resync (new script or `task_nodes.py` subcommand) called from `task-review-cycle` hub path before `merge-and-cleanup.sh`; record the bump level where the resync can read it

## 4 — concurrent tree gate

- [ ] [HARNESS] working tree gate proceeds past other `.worktrees/` when the main checkout is clean on base, announcing them in one line; resume only on `--resume <slug>` or a named request *(blocked by: 2-collapse-free-tree)* *(blocked by: 3-pre-merge-resync)*
  Source: docs/design/concurrent-tree-cycles.md → Implementation Decisions → Gate relaxation; Explicit resume
  Done when: `task-next/SKILL.md` gate table splits the `task_worktree` row, `task_contract_dirty` row marked legacy, `edge-cases.md` *Work already in flight* resumes worktrees only on explicit request → `validate-harness.sh` + a manual run with a second worktree present
  Approach: edit the gate rows and edge-case prose; add `--resume` to task-next's flag list

## 5 — task new tree

- [ ] [HARNESS] `task-new --tree` runs the free-text cycle in a worktree even from base *(blocked by: 2-collapse-free-tree)*
  Source: docs/design/concurrent-tree-cycles.md → Implementation Decisions → `task-new --tree`
  Done when: `task-new/SKILL.md` accepts `--tree` and points to the shared worktree-cycle description; no `tasks.md` written → `validate-harness.sh` + a manual `task-new --tree` run
  Approach: one override line in task-new Step 3 → *Branch*

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
