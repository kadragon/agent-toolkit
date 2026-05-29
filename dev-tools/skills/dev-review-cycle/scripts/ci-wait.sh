#!/usr/bin/env bash
# Wait for all CI checks on a PR to complete.
#
# Usage: ci-wait.sh <pr_number>
# Output: JSON to stdout — {passed: bool}
#
# The orchestrator enforces a 15-minute background timeout externally.

set -euo pipefail

PR_NUMBER="${1:?Usage: ci-wait.sh <pr_number>}"
TIMEOUT_SECS=870
POLL_INTERVAL=20
DEADLINE=$(( $(date +%s) + TIMEOUT_SECS ))

while true; do
  EXIT=0
  STATUS=$(gh pr checks "$PR_NUMBER" --json bucket 2>/dev/null) || EXIT=$?

  if [ "$EXIT" -eq 8 ]; then
    : # pending — fall through to sleep
  elif [ "$EXIT" -ne 0 ]; then
    jq -n --arg reason "gh exit $EXIT" '{"passed": false, "reason": $reason}'
    exit 0
  else
    PENDING=$(printf '%s' "$STATUS" | jq '[.[] | select(.bucket == "pending")] | length' 2>/dev/null || echo 1)
    if [ "$PENDING" -eq 0 ]; then
      FAILED=$(printf '%s' "$STATUS" | jq '[.[] | select(.bucket == "fail" or .bucket == "cancel")] | length')
      if [ "$FAILED" -eq 0 ]; then
        jq -n '{passed: true}'
      else
        jq -n '{passed: false}'
      fi
      exit 0
    fi
  fi

  NOW=$(date +%s)
  if [ "$NOW" -ge "$DEADLINE" ]; then
    jq -n --argjson pr "$PR_NUMBER" '{"passed": false, "reason": "timeout", "pr_number": $pr}'
    exit 0
  fi

  sleep "$POLL_INTERVAL"
done
