# Backlog

## 5. P2 — subagent-model-selection-evaluation

Source: `docs/design/harness-policy-alignment.md` → Implementation Decisions, slice 5 and Testing Decisions. Read the paired-run protocol before launching agents; keep the existing headless review-effort experiment separate.

- [ ] [HARNESS] Evaluate approximately 10–20 representative delegated tasks against current settings using paired inputs/criteria: Claude per-spawn overrides and Codex unpinned evaluation roles or built-ins; record requested/actual settings, client/default/forced context, quality, retries, lead review, elapsed time, tokens and measured or explicitly estimated cost; recommend role-specific keep/change/unverified outcomes without removing production pins. Read `docs/design/harness-policy-alignment.md`, slice 5, before forming the contract.

Acceptance: preregister 10–20 task IDs total, finite attempts/time/cost-token budgets per platform, observation methods and benefit thresholds; setting-unverified runs cannot support model-effect claims; recommendations meet the design's paired-input/repeat/quality evidence bars and include total retry/review cost; unfinished platforms remain unverified and pin changes require a follow-up. Approach: staged platform runs using existing evaluation conventions and evaluation-only selection reasons; no permanent telemetry or reviewer-process changes.

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Harness — review effort follow-up

- [ ] [harness] task-review-cycle: measure `EFFORT=high` vs default (and `low`) on a security plant buried in a large, mostly benign diff — f1–f7 (`dev/skills/task-review-cycle/evals/security-effort/RESULTS.md`) are ≤9-line diffs that hit a recall ceiling twice; record the resolved model ID per run (source: code-review PR #298)

## Review Backlog

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*
