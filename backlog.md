# Backlog

## Now

## Next

- [ ] [harness] `harness-check.yml` — add `OLD_CODEX` baseline: `git show origin/main:{plugin}/.codex-plugin/plugin.json | jq -r .version`. Without it, Codex-only version drift emits misleading "Claude manifest not bumped" error. (source: pr-review-toolkit:review-pr, PR #35)
- [ ] [doc] `docs/platform-specs.md` Codex plugin.json example — add `"hooks": "./hooks.json"` (omitted despite spec saying Codex supports hooks field). (source: pr-review-toolkit:review-pr, PR #35)
- [ ] [doc] `docs/platform-specs.md:126` — replace hardcoded `"version": "3.0.7"` with `"version": "X.Y.Z"` in example JSON. (source: pr-review-toolkit:review-pr, PR #35)
- [ ] [doc] `docs/platform-specs.md` Sources section — verify URLs (`code.claude.com` vs `docs.anthropic.com`, Codex URL format). (source: pr-review-toolkit:review-pr, PR #35)

- [ ] [debt] `--seed` in persona-debate not reproducible cross-run over HTTP (parquet fetch order varies). Fix: DuckDB `USING SAMPLE n ROWS (reservoir, REPEATABLE(seed))`. (source: pr-review-toolkit:review-pr, verified empirically) — `productivity/skills/persona-debate/scripts/sample_personas.py:109` *(deferred: needs DuckDB reservoir rewrite)*

## Someday

## History

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
