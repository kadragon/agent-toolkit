# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## 5 — evidence per command

- [ ] [FIX] cycle_state evidence per command: `evidence` keeps one record per command instead of overwriting; `inspect` treats a `None` tree as a mismatch
  - Source: 2026-10-26 review, stage 2
  - Done when: test — lint `--exit 1` then tests `--exit 0` → `inspect` still shows the failing lint record; `write-tree` failure → `tree_matches_current: false`

## 6 — batch unit outcomes

- [ ] [FIX] task-next batch unit outcomes: batch.md A5 records merged/excluded/conflicted units with `cycle_state.py note` on the integration branch; A6 runs `retire --branch wt/<slug>` for each landed unit
  - Source: 2026-10-26 review, stage 2
  - Done when: batch.md names both commands; edge-cases.md resume table has a parallel-run row reading the note

## 7 — base branch portability

- [ ] [FIX] task-next base branch portability: working-tree gate rows say base branch (`main`/`master`) everywhere and compute `task_worktree` unconditionally (clean base + worktree → in flight); tree.md resolves base from `origin/HEAD` and fast-forwards local base before `worktree add` (stop if not ff); task-new applies task-next's gate table as written instead of restating it
  - Source: 2026-10-26 review, stages 1–2
  - Done when: on a `master` repo the spec→tickets carry row matches; a clean base with a live `--tree` worktree reports in-flight

## 8 — task-next lean pass

- [ ] [HARNESS] task-next lean pass: replace repeated Git-authority and delegation-threshold restatements (cycle.md, SKILL.md, batch A2, tree.md, edge-cases.md) with one-line pointers to `git-authorization.md` / `docs/delegation.md`; drop the 0-count `--full-scan` row; `.worktrees/` ignore via `info/exclude` replaces the `.gitignore` snapshot/restore and dead `GITIGNORE_ADDED`; state that `--tree` is the user's explicit direction to delegate *(blocked by: 6-batch-unit-outcomes)* *(blocked by: 7-base-branch-portability)*
  - Source: 2026-10-26 review, stage 2
  - Done when: `test_cycle_state.py` green; `grep GITIGNORE_ADDED` empty; net line count down

## 9 — downstream portable references

- [ ] [HARNESS] downstream portable references: task-grill drops the `~/.claude/CLAUDE.md` "Grill" citation (no such rule); task-tickets cuts the `check_skill_triggers.py` rename rationale and gate restatement to one line each (reasoning moves to `docs/conventions.md`); edge-cases.md drops the "never-auto-default rule" sentence
  - Source: 2026-10-26 review, stages 1–2
  - Done when: no shipped skill text cites a repo-root-only script or the user-private CLAUDE.md as a rule source

## 10 — task-new tag and routing

- [ ] [FIX] task-new tag and routing: infer the tag from cycle.md's Sprint Contract Tag list (not 3 tags → untagged → `fix/`); check size before clarity in the routing rows; description mentions the spec + tickets route; route "queue without implementing" to task-tickets
  - Source: 2026-10-26 review, stage 1
  - Done when: a docs-only request yields `[DOCS]` and a `docs/` branch; trigger evals still pass

## 11 — task-tickets output shape

- [ ] [FIX] task-tickets output shape: write source citation, acceptance criteria and approach as indented lines under the item; blocked-by slug = words of the blocking ticket's heading in order; marker cleared by the blocking ticket's cycle (cycle.md *Cleanup*), not by hand; `/dev:task-next` form everywhere; task-spec review gate gets an unattended default row in harness-invariants.md; drop "phased list" from docs/workflows.md *plan*
  - Source: 2026-10-26 review, stage 1
  - Done when: `backlog_candidates.py --full-scan` folds the indented lines into one item; `prune-backlog` warns on a landed blocker written per the slug rule

## 12 — side loop hand backs

- [ ] [HARNESS] side loop hand backs: task-debug ends with a hand-back (repro command, regression test id, surviving hypothesis; inside a cycle add the test as a criterion and `cycle_state.py note` all three); test-prune appends Gaps / Production bugs rows to `backlog.md` (bugs name `dev:task-debug`) and replaces "the calling workflow" with "tell the user to run `/task-review` before other work"
  - Source: 2026-10-26 review, stage 4
  - Done when: both SKILL.md files state the return; test-prune report has a backlog destination

## 13 — test-prune ledger drop

- [ ] [HARNESS] test-prune ledger drop: remove the run ledger (`scripts/prune_ledger.py`, `references/run-ledger.md`, SKILL *Run ledger*) — 4 recorded runs, zero `carried_from` units; keep the clean-HEAD precondition as one inline `git status` check *(blocked by: 12-side-loop-hand-backs)*
  - Source: 2026-10-26 review, stage 4
  - Done when: `grep -rn prune_ledger dev .github` empty; SKILL.md still refuses a dirty tracked tree

## Review Backlog

### PR #357 — task-review-cycle lean pass (2026-10-26)

- [ ] [harness] `prune-backlog` deletes the checkbox line but leaves its nested `  - Source:` / `  - Done when:` sub-bullets and the emptied `##` heading; removed by hand in PR #357 and again in PR #358 (source: cycle) — dev/skills/task-next/scripts/task_nodes.py

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
