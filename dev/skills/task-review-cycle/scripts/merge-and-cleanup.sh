#!/usr/bin/env bash
# Merge a PR using the best available strategy, then clean up local branch.
#
# Usage: merge-and-cleanup.sh <pr_number> <base_branch> <feature_branch> <merge_strategy_json>
#                            [worktree_path] [--expected-head <sha>] [--dispatch-run <run.json>]
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
  echo "                            [worktree_path] [--expected-head <sha>] [--dispatch-run <run.json>]"
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
DISPATCH_RUN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-head)
      [[ -z "$EXPECTED_HEAD" && "${2:-}" =~ ^[0-9a-f]{40}$ ]] || usage
      EXPECTED_HEAD="$2" ;;
    --dispatch-run)
      [[ -z "$DISPATCH_RUN" && -n "${2:-}" && "$2" != --* ]] || usage
      DISPATCH_RUN="$2" ;;
    *) usage ;;
  esac
  shift 2
done

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
MERGED_HEAD=$(jq -r '.head_sha // empty' <<<"$MERGE_RESULT" 2>/dev/null || true)
if [ "$MERGE_OK" = "true" ]; then
  MERGED_HEAD="${EXPECTED_HEAD:-$MERGED_HEAD}"
  MERGE_MSG="PR #${PR_NUMBER} merged with ${MERGE_METHOD}"
  if [ -n "$DISPATCH_RUN" ]; then
    TIMING_PY=$(command -v python3 || command -v python || true)
    if [ -z "$TIMING_PY" ]; then
      echo "WARN: dispatch merge timing unavailable without Python" >&2
    else
      TIMING=("$TIMING_PY" -I "$SCRIPT_DIR/../../dispatch/scripts/dispatch.py" timing "$DISPATCH_RUN" merged)
      if [ -n "$MERGED_HEAD" ]; then
        TIMING+=("$MERGED_HEAD")
      fi
      "${TIMING[@]}" || true
    fi
  fi
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

branch_worktree() {
  local repo_git_dir checked_out git_dir
  checked_out=$(git branch --list --format='%(worktreepath)' -- "$FEATURE_BRANCH") || return 1
  if [ -n "$checked_out" ]; then
    printf '%s\n' "$checked_out"
    return
  fi
  # A detached worktree can still own a branch during rebase or bisect.
  repo_git_dir=$(git rev-parse --path-format=absolute --git-common-dir) || return 1
  for git_dir in "$repo_git_dir" "$repo_git_dir"/worktrees/*; do
    if grep -Fxq -e "$FEATURE_REF" -e "$FEATURE_BRANCH" -- \
      "$git_dir/rebase-merge/head-name" "$git_dir/rebase-apply/head-name" \
      "$git_dir/rebase-merge/update-refs" "$git_dir/BISECT_START" 2>/dev/null; then
      printf '%s\n' "$git_dir"
      return
    fi
  done
}

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
      elif git fetch origin "$BASE_BRANCH" >/dev/null 2>&1; then
        git merge --ff-only FETCH_HEAD >/dev/null 2>&1 || true
      fi
    fi
  fi
  if [ "$CAN_CLEAN" = "true" ]; then
    if [ -n "$WORKTREE_PATH" ]; then
      PY=$(command -v python3 || command -v python || true)
      BROKER_NOTE=""
      HOLDER=""
      if [ -n "$PY" ] && [ -d "$WORKTREE_PATH" ]; then
        BROKER_NOTE=$("$PY" -I -X utf8 "$SCRIPT_DIR/broker-cleanup.py" --idle-only "$WORKTREE_PATH" 2>&1) || true
        SWEEP="$SCRIPT_DIR/../../task-next/scripts/worktree_sweep.py"
        # Windows can partially remove a locked worktree before encountering the
        # holder. On POSIX a waiting caller's cwd does not prevent removal.
        case "$(uname -s)" in
          MINGW* | MSYS* | CYGWIN*)
            HOLDER=$("$PY" -I -X utf8 "$SWEEP" --holder "$WORKTREE_PATH" 2>&1) || true
            ;;
        esac
      fi
      WORKTREE_GIT_DIR=$(git -C "$WORKTREE_PATH" rev-parse --absolute-git-dir 2>/dev/null || true)
      if [ -n "$WORKTREE_GIT_DIR" ] && { [ -d "$WORKTREE_GIT_DIR/rebase-merge" ] ||
        [ -d "$WORKTREE_GIT_DIR/rebase-apply" ] || [ -f "$WORKTREE_GIT_DIR/BISECT_START" ]; }; then
        WORKTREE_MSG="WARNING: Could not remove worktree '${WORKTREE_PATH}': rebase or bisect is in progress"
      elif [ -n "$HOLDER" ] || [ -n "$BROKER_NOTE" ]; then
        WORKTREE_MSG="WARNING: Could not remove worktree '${WORKTREE_PATH}': ${BROKER_NOTE} ${HOLDER}"
      elif REMOVE_ERR=$(git worktree remove "$WORKTREE_PATH" 2>&1); then
        WORKTREE_MSG="Worktree '${WORKTREE_PATH}' removed"
      else
        if [ -n "$PY" ]; then
          HOLDER=$("$PY" -I -X utf8 "$SWEEP" --holder "$WORKTREE_PATH" 2>&1) || true
        fi
        WORKTREE_MSG="WARNING: Could not remove worktree '${WORKTREE_PATH}': ${REMOVE_ERR}${HOLDER:+ (${HOLDER})}"
      fi
    fi

    # Squash/rebase changes commit IDs. Compare and delete the exact merged
    # head in one ref update so a concurrent local commit keeps its branch.
    FEATURE_REF="refs/heads/${FEATURE_BRANCH}"
    if [[ "$WORKTREE_MSG" == WARNING:* ]] && [ -d "$WORKTREE_PATH" ]; then
      CLEANUP_MSG="Local branch '${FEATURE_BRANCH}' kept with its worktree"
    elif ! LOCAL_HEAD=$(git show-ref --verify --hash "$FEATURE_REF" 2>/dev/null); then
      CLEANUP_MSG="WARNING: Local branch '${FEATURE_BRANCH}' not found — check the branch name"
    elif ! [[ "$MERGED_HEAD" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]]; then
      CLEANUP_MSG="WARNING: Local branch '${FEATURE_BRANCH}' kept because the merged head is unknown"
    elif [ "$LOCAL_HEAD" != "$MERGED_HEAD" ]; then
      CLEANUP_MSG="WARNING: Local branch '${FEATURE_BRANCH}' kept because its tip does not match the merged head"
    elif ! CHECKED_OUT=$(branch_worktree); then
      CLEANUP_MSG="WARNING: Could not check whether local branch '${FEATURE_BRANCH}' is in use"
    elif [ -n "$CHECKED_OUT" ]; then
      CLEANUP_MSG="WARNING: Local branch '${FEATURE_BRANCH}' is checked out at '${CHECKED_OUT}'"
    elif DELETE_ERR=$(git update-ref --no-deref -d "$FEATURE_REF" "$MERGED_HEAD" 2>&1 >/dev/null); then
      git config --remove-section "branch.${FEATURE_BRANCH}" >/dev/null 2>&1 || true
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
