## Review Backlog

### PR #15 — [DOCS] hwpx skill: lean SKILL.md, dump_table.py, cell editing patterns (2026-05-28)

- [ ] [doc] Fixed OWPML attribute order assumption undocumented in `_own_cell_addr` / `_cell_span` (source: pr-review-toolkit:review-pr) — `dump_table.py:102,117`

### PR #13 — [FEAT] harness-init: mechanical auto-delegation routing (2026-05-27)

- [x] [docs] Citation added for "~50% trigger rate" — Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)" (2025-11-06), https://scottspence.com/posts/claude-code-skills-dont-auto-activate. Year corrected from 2026 → 2025. Applied to `SKILL.md` (×2), `references/orchestrator-template.md`, `references/trigger-router-template.md` (×3) (source: pr-review-toolkit:review-pr).
- [x] [docs] Bilingual policy: keep KO+EN as defaults (harness authored for bilingual KO/EN user); added "Localization note" to `references/orchestrator-template.md` and `references/trigger-router-template.md` instructing English-only repos to drop Korean lines, other-language repos to translate. EN lines always kept (source: pr-review-toolkit:review-pr).

### main — [FEAT] dev-review-cycle: dynamic 1–N review skill selection (2026-05-23)

- [x] [debt] `sort -r` lexicographic version ordering — fixed with `sort -rV 2>/dev/null || sort -r` fallback (source: code-review) — `detect-review-skills.sh:112`
- [x] [debt] jq called per-candidate in loop — accumulate as text, build JSON once at end for large plugin sets (source: agy) — `detect-review-skills.sh:70-74`
- [x] [debt] builtin candidates always present → `count == 0` fallback in SKILL.md dead code; replaced with "all sub-agents failed" fallback in Collecting Results (source: agy, code-review) — `SKILL.md:102`

### PR #6 — [FIX] harness-sync: prevent crashes in parallel run (2026-05-04)

- [x] [debt] `symlink-guard.sh` Case 4: text-form pointer safe for POSIX peers only when `.agents/skills` entry tracked as git mode 120000; warn or guard if not (source: Claude) — `dev-tools/skills/harness-init/scripts/symlink-guard.sh:44`

### PR #17 — [REFACTOR] split marketplace into dev-tools + productivity plugins (2026-05-29)

- [ ] [doc] Add migration note for `toolkit:harness-maintenance` → `dev-tools:harness-maintenance` hook rename in README.md (source: review)
- [ ] [debt] `validate_hwpx` catches only `BadZipFile`; broaden to `except (BadZipFile, OSError)` to handle missing/permission errors (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/build_hwpx.py:147`
- [ ] [debt] `validate-harness.sh` section 6b uses `grep` but header comment claims "zero grep" — narrow comment to sections 1–5/7–10 (source: pr-review-toolkit:review-pr) — `dev-tools/skills/harness-init/scripts/validate-harness.sh:192`
- [ ] [debt] `reconcile-harness.py` missing exec bit (mode 100644) — `git update-index --chmod=+x` if direct invocation needed (source: pr-review-toolkit:review-pr)
- [ ] [doc] README.md Codex install path ambiguous — split `dev-tools/skills/<name>` and `productivity/skills/<name>` into labelled separate lines (source: pr-review-toolkit:review-pr) — `README.md:55`
