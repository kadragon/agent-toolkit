# Backlog

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

### PR #300 — Re-qualify context-pointer WARNs (2026-10-05)

- [ ] [constraint] check_harness_drift `resolve_line_target` returns no problem for an unresolved bare sibling `*.md` name inside `references/*.md`, so the `references/x.md` → `x.md` rewrites lost the fail-closed rename check (`references/` prefix only) — make an unresolved bare sibling name in a references/ doc an error (source: code-review) — scripts/ci/check_harness_drift.py:868
- [ ] [doc] hwpx heading `## Workflow 2 (unpack → Edit → pack) caution` is still a SKILL.md-relative pointer; `check_context_pointers` skips `#` lines — qualify as SKILL.md Workflow 2 if no anchor depends on it (source: code-review) — prod/skills/hwpx/references/xml-integrity.md:95

### PR #290 — task-grill skill-extraction interview slots (2026-10-02)

- [ ] [harness] No consumer carries the `Skill slots:` block: neither the Sprint Contract template (`docs/eval-criteria.md`) nor the task-spec template has a field for it, and no skill-authoring route (harness-capture/harness-curate → `skill-creator`) invokes task-grill first; caller wiring was deferred by user decision (source: code-review) — dev/skills/task-grill/SKILL.md:80 *(deferred: caller wiring held by user decision; excluded again from the 2026-10-02 batch)*

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*
