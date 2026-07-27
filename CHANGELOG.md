# Changelog

## Unreleased

- [done] task-review Codex capture (dev v4.0.9) — `preflight.sh` now finds `codex-companion.mjs` at its real layouts (`cache/*/codex/<ver>/scripts/`, `marketplaces/*/plugins/codex/scripts/`) and ranks by the version component, so plugin mode stops silently degrading to the `codex review` CLI; `codex-review.sh` keeps stdout to the final review alone (transcript redirected to a log, diagnostics byte-bounded at 2 KB with the full path named, `.rendered`/raw-JSON fallbacks dropped because both carry the reasoning trace, status-0-with-empty-body reported as "no findings" instead of a failure) (2026-07-27)

- [done] task-next HTML-comment false positives (dev v4.0.3) — `backlog_candidates.py` now blanks out `<!-- ... -->` spans before tokenizing (line count preserved), so a commented-out `## Feature Name` / `- [ ] Simplest case` template no longer surfaces as a candidate group; SKILL.md hand-grep fallback documents the same rule (2026-07-27)
- [done] hwpx stale-linesegarray guard (prod v3.0.2) — `validate.py validate --baseline` now reports paragraphs whose text changed while the line-break cache was carried over (positional alignment; Hancom reuses the placeholder id `2147483648`), the failure mode that makes Hancom silently open a blank `빈 문서`; Bulk File Edit recipe gained the missing `strip-lineseg` step; rule 19 raised 🟡→🔴; dead script names fixed in editing-gotchas.md (2026-07-27)
- [done] Fix Windows Codex hook commands and hook test portability; clean stale plugin rename references and global legacy installations (2026-07-21)
- [done] Naming unification — plugins `dev-tools`→`dev` (v4.0.0), `productivity`→`prod` (v3.0.0); dev skills regrouped into `task-*`/`harness-*`/`repo-*` families; `repo-quiz` moved to prod; retired `orchestrate` + `loop-engineer`; harness-check.yml made rename-tolerant (2026-07-21)
- [done] Scrub router-var remnant — conventions.md SCREAMING_SNAKE example ROUTES_FILE → SKILL_DIR; sweep.sh exclusion kept for live trigger-router-template.md (2026-07-17)
- [done] preflight.sh base_branch staleness fix — fast-forward local base branch before scoping diffs (2026-07-07)
- [done] PR #119 review backlog — hwpx validate.py XXE/billion-laughs hardening via defusedxml (2026-07-05)
- [done] Now: 5 skill FIX findings (2026-07-05)
- [done] Next: hwpx/dev-review-cycle drift ratchet + doc dedup (7 items) (2026-07-05)
- [done] batch-skill-review-backlog-5 — dependabot-manager triage guard, dev-review-cycle quoting, persona-debate docs, orchestrate description, loop-engineer slug collision (5 units) (2026-07-05)
- [done] batch-dependabot-persona-router — dependabot-manager bash 3.2 empty-array guard, persona-debate router-drift quote fix (2 units) (2026-07-05)
- [done] Someday backlog cleanup — next-tasks progressive disclosure, harness-init sweep.sh/maintenance.md drift, hwpx --test coverage, harness-curator Step 2/5 cleanup (4 items) (2026-07-05)
