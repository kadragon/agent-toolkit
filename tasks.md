## Review Backlog

### PR #29 — [HARNESS] dev-review-cycle: fix merge cleanup + scope clarity + shell doc rule (2026-06-07)

- [x] [debt] `actions.md:72` — `gh api repos/{owner}/{repo}/releases` fetches the **app** repo's releases, not the upgraded dependency's releases; returns irrelevant/empty data for major PRs. Fix: resolve dep source from PR body or package metadata before calling releases API. (source: codex) — Added dep_repo resolution step with npm/Actions/PyPI guidance; skip+notify if unresolvable.
- [x] [debt] `actions.md:69` — jq body filter `.body` not truncated; large release notes bloat context. Fix: cap at 500 chars with `(.body // "" | .[0:500])`. (source: pr-review-toolkit:review-pr) — Applied to jq query in Step 0.

### PR #28 — [FIX] harness-curator: resolve asset repo before stale-code git check (2026-06-07)

- [x] [harness] Skill/agent instruction fixes use `[HARNESS]` commit type, not `[FIX]` — `[FIX]` requires reproducing test per CLAUDE.md (source: pr-review-toolkit:review-pr) — Acknowledged (retro process note; no file change needed).

### PR #26 — [FEAT] harness-curator agent analysis + productivity persona-debate skill (2026-06-04)

- [ ] [debt] `--seed` seeds `random()` but isn't reproducible cross-run over HTTP (parquet fetch order varies). For true reproducibility use DuckDB `USING SAMPLE n ROWS (reservoir, REPEATABLE(seed))`. Help text softened in-PR; proper fix deferred (source: pr-review-toolkit:review-pr, verified empirically) — `productivity/skills/persona-debate/scripts/sample_personas.py:109` *(deferred: needs DuckDB reservoir rewrite)*

### PR #15 — [DOCS] hwpx skill: lean SKILL.md, dump_table.py, cell editing patterns (2026-05-28)

- [x] [doc] Fixed OWPML attribute order assumption undocumented in `_own_cell_addr` / `_cell_span` (source: pr-review-toolkit:review-pr) — `dump_table.py:102,117` — Added comment to `_own_cell_addr` and docstring to `_cell_span` noting fixed-order assumption.

### PR #13 — [FEAT] harness-init: mechanical auto-delegation routing (2026-05-27)

- [x] [docs] Citation added for "~50% trigger rate" — Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)" (2025-11-06), https://scottspence.com/posts/claude-code-skills-dont-auto-activate. Year corrected from 2026 → 2025. Applied to `SKILL.md` (×2), `references/orchestrator-template.md`, `references/trigger-router-template.md` (×3) (source: pr-review-toolkit:review-pr).
- [x] [docs] Bilingual policy: keep KO+EN as defaults (harness authored for bilingual KO/EN user); added "Localization note" to `references/orchestrator-template.md` and `references/trigger-router-template.md` instructing English-only repos to drop Korean lines, other-language repos to translate. EN lines always kept (source: pr-review-toolkit:review-pr).

### main — [FEAT] dev-review-cycle: dynamic 1–N review skill selection (2026-05-23)

- [x] [debt] `sort -r` lexicographic version ordering — fixed with `sort -rV 2>/dev/null || sort -r` fallback (source: code-review) — `detect-review-skills.sh:112`
- [x] [debt] jq called per-candidate in loop — accumulate as text, build JSON once at end for large plugin sets (source: agy) — `detect-review-skills.sh:70-74`
- [x] [debt] builtin candidates always present → `count == 0` fallback in SKILL.md dead code; replaced with "all sub-agents failed" fallback in Collecting Results (source: agy, code-review) — `SKILL.md:102`

### PR #6 — [FIX] harness-sync: prevent crashes in parallel run (2026-05-04)

- [x] [debt] `symlink-guard.sh` Case 4: text-form pointer safe for POSIX peers only when `.agents/skills` entry tracked as git mode 120000; warn or guard if not (source: Claude) — `dev-tools/skills/harness-init/scripts/symlink-guard.sh:44`

### PR #24 — [FEAT] dev-tools: adopt task-audit command + staleness nudge hook (2026-06-03)

- [x] [debt] `all` scope could dump context-sized history with many projects. Resolved: harness-curator scanner adds `PROJECT_CAP` (top-N busiest projects) + per-project `PROMPT_CAP`/`CORRECTION_CAP`, all with printed drop counts (source: codex) — `dev-tools/skills/harness-curator/scripts/scan_transcripts.py`
- [x] [debt] `--project` arg parsing broke on paths with spaces. Resolved: scanner reads `sys.argv[1:]` directly (no string re-split) and SKILL.md documents quoting the path (source: agy, codex, pr-review) — `dev-tools/skills/harness-curator/scripts/scan_transcripts.py`

### PR #17 — [REFACTOR] split marketplace into dev-tools + productivity plugins (2026-05-29)

- [x] [doc] Add migration note for `toolkit:harness-maintenance` → `dev-tools:harness-maintenance` hook rename in README.md (source: review) — Added migration note under `## Installation` in README.md.
- [x] [debt] `validate_hwpx` catches only `BadZipFile`; broaden to `except (BadZipFile, OSError)` to handle missing/permission errors (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/build_hwpx.py:147` — Fixed; `BadZipFile` also moved to top-level import.
- [x] [debt] `validate-harness.sh` section 6b uses `grep` but header comment claims "zero grep" — narrow comment to sections 1–5/7–10 (source: pr-review-toolkit:review-pr) — `dev-tools/skills/harness-init/scripts/validate-harness.sh:18` — Narrowed performance comment to sections 1–5/7–10; noted section 6b grep.
- [x] [debt] `reconcile-harness.py` missing exec bit (mode 100644) — `git update-index --chmod=+x` if direct invocation needed (source: pr-review-toolkit:review-pr) — wontfix: always invoked as `python3 … reconcile-harness.py`; exec bit not needed.
- [x] [doc] README.md Codex install path ambiguous — split `dev-tools/skills/<name>` and `productivity/skills/<name>` into labelled separate lines (source: pr-review-toolkit:review-pr) — `README.md:55` — Split into two labelled example blocks.
