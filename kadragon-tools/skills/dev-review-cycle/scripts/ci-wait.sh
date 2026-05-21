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

if gh pr checks "$PR_NUMBER" --watch --fail-fast; then
  jq -n '{passed: true}'
else
  jq -n '{passed: false}'
fi
