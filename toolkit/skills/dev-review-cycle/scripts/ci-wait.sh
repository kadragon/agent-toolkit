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

timeout 870 gh pr checks "$PR_NUMBER" --watch --fail-fast || GH_EXIT=$?
GH_EXIT="${GH_EXIT:-0}"

if [ "$GH_EXIT" -eq 0 ]; then
  jq -n '{passed: true}'
elif [ "$GH_EXIT" -eq 124 ]; then
  jq -n --argjson pr "$PR_NUMBER" '{"passed": false, "reason": "timeout", "pr_number": $pr}'
else
  jq -n '{passed: false}'
fi
