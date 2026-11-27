# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## 7 — security-overview on issues backend

- [ ] [FEAT] Make `dev/commands/security-overview.md` backend-aware: report-only (alert numbers, no queue write) on a public GitHub repo; one `security`-labelled issue per alert with a hidden `gh-alert` marker on a private one; `backlog.md` path unchanged elsewhere
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Security findings
  Done when: the command and `references/security-overview/backlog-template.md` state the three routes; a rescan on a private fixture creates nothing already marked; a run on a public repo writes nothing; the command's `description:`, the `README.md` command row and `references/security-overview/api-patterns.md`'s "backlog.md severity" mapping no longer say alerts always go to `backlog.md`
  Approach: visibility from `describe`; idempotency by body marker search instead of the backlog section replace

## 8 — task-new routing on issues backend

- [ ] [FEAT] Update `task-new` routing: on the issues backend, *Queue without implementing* calls `task-tickets`, which files issues directly under the standing `queue-write` grant, with no *Queue documentation cycle* and no commit-authority check, and the working-tree gate's `backlog.md` carve-out and `queue_delta` apply only on the `backlog` backend
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Writers and authority
  Done when: `task-new/SKILL.md` and `task-next/SKILL.md` → *Working tree gate* read correctly for both backends; `docs/design/` stays carried; the `task-new`/`task-next` workflow eval cases updated for the issues route, and the `backlog.md` queries in `task-next`/`task-new` `evals/trigger-eval.json` gain an issues-queue counterpart
  Approach: backend from `queue_backend.py describe`; parallel-worktree queue-edit blocker applies only to `backlog`

## 9 — harness-init and validators backend split

- [ ] [HARNESS] Split the harness tooling by backend: `reconcile-harness.py` skips its `backlog.md` writes, `validate-harness.sh` §9 expects no `backlog.md` on a GitHub origin and warns with the migration pointer on open items, `check_plugin_contracts.py` backlog-history skips the issues backend, and the harness-init templates and `harness-invariants.md` *Reconciliation Contract* state the split
  Source: docs/design/github-issues-queue.md → Script and doc surface per backend
  Done when: `test_reconcile_harness.py`, `test_validate_harness.py`, `check_plugin_contracts.py --test` and `scripts/ci/test_check_harness_drift.py` pass with new GitHub-origin cases; `validate-harness.sh` and `check_harness_drift.py` green on this repo; the remaining harness-init prose states the split as well — `references/maintenance.md` ("`backlog.md` = the only persistent queue", the schema checks, the `Backlog: N queued` / `Backlog clear.` messages, the queue summary), `harness-init/SKILL.md` Step 4a, `maturity-levels.md`, `golden-principles-guide.md`, `architecture-template.md` — plus the `harness-curate/SKILL.md` `[x]` backlog-history line and the `session-start/harness-maintenance.sh` comment
  Approach: backend from `queue_backend.py describe` (shell callers use its exit/JSON); `check_harness_drift.py` only if new prose trips it

## 10 — backlog migration script and knue-pic pilot

- [ ] [FEAT] Add `task-next/scripts/migrate_backlog.py` (dry-run default, `--apply` under the standing `queue-write` grant, `backlog-migrated` create keys, public-repo security refusal, and the "stays on the file queue until you run migrate_backlog.py" warning on github.com repos with open items) and pilot it on `../knue-pic`
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Migration; Testing Decisions
  Done when: `migrate_backlog.py --test` passes (groups, blockers, deferred, rejected, security refusal, re-run reuse, a partial run keeps every line whose issue or relation is unconfirmed, the warning) and is wired in `harness-check.yml`; the knue-pic dry-run plan is checked against the source `backlog.md` before `--apply` (a mapping check, not an authority gate), and one knue-pic `task-next --tree` cycle closes an issue through its PR
  Approach: reuse `backlog_candidates.py` tokenizer; `--apply` deletes only confirmed lines and leaves the `backlog.md` change for the user to commit

## 11 — adopt issues queue in agent-toolkit

- [ ] [PLAN] Migrate this repo's own `backlog.md` (Rejected entries → closed-not-planned issues) with `migrate_backlog.py`, and update `AGENTS.md`, `docs/architecture.md`, `docs/workflows.md` and `docs/conventions.md` lines that name `backlog.md` as the queue, plus the same wording in `AGENTS.md`'s role table, `.claude/agents/implementer.md`, `docs/delegation.md` and `docs/invocation.md` → *Classification — `dev/`* *(blocked by: 3-dispatch-pick-via-queue-backend)* *(blocked by: 7-security-overview-on-issues-backend)* *(blocked by: 8-task-new-routing-on-issues-backend)* *(blocked by: 9-harness-init-and-validators-backend-split)* *(blocked by: 10-backlog-migration-script-and-knue-pic-pilot)*
  Source: docs/design/github-issues-queue.md → Further Notes (Bootstrap)
  Done when: `queue_backend.py list` on this repo shows no legacy-backlog warning; the rejected entries are listed by `rejected`; `validate-harness.sh` green
  Approach: dry-run first, then `--apply`

## Review Backlog

### PR #467 — Select task-next work through the queue backend and close covered issues from the PR (2026-11-27)

- [ ] [debt] On the issues backend, cleanup's `prune-tasks` deletes the worktree `## Covers` claim before the PR exists, so between cleanup and PR creation another run's `list` offers the same issue; add a claim source that survives cleanup (e.g. the worktree branch's archived refs) in `github_claims` (source: code-review) (introduced here) — dev/skills/task-next/scripts/queue_backend.py:564

### PR #468 — Add github queue writes, the queue-write grant and issue filing in task-tickets (2026-11-27)

- [ ] [debt] `key_index` and `github_rejected` walk every issue / closed `task-queue` issue (cap 100 pages of 100); past that every github `create` goes pending — look up only the batch's keys, or filter rejected by `reason:not-planned` search (source: code-review, agy) (introduced here) — dev/skills/task-next/scripts/queue_backend.py:key_index
- [ ] [debt] On a truncated github `list`, a parent's sub-issue on an unread page is excluded as "not a trusted task-queue issue" instead of "incomplete read", and the parent is still offered (source: agy) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:why_not
- [ ] [debt] `handle()` resolves the backend for `show`/`rejected` from the working tree, ignoring the request's `rev`, so a github.com repo whose `backlog.md` has open items only at `rev` queries GitHub instead (source: agy) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:handle

### PR #471 — Route findings writers through the queue backend (2026-11-27)

- [ ] [debt] Sweep quick mode exits 0 before reporting findings from an adapted lint check (source: codex) (pre_existing) — dev/skills/harness-init/scripts/sweep.sh:40

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
