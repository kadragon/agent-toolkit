## Review Backlog

### PR #13 — [FEAT] harness-init: mechanical auto-delegation routing (2026-05-27)

- [ ] [docs] Add citation URL/title for "Scott Spence 2026 — ~50% trigger rate" referenced in `SKILL.md`, `references/orchestrator-template.md`, `references/trigger-router-template.md`. Currently unsourced — harness Agent Integrity Principle requires verifiable refs (source: pr-review-toolkit:review-pr).
- [ ] [docs] Decide template-wide bilingual policy. Korean placeholders inside English description templates in `references/orchestrator-template.md` may break monolingual repos; either drop or add explicit "translate or remove for English-only repos" note across all templates that use the pattern (source: pr-review-toolkit:review-pr).

### main — [FEAT] dev-review-cycle: dynamic 1–N review skill selection (2026-05-23)

- [x] [debt] `sort -r` lexicographic version ordering — fixed with `sort -rV 2>/dev/null || sort -r` fallback (source: code-review) — `detect-review-skills.sh:112`
- [x] [debt] jq called per-candidate in loop — accumulate as text, build JSON once at end for large plugin sets (source: agy) — `detect-review-skills.sh:70-74`
- [x] [debt] builtin candidates always present → `count == 0` fallback in SKILL.md dead code; replaced with "all sub-agents failed" fallback in Collecting Results (source: agy, code-review) — `SKILL.md:102`

### PR #6 — [FIX] harness-sync: prevent crashes in parallel run (2026-05-04)

- [x] [debt] `symlink-guard.sh` Case 4: text-form pointer safe for POSIX peers only when `.agents/skills` entry tracked as git mode 120000; warn or guard if not (source: Claude) — `toolkit/skills/harness-init/scripts/symlink-guard.sh:44`