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

### PR #291 — review backlog batch: merge cleanup, curate nudge, PR staging, security floor (2026-10-02)

- [ ] [constraint] Step 1's dirty-tree commit (`commit-and-push.sh --no-push` without `--files`) still stages every changed/untracked file via changed-files.sh, so a stray edit present before Step 1 is committed and then pushed; `--no-commit` closed only the PR-push half of PR #277 (source: code-review) — dev/skills/task-review-cycle/SKILL.md:84
- [ ] [constraint] No test drives `hub.sh merge`'s GitHub remote-head delete (MERGED vs queued vs cross-repository); add a stub-`gh` case asserting when the refs DELETE fires (source: code-review) — dev/skills/task-review-cycle/scripts/hub.sh:311
- [ ] [constraint] Nothing mechanically keeps `--no-commit` on the hub PR block's `--pr` call; assert it where a test already parses SKILL.md's Step 1 bash (source: code-review) — dev/skills/task-review-cycle/SKILL.md:111

### PR #290 — task-grill skill-extraction interview slots (2026-10-02)

- [ ] [harness] No consumer carries the `Skill slots:` block: neither the Sprint Contract template (`docs/eval-criteria.md`) nor the task-spec template has a field for it, and no skill-authoring route (harness-capture/harness-curate → `skill-creator`) invokes task-grill first; caller wiring was deferred by user decision (source: code-review) — dev/skills/task-grill/SKILL.md:80 *(deferred: caller wiring held by user decision; excluded again from the 2026-10-02 batch)*

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*
- [ ] [DOCS] Close or annotate row 7 of `docs/design/task-graph-audit.md` — it still lists the `2-1 Agent-path review slot → SendMessage` gap as an open P0 and calls `claude-review.sh` the non-Claude fallback; PR #272 removed both *(deferred: audit doc, no runtime effect)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*
