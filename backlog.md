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

### PR #451 — Keep the cache countdown on narrow status bands and tidy the status-band mod (2026-11-26)

- [ ] [debt] The countdown a step writes behind it can land after a refresh forfeited that cache for a model switch, so the old model's `cache …` shows under the new one until the next tick: skip the write when `current.model` differs from the step's model (source: code-review, agy) — mods/hooks/status-band/register.tsx:358 (pre_existing)
- [ ] [debt] `covered` compares a project path and the working directory with `startsWith` without unifying `\\` and `/`, so `C:\work\repo` misses `C:/work/repo/src` and the user-scope install is read instead (source: codex) — mods/hooks/status-band/count.ts:12 (pre_existing)
- [ ] [debt] Rename for meaning where comments were removed: `widthOf` to carry the one-cell-per-character assumption, `room` in `timesSegments` to `cellsLeft`, `Live.isCurateOwned` to `hasSessionCurateVerdict` (source: comments) — mods/hooks/status-band/register.tsx:58

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
