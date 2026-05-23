## Review Backlog

### main — [FEAT] dev-review-cycle: dynamic 1–N review skill selection (2026-05-23)

- [x] [debt] `sort -r` lexicographic version ordering — already fixed with `sort -rV 2>/dev/null || sort -r` fallback (source: code-review) — `detect-review-skills.sh:112`
- [x] [debt] jq called per-candidate in loop — accumulate as text, build JSON once at end for large plugin sets (source: agy) — `detect-review-skills.sh:70-74`
- [x] [debt] builtin candidates always present → `count == 0` fallback in SKILL.md is dead code; replaced with "all sub-agents failed" fallback in Collecting Results (source: agy, code-review) — `SKILL.md:102`

### PR #6 — [FIX] harness-sync: prevent crashes in parallel run (2026-05-04)

- [x] [debt] `symlink-guard.sh` Case 4: text-form pointer is only safe for POSIX peers when `.agents/skills` entry is already tracked as git mode 120000; warn or guard if not (source: Claude) — `kadragon-tools/skills/harness-init/scripts/symlink-guard.sh:44`
