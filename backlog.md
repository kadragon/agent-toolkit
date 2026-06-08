# Backlog

## Now

- [ ] [debt] `validate.py:175` — double-read of section XML in `do_validate`: bytes read once for tree parse, again via `zf.read()` for regex ID extraction. Consolidate into single read. (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/validate.py`
- [ ] [debt] `build.py:cmd_analyze` — hard-wired to `section0.xml` only; multi-section HWPX shows only first section. Enumerate all sections like `collect_metrics` does. (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/build_hwpx.py`
- [ ] [debt] `validate.py:31` — `SECTION_N_RE` imported as alias `SECTION_RE`, shadowing the non-capturing `SECTION_RE` from `_common`. Rename local alias. (source: agy)

## Next

- [ ] [debt] `--seed` in persona-debate not reproducible cross-run over HTTP (parquet fetch order varies). Fix: DuckDB `USING SAMPLE n ROWS (reservoir, REPEATABLE(seed))`. (source: pr-review-toolkit:review-pr, verified empirically) — `productivity/skills/persona-debate/scripts/sample_personas.py:109` *(deferred: needs DuckDB reservoir rewrite)*

## Someday

## History

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
