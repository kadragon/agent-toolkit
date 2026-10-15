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

### PR #325 — HWPX content comparison (2026-10-15)

- [ ] [debt] `table.py replace` misses valid cells when `hp:cellAddr` serializes `rowAddr` before `colAddr`: `_own_cell_addr` requires the opposite attribute order, producing `cell colAddr=0 rowAddr=0 not found`; reproduced during the compare integration check, while the same cell with reordered attributes succeeds (source: integration-check; pre-existing) — prod/skills/hwpx/scripts/table.py:56

### PR #322 — commit-guard heredoc in arithmetic and ANSI-C quote after a pid (2026-10-15)

- [ ] [FIX] commit-guard allows a commit whose segment `shlex` cannot read: `git commit -m wip $'a\'b'` (a `$'…'` with an escaped quote, or a nested-quote token) makes `_tokens` return `[]` and fail open; a command word built by an expansion (`$()git commit`, `$!git commit`, `${x#a}<<EOF git commit`) also exits 0 from `main` while bash runs the commit — found by the bash-with-stub-git fuzz, 3 seeds, every miss present before PR #321 (source: contract) — dev/hooks/commit-guard/guard.py `_tokens`, `_command_start`
- [ ] [debt] a `case` pattern `)` inside `$( … )` closes the substitution early in `_scan`, so a heredoc announced later in it reaches past the real `)`: `x=$(case a in a) cat <<EOF;; esac)` then a `git commit` line; unverified on bash 5 (bash 3.2 rejects it) — fold into the PR #321 `case`-arm item (source: code-review) — dev/hooks/commit-guard/guard.py `_scan`

### PR #321 — commit-guard shell keyword, redirect and heredoc (2026-10-12)

- [ ] [FIX] commit-guard does not see a commit in a `case` arm or a function body: `case x in x) git commit -m 'wip';; esac` and `f() { git commit -m 'wip'; }; f` exit 0 from `main` — `_command_start` reads past keywords and redirects, not past a `pattern)` or a `name() {`; predates this PR (source: contract) — dev/hooks/commit-guard/guard.py `_command_start`

### PR #313 — mods status band above the prompt (2026-10-11)

- [ ] [constraint] the band's on-screen look (colors, truncation, the engine's `[-]` mark, wide-character row counts) is checked by mount tests only; nobody has looked at it in a live terminal (source: contract) — mods/hooks/band.tsx *(deferred: needs a person to look at the band in a live terminal; an agent session cannot see it — delete this line once someone has)*

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*

## mods — follow-ups

- [ ] [CONSTRAINT] Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml` — today both are a local gate only (`docs/runbook.md` → Validate); `check_test_suites_wired.py` lists only `*.py` suites, so it reports all suites wired while the mods `*.test.ts(x)` files run in no job — extend it in the same change; first settle how CI installs a pinned `claude` CLI and whether `plugin test` runs unauthenticated *(deferred: user chose local evidence for V1 on 2026-10-11)*
