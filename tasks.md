# Tasks

## Review Backlog

### PR #36 — hwpx: Now-backlog debt (2026-06-09)

- [ ] [debt] `build.py:cmd_analyze` — `"TABLE id=" in result` sentinel fragile; if `_analyze_section` format string changes, `--table-id` silently breaks. Fix: `_analyze_section` returns `(str, bool)` or separate `_section_has_table(root, id) -> bool`. (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/build.py:530`
- [ ] [debt] `build.py:cmd_analyze` — `--table-id` mode prints `_analyze_section` document-structure metadata header for every matching section, cluttering output. Fix: strip header from `table_id_filter` result path or refactor `_analyze_section` to skip metadata when filter is active. (source: agy) — `productivity/skills/hwpx/scripts/build.py:528`
- [ ] [debt] `_common.py:18` — `SECTION_RE` (non-capturing) unused outside `_common` now that `validate.py` uses `SECTION_N_RE` directly. Replace `SECTION_RE` with `SECTION_N_RE` in `get_ids_from_hwpx` and delete the `SECTION_RE` definition to reduce duplication. (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/_common.py:18`

### PR #40 — fix: agy review silent failure on Windows (2026-06-10)

- [ ] [debt] `agy-review.sh` — Linux/Mac non-TTY context also silently loses agy output if agy uses platform-specific console rendering there too; no guard added for non-Windows platforms. (source: inline) — `dev-tools/skills/dev-review-cycle/scripts/agy-review.sh`
- [ ] [constraint] `preflight.sh` — no test coverage for the new Windows agy-disable branch; manual smoke test only. (source: code-review, pr-review-toolkit:review-pr) — `dev-tools/skills/dev-review-cycle/scripts/preflight.sh`
