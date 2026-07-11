# CI Failure Handling Guide

Detailed procedure for handling CI failures (Step 6 of dev-review-cycle).

## Wait for CI

Run the CI wait script and check the result:

```bash
# timeout: 900000
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/ci-wait.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/ci-wait.sh" >&2; exit 1; }
RESULT=$(bash "$SKILL_DIR/scripts/ci-wait.sh" <PR_NUMBER>)
PASSED=$(echo "$RESULT" | jq -r '.passed')
REASON=$(echo "$RESULT" | jq -r '.reason // empty')
```

Allow up to 15 minutes (900000ms). Branch on both `PASSED` and `REASON`:

- `PASSED` is `true` → proceed to merge.
- `PASSED` is `false` and `REASON` is empty → a real CI failure (an actual check failed). Go to "Handle CI Failure" below; this counts toward the 3-strikes limit.
- `PASSED` is `false` and `REASON == "timeout"` → CI has not finished after 15 minutes. This is NOT a failure — do not fetch logs, do not count toward 3-strikes. Stop and ask the user: "CI hasn't completed after 15 min on PR #<PR_NUMBER>. (a) keep waiting — re-run ci-wait.sh, (b) check the CI dashboard yourself and report back, (c) abandon this PR." Wait for the user's choice — do not silently re-loop `ci-wait.sh` automatically.
- `PASSED` is `false` and `REASON` is present but not `"timeout"` (a hub API/`ci-status` lookup hiccup) → retry `ci-wait.sh` once; if it recurs, escalate exactly like the timeout case above.

## Handle CI Failure

### 1. Fetch Failure Logs

Use the bundled script:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/ci-failure-logs.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/ci-failure-logs.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/ci-failure-logs.sh" <PR_NUMBER>
```

The script identifies failed checks and returns JSON with logs for each failure (last 200 lines per job on GitHub). On Forgejo remotes the response has `logs_available: false` — the API exposes no job logs (≤ v15), only the failed check names and `target_url` links. In that case: report each failed check's name and link to the user, then reproduce the failure locally (run the project's test/lint command) and diagnose from local output instead of CI logs.

### 2. Classify the Fix

- **Trivial fix** (lint, type error, formatting, flaky test retry): Apply the fix directly.
- **Logic change** (behavioral modification, new/changed code paths): Apply the fix, then re-run Step 2-3 (collect reviews and get user approval) before pushing.

### 3. Verify Locally

Run tests locally to confirm the fix works.

### 4. Commit and Push

Determine the commit message yourself based on the fix just applied (you have full context). Reference the PR number in the message. Then stage, commit with that message, and push directly — no subagent needed for a single-file CI fix.

### 5. Re-check CI

Return to the CI wait step. If CI fails **3 consecutive times** (no passing run in between — counter resets on any pass), stop the workflow and ask the user for guidance. Timeouts and repeated CI-status errors do NOT increment this counter — they route to the user-escalation branch in "Wait for CI" instead.

## Merge and Clean Up

After CI passes, merge the PR and clean up:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/merge-and-cleanup.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/merge-and-cleanup.sh" >&2; exit 1; }
# All 4 positional args are REQUIRED. Values come from pre-flight JSON output.
# merge_strategy must be a JSON object, NOT a bare word like "squash".
bash "$SKILL_DIR/scripts/merge-and-cleanup.sh" \
  <PR_NUMBER> <BASE_BRANCH> <FEATURE_BRANCH> '<MERGE_STRATEGY_JSON>' [worktree_path]

# Concrete example:
bash "$SKILL_DIR/scripts/merge-and-cleanup.sh" \
  9 main feat/add-login '{"squash":true,"merge":true,"rebase":true}'
```

The script selects the best merge strategy (squash > merge > rebase) from the JSON, merges with `--delete-branch`, then checks out the base branch, fetches and fast-forward merges `FETCH_HEAD` (avoids `git pull` failures when `pull.rebase` is unconfigured; `ff-only` fails gracefully on unpushed local commits instead of discarding them), and safely deletes the local feature branch (`-d`, not `-D`). If a worktree path is provided, it removes that too.

**Common mistake:** `merge-and-cleanup.sh 9 squash` — this passes only 2 args. The script requires 4: pr_number, base_branch, feature_branch, and merge_strategy as JSON.

If `merge_ok` is false in the output, report the error (e.g., merge conflicts, branch protection) and suggest the user resolve manually. If cleanup warnings appear, report them but do not block.
