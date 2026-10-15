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

### PR #324 — commit-guard expansion, case arm, function body (2026-10-15)

- [ ] [FIX] commit-guard does not see a commit inside a command-position substitution: `$(git commit -m wip)` exits 0 from `main` while bash runs the commit — `_command_start` steps over the `$( … )` body without reading it; predates PR #324 (source: code-review) — dev/hooks/commit-guard/guard.py `_command_start`
- [ ] [FIX] commit-guard loses a commit behind a substitution that `_split_segments` splits: `x=$(true; echo) git commit`, `x=$(a | b) git commit`, ``x=`true; echo` git commit`` exit 0 from `main` — a `;`, `|` or case `)` inside an unquoted `$( … )` or backticks still ends the segment, so the closing `)` lands in the next one; predates PR #324 (source: code-review) — dev/hooks/commit-guard/guard.py `_split_segments`
- [ ] [FIX] commit-guard misses a commit behind a double-quoted empty expansion, `"$x"git commit -m wip`: `_strip_expansions` reads only unquoted expansions; predates PR #324 (source: code-review) — dev/hooks/commit-guard/guard.py `_strip_expansions`
- [ ] [FIX] commit-guard does not see a branch switch or `cd` behind an expansion: `git checkout -b feat && $x git checkout main && git commit -m '[FIX] x'` credits `feat` while bash commits on `main`; `_bare_switch_target`, `_is_unmodeled_git_segment` and the `cd` tracking read no expansions, and reading them must not let `$x git checkout feature/y` unblock a commit; predates PR #324 (source: code-review) — dev/hooks/commit-guard/guard.py `main`
- [ ] [debt] an extglob case pattern `@(a|x))` ends at its inner `)` in `_scan`, so the arm's commit is read as text: track paren depth for `[?*+@!](` groups in `case_pat`; predates PR #324 (source: code-review) — dev/hooks/commit-guard/guard.py `_scan`

### PR #313 — mods status band above the prompt (2026-10-11)

- [ ] [constraint] the band's on-screen look (colors, truncation, the engine's `[-]` mark, wide-character row counts) is checked by mount tests only; nobody has looked at it in a live terminal (source: contract) — mods/hooks/band.tsx *(deferred: needs a person to look at the band in a live terminal; an agent session cannot see it — delete this line once someone has)*

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*

## mods — follow-ups

- [ ] [CONSTRAINT] Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml` — today both are a local gate only (`docs/runbook.md` → Validate); `check_test_suites_wired.py` lists only `*.py` suites, so it reports all suites wired while the mods `*.test.ts(x)` files run in no job — extend it in the same change; first settle how CI installs a pinned `claude` CLI and whether `plugin test` runs unauthenticated *(deferred: user chose local evidence for V1 on 2026-10-11)*
