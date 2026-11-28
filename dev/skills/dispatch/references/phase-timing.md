# Phase timing

Read `collect` → `timing` or run `dispatch.py timing <receipt>` to read the record without Herdr.
Absolute timestamps are Unix milliseconds. Each duration measures an observed interval:

- Startup runs from the launch call to confirmed delivery.
- Implementation runs from confirmed delivery to the first review launch.
- Review and CI attempts can overlap. Each carries the candidate SHA, start, finish, and outcome.
- Restart runs from confirmed close to the replacement launch. Replacement startup is separate.
- Merge runs from the original launch to confirmation. The merge record carries the verified
  feature head when available. Until merge, the final head comes from the child's result.

Missing measurements are `null` in JSON and `?` in the brief display. Historical receipts may
lack launch or delivery timing. The record keeps eight launches and sixteen attempts per
phase per launch, with counts for dropped entries. Interrupted attempts keep their start
time and may be completed after a relaunch.

Set `DISPATCH_TIMING_RUN` to the child's receipt for `ci-wait.sh` and `merge-and-cleanup.sh`.
For a merge confirmed separately, run `dispatch.py timing <receipt> merged <confirmed feature head>`
after verifying the merge. Omit the SHA if the verified source does not provide it.
