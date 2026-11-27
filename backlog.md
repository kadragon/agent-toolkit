# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## 11 — adopt issues queue in agent-toolkit

- [ ] [PLAN] Migrate this repo's own `backlog.md` (Rejected entries → closed-not-planned issues) with `migrate_backlog.py`, and update `AGENTS.md`, `docs/architecture.md`, `docs/workflows.md` and `docs/conventions.md` lines that name `backlog.md` as the queue, plus the same wording in `AGENTS.md`'s role table, `.claude/agents/implementer.md`, `docs/delegation.md` and `docs/invocation.md` → *Classification — `dev/`* *(blocked by: 3-dispatch-pick-via-queue-backend)*
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

### PR #473 — Add migrate_backlog.py to move a backlog.md queue onto GitHub issues (2026-11-27)

- [ ] [debt] A migration re-run reuses an issue by its `backlog-migrated` key without comparing bodies, so an item edited (e.g. its nested sub-bullets) between a partial run and the re-run is deleted while the issue keeps the old text; refresh or compare the body before deleting the line (source: codex) (introduced here) — dev/skills/task-next/scripts/migrate_backlog.py:apply_plan
- [ ] [debt] Two concurrent `create`/`publish`/migration runs can both miss a queue-key and file the same item twice; serialize the key lookup and filing under a lock in the git common dir (source: codex) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:_post_items
- [ ] [debt] `_registry_command` raises AttributeError (a traceback) when the registry's `hosts` is a non-empty array instead of an object; report a QueueError naming the registry path (source: codex) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:_registry_command
- [ ] [debt] Advisory comments pass on PR #473 asked to replace rationale comments in `migrate_backlog.py` with structure — rename `_prunable` → `_unprunable_reason`, `_heading_notes` → `_orphan_heading_prose`, return NamedTuples from `split_title`/`_resolve_blocker`, extract the refusal fixpoint as `_settle_refusals` — and to pin `_item_span` against `prune_lines` with a test; kept as comments under `--auto` (source: comments) (introduced here) — dev/skills/task-next/scripts/migrate_backlog.py

### PR #472 — Route security overview by repository visibility (2026-11-27)

- [ ] [debt] Serialize GitHub issue lookup and creation for concurrent queue writers sharing a Git common directory so two scans cannot file the same alert concurrently (source: codex) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:_post_items
- [ ] [debt] Include the target repository when indexing pending queue drafts so an origin change cannot replace a draft in another repository with the same key (source: codex) (pre_existing) — dev/skills/task-next/scripts/queue_backend.py:github_create
- [ ] [debt] Distinguish Code Scanning permission errors from a disabled feature before allowing zero-alert backlog cleanup (source: codex) (pre_existing) — dev/commands/security-overview/fetch-alerts.sh
- [ ] [debt] Keep existing legacy security backlog items for any alert type whose scan failed or was truncated before replacing the section (source: code-review) (pre_existing) — dev/commands/security-overview.md

### PR #475 — Route task-new queue-only requests through the selected backend (2026-11-27)

- [ ] [debt] Give task-new an exhaustive duplicate check covering claims, sub-issues, and incomplete GitHub candidate scans (source: codex) — dev/skills/task-new/SKILL.md:23 (introduced here)
- [ ] [debt] Check the ticket-writing checkout before authoring a multi-session spec so a known backend mismatch does not leave an unqueued design (source: codex) — dev/skills/task-new/SKILL.md:81 (introduced here)
- [ ] [debt] Make label bootstrap tolerate another queue writer creating a missing GitHub label between lookup and creation (source: codex) — dev/skills/task-next/scripts/queue_backend.py:856 (pre_existing)
- [ ] [debt] Clear the stale item 3 blocker from repository migration after verifying PR #466 merged (source: agy) — backlog.md:23 (pre_existing)

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
