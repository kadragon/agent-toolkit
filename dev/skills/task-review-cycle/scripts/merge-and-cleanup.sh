#!/usr/bin/env bash
# Merge a PR using the best available strategy, then clean up local branch.
#
# Usage: merge-and-cleanup.sh <pr_number> <base_branch> <feature_branch> <merge_strategy_json>
#                            [worktree_path] [--expected-head <sha>]
#   merge_strategy_json: e.g. '{"squash":true,"merge":true,"rebase":true}'
#   worktree_path: optional, removes the worktree before the local branch is deleted
#   --expected-head: atomically match the reviewed full SHA when merging on GitHub
#
# Output: JSON with merge result and cleanup status. merge_ok=false skips local cleanup; then
# queued=true means the PR entered a merge queue, unconfirmed=true that gh could not report its state.

set -euo pipefail

# --- Argument validation ---
usage() {
  echo "Usage: merge-and-cleanup.sh <pr_number> <base_branch> <feature_branch> <merge_strategy_json>"
  echo "                            [worktree_path] [--expected-head <sha>]"
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
shift 4
WORKTREE_PATH=""
if [[ $# -gt 0 && "$1" != --* ]]; then
  WORKTREE_PATH="$1"
  shift
fi
EXPECTED_HEAD=""
if [[ $# -eq 2 && "$1" == --expected-head && "$2" =~ ^[0-9a-f]{40}$ ]]; then
  EXPECTED_HEAD="$2"
elif [[ $# -ne 0 ]]; then
  usage
fi

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
MERGE_METHOD=""
if [[ "$MERGE_STRATEGY_JSON" =~ \"squash\"[[:space:]]*:[[:space:]]*true ]]; then
  MERGE_METHOD="squash"
elif [[ "$MERGE_STRATEGY_JSON" =~ \"merge\"[[:space:]]*:[[:space:]]*true ]]; then
  MERGE_METHOD="merge"
elif [[ "$MERGE_STRATEGY_JSON" =~ \"rebase\"[[:space:]]*:[[:space:]]*true ]]; then
  MERGE_METHOD="rebase"
else
  MERGE_METHOD="squash"
fi

# --- Merge PR (hub.sh routes to gh or the Forgejo/Gitea REST API) ---
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/git-authority.sh"
require_git_authority --branch "$FEATURE_BRANCH" --action base-merge
HUB_MERGE_ARGS=(merge "$PR_NUMBER" "$MERGE_METHOD" "$FEATURE_BRANCH")
if [ -n "$EXPECTED_HEAD" ]; then
  HUB_MERGE_ARGS+=("$EXPECTED_HEAD")
fi
MERGE_RESULT=$(bash "$SCRIPT_DIR/hub.sh" "${HUB_MERGE_ARGS[@]}" 2>&1 || echo '{"merge_ok": false, "merge_output": "hub.sh merge invocation failed"}')
MERGE_OK=$(jq -r '.merge_ok // false' <<<"$MERGE_RESULT" 2>/dev/null || echo false)
MERGE_OUTPUT=$(jq -r '.merge_output // ""' <<<"$MERGE_RESULT" 2>/dev/null || printf '%s' "$MERGE_RESULT")
QUEUED=$(jq -r '.queued // false' <<<"$MERGE_RESULT" 2>/dev/null || echo false)
UNCONFIRMED=$(jq -r '.unconfirmed // false' <<<"$MERGE_RESULT" 2>/dev/null || echo false)
if [ "$MERGE_OK" = "true" ]; then
  MERGE_MSG="PR #${PR_NUMBER} merged with ${MERGE_METHOD}"
elif [ "$QUEUED" = "true" ]; then
  MERGE_MSG="PR #${PR_NUMBER} queued for merge, not merged yet"
elif [ "$UNCONFIRMED" = "true" ]; then
  MERGE_MSG="PR #${PR_NUMBER} merge not confirmed (state unavailable); check the hub before retrying"
else
  MERGE_MSG="Merge failed for PR #${PR_NUMBER}"
fi

# --- Local cleanup (only if merge succeeded) ---
CLEANUP_MSG=""
WORKTREE_MSG=""

# hub.sh merge deletes the remote head only (both hubs); this block is the sole owner of the
# local branch and worktree.
if [ "$MERGE_OK" = "true" ]; then
  CAN_CLEAN=true
  IN_TARGET=false
  BASE_NOTE=""
  # Run from inside the linked worktree being removed, `git checkout <base>` fails: base is checked
  # out in the main worktree. Only then move there — and never switch the branch it holds, which
  # may be another agent's: on a different branch, base is left un-updated and cleanup continues.
  if [ -n "$WORKTREE_PATH" ]; then
    WORKTREE_PATH=$(CDPATH= cd -- "$WORKTREE_PATH" 2>/dev/null && pwd -P || printf '%s' "$WORKTREE_PATH")
    WORKTREE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
    if [ -n "$WORKTREE_ROOT" ] && [ "$WORKTREE_ROOT" -ef "$WORKTREE_PATH" ]; then
      IN_TARGET=true
      MAIN_WORKTREE=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
      if ! cd "$MAIN_WORKTREE" 2>/dev/null; then
        CAN_CLEAN=false
        CLEANUP_MSG="WARNING: Could not enter main worktree '${MAIN_WORKTREE}'; local cleanup skipped"
      fi
    fi
  fi
  if [ "$CAN_CLEAN" = "true" ]; then
    CURRENT_BRANCH=$(git branch --show-current)
    if [ "$IN_TARGET" = "true" ] && [ "$CURRENT_BRANCH" != "$BASE_BRANCH" ]; then
      BASE_NOTE=" (base '${BASE_BRANCH}' not updated: main worktree is on '${CURRENT_BRANCH:-detached HEAD}')"
    # The remote merge already landed: a failed checkout (dirty tree, unknown base) must still
    # reach the JSON below, not exit under set -e with the merge result unreported.
    elif ! CHECKOUT_ERR=$(git checkout "$BASE_BRANCH" 2>&1 >/dev/null); then
      CAN_CLEAN=false
      CLEANUP_MSG="WARNING: Could not check out '${BASE_BRANCH}'; local cleanup skipped: ${CHECKOUT_ERR}"
    else
      # A dirty checkout (e.g. one task-next --tree left as is) must not move under its owner;
      # untracked files do not count (a fast-forward that would overwrite one just fails, harmlessly).
      BASE_STATUS=$(git status --porcelain --untracked-files=no 2>/dev/null || true)
      if [ -n "$BASE_STATUS" ]; then
        BASE_NOTE=" (base '${BASE_BRANCH}' not fast-forwarded: checkout has uncommitted changes)"
        echo "NOTE: base '${BASE_BRANCH}' not fast-forwarded: checkout has uncommitted changes" >&2
      else
        git fetch origin "$BASE_BRANCH" >/dev/null 2>&1 || true
        git merge --ff-only FETCH_HEAD >/dev/null 2>&1 || true
      fi
    fi
  fi
  if [ "$CAN_CLEAN" = "true" ]; then
    # Worktree first: a worktree holding the feature branch blocks `git branch -D`.
    if [ -n "$WORKTREE_PATH" ]; then
      PY=$(command -v python3 || command -v python || true)
      BROKER_NOTE=""
      HOLDER=""
      if [ -n "$PY" ]; then
        BROKER_NOTE=$("$PY" -I -X utf8 "$SCRIPT_DIR/broker-cleanup.py" "$WORKTREE_PATH" 2>&1) || true
        SWEEP="$SCRIPT_DIR/../../task-next/scripts/worktree_sweep.py"
        HOLDER=$("$PY" -I -X utf8 "$SWEEP" --holder "$WORKTREE_PATH" 2>&1) || true
      fi
      if [ -n "$HOLDER" ] || [ -n "$BROKER_NOTE" ]; then
        WORKTREE_MSG="WARNING: Could not remove worktree '${WORKTREE_PATH}': ${BROKER_NOTE} ${HOLDER}"
      elif REMOVE_ERR=$(git worktree remove "$WORKTREE_PATH" 2>&1); then
        WORKTREE_MSG="Worktree '${WORKTREE_PATH}' removed"
      else
        WORKTREE_MSG="WARNING: Could not remove worktree '${WORKTREE_PATH}': ${REMOVE_ERR}"
      fi
    fi

    # squash/rebase merges change commit hash so -d sees "not fully merged"; -D is safe here
    # because we already confirmed merge_ok above.
    if [[ "$WORKTREE_MSG" == WARNING:* ]]; then
      CLEANUP_MSG="Local branch '${FEATURE_BRANCH}' kept with its worktree"
    elif ! git show-ref --verify --quiet "refs/heads/${FEATURE_BRANCH}"; then
      CLEANUP_MSG="WARNING: Local branch '${FEATURE_BRANCH}' not found — check the branch name"
    elif DELETE_ERR=$(git branch -D "$FEATURE_BRANCH" 2>&1 >/dev/null); then
      CLEANUP_MSG="Local branch '${FEATURE_BRANCH}' deleted"
    else
      CLEANUP_MSG="WARNING: Could not delete local branch '${FEATURE_BRANCH}': ${DELETE_ERR}"
    fi
    CLEANUP_MSG="${CLEANUP_MSG}${BASE_NOTE}"
  fi
else
  CLEANUP_MSG="Skipped — merge did not succeed"
fi

# --- Output JSON safely with jq ---
jq -n \
  --argjson merge_ok "$MERGE_OK" \
  --argjson queued "$QUEUED" \
  --argjson unconfirmed "$UNCONFIRMED" \
  --arg merge_method "$MERGE_METHOD" \
  --arg merge_message "$MERGE_MSG" \
  --arg merge_output "$MERGE_OUTPUT" \
  --arg cleanup_message "$CLEANUP_MSG" \
  --arg worktree_message "$WORKTREE_MSG" \
  '{
    merge_ok: $merge_ok,
    queued: $queued,
    unconfirmed: $unconfirmed,
    merge_method: $merge_method,
    merge_message: $merge_message,
    merge_output: $merge_output,
    cleanup_message: $cleanup_message,
    worktree_message: $worktree_message
  }'
