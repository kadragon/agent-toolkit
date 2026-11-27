# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## 1 — queue backend contract and resolver

- [ ] [FEAT] Add `task-next/scripts/queue_backend.py` (resolver + contract v1 framing) and `references/queue-backend-contract.md`; the built-in `backlog` backend maps `backlog_candidates.py` output onto the contract and adds `show` and `rejected` readers, so selection is unchanged everywhere
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Backend resolution, Backend contract (version 1)
  Done when: `python3 dev/skills/task-next/scripts/queue_backend.py --test` passes — resolver order (env, github.com host, open `backlog.md` items keep `backlog`, user registry, fallback), exit codes 0/1/2, `create` → `edit_file` on `backlog`, `backlog` `list` matching `backlog_candidates.py --json --counts` after the documented mapping (same titles, order, open-item counts) and honoring `ref`/`tasks`, `show` and `rejected` on fixtures, a fixture adapter plugged in through the registry; the test step is wired in `harness-check.yml`
  Approach: stdlib-only CLI `<op>` + JSON stdin/stdout; `github` resolves but returns exit 2 for every op until ticket 2

## 2 — github backend read path

- [ ] [FEAT] Implement `describe`, `list` and `show` for the `github` backend: `task-queue` label + author-association trust gate, parent/sub-issue groups, sub-issue eligibility (sub-issues never standalone), blocked/deferred parking, and the three claim sources with `origin/HEAD` resolved as `dispatch.py` does *(blocked by: 1-queue-backend-contract-and-resolver)*
  Source: docs/design/github-issues-queue.md → Implementation Decisions → GitHub mapping
  Done when: `queue_backend.py --test` covers each mapping rule against recorded `gh api graphql` JSON fixtures through an injectable runner (no network); a live read-only `list` with `AGENT_QUEUE_BACKEND=github` against `kadragon/knue-pic` runs (zero candidates expected before migration)
  Approach: GraphQL over issues, labels, blockedBy, subIssues, closedByPullRequestsReferences, paging every connection selection depends on and reporting an incomplete result (never an empty queue) at a page limit; hard error when `gh` is missing or unauthenticated, never a `backlog.md` fallback

## 3 — dispatch pick via queue backend

- [ ] [FEAT] Switch `dispatch.py pick` to `queue_backend.py list` and make its "no backlog.md: no queue" check and `dispatch/SKILL.md` wording backend-aware *(blocked by: 2-github-backend-read-path)*
  Source: docs/design/github-issues-queue.md → Script and doc surface per backend
  Done when: `python3 dev/skills/dispatch/scripts/test_dispatch.py` passes with new cases for a GitHub repo without `backlog.md` (issues listed) and a non-GitHub repo (unchanged output); warnings reach stderr
  Approach: keep the JSON shape `pick` prints today; `--tree` passes `ref: origin/HEAD` in the `list` request, which `backlog` honors and `github` ignores

## 4 — task-next selection and closing on issues

- [ ] [FEAT] Run `task-next` selection through `queue_backend.py`, record covered refs in `## Covers`, skip `prune-backlog` and blocked-marker sync on the issues backend, and have the review cycle write one closing line per ref into the PR body and merge commit *(blocked by: 2-github-backend-read-path)*
  Source: docs/design/github-issues-queue.md → Implementation Decisions → GitHub mapping (Claim, Completion); Script and doc surface per backend
  Done when: `task-next/SKILL.md`, `references/cycle.md`, `tree.md`, `batch.md`, `edge-cases.md` and `task-review-cycle` read backend-neutral with an issues branch; `backlog`-backend prose and `backlog_candidates.py --test` unchanged; a dry-run walkthrough on a GitHub fixture repo shows selection → `## Covers` refs → PR body `Closes #N`
  Approach: `--ref BASE_SHA` is passed as `list` `ref` (pins the file queue on `backlog`, the branch base on both); a parent covers its eligible sub-issues, and its own ref joins `## Covers` only when every open sub-issue is covered

## 5 — github backend writes and task-tickets

- [ ] [FEAT] Implement `create`, `rejected`, `reject` and `defer` for the `github` backend, the standing `queue-write` grant and the `no-queue-write` limit in `git-authorization.md`, the failure-path pending store with `queue_backend.py publish`, and switch `task-tickets` to file one issue per ticket with dependencies *(blocked by: 2-github-backend-read-path)*
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Backend contract, GitHub mapping (Blocked by, Rejected), Writers and authority
  Done when: `queue_backend.py --test` covers batch-key dependencies, retry-safe `create` (`queue-key` body marker reuse on a lost response, missing relations completed, `incomplete[]` kept pending), label bootstrap, closed-not-planned listing, and pending store write/publish under the git common dir on the failure path only (`gh` failing mid-write, `no-queue-write`); `task-tickets/SKILL.md` files issues on `github` with no per-run approval, in attended and unattended runs alike, and keeps the `backlog.md` path on `edit_file`; no working-tree change results from a `github` `create`
  Approach: `addBlockedBy`/`addSubIssue` mutations; Git limits never restrict `queue-write`; only on failure do drafts go to `$(git rev-parse --git-common-dir)/agent-queue/pending.json`

## 6 — findings writers on queue backend

- [ ] [FEAT] Route every findings writer through `queue_backend.py create`/`rejected`: `task-review-cycle` (parent + sub-issues for ≥2 findings, draft security advisory for a `security` finding on a public repo), `harness-capture`, `test-prune`, `repo-architecture`, `reference-review`, `harness-init/scripts/sweep.sh` *(blocked by: 5-github-backend-writes-and-task-tickets)*
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Writers and authority, Security findings
  Done when: each writer's prose names the backend call and keeps the `edit_file` path verbatim for `backlog`; on `github` every writer files without per-run approval, including `--auto`, dispatched and unattended runs (`harness-capture` deltas and deferred memory prunes included), and uses the pending store only on the failure path; a security finding on a `public` backend is never written to an issue or file; the advisory call is exercised once on a private test repo or recorded as unverified
  Approach: `consolidation-guide.md` → *Recording out-of-scope and non-blocking findings* becomes backend-neutral; the rejected check reads `rejected`

## 7 — security-overview on issues backend

- [ ] [FEAT] Make `dev/commands/security-overview.md` backend-aware: report-only (alert numbers, no queue write) on a public GitHub repo; one `security`-labelled issue per alert with a hidden `gh-alert` marker on a private one; `backlog.md` path unchanged elsewhere *(blocked by: 5-github-backend-writes-and-task-tickets)*
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Security findings
  Done when: the command and `references/security-overview/backlog-template.md` state the three routes; a rescan on a private fixture creates nothing already marked; a run on a public repo writes nothing
  Approach: visibility from `describe`; idempotency by body marker search instead of the backlog section replace

## 8 — task-new routing on issues backend

- [ ] [FEAT] Update `task-new` routing: on the issues backend, *Queue without implementing* calls `task-tickets`, which files issues directly under the standing `queue-write` grant, with no *Queue documentation cycle* and no commit-authority check, and the working-tree gate's `backlog.md` carve-out and `queue_delta` apply only on the `backlog` backend *(blocked by: 4-task-next-selection-and-closing-on-issues)* *(blocked by: 5-github-backend-writes-and-task-tickets)*
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Writers and authority
  Done when: `task-new/SKILL.md` and `task-next/SKILL.md` → *Working tree gate* read correctly for both backends; `docs/design/` stays carried; the `task-new`/`task-next` workflow eval cases updated for the issues route
  Approach: backend from `queue_backend.py describe`; parallel-worktree queue-edit blocker applies only to `backlog`

## 9 — harness-init and validators backend split

- [ ] [HARNESS] Split the harness tooling by backend: `reconcile-harness.py` skips its `backlog.md` writes, `validate-harness.sh` §9 expects no `backlog.md` on a GitHub origin and warns with the migration pointer on open items, `check_plugin_contracts.py` backlog-history skips the issues backend, and the harness-init templates and `harness-invariants.md` *Reconciliation Contract* state the split *(blocked by: 4-task-next-selection-and-closing-on-issues)*
  Source: docs/design/github-issues-queue.md → Script and doc surface per backend
  Done when: `test_reconcile_harness.py`, `test_validate_harness.py`, `check_plugin_contracts.py --test` and `scripts/ci/test_check_harness_drift.py` pass with new GitHub-origin cases; `validate-harness.sh` and `check_harness_drift.py` green on this repo
  Approach: backend from `queue_backend.py describe` (shell callers use its exit/JSON); `check_harness_drift.py` only if new prose trips it

## 10 — backlog migration script and knue-pic pilot

- [ ] [FEAT] Add `task-next/scripts/migrate_backlog.py` (dry-run default, `--apply` under the standing `queue-write` grant, `backlog-migrated` create keys, public-repo security refusal, and the "stays on the file queue until you run migrate_backlog.py" warning on github.com repos with open items) and pilot it on `../knue-pic` *(blocked by: 4-task-next-selection-and-closing-on-issues)* *(blocked by: 5-github-backend-writes-and-task-tickets)*
  Source: docs/design/github-issues-queue.md → Implementation Decisions → Migration; Testing Decisions
  Done when: `migrate_backlog.py --test` passes (groups, blockers, deferred, rejected, security refusal, re-run reuse, a partial run keeps every line whose issue or relation is unconfirmed, the warning) and is wired in `harness-check.yml`; the knue-pic dry-run plan is checked against the source `backlog.md` before `--apply` (a mapping check, not an authority gate), and one knue-pic `task-next --tree` cycle closes an issue through its PR
  Approach: reuse `backlog_candidates.py` tokenizer; `--apply` deletes only confirmed lines and leaves the `backlog.md` change for the user to commit

## 11 — adopt issues queue in agent-toolkit

- [ ] [PLAN] Migrate this repo's own `backlog.md` (Rejected entries → closed-not-planned issues) with `migrate_backlog.py`, and update `AGENTS.md`, `docs/architecture.md`, `docs/workflows.md` and `docs/conventions.md` lines that name `backlog.md` as the queue *(blocked by: 6-findings-writers-on-queue-backend)* *(blocked by: 7-security-overview-on-issues-backend)* *(blocked by: 8-task-new-routing-on-issues-backend)* *(blocked by: 9-harness-init-and-validators-backend-split)* *(blocked by: 10-backlog-migration-script-and-knue-pic-pilot)*
  Source: docs/design/github-issues-queue.md → Further Notes (Bootstrap)
  Done when: `queue_backend.py list` on this repo shows no legacy-backlog warning; the rejected entries are listed by `rejected`; `validate-harness.sh` green
  Approach: dry-run first, then `--apply`

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
