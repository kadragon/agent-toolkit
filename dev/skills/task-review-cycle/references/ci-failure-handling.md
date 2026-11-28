# CI Failure Handling Guide

Detailed procedure for handling CI failures (Step 6 of task-review-cycle).

## Wait for CI

Run the CI wait script and check the result:

```bash
# timeout: 600000
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/ci-wait.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/ci-wait.sh" >&2; exit 1; }
HUB_TYPE="<hub type printed by Setup>"
PR_NUMBER="<PR number>"
DISPATCH_TIMING_RUN="<absolute run.json path when dispatched, otherwise empty>"
CI_ARGS=("$PR_NUMBER")
case "$HUB_TYPE" in
  github)
    REVIEWED_HEAD="<full SHA recorded in Final verification>"
    CI_ARGS+=(--expected-head "$REVIEWED_HEAD")
    ;;
  forgejo) ;;
  *) echo "Could not identify the hub from Setup" >&2; exit 1 ;;
esac
RESULT=$(DISPATCH_TIMING_RUN="$DISPATCH_TIMING_RUN" bash "$SKILL_DIR/scripts/ci-wait.sh" "${CI_ARGS[@]}")
PASSED=$(echo "$RESULT" | jq -r '.passed')
REASON=$(echo "$RESULT" | jq -r '.reason // empty')
```

Allow 600000ms — the Bash tool's ceiling; the script's own 9-minute deadline fires inside it so a `timeout` result normally arrives. Branch on both `PASSED` and `REASON`:

- `PASSED` is `true` → on GitHub the CI snapshot matched `REVIEWED_HEAD`. On Forgejo, confirm
  the snapshot from `hub.sh ci-status <PR_NUMBER>` describes the candidate's SHA. When Forgejo
  reports no configured checks, verify the remote PR head directly.
- `PASSED` is `false` and `REASON == "head-mismatch"`, or the Forgejo remote head moved → fetch
  and inspect the new head. Fast-forward only within the approved scope. Run targeted checks
  and resume under the existing review budget with new candidate evidence. If the change is
  out of scope or fast-forward is impossible, report the blocker and keep the PR open.
- `PASSED` is `false` and `REASON == "head-missing"` → retry once with the same reviewed SHA.
  Report the blocker if the hub still cannot identify the head. A missing or different SHA
  leaves the strike counter unchanged.
- `PASSED` is `false` and `REASON == "ci-config-unverified"` → retry from a checkout matching
  the reviewed tree so the wait can establish whether PR CI is configured.
- `PASSED` is `false` and `REASON` is empty → a real CI failure (an actual check failed). Go to "Handle CI Failure" below. The script has already counted this strike and reports the running total in `.failures`; you do not track it yourself.
- `PASSED` is `false` and `REASON == "rework-cap"` → the 3rd consecutive real failure. **Hard stop** — do not fetch logs, do not attempt another fix. Report the PR number and `.failures` to the user and ask for guidance. If the user decides to keep going anyway, clear the counter with `rm -f "$(git rev-parse --git-dir)/task-review-ci-strikes-<pr>"` — resolve the git dir with that command rather than assuming `.git/`, which is wrong inside a `--tree` worktree.
- `PASSED` is `false` and `REASON == "timeout"` → CI has not finished after 9 minutes. This is NOT a failure — do not fetch logs, do not count toward 3-strikes. Re-run `ci-wait.sh` once; if it times out again, stop and ask the user: "CI hasn't completed after 18 min on PR #<PR_NUMBER>. (a) keep waiting — re-run ci-wait.sh, (b) check the CI dashboard yourself and report back, (c) abandon this PR." One automatic re-run only — a second timeout waits for the user's choice.
- `PASSED` is `false` and `REASON == "checks-never-registered"` → the repo configures CI (a `.github`/`.forgejo`/`.gitea` workflow file exists) but no check ever attached to the PR within 5 minutes. NOT a failure — do not fetch logs, no strike is counted. Either the runner queue is still cold or the workflow's trigger/`paths:` filter excludes this PR. Retry `ci-wait.sh` once; if it recurs, stop and ask the user: "No CI check has registered on PR #<PR_NUMBER> after 10 min, but the repo has workflows. (a) keep waiting, (b) confirm the workflow does not apply to this PR and merge without CI, (c) abandon this PR." **Never merge on this reason alone** — it is the answer that used to arrive as a false `passed: true`.
- `PASSED` is `false` and `REASON` is any other value (a hub API/`ci-status` lookup hiccup) → retry `ci-wait.sh` once; if it recurs, stop and ask the user with the timeout case's three options.
- `RESULT` is empty (a stalled status call outlived the ceiling and the Bash tool killed the script) → stop and ask the user with the timeout case's three options (no automatic re-run).

Abandoning a PR — option (c) above — follows `../task-next/references/cycle.md` → *Hand off*: restore carried spec/ticket edits first, each step behind its `authorize` check.

## Handle CI Failure

### 1. Fetch Failure Logs

On GitHub, pass the same reviewed SHA used by the CI wait:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/ci-failure-logs.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/ci-failure-logs.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/ci-failure-logs.sh" <PR_NUMBER> --expected-head <REVIEWED_HEAD>
```

For `reason: "head-changed"` or `reason: "head-unavailable"`, retry the diagnostics once with the same reviewed SHA. This leaves the CI failure strike count unchanged. If the second lookup is still inconclusive, compare the live PR head with the reviewed SHA. Follow the *Wait for CI* head-mismatch recovery if the head changed. Otherwise report that failure logs could not be verified.

On Forgejo, pass only the PR number. When `logs_available` is false, report each failed check's name and link, then reproduce the failure locally and use that output to diagnose it.

### 2. Classify the Fix

- **Trivial fix** (lint, type error, formatting, flaky test retry): Apply the fix and run the affected checks.
- **Logic change** (behavioral modification, new/changed code paths): Apply the fix, run targeted
  checks, and follow `consolidation-guide.md` → *Fix rounds and re-review* before pushing.
  The existing review budget and contract/security gates still apply. Without `--auto`, get
  approval for the logic change before pushing.

### 3. Commit and Push

Reference the PR number in the message. Use `commit-and-push.sh` with the exact fix paths so
commit/push authority is checked; never bypass it with raw Git writes.

### 4. Re-check CI

After pushing a GitHub CI fix, record the full SHA from `git rev-parse HEAD` as the new
`Reviewed head` once review and targeted evidence cover the fix. Use that SHA for this wait
and later verification. A retry without a repair keeps the previously recorded SHA.

Return to the CI wait step. `ci-wait.sh` counts consecutive real failures itself and switches to
`reason: "rework-cap"` on the 3rd — that is the stop signal, and it is an exit condition you read,
not a tally you keep. A passing run clears the counter; timeouts and CI-status errors never
increment it (they route to the user-escalation branch in "Wait for CI" instead).

## Merge and Clean Up

SKILL.md Step 6 → *Hub path* issues the merge. Append `--dispatch-run <absolute run.json path>`
to that invocation for a dispatched run. Record a separately confirmed merge per
`consolidation-guide.md` → *Dispatch timing*. In the helper's JSON, `merge_ok: false` → report
the error (conflicts, branch protection) and suggest the user resolve it; `queued: true` = in a
merge queue, not merged yet; `unconfirmed: true` = state unknown, check the PR before retrying.
Cleanup warnings are reported, never blocking.
