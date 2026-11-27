# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.


## 6 — findings writers on queue backend

- [ ] [FEAT] Route every findings writer through `queue_backend.py create`/`rejected`: `task-review-cycle` (parent + sub-issues for ≥2 findings, draft security advisory for a `security` finding on a public repo), `harness-capture`, `test-prune`, `repo-architecture`, `reference-review`, `harness-init/scripts/sweep.sh`
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Writers and authority, Security findings
  Done when: each writer's prose names the backend call and keeps the `edit_file` path verbatim for `backlog`; on `github` every writer files without per-run approval, including `--auto`, dispatched and unattended runs (`harness-capture` deltas and deferred memory prunes included), and uses the pending store only on the failure path; a security finding on a `public` backend is never written to an issue or file; the advisory call is exercised once on a private test repo or recorded as unverified; `task-review-cycle/references/comment-rules.md` (the two "file under `## Review Backlog`" rules) and `late-source-reclaim.md` (the `## Review Backlog` note) are backend-neutral too
  Approach: `consolidation-guide.md` → *Recording out-of-scope and non-blocking findings* becomes backend-neutral; the rejected check reads `rejected`

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

## 11 — adopt issues queue in agent-toolkit

- [ ] [PLAN] Migrate this repo's own `backlog.md` (Rejected entries → closed-not-planned issues) with `migrate_backlog.py`, and update `AGENTS.md`, `docs/architecture.md`, `docs/workflows.md` and `docs/conventions.md` lines that name `backlog.md` as the queue, plus the same wording in `AGENTS.md`'s role table, `.claude/agents/implementer.md`, `docs/delegation.md` and `docs/invocation.md` → *Classification — `dev/`* *(blocked by: 3-dispatch-pick-via-queue-backend)* *(blocked by: 6-findings-writers-on-queue-backend)* *(blocked by: 7-security-overview-on-issues-backend)* *(blocked by: 8-task-new-routing-on-issues-backend)* *(blocked by: 9-harness-init-and-validators-backend-split)*
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

### PR #473 — Add migrate_backlog.py to move a backlog.md queue onto GitHub issues (2026-11-27)

- [ ] [debt] A migration re-run reuses an issue by its `backlog-migrated` key without comparing bodies, so an item edited (e.g. its nested sub-bullets) between a partial run and the re-run is deleted while the issue keeps the old text; refresh or compare the body before deleting the line (source: codex) (introduced here) — dev/skills/task-next/scripts/migrate_backlog.py:apply_plan
- [ ] [debt] Two concurrent `create`/`publish`/migration runs can both miss a queue-key and file the same item twice; serialize the key lookup and filing under a lock in the git common dir (source: codex) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:_post_items
- [ ] [debt] `_registry_command` raises AttributeError (a traceback) when the registry's `hosts` is a non-empty array instead of an object; report a QueueError naming the registry path (source: codex) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:_registry_command
- [ ] [debt] Advisory comments pass on PR #473 asked to replace rationale comments in `migrate_backlog.py` with structure — rename `_prunable` → `_unprunable_reason`, `_heading_notes` → `_orphan_heading_prose`, return NamedTuples from `split_title`/`_resolve_blocker`, extract the refusal fixpoint as `_settle_refusals` — and to pin `_item_span` against `prune_lines` with a test; kept as comments under `--auto` (source: comments) (introduced here) — dev/skills/task-next/scripts/migrate_backlog.py

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
