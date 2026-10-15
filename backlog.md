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

### commit-guard substitutions + HWPX cellAddr order follow-ups (2026-10-15)

- [ ] [FIX] commit-guard does not read a backtick substitution inside double quotes, ``echo "`git commit -m wip`"`` (exits 0 from `main`), nor a `$( … )` in a heredoc body under an unquoted delimiter: `_scan`'s `double` and `bodies` mark both as text, so `_split_full` records no body for them (source: integration-check; pre-existing) — dev/hooks/commit-guard/guard.py `_scan`
- [ ] [debt] `table.py insert`/`delete` still need `colAddr` before `rowAddr` and `colSpan` before `rowSpan`: `CELL_RE` and `TRIPLET_RE` skip a reordered cell, so `delete` neither refuses its rowSpan>1 anchor nor shrinks its span; only the readers `_own_cell_addr`/`_cell_span` were made order-free (source: integration-check; pre-existing) — prod/skills/hwpx/scripts/table.py `TRIPLET_RE`

### PR #313 — mods status band above the prompt (2026-10-11)

- [ ] [constraint] the band's on-screen look (colors, truncation, the engine's `[-]` mark, wide-character row counts) is checked by mount tests only; nobody has looked at it in a live terminal (source: contract) — mods/hooks/band.tsx *(deferred: needs a person to look at the band in a live terminal; an agent session cannot see it — delete this line once someone has)*

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*

## mods — follow-ups

- [ ] [CONSTRAINT] Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml` — today both are a local gate only (`docs/runbook.md` → Validate); `check_test_suites_wired.py` lists only `*.py` suites, so it reports all suites wired while the mods `*.test.ts(x)` files run in no job — extend it in the same change; first settle how CI installs a pinned `claude` CLI and whether `plugin test` runs unauthenticated *(deferred: user chose local evidence for V1 on 2026-10-11)*
