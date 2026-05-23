## Review Backlog

### main — [FEAT] dev-review-cycle: dynamic 1–N review skill selection (2026-05-23)

- [ ] [debt] `sort -r` lexicographic version ordering — 1.9.x beats 1.10.x; replace with `sort -rV` when GNU coreutils available (source: code-review) — `detect-review-skills.sh:107`
- [ ] [debt] jq called per-candidate in loop — accumulate as text, build JSON once at end for large plugin sets (source: agy) — `detect-review-skills.sh:70-74`
- [ ] [debt] builtin candidates always present → `count == 0` fallback in SKILL.md is dead code; consider adding "all sub-agents failed" fallback condition instead (source: agy, code-review) — `SKILL.md:102`

### PR #6 — [FIX] harness-sync: prevent crashes in parallel run (2026-05-04)

- [ ] [debt] `symlink-guard.sh` Case 4: text-form pointer is only safe for POSIX peers when `.agents/skills` entry is already tracked as git mode 120000; warn or guard if not (source: Claude) — `kadragon-tools/skills/harness-sync/scripts/symlink-guard.sh:44`
