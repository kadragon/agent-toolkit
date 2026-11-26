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

### PR #445 — Slim the status band to a context percent and one figure row (2026-11-26)

- [ ] [debt] Record the cache owner from the step's own model, not a later `$.session.model()` read: a switch between response end and that read tags A's expiry as B's (source: codex) — mods/hooks/status-band/register.tsx:361 (pre_existing)
- [ ] [debt] In a narrow terminal the trailing `cache …` figure is cut first; pass the width and drop reset times before the cache (source: codex) — mods/hooks/status-band/register.tsx:422 (introduced here)
- [ ] [debt] Rename for meaning where comments were removed: `TICK_MS` from `MINUTE_MS`, `Live.hasSetup`, `loadCurate` (throttled background check), `resetSetup` (drops the session's curate verdict) (source: comments) — mods/hooks/status-band/register.tsx
- [ ] [debt] Type the unreadable-settings case in the test `World` (e.g. `settings: Record<string, unknown> | 'unreadable'`) (source: comments) — mods/hooks/status-band/register.test.tsx:47
- [ ] [constraint] Fail `scripts/check_mods.py` when `mods/hooks/status-band/count.ts` imports from `claude-code`, then drop its header rule (source: comments) — mods/hooks/status-band/count.ts:1

### PR #447 — Relax dispatch weekly quota pace (2026-11-26)

- [ ] [debt] Treat Claude quota snapshots with missing required fields as unknown so Codex assessment still runs (source: codex) — `dev/skills/dispatch/scripts/quota.py:102` (pre_existing)

### PR #452 — Harden review-recall runs and fingerprint coverage (2026-11-26)

- [ ] [harness] Treat a failing fallback `git diff` in `agy-review.sh` as an error, not an empty diff, so only a successful empty comparison skips the review (source: codex) — `dev/skills/task-review-cycle/scripts/agy-review.sh:21` (pre_existing)
- [ ] [harness] Add `preflight.sh` to the recall fingerprint inputs, since it picks the Codex mode and companion path `run.sh` runs (source: codex) — `dev/skills/task-review-cycle/evals/review-recall/check-results.sh:9` (pre_existing)
- [ ] [debt] Name the code for the removed comments: a `claim_out_dir_lock` function in `run.sh`, a `BENCH_BRANCH` variable for the `bench` sidecar key, and a `require_commit_ref` guard in `agy-review.sh` (source: comments) — `dev/skills/task-review-cycle/evals/review-recall/run.sh:62`
- [ ] [harness] Trap `INT` and `TERM` in `run.sh` so a cancelled run stops its background fixtures and releases its lock (source: agy) — `dev/skills/task-review-cycle/evals/review-recall/run.sh:58` (introduced here)

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
