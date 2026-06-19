# Backlog

## Now

## Next


## Someday

## History

### PR #51 — next-tasks debt batch (2026-06-14)

- [x] [debt] `dev-tools/hooks/failure-log/log.py:append_capped` — opened log + `.gitignore` with `os.O_NOFOLLOW`; pre-planted symlink now raises ELOOP (caught silently). (source: security-review PR #49, conf 40)
- [x] [debt] `dev-tools/hooks/failure-log/summarize.py:main` — `--help`/`-h` handled before path resolution; prints usage, no git_root lookup. (source: agy)
- [x] [debt] `status` → `codex_status` (zsh read-only special). (source: agy) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:30`
- [x] [debt] Empty `RAW` on companion crash → `WARN: codex companion exited %s with no stdout`. (source: review) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:33`
- [x] [debt] Three distinct jq fallback WARNs via `mktemp` stderr capture. (source: review, pr-review-toolkit:review-pr, agy) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:39-42`
- [x] [doc] Comment updated to include "jq parse failure" as fallback trigger. (source: pr-review-toolkit:review-pr)
- [x] [fix] `log.py:191` — `.gitignore` line boundary: existing content without trailing `\n` caused `keep*` corruption; prefix `\n` now added when needed. (source: codex — empirically proven)
- [x] [fix] `log.py:186,196` — `gi_fd`/`log_fd` fd leak guard: `try/except OSError: os.close(fd); raise` wraps `os.fdopen()` calls. (source: pr-review-toolkit:review-pr, conf 95)

### PR #48 — next-tasks batch (2026-06-12)

- [x] [harness] `harness-check.yml` — `OLD_CODEX` baseline added; all four divergence cases now emit distinct errors. (source: PR #35)
- [x] [doc] `docs/platform-specs.md` Codex example — added `"hooks": "./hooks.json"`. (source: PR #35)
- [x] [doc] `docs/platform-specs.md:126` — `"version": "3.0.7"` → `"version": "X.Y.Z"`. (source: PR #35)
- [x] [doc] `docs/platform-specs.md` Sources — all 5 URLs verified HTTP 200, no changes needed. (source: PR #35)
- [x] [spec] `loop-engineer` description — measured 590 chars, already under Codex 1024 limit; item was stale. (source: PR #43)
- [x] [debt] `dev-tools/hooks.json` — `:?` guard on `PLUGIN_ROOT`; both-unset now errors loudly. (source: tasks.md PR #47)
- [x] [debt] `validate-harness.sh:70` — `grep -Iq` exit 2 captured; unreadable file → `warn` + `continue`. (source: tasks.md PR #47)

### PR #36 — hwpx: Now-backlog debt (2026-06-09)

- [x] [debt] `validate.py` — `SECTION_N_RE as SECTION_RE` alias removed; renamed all 4 uses to `SECTION_N_RE`. (source: agy)
- [x] [debt] `validate.py:do_validate` — section bytes cached during parse loop; eliminated second `zf.read()` at line 175. (source: pr-review-toolkit:review-pr)
- [x] [fix] `build.py:cmd_analyze` — multi-section HWPX supported; enumerates all sections, loops for analysis + `--table-id` search. (source: pr-review-toolkit:review-pr)

### PR #33 — hwpx: port lxml → stdlib ET (2026-06-08)

- [x] [debt] Multi-section HWPX in `collect_metrics` — extracted `_collect_one_section`; enumerates all sections. (source: agy)
- [x] [debt] `_assert_int` used once — inlined `assert open_inner is not None`. (source: pr-review-toolkit)
- [x] [debt] `end or 0` silently swallowed bug — replaced with `assert end is not None`. (source: pr-review-toolkit)
- [x] [debt] `_validate_hwpx` lxml guard — moot, lxml removed in PR #33.

### PR #29 — dev-review-cycle cleanup (2026-06-07)

- [x] [debt] releases API fetched wrong repo — added dep_repo resolution step.
- [x] [debt] jq body filter uncapped — capped at 500 chars.

### PR #28 — harness-curator (2026-06-07)

- [x] [harness] `[HARNESS]` vs `[FIX]` commit type clarification (retro, no file change).

### PR #26 — harness-curator agent analysis (2026-06-04)

- [x] [debt] scanner `PROJECT_CAP` + `PROMPT_CAP`/`CORRECTION_CAP` added. (source: codex)
- [x] [debt] `--project` arg parsing fixed for paths with spaces.

### PR #24 — task-audit + staleness nudge (2026-06-03)

- [x] [debt] `sort -rV` fallback for lexicographic ordering. (source: code-review)
- [x] [debt] jq in loop → accumulate as text, build JSON once.
- [x] [debt] dead code fallback removed from SKILL.md.

### PR #17 — split marketplace (2026-05-29)

- [x] [doc] Migration note `toolkit:harness-maintenance` → `dev-tools:harness-maintenance`.
- [x] [debt] `validate_hwpx` broadened to `except (BadZipFile, OSError)`.
- [x] [debt] `validate-harness.sh` section 6b grep comment narrowed.

### PR #13 — harness-init auto-delegation routing (2026-05-27)

- [x] [docs] Citation for "~50% trigger rate" — Scott Spence 2025-11-06.
- [x] [docs] Bilingual policy: KO+EN defaults; localization note added.

### PR #6 — harness-sync parallel crash fix (2026-05-04)

- [x] [debt] `symlink-guard.sh` Case 4: git mode 120000 guard noted.
