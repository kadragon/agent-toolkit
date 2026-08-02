#!/usr/bin/env bash
# Wait for all CI checks on a PR to complete.
# Backend-agnostic: polls via hub.sh ci-status (gh for GitHub, REST for Forgejo).
#
# Usage: ci-wait.sh <pr_number>
# Output: JSON to stdout — {passed: bool}
#
# The orchestrator enforces a 15-minute background timeout externally.
#
# Rework cap: consecutive REAL CI failures are counted in a per-PR strike file under
# the repo's git dir. At MAX_STRIKES the script reports reason "rework-cap" so the
# orchestrator hard-stops on an exit code instead of remembering how many times it has
# already been round this loop. A pass clears the file; timeouts and ci-status errors
# never increment it — they are not rework.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PR_NUMBER="${1:?Usage: ci-wait.sh <pr_number>}"
MAX_STRIKES="${CI_WAIT_MAX_STRIKES:-3}"
# A non-numeric override would make the -ge test and --argjson both fail, and under
# `set -euo pipefail` the script would die with no JSON at all — worse than any cap.
case "$MAX_STRIKES" in ''|*[!0-9]*) MAX_STRIKES=3 ;; esac

GIT_DIR=$(git rev-parse --git-dir 2>/dev/null || true)
STRIKE_FILE=""
if [ -n "$GIT_DIR" ]; then
  STRIKE_FILE="$GIT_DIR/task-review-ci-strikes-$PR_NUMBER"
fi

read_strikes() {
  # Missing, unreadable, or non-numeric all mean "no strikes recorded yet".
  local n=0
  if [ -n "$STRIKE_FILE" ] && [ -r "$STRIKE_FILE" ]; then
    n=$(cat "$STRIKE_FILE" 2>/dev/null || echo 0)
  fi
  case "$n" in
    ''|*[!0-9]*) echo 0 ;;
    *) echo "$n" ;;
  esac
}

clear_strikes() {
  [ -n "$STRIKE_FILE" ] && rm -f "$STRIKE_FILE"
  return 0
}

# Env-overridable so the timeout branch is reachable in a test without editing the script.
TIMEOUT_SECS="${CI_WAIT_TIMEOUT_SECS:-870}"
POLL_INTERVAL="${CI_WAIT_POLL_INTERVAL:-20}"
case "$TIMEOUT_SECS" in ''|*[!0-9]*) TIMEOUT_SECS=870 ;; esac
case "$POLL_INTERVAL" in ''|*[!0-9]*) POLL_INTERVAL=20 ;; esac
# Some repos have no CI at all. Give checks this long to appear before
# concluding "no CI configured" and passing.
NO_CHECKS_GRACE_SECS="${CI_WAIT_NO_CHECKS_GRACE_SECS:-90}"
case "$NO_CHECKS_GRACE_SECS" in ''|*[!0-9]*) NO_CHECKS_GRACE_SECS=90 ;; esac
START=$(date +%s)
DEADLINE=$(( START + TIMEOUT_SECS ))

while true; do
  STATUS_JSON=$(bash "$SCRIPT_DIR/hub.sh" ci-status "$PR_NUMBER" 2>/dev/null || echo '{}')
  STATUS=$(jq -r '.status // "error"' <<<"$STATUS_JSON")
  NOW=$(date +%s)

  case "$STATUS" in
    success)
      clear_strikes
      jq -n '{passed: true}'
      exit 0
      ;;
    failure)
      STRIKES=$(read_strikes)
      STRIKES=$(( STRIKES + 1 ))
      [ -n "$STRIKE_FILE" ] && printf '%s\n' "$STRIKES" > "$STRIKE_FILE"
      if [ "$STRIKES" -ge "$MAX_STRIKES" ]; then
        jq -n --argjson n "$STRIKES" --argjson max "$MAX_STRIKES" \
          '{passed: false, reason: "rework-cap", failures: $n, max_failures: $max}'
      else
        jq -n --argjson n "$STRIKES" '{passed: false, failures: $n}'
      fi
      exit 0
      ;;
    none)
      if [ $(( NOW - START )) -ge "$NO_CHECKS_GRACE_SECS" ]; then
        clear_strikes  # a pass is a pass: no-CI must reset the counter like `success` does
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
