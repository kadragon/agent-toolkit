# Prod deconstrain pass (2026-11-12)

Status: shipped in prod v3.2.15. The user approved all 16 rows of the prod table.

This pass applies the dev pass's rule (PR #387, `docs/design/model-upgrade-deconstrain.md`) to
`prod/`. A rule is cut when three things hold. It stops or delegates on a routine step. Its
introducing commit records no failure behind it. It is not on the Keep list: irreversible or
remote effects, mechanical gates, and incident-born rules whose cause still holds. References
are Anthropic's `agent-skills/best-practices` and `prompting-claude-fable-5-2`, fetched
2026-11-12.

## What changed

- **kr-style `kr_audit.py`: S2 allowances now scale with length.**
  - Before, each allowance was a single count for the whole document. For example, P10
    `에 대한` and P21 `-적 N` were each allowed once.
  - The pattern table describes density, so a long report kept failing the exit-0 gate that
    gongmun-draft and report-draft require. The draft then had to be bent to fit a count.
  - The allowance now caps the hits inside any 10 consecutive sentences. A period after a digit
    does not end a sentence, so dates and item numbers don't inflate the count.
  - Self-test cases cover four shapes: a short note fails, the same two hits spread over 20
    sentences pass, two hits clustered inside 40 sentences fail, and dated 공문 lines fail.
- **Stop-and-ask steps on routine drafts become stated defaults.**
  - report-draft A1: skeleton approval happens only when the form, type, or audience cannot be
    inferred.
  - report-draft B2: the save-mode question is removed. B3 already fixes the answer
    (`_수정.hwpx`).
  - gongmun-draft: an unknown approver goes on the Step 5 list instead of stopping mid-draft.
  - persona-debate step 1: the recommended panel is used and stated. The skill asks only when the
    target group is ambiguous.
  - hwpx: when intent is unclear, the skill picks the implied mode and says which one.
- **Prescribed tactics become criteria.**
  - hwpx restore mode: how to fit the page count is left to judgment, and page-guard is the
    gate.
  - kr-style: the three-어절 modifier hard limit is now a candidate for splitting.
  - report-draft §8: the checklist is the quality bar, and unresolved items are reported once.
  - repo-quiz step 2: shortened to one line.
- **Repeated verification and no-ops are cut.**
  - hwpx bulk-edit: Hancom open per stage is replaced by `validate --baseline` per stage plus one
    final Hancom open.
  - Restated assert-count rules now point to Rule 15.
  - Removed: the stale `lxml` install, the up-front `olefile` install, the duplicated non-ASCII
    section, and a scripted user message.
  - hwpx Workflow 3: a filepath routes to extraction only when no other instruction comes with it.

## Kept on purpose

- `.hwp` originals are still deleted after verified conversion. The user confirmed this on
  2026-11-12.
- The exit-0 gates of kr_audit and lint.
- persona-debate's per-persona isolation and the "never opus" rule. This was a prior decision
  in `docs/design/skill-review-followups.md`.
- gongmun-draft's `[확인 필요]` and the "no invented dates" rule.
- The hwpx Hancom-open final gate, the row-delete completion gate, and the OWPML mechanics.

## Re-file bar

Restore a cut rule only with a recorded session where its absence caused the failure it guarded.
