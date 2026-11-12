# Model-upgrade deconstrain pass (2026-11-12)

Status: shipped in dev v4.11.39. The user approved all 17 rows of the reference-review table.

## References

Anthropic docs, fetched 2026-11-12:

- `platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices`: *Set appropriate
  degrees of freedom*.
- `platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices`:
  "Prefer general instructions over prescriptive steps".
- `platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-2`:
  *Keep caution from piling up* and *Review prompts and harnesses designed for earlier models*.
  These two sections cover validation stop conditions, standing instructions to delegate, and the
  fact that the model reads "never" as absolute.

## Rule

Each cut rule met three conditions. It stopped or delegated on a routine step. It had no recorded
failure behind it, according to the provenance of its introducing commit. It touched nothing on
the Keep list: irreversible or remote side effects, mechanical gates, and incident-born rules
whose cause still holds.

## What changed

- **Stop on first failure → fix forward or default:**
  - review-cycle Step 4.1: a failed fix check is fixed once, then that finding's edits are
    reverted and filed to `## Review Backlog`. A `contract` finding still stops the merge.
  - harness-init Step 9: one fix pass on files this run wrote.
  - qa-verifier: the 3-failure early stop is gone.
  - Spawn contract: only Objective and Boundaries are required. This touches
    `.claude/agents/implementer.md`, harness-invariants, and `docs/delegation.md`.
- **Standing delegation or re-verification → optional:**
  - repo-dependabot `sonnet` fan-out.
  - workflows-template Step 5, folded into Step 4.
  - harness-curate's adversarial-reviewer spawn, now an inline keep case.
  - test-prune's fixed 3× suite runs.
- **Prescribed reasoning → criteria:**
  - task-debug: hypothesis count, show-first, full minimisation, numbered TDD steps.
  - task-grill: step 6 is folded into *Exit*, so the skill goes to v2.0.0.
  - task-next `cycle.md`: `[FEAT]` test-first and the stuck-note premise ordering.
- **No-ops:**
  - The review-cycle inline checklist.
  - batch A1 reply parsing.
  - The dependabot failure-pattern table and the manual `gh pr view` step.
  - repo-architecture "use these terms exactly".
- **Approval gate:** harness-capture memory writes now report after the write. Deletes and
  prunes still need approval.

## Prior decisions reopened

Both decisions were reopened by the user's approval of this pass.

- **#215 never-auto-default list** (`harness-invariants.md` → *Non-Interactive Gate Defaults*):
  - The >8 large-group guard now takes the first 8 open items in document order. The
    version-bump level is chosen by semver and stated in the PR body.
  - CI `timeout` re-runs once; a second timeout still stops. Other CI lookup failures still ask
    after their one retry.
- **2026-09-04 diet** kept harness-curate's independent delete reviewer. It is now an inline keep
  case that greps for routes the scanner cannot see.

## Kept on purpose

- The `bash`-free merge invocation.
- The panel no-wait rule.
- The risk-routing floor.
- qa-verifier's 15-call cap (fc413ea).
- test-prune mutation traps.
- task-debug's "no red-capable command, no Phase 2".
- Destructive-command guard and the CI `rework-cap` stop.

## Re-file bar

Restore a cut rule only with a recorded session where its absence caused the failure it guarded.
