#!/usr/bin/env bash
# Poll CI status for multiple PRs until all reach a terminal state (or timeout).
# Usage: poll-ci.sh [--interval N] [--timeout N] "owner/repo:123" "owner/repo:456" ...
#   --interval  seconds between polls (default: 30)
#   --timeout   max seconds to wait (default: 600)
# Output: JSON array — same schema as triage.sh, with final categories

set -euo pipefail

INTERVAL=30
TIMEOUT=600
entries=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval) INTERVAL="$2"; shift 2 ;;
    --timeout)  TIMEOUT="$2";  shift 2 ;;
    *) entries+=("$1"); shift ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
start=$SECONDS

while true; do
  result=$("$SCRIPT_DIR/triage.sh" "${entries[@]}")

  pending=$(echo "$result" | jq '[.[] | select(.category == "ci_pending")] | length')

  if [[ "$pending" -eq 0 ]]; then
    echo "$result"
    exit 0
  fi

  elapsed=$(( SECONDS - start ))
  if [[ "$elapsed" -ge "$TIMEOUT" ]]; then
    echo "$result"
    exit 1  # timeout — caller should check for ci_pending in output
  fi

  sleep "$INTERVAL"
done
