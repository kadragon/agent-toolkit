# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Dispatch — result and send robustness (2026-11-23)

- [ ] [feat] Home-configured handoff lines for `launch`. KNUE repos need the same line in every Codex child's first message ("외부 리뷰 승인: Codex·Claude 허용, agy 제외"), or Codex's auto-approval reviewer refuses task-review's diff egress mid-cycle; the home session forgot it on 2026-11-23 and a child stopped to ask. Let the home repo declare extra handoff lines per repo path prefix (e.g. a file next to `repos/*.md`) that `launch` appends after the verbatim fields. Done-when: a launch into a matching repo carries the configured line without the home session typing it — dev/skills/dispatch/scripts/dispatch.py

## 1 — Dispatch child stop reasons

- [ ] [FEAT] Report why a child stopped or stalled in one line from `dispatch collect` so the home session can act without reading the terminal itself.
  Source: [orca-orchestration-kit changelog](https://github.com/newrise0410/orca-orchestration-kit), `status.py --stall` (v0.8.3–v0.8.5).
  Done when: `test_dispatch.py` covers one-line reports for all five cases: usage limit, safety or usage-policy filter, error, waiting for a dialog, and no new turn or commit for N minutes.
  Approach: Use child status and activity in `dispatch.py`, including the terminal screen for Codex filter notices that are absent from the transcript.

## 2 — Dispatch scope decisions after repeated review findings

- [ ] [HARNESS] Check for a shared blocking finding category across two consecutive review send-backs on the same change before dispatch escalates the model.
  Source: [orca-orchestration-kit changelog](https://github.com/newrise0410/orca-orchestration-kit), v0.9.0 lesson L-22.
  Done when: Two consecutive send-backs sharing a category prompt the user to narrow or explicitly bound the guarantees and exclusions, and dispatch pauses model escalation pending that decision. Two send-backs with distinct categories follow the existing escalation path.
  Approach: Include a category for each blocking finding in task-review output and apply the comparison in `dev/skills/dispatch/references/escalation.md`.

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
