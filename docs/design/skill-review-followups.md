# Skill Review Follow-ups

## Problem Statement

The 2026-10-09 skill review (20 skills: 14 dev + 6 prod) against
`docs/design/harness-policy-alignment.md` found a set of defects that are
**not** covered by the five frozen backlog items 1–5. The existing
`harness-policy-alignment` slices own delegation wording, review
authorization, harness-init simplification, and model-selection policy/eval.
What remains is lower-risk hygiene: missing `version:` frontmatter, one
trigger-description contradiction, one evidence-rule contradiction, one
cross-skill filesystem coupling, and two overclaim wordings. None blocks the
P0/P1 rollout, but each causes a concrete failure: version CI drift,
missed/incorrect triggering, author confusion on fabricated values, or a
break if skills are ever packaged separately.

## Solution

Ship three small vertical slices after (not inside) the P0/P1 work. Each
slice is independently verifiable and mergeable; no slice changes
authorization semantics, delegation thresholds, model pins, or review-cycle
behavior. Keep provider IDs and model policy out — the P2 slices own those.

## User Stories

- As a skill consumer, I want trigger descriptions to match what the skill
  actually handles, so `.hwp` requests route correctly.
- As a report/gongmun author, I want one unambiguous rule for unverified
  values, so I neither fabricate a date nor stall without a placeholder.
- As a plugin maintainer, I want every shipped `SKILL.md` to carry a
  `version:` and accurate tool/scope claims, so CI and audits stay green.

## Implementation Decisions

### Slice A — frontmatter hygiene (versions + allowed-tools audit)

- Add `version:` to the six assets missing it: `dev/skills/harness-init`,
  `dev/skills/task-review`, `dev/skills/task-review-cycle`,
  `dev/skills/repo-dependabot`, `prod/skills/hwpx`,
  `prod/skills/persona-debate`. Verified by grep 2026-10-09: only 10
  `^version:` hits under `dev/skills` (capture, spec, curate, grill,
  next, tickets, reference-review, debug, new, repo-architecture); the four
  above have none. Under `prod/`, gongmun 1.0.1, kr-style 1.0.1, repo-quiz
  1.1.3, report-draft 1.0.1 carry one; hwpx and persona-debate do not.
- Follow `docs/conventions.md` Plugin Version Bump Rules per slice: patch
  unless something invoked by name is removed/renamed (then major). Keep
  Claude and Codex manifests synchronized when shipped assets change.
- Audit `allowed-tools` only, do not blanket-add: gongmun-draft and
  report-draft currently have none (full access for text drafting — broader
  than needed but defensible for report-draft which uses WebFetch/WebSearch);
  kr-style omits `Glob` (`kr-style/SKILL.md:10`); repo-quiz includes `Glob`
  + `Edit`. Decide per skill, document the reason in one line each.
- `repo-dependabot/SKILL.md:91` `sonnet` subagent note and
  `persona-debate/SKILL.md:35` "Never opus" stay unchanged in this slice;
  model-pin policy belongs to P2 (`subagent-model-selection-policy`), whose
  scope is `docs/` only.

### Slice B — hwpx trigger + report-draft coupling

- Resolve the contradiction: `prod/skills/hwpx/SKILL.md:7` description says
  "NOT legacy binary .hwp" while `:218` auto-converts `.hwp` via
  `convert_hwp.ps1` (plus `:98`, `:156` OLE-fallback notes). A `.hwp`
  request may not trigger the skill though the body handles it. Fix the
  description (e.g. ".hwp accepted via auto-conversion to .hwpx"), not the
  behavior; keep the Hancom/COM-unavailable fallback guidance.
- Decouple `prod/skills/report-draft/SKILL.md:17-18`
  `HWPX_DIR="$SKILL_DIR/../hwpx"` sibling-filesystem coupling. Prefer
  Skill-tool invocation of `hwpx` over direct cross-skill script paths; at
  minimum resolve via the owning plugin root rather than `..`. Works today
  only because both live in one `prod/` plugin — fragile on separate
  packaging. Same pattern check for any other `../<skill>` references.
- Cosmetic, same slice: `hwpx/SKILL.md:61` lone Korean header in an
  otherwise English skill — normalize language or mark intentional.

### Slice C — evidence and wording corrections

- `prod/skills/gongmun-draft/SKILL.md:18` ("근거를 못 찾은 문장은 쓰지 말고
  사용자에게 묻는다") vs `:97` ("지어낼 뻔했던 값은 `[확인 필요]`로 남기고
  목록에 적는다"): pick one rule and apply to both places. Recommended:
  keep writing the draft with `[확인 필요]` placeholders (never fabricate a
  date/condition that becomes an external promise) **and** list every
  placeholder in Step 5 — i.e. fix `:18` to match `:97`, not the reverse.
  `Step 4:82` hardcoded `prod:kr-style` call stays (consistent with
  report-draft); do not add fallback routing in this slice.
- `prod/skills/repo-quiz/SKILL.md:249` vs `:247`: "script is the single
  writer of state" overclaims while `Edit` (`:9`) may append prose to
  `mistakes.md`. Narrow the invariant ("single writer of
  `progress.json`/`history.jsonl`; `mistakes.md` prose appends via `Edit`
  are the scoped exception") or remove `Edit` if unused.
- `persona-debate` availability note stays as-is (HF parquet + `uv`, no
  offline fallback — honestly disclosed, out of scope for this slice).

## Testing Decisions

- Slice A: frontmatter checker (`scripts/ci/check_skill_frontmatter.py` +
  `test_check_skill_frontmatter.py`) and full harness validation pass;
  `grep -r '^version:' dev/skills prod/skills` shows zero misses; version
  bumps follow conventions with both manifests in sync.
- Slice B: trigger-collision check passes; `.hwp` request routes to `hwpx`
  (manual trigger test); report-draft flows still pass with hwpx scripts
  reachable after decoupling (run its lint/validate paths).
- Slice C: docs-only inspection — both gongmun lines agree; repo-quiz
  invariant matches `allowed-tools`; no behavior tests needed.

## Out of Scope

- Everything owned by `harness-policy-alignment` backlog 1–5: delegation
  thresholds, invocation-axis docs, review authorization boundary,
  harness-init simplification, model-selection policy/evaluation. No
  duplicate tickets.
- Removing `persona-debate` "Never opus" / `repo-dependabot` sonnet notes,
  adding model routers/telemetry, moving local agents into plugins,
  shortening task cycles, touching global instructions.
- `kr-style` "few paragraphs" vagueness and `repo-quiz` recap emoji:
  cosmetic, no failure named — dropped per reference-review Adopt rule.

## Further Notes

- Source: 2026-10-09 review conversation (4 parallel reviewers: task
  lifecycle, harness meta, prod, delegation-docs verification). P0/P1/P2
  claims verified against the tree; only the residual hygiene above is
  ticketed here.
- `prod:kr-style` / `prod:hwpx` / `prod:persona-actor` cross-asset Skill
  references resolve within `prod/` (verified); only report-draft's
  filesystem path is the coupling defect.
- Run after backlog 1–3 land (soft ordering, not a technical block):
  slices touch adjacent `SKILL.md` frontmatter/descriptions and should not
  race P0/P1 edits to the same dev assets.
