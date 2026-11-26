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

### PR #452 — Harden review-recall runs and fingerprint coverage (2026-11-26)

- [ ] [harness] Treat a failing fallback `git diff` in `agy-review.sh` as an error, not an empty diff, so only a successful empty comparison skips the review (source: codex) — `dev/skills/task-review-cycle/scripts/agy-review.sh:21` (pre_existing)
- [ ] [harness] Add `preflight.sh` to the recall fingerprint inputs, since it picks the Codex mode and companion path `run.sh` runs (source: codex) — `dev/skills/task-review-cycle/evals/review-recall/check-results.sh:9` (pre_existing)
- [ ] [debt] Name the code for the removed comments: a `claim_out_dir_lock` function in `run.sh`, a `BENCH_BRANCH` variable for the `bench` sidecar key, and a `require_commit_ref` guard in `agy-review.sh` (source: comments) — `dev/skills/task-review-cycle/evals/review-recall/run.sh:62`
- [ ] [harness] Trap `INT` and `TERM` in `run.sh` so a cancelled run stops its background fixtures and releases its lock (source: agy) — `dev/skills/task-review-cycle/evals/review-recall/run.sh:58` (introduced here)

### PR #454 — Skip a stale cache countdown after a model switch and match project paths across separators (2026-11-26)

- [ ] [debt] A narrow band drops only the reset times to fit the row, so with several windows the usage figures still push the cache countdown off a row that has room for it: keep dropping windows until the cache fits (source: codex) — mods/hooks/status-band/format.ts:183 (pre_existing)
- [ ] [debt] A step's effort is shown under whatever model the next refresh reads, so switching from Opus to Haiku right after a step shows Opus's effort before any Haiku step ran: store the model with the effort and keep it only for that model (source: codex) — mods/hooks/status-band/register.tsx:191 (pre_existing)
- [ ] [debt] `covered` compares paths case-sensitively, so on Windows `C:\work\repo` misses `c:/work/repo/src` and the user-scope install is read: compare Windows-style paths case-insensitively (source: code-review) — mods/hooks/status-band/count.ts:17 (pre_existing)
- [ ] [constraint] The band counts one terminal cell per character (`cellsByLength`): test that every glyph in `UNICODE` and the other `Glyphs` sets is one cell wide, then drop the comment on `cellsByLength` (source: comments) — mods/hooks/status-band/format.ts:139
- [ ] [debt] Name the model check for the removed comment: extract `cacheModel !== undefined && sessionModel !== '' && !isSameModel(...)` in the step hook into a predicate such as `ranUnderLeftModel` (source: comments) — mods/hooks/status-band/register.tsx:364
- [ ] [debt] Name the test gates for the removed comment: rename `World.nowGate` and `World.modelGate` to say they hold back only the next reading, e.g. `holdNextNow` and `holdNextModel` (source: comments) — mods/hooks/status-band/register.test.tsx:54

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
