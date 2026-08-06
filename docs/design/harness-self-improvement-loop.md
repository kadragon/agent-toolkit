# Harness Self-Improvement Loop

> Concept source: Lilian Weng, "Harness Engineering for Self-Improvement"
> (https://lilianweng.github.io/posts/2026-07-04-harness/), surfaced via GeekNews
> (https://news.hada.io/topic?id=32179). Borrowed mechanisms: Self-Harness
> (weakness mining → bounded proposal → held-out validation), AHE decision
> observability (every edit paired with a falsifiable prediction), ACE
> structured-delta curation.

## Problem Statement

The three harness skills (`harness-init` / `harness-capture` / `harness-curate`)
form an **open pipeline, not a closed loop**:

1. **No validation stage.** A `harness-curate` proposal routes to a creator
   (skill-creator / hookify / update-config) and ends at user confirmation +
   commit. Nothing measures whether the edit actually improved anything —
   the Self-Harness stage-3 analogue ("accept only with no regression") is
   absent. An ineffective harness edit persists forever.
2. **Records carry no predictions.** `harness-evolution.md`'s change-history
   schema records Date/Change/Scope/Reason — post-hoc only. AHE pairs every
   edit with a predicted impact that a later cycle can falsify; without it,
   the loop cannot tell a load-bearing edit from dead weight, and the
   pending-candidate nudge (currently 8+ days stale) has no re-audit hook.
3. **Weakness mining depends on user corrections.** `harness-curate`'s signals
   are user-pushback and prompt clusters. The paper's core move is mining
   **verifier-grounded** failures — and this repo already produces those
   signals (qa-verifier rejections, `ci-wait.sh` 3-consecutive-failure hard
   stops, hook denials, `.toolUseResult.is_error`) but the scanner never reads
   them. A loop that only learns when the user complains does not reduce user
   load, which is the point of self-improvement.
4. **The evolution protocol is split.** `harness-init/references/harness-evolution.md`
   duplicates curate's signal→fix routing (2× feedback → update skill/agent),
   so the same rule lives in two skills and drifts — the exact defect
   curate's own Signal 7 exists to catch.

## Solution

Keep the three-skill structure (init = scaffolding / capture = warm path /
curate = cold path) and the existing safety posture (route-on-confirmation,
never auto-generate, global/base instruction layers read-only — these already
match the paper's "human oversight sits outside the loop"). Close the loop
with four additions:

```
Observe (Signal 8: verifier-grounded failures, scanner-emitted)
   → Mine/Cluster (curate, existing Step 3 judgment)
   → Propose (existing creator routing, bounded editable surface)
   → Validate (NEW: per-route objective check is the acceptance criterion)
   → Record (NEW: harness-log entry with falsifiable prediction)
   → Re-audit (NEW: next curate run loads unverified predictions; failed
     predictions become prune candidates)
```

Explicitly **not adopted** from the paper: DGM/MCE evolutionary search
(population, crossover) — no cheap harness-quality verifier exists here, and
the paper's own reward-hacking / diversity-collapse warnings apply; and any
weakening of route-on-confirmation.

## User Stories

- As the operator, I want harness weaknesses surfaced from machine verdicts
  (CI failures, qa-verifier rejections, hook denials), so that the harness
  improves without me having to notice and complain first.
- As the operator, I want every accepted harness edit to pass an objective
  check before it lands, so that plausible-but-useless edits are rejected
  instead of accumulating.
- As the operator, I want each harness change recorded with a prediction that
  the next curate run re-examines, so that ineffective edits are found and
  pruned mechanically instead of persisting by default.
- As a future session, I want one authoritative loop contract (editable
  surface, validation gate, record schema), so that curate and init cannot
  drift apart on the same rules.

## Implementation Decisions

**D1 — Signal 8 "verifier-grounded failure" is scanner-emitted, not model-grepped.**
Extend `scan_transcripts.py` with a `VERIFIER-FAILURES` block (capped, dropped
counts printed, same bounds discipline as existing blocks). Sources, best-effort
per `transcript-format.md`:
- `tool_result` / `.toolUseResult.is_error` on Bash calls matching CI/test
  invocations (e.g. `ci-wait.sh`, `pytest`, `validate-harness.sh` non-zero).
- Agent tool_use with `subagent_type` `qa-verifier` whose returned text
  contains a rejection verdict (pattern list in the reference; heuristic,
  confirm-by-reading like CORRECTION-SIGNALS).
- Hook denial records (PreToolUse block messages).
Detection rule + routing brief documented as **Signal 8** in
`signal-taxonomy.md`; threshold ≥2 same-cluster failures (or 1 with
systematic cause), consistent with Signals 3/5. Clustering and causal
judgment stay with the model — the scanner extracts only.

**D2 — Validation gate lives in curate Step 7 as the acceptance criterion.**
Every routed brief's exit criterion must name an objective check, per route:

| Route | Acceptance check |
|---|---|
| skill create/modify | `skill-creator` eval pass (it owns evals — no parallel harness) |
| description fix | skill-creator description-optimizer train/test pass |
| hook / settings | trigger simulation (echo-pipe test, as harness-init Step 7b does) exits with expected verdict |
| agent create/modify | one re-run of the failing case (or dry-run) succeeds |
| docs / memory write | n/a — record-only; prediction field still required (D3) |

No verifier available for a given edit → the edit may still land on user
confirmation, but its record is marked `unverified` (global CLAUDE.md:
disclose the limit) and it is first in line at re-audit. Failing the check →
revert, do not land.

**D3 — Prediction schema extends the harness-log change history.**
`harness-evolution.md` §Change History (the schema authority, referenced by
`orchestrator-template.md` pointer blocks) gains two columns:
`Predicted impact` (falsifiable, e.g. "trigger-miss for X drops to 0 in next
5 sessions") and `Verified` (`pending` / date+evidence / `failed`). This
repo's own harness edits use the same schema in a repo-root
`docs/harness-log.md` (created by the first edit under this loop).

**D4 — Re-audit runs inside curate, current/--project scope only.**
A new curate step (after Step 2 inventory) reads the target repo's
`docs/harness-log.md`, loads rows with `Verified: pending`, and checks each
prediction against this run's scan output. Prediction held → stamp date +
evidence. Prediction failed → surface as a prune/rework candidate in the
Step 6 report (adversarial check before delete, as with Signal 4 demote).
Same scope limitation as Signal 7 (needs a resolvable repo path); no state
file changes — the log itself is the state.

**D5 — `harness-evolution.md` becomes the loop contract; detection moves to curate.**
It stays in `harness-init/references/` because init owns the harness-log
schema and ships it into target repos. Rewrite it to carry only: (a) the
editable-surface manifest (may edit: repo skills/agents/hooks/docs;
confirmation-gated: repo CLAUDE.md/AGENTS.md; read-only: global CLAUDE.md,
base instructions, verifiers — validate-harness.sh, qa-verifier, CI),
(b) the validation-gate table (D2), (c) the record schema (D3). Its
signal-detection tables (duplicating curate's) are deleted; curate's
signal-taxonomy is the single detection authority, and evolution.md points
to it. `harness-init` SKILL.md's "Harness Evolution" section updates its
description accordingly.

**D6 — `harness-capture` gets a minimal delta.**
Warm-path write-backs (memory/doc edits) add one line to the write proposal:
"failure this prevents" — the warm-path form of the prediction field. No
schema change to auto-memory files; the line goes in the memory body. No
other capture changes — it is already ACE-shaped.

**D7 — Versioning.** All changes land in `dev/` plugin; one minor bump
(behavior addition, nothing renamed/removed) for both
`dev/.claude-plugin/plugin.json` and `dev/.codex-plugin/plugin.json`.

## Testing Decisions

- **Scanner (D1):** extend `test_scan_transcripts.py` with fixture transcripts
  containing a failing-CI Bash result, a qa-verifier rejection tool_result,
  and a hook-denial record; assert the `VERIFIER-FAILURES` block, caps, and
  dropped-count lines. `python3 scripts/test_scan_transcripts.py` green.
- **Re-audit (D4):** if implemented as script logic, unit-test the
  pending-row parse against a fixture `harness-log.md`; if prose-only
  (model-executed), verify via a dry-run transcript walkthrough documented in
  the PR (observable verification, per global bug-fix rule).
- **Prose changes (D2/D3/D5/D6):** `validate-harness.sh` (structure) + CI
  `harness-check.yml` (version bump) green; sibling-reference grep for every
  renamed/moved rule (feedback memory: check sibling references) — in
  particular every pointer to `harness-evolution.md` sections that D5 deletes.
- **No weakened tests:** existing scanner tests must pass unchanged.

## Out of Scope

- DGM / MCE evolutionary search, population maintenance, agentic crossover.
- Any autonomous (non-confirmed) harness editing; route-on-confirmation stays.
- Editing verifiers from within the loop (validate-harness.sh, qa-verifier
  definition, CI workflows are read-only to loop-originated edits).
- Codex-side Signal 8 mining (`function_call_output` parsing) — deferred;
  Claude transcripts first. Noted in the scanner as a documented gap, not
  silent.
- prod/ plugin changes.
- Retroactively back-filling predictions for past harness edits.

## Further Notes

- Ordering matters: D1 (signal quality) before D2/D4 gain meaning; D3/D5 can
  proceed in parallel with D1. Suggested ticket order: D1 → D5(+D3) → D2 →
  D4 → D6.
- Risk: verifier-failure heuristics over-collect (a CI failure caused by the
  task, not the harness). Mitigation mirrors HARNESS-FRICTION's documented
  posture: over-collect deliberately, model reads before routing, causal
  judgment required ("terminal verifier-level cause" per Self-Harness).
- The 8-day-stale curator nudge is evidence for D4: pending candidates need a
  mechanical re-audit path, not operator memory.
- Follow-up (not this cycle): if prediction re-audit proves useful, consider
  surfacing `Verified: failed` count in the SessionStart nudge.
