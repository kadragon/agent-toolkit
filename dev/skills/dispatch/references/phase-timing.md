# Phase timing

Read `collect` → `timing` or run `dispatch.py timing <receipt>` to read the record without Herdr.
Absolute timestamps are Unix milliseconds. Each duration measures an observed interval:

- Startup runs from the launch call to confirmation. Codex confirms through `send`, including
  recovery of its original acknowledgment when available. Claude confirms before starting work
  with the `timing ... delivered` command supplied at launch.
- Implementation runs from confirmed delivery to the first review launch.
- Review and CI attempts can overlap. Each carries the candidate SHA, start, finish, and outcome.
  A review of staged changes gets its head when the reviewed tree is committed. CI outcomes
  with an unverified head use the `-unverified` suffix. A completed wait without configured
  checks reports `no-checks`.
- Restart runs from confirmed close to the replacement launch. Replacement startup is separate.
- Merge runs from the original launch to confirmation. The merge record carries the verified
  feature head when available. The current child report supplies the final head while
  merge data has no SHA.

Missing measurements are `null` in JSON and `?` in the brief display. Historical receipts may
lack launch or delivery timing. The record keeps eight launches and sixteen attempts per
phase per launch, with counts for dropped entries. Interrupted attempts keep their start
time and may be completed after a relaunch.

Set `DISPATCH_TIMING_RUN` to the child's receipt when invoking `ci-wait.sh`. Pass
`--dispatch-run <receipt>` to `merge-and-cleanup.sh`.
For a merge confirmed separately, run `dispatch.py timing <receipt> merged <confirmed feature head>`
after verifying the merge. Omit the SHA if the verified source does not provide it.

When closing a child with a current `ready` result, `collect --close` uses any recorded merge for
the reported head. Otherwise it checks the reported GitHub PR and records when it confirms that
the same head was merged. If GitHub reports a different head, refresh the child's report before closing.
