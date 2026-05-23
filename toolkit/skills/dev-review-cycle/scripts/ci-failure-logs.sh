#!/usr/bin/env bash
# Fetch CI failure logs for a PR.
# Identifies failed checks, extracts run IDs, and fetches failed job logs.
#
# Usage: ci-failure-logs.sh <pr_number>
# Output: JSON array of {name, state, run_id, logs} for each failed check.

set -euo pipefail

PR_NUMBER="${1:?Usage: ci-failure-logs.sh <pr_number>}"

# Get failed checks with their links
FAILED_CHECKS=$(gh pr checks "$PR_NUMBER" --json name,state,link \
  --jq '[.[] | select(.state == "FAILURE")]')

if [ "$FAILED_CHECKS" = "[]" ] || [ -z "$FAILED_CHECKS" ]; then
  echo '{"failed_checks": [], "message": "No failed checks found"}'
  exit 0
fi

# Build result array with logs for each failed check
RESULTS="[]"

while IFS= read -r check; do
  NAME=$(echo "$check" | jq -r '.name')
  LINK=$(echo "$check" | jq -r '.link')

  # Extract run ID from the check link URL (numeric segment after /runs/)
  RUN_ID=$(echo "$LINK" | grep -oE '/runs/[0-9]+' | grep -oE '[0-9]+' | head -1 || true)

  LOGS=""
  if [ -n "$RUN_ID" ]; then
    # Limit to last 200 lines per job to avoid context/memory overflow
    LOGS=$(gh run view "$RUN_ID" --log-failed 2>&1 | tail -200 || echo "Failed to fetch logs for run $RUN_ID")
  else
    LOGS="Could not extract run ID from link: $LINK"
  fi

  RESULTS=$(echo "$RESULTS" | jq \
    --arg name "$NAME" \
    --arg run_id "${RUN_ID:-unknown}" \
    --arg logs "$LOGS" \
    '. + [{"name": $name, "run_id": $run_id, "logs": $logs}]')

done < <(echo "$FAILED_CHECKS" | jq -c '.[]')

echo "$RESULTS" | jq '{"failed_checks": ., "count": (. | length)}'
