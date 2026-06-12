#!/usr/bin/env bash
# Wait for all CI checks on a PR to complete.
# Backend-agnostic: polls via hub.sh ci-status (gh for GitHub, REST for Forgejo).
#
# Usage: ci-wait.sh <pr_number>
# Output: JSON to stdout — {passed: bool}
#
# The orchestrator enforces a 15-minute background timeout externally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PR_NUMBER="${1:?Usage: ci-wait.sh <pr_number>}"
TIMEOUT_SECS=870
POLL_INTERVAL=20
# Some repos have no CI at all. Give checks this long to appear before
# concluding "no CI configured" and passing.
NO_CHECKS_GRACE_SECS=90
START=$(date +%s)
DEADLINE=$(( START + TIMEOUT_SECS ))

while true; do
  STATUS_JSON=$(bash "$SCRIPT_DIR/hub.sh" ci-status "$PR_NUMBER" 2>/dev/null || echo '{}')
  STATUS=$(jq -r '.status // "error"' <<<"$STATUS_JSON")
  NOW=$(date +%s)

  case "$STATUS" in
    success)
      jq -n '{passed: true}'
      exit 0
      ;;
    failure)
      jq -n '{passed: false}'
      exit 0
      ;;
    none)
      if [ $(( NOW - START )) -ge "$NO_CHECKS_GRACE_SECS" ]; then
        jq -n '{passed: true, reason: "no CI checks found"}'
        exit 0
      fi
      ;;
    pending)
      : # fall through to sleep
      ;;
    *)
      jq -n --arg reason "ci-status returned: $STATUS" '{passed: false, reason: $reason}'
      exit 0
      ;;
  esac

  if [ "$NOW" -ge "$DEADLINE" ]; then
    jq -n --arg pr "$PR_NUMBER" '{"passed": false, "reason": "timeout", "pr_number": $pr}'
    exit 0
  fi

  sleep "$POLL_INTERVAL"
done
