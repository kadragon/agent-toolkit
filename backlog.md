# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Harness — skill diet (over-engineering / over-instruction for Claude 5)

Source: `docs/design/skill-diet-audit.md`. Removal only — no new gates, telemetry, or
rationale prose. Decisions resolved 2026-10-28: D1 keep PR #277 panel default; D2 cut harness-init Step 7b
to one line and drop its validator grep.

- [ ] **skill-diet-prod-and-meta** — Slice 5: persona-debate `debate-method.md` to why + template; repo-quiz `state-reference.md` mechanics; kr-style loop one line in gongmun Step 4 / report G2, dead `$LINT` block; harness-capture repo-specific text + `routing.md`; harness-curate 2nd/3rd copies; task-grill / task-spec triple copies (trigger check before touching grill description); `skill-evaluator` / `qa-verifier` no-ops (~250 lines)

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
