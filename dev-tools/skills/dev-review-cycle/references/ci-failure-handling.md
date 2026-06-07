# CI Failure Handling Guide

Detailed procedure for handling CI failures (Step 6 of dev-review-cycle).

## Wait for CI

Run the CI wait script and check the result:

```bash
# timeout: 900000
RESULT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/ci-wait.sh <PR_NUMBER>)
PASSED=$(echo "$RESULT" | jq -r '.passed')
```

If `PASSED` is `true`, proceed to merge. If `false`, handle CI failure below. Allow up to 15 minutes (900000ms).

## Handle CI Failure

### 1. Fetch Failure Logs

Use the bundled script:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/ci-failure-logs.sh <PR_NUMBER>
```

The script identifies failed checks, extracts run IDs, and returns JSON with logs for each failure (last 200 lines per job).

### 2. Classify the Fix

- **Trivial fix** (lint, type error, formatting, flaky test retry): Apply the fix directly.
- **Logic change** (behavioral modification, new/changed code paths): Apply the fix, then re-run Step 2-3 (collect reviews and get user approval) before pushing.

### 3. Verify Locally

Run tests locally to confirm the fix works.

### 4. Commit and Push

Determine the commit message yourself based on the fix just applied (you have full context). Reference the PR number in the message. Then stage, commit with that message, and push directly — no subagent needed for a single-file CI fix.

### 5. Re-check CI

Return to the CI wait step. If CI fails **3 consecutive times** (no passing run in between — counter resets on any pass), stop the workflow and ask the user for guidance.

## Merge and Clean Up

After CI passes, merge the PR and clean up:

```bash
# All 4 positional args are REQUIRED. Values come from pre-flight JSON output.
# merge_strategy must be a JSON object, NOT a bare word like "squash".
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/merge-and-cleanup.sh \
  <PR_NUMBER> <BASE_BRANCH> <FEATURE_BRANCH> '<MERGE_STRATEGY_JSON>' [worktree_path]

# Concrete example:
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/merge-and-cleanup.sh \
  9 main feat/add-login '{"squash":true,"merge":true,"rebase":true}'
```

The script selects the best merge strategy (squash > merge > rebase) from the JSON, merges with `--delete-branch`, then checks out the base branch, fetches and hard-resets to `origin/<base>` (avoids `git pull` failures when `pull.rebase` is unconfigured), and safely deletes the local feature branch (`-d`, not `-D`). If a worktree path is provided, it removes that too.

**Common mistake:** `merge-and-cleanup.sh 9 squash` — this passes only 2 args. The script requires 4: pr_number, base_branch, feature_branch, and merge_strategy as JSON.

If `merge_ok` is false in the output, report the error (e.g., merge conflicts, branch protection) and suggest the user resolve manually. If cleanup warnings appear, report them but do not block.
