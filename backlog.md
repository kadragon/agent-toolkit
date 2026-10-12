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

### PR #320 — commit-guard comment and line-end operator (2026-10-12)

- [ ] [FIX] commit-guard does not see a commit behind a shell keyword or a leading redirect: `if true; then git commit -m 'wip'; fi`, `for f in a; do git commit -m 'wip'; done` and `>log git commit -m 'wip'` exit 0 from `main` — `_is_git_commit` wants `git` as the first word after `command`/`exec`; predates this PR (source: code-review) — dev/hooks/commit-guard/guard.py `_is_git_commit`
- [ ] [FIX] commit-guard parses a heredoc body as commands: an apostrophe in the body (`Don't panic`) fuses every later line into one segment and hides a commit after the heredoc, and a body line reading `git commit -m "wip"` false-blocks — since this PR also when it follows a `#` body line, which used to swallow it (source: code-review) — dev/hooks/commit-guard/guard.py `_split_segments`
- [ ] [debt] commit-guard keeps four hand-rolled quote scanners (`_strip_comments`, the newline pass in `_split_segments`, `_outside_quotes`, `_has_expandable_subst`) that disagree on escapes, and none follows a quote nested in `"$( … )"`: `echo "$(echo "x #")"; git commit -m 'wip'` exits 0 from `main`; predates this PR (source: code-review) — dev/hooks/commit-guard/guard.py

### PR #313 — mods status band above the prompt (2026-10-11)

- [ ] [constraint] the band's on-screen look (colors, truncation, the engine's `[-]` mark, wide-character row counts) is checked by mount tests only; nobody has looked at it in a live terminal (source: contract) — mods/hooks/band.tsx

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*

## mods — follow-ups

- [ ] [CONSTRAINT] Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml` — today both are a local gate only (`docs/runbook.md` → Validate); `check_test_suites_wired.py` lists only `*.py` suites, so it reports all suites wired while the mods `*.test.ts(x)` files run in no job — extend it in the same change; first settle how CI installs a pinned `claude` CLI and whether `plugin test` runs unauthenticated *(deferred: user chose local evidence for V1 on 2026-10-11)*
