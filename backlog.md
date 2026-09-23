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

### PR #278 — SessionStart nudge when a harness-curate run is due (2026-09-23)

- [ ] [debt] `record_run.py --check-due` counts only Claude transcripts, so a Codex-only repo never gets the curate nudge; count the project's date-partitioned Codex sessions too (`scan_transcripts.py` already locates them) (source: codex) — dev/skills/harness-curate/scripts/record_run.py:127

### PR #277 — review panel on by default for non-lite routes (2026-09-21)

- [ ] [constraint] Step 1's hub PR block calls `commit-and-push.sh --pr` without `--files`, so a dirty tree is auto-staged: PR #277 swept unrelated `.gitignore`/`.ignore` edits into a pushed commit (reverted in-branch). Pass the Step 1 file list, or make `--pr` reuse the existing commit when HEAD already holds the change (source: cycle) — dev/skills/task-review-cycle/SKILL.md:104

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*
- [ ] [DOCS] Close or annotate row 7 of `docs/design/task-graph-audit.md` — it still lists the `2-1 Agent-path review slot → SendMessage` gap as an open P0 and calls `claude-review.sh` the non-Claude fallback; PR #272 removed both *(deferred: audit doc, no runtime effect)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*

### Salvaged from `plan/security-hit-pattern` (branch deleted 2026-09-18)

- [ ] [HARNESS] `SECURITY_HIT` misses security-relevant hook files — the pattern in `dev/skills/task-review-cycle/references/risk-routing.md:15` (`auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment|\.github/workflows`) does not match `dev/hooks/commit-guard/guard.py` or `dev/hooks/memory-guard/guard.py`, so a change to a guard hook never raises `EFFORT="high"` and never forces the hub route. Add `hooks/.*guard` (and consider `dev/hooks/` generally) to the pattern. Originally filed 2026-07-04 against the old `dev-tools/hooks/commit-guard/` path; paths rewritten here. The companion item on the commit-guard `;`/newline false-block is already resolved by the in-chain branch attribution in `guard.py:751-787`.
