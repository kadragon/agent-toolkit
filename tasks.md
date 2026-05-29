## Review Backlog

### PR #13 — [FEAT] harness-init: mechanical auto-delegation routing (2026-05-27)

- [x] [docs] Citation added for "~50% trigger rate" — Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)" (2025-11-06), https://scottspence.com/posts/claude-code-skills-dont-auto-activate. Year corrected from 2026 → 2025. Applied to `SKILL.md` (×2), `references/orchestrator-template.md`, `references/trigger-router-template.md` (×3) (source: pr-review-toolkit:review-pr).
- [x] [docs] Bilingual policy: keep KO+EN as defaults (harness authored for bilingual KO/EN user); added "Localization note" to `references/orchestrator-template.md` and `references/trigger-router-template.md` instructing English-only repos to drop Korean lines, other-language repos to translate. EN lines always kept (source: pr-review-toolkit:review-pr).

### main — [FEAT] dev-review-cycle: dynamic 1–N review skill selection (2026-05-23)

- [x] [debt] `sort -r` lexicographic version ordering — fixed with `sort -rV 2>/dev/null || sort -r` fallback (source: code-review) — `detect-review-skills.sh:112`
- [x] [debt] jq called per-candidate in loop — accumulate as text, build JSON once at end for large plugin sets (source: agy) — `detect-review-skills.sh:70-74`
- [x] [debt] builtin candidates always present → `count == 0` fallback in SKILL.md dead code; replaced with "all sub-agents failed" fallback in Collecting Results (source: agy, code-review) — `SKILL.md:102`

### PR #6 — [FIX] harness-sync: prevent crashes in parallel run (2026-05-04)

- [x] [debt] `symlink-guard.sh` Case 4: text-form pointer safe for POSIX peers only when `.agents/skills` entry tracked as git mode 120000; warn or guard if not (source: Claude) — `dev-tools/skills/harness-init/scripts/symlink-guard.sh:44`