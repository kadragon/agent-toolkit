#!/usr/bin/env bash
# Wait for all CI checks on a PR to complete.
#
# Usage: ci-wait.sh <pr_number>
# Output: JSON to stdout — {passed: bool}
#
# The orchestrator enforces a 15-minute background timeout externally.
# This script waits for gh to report a final result and returns structured JSON.

set -euo pipefail

PR_NUMBER="${1:?Usage: ci-wait.sh <pr_number>}"
TIMEOUT_SECS=870

# Portable timeout: background job + sleep killer (GNU timeout not available on macOS)
gh pr checks "$PR_NUMBER" --watch --fail-fast &
GH_PID=$!

( sleep "$TIMEOUT_SECS" && kill "$GH_PID" 2>/dev/null ) &
KILLER_PID=$!

wait "$GH_PID" 2>/dev/null || GH_EXIT=$?
GH_EXIT="${GH_EXIT:-0}"

kill "$KILLER_PID" 2>/dev/null
wait "$KILLER_PID" 2>/dev/null || true

# kill sends SIGTERM (exit 143) or SIGKILL (137); treat as timeout
if [ "$GH_EXIT" -eq 0 ]; then
  jq -n '{passed: true}'
elif [ "$GH_EXIT" -eq 143 ] || [ "$GH_EXIT" -eq 137 ]; then
  jq -n --argjson pr "$PR_NUMBER" '{"passed": false, "reason": "timeout", "pr_number": $pr}'
else
  jq -n '{passed: false}'
fi
