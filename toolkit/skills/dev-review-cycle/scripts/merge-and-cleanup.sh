#!/usr/bin/env bash
# Merge a PR using the best available strategy, then clean up local branch.
#
# Usage: merge-and-cleanup.sh <pr_number> <base_branch> <feature_branch> <merge_strategy_json> [worktree_path]
#   merge_strategy_json: e.g. '{"squash":true,"merge":true,"rebase":true}'
#   worktree_path: optional, removes the worktree after cleanup
#
# Output: JSON with merge result and cleanup status.

set -euo pipefail

# --- Argument validation ---
usage() {
  echo "Usage: merge-and-cleanup.sh <pr_number> <base_branch> <feature_branch> <merge_strategy_json> [worktree_path]"
  echo ""
  echo "  pr_number           PR number (integer)"
  echo "  base_branch         Target branch (e.g. main)"
  echo "  feature_branch      Branch to merge and delete"
  echo "  merge_strategy_json JSON object, e.g. '{\"squash\":true,\"merge\":true,\"rebase\":true}'"
  echo "  worktree_path       (optional) Worktree directory to remove after merge"
  echo ""
  echo "Example:"
  echo "  merge-and-cleanup.sh 9 main feat/my-feature '{\"squash\":true}'"
  exit 1
}

# Common mistake: passing strategy name instead of full args (e.g. "9 squash")
if [[ $# -eq 2 && "$2" =~ ^(squash|merge|rebase)$ ]]; then
  echo "ERROR: Got 'merge-and-cleanup.sh $1 $2' — missing <base_branch> <feature_branch> <merge_strategy_json>."
  echo "       Did you mean: merge-and-cleanup.sh $1 main <feature_branch> '{\"$2\":true}' ?"
  echo ""
  usage
fi

if [[ $# -lt 4 ]]; then
  echo "ERROR: Expected at least 4 arguments, got $#."
  usage
fi

PR_NUMBER="$1"
BASE_BRANCH="$2"
FEATURE_BRANCH="$3"
MERGE_STRATEGY_JSON="$4"
WORKTREE_PATH="${5:-}"

# Validate PR number is numeric
if ! [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "ERROR: pr_number must be an integer, got '$PR_NUMBER'."
  usage
fi

# Validate merge_strategy_json is valid JSON
if ! echo "$MERGE_STRATEGY_JSON" | jq empty 2>/dev/null; then
  echo "ERROR: merge_strategy_json is not valid JSON: '$MERGE_STRATEGY_JSON'"
  echo "       Expected something like '{\"squash\":true}'"
  usage
fi

# --- Determine merge method (squash > merge > rebase) ---
MERGE_FLAG=""
if [[ "$MERGE_STRATEGY_JSON" =~ \"squash\"[[:space:]]*:[[:space:]]*true ]]; then
  MERGE_FLAG="--squash"
elif [[ "$MERGE_STRATEGY_JSON" =~ \"merge\"[[:space:]]*:[[:space:]]*true ]]; then
  MERGE_FLAG="--merge"
elif [[ "$MERGE_STRATEGY_JSON" =~ \"rebase\"[[:space:]]*:[[:space:]]*true ]]; then
  MERGE_FLAG="--rebase"
else
  MERGE_FLAG="--squash"
fi

# --- Merge PR ---
MERGE_OK=true
MERGE_OUTPUT=""
if MERGE_OUTPUT=$(gh pr merge "$PR_NUMBER" "$MERGE_FLAG" --delete-branch 2>&1); then
  MERGE_MSG="PR #${PR_NUMBER} merged with ${MERGE_FLAG#--}"
else
  MERGE_OK=false
  MERGE_MSG="Merge failed for PR #${PR_NUMBER}"
fi

# --- Local cleanup (only if merge succeeded) ---
CLEANUP_MSG=""
WORKTREE_MSG=""

if [ "$MERGE_OK" = "true" ]; then
  git checkout "$BASE_BRANCH" >/dev/null 2>&1
  git pull origin "$BASE_BRANCH" >/dev/null 2>&1

  # Use -d (safe delete) — only deletes if fully merged
  if git branch -d "$FEATURE_BRANCH" >/dev/null 2>&1; then
    CLEANUP_MSG="Local branch '${FEATURE_BRANCH}' deleted"
  else
    CLEANUP_MSG="WARNING: Could not delete local branch '${FEATURE_BRANCH}' (may not be fully merged)"
  fi

  # Worktree cleanup if path provided
  if [ -n "$WORKTREE_PATH" ]; then
    if git worktree remove "$WORKTREE_PATH" 2>/dev/null; then
      WORKTREE_MSG="Worktree '${WORKTREE_PATH}' removed"
    else
      WORKTREE_MSG="WARNING: Could not remove worktree '${WORKTREE_PATH}'. Clean up manually."
    fi
  fi
else
  CLEANUP_MSG="Skipped — merge did not succeed"
fi

# --- Output JSON safely with jq ---
jq -n \
  --argjson merge_ok "$MERGE_OK" \
  --arg merge_method "${MERGE_FLAG#--}" \
  --arg merge_message "$MERGE_MSG" \
  --arg merge_output "$MERGE_OUTPUT" \
  --arg cleanup_message "$CLEANUP_MSG" \
  --arg worktree_message "$WORKTREE_MSG" \
  '{
    merge_ok: $merge_ok,
    merge_method: $merge_method,
    merge_message: $merge_message,
    merge_output: $merge_output,
    cleanup_message: $cleanup_message,
    worktree_message: $worktree_message
  }'
