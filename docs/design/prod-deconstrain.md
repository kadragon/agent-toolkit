# Prod deconstrain pass (2026-11-12)

Status: shipped in prod v3.2.15. The user approved all 16 rows of the prod table.

This pass applies the rule and the Keep list from `docs/design/model-upgrade-deconstrain.md` to
`prod/`. That file also lists the Anthropic references.

## What changed

- **kr-style `kr_audit.py`: S2 allowances now scale with length.**
  - Before, each allowance was a single count for the whole document. For example, P10
    `에 대한` and P21 `-적 N` were each allowed once.
  - The pattern table describes density, so a long report kept failing the exit-0 gate that
    gongmun-draft and report-draft require. The draft then had to be bent to fit a count.
  - The allowance is now `limit × ceil(sentences / 10)`.
  - New self-test cases cover both sides: two `-적 N` in a short note fail, and the same two
    across 20 sentences pass. The 20-sentence case fails on the old code.
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
