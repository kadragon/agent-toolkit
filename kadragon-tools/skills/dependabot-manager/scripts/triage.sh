#!/usr/bin/env bash
# Batch triage dependabot PRs via gh CLI.
# Usage: triage.sh "owner/repo:123" "owner/repo:456" ...
# Output: JSON array of triage results (category, mergeStateStatus, failedChecks)
#
# Categories: ready | ci_failed | ci_pending | needs_rebase | no_ci | closed

set -euo pipefail

results=()

for entry in "$@"; do
  repo="${entry%%:*}"
  number="${entry##*:}"

  data=$(gh pr view "$number" --repo "$repo" \
    --json number,title,state,mergeStateStatus,statusCheckRollup 2>/dev/null) || {
    results+=("{\"repo\":\"$repo\",\"number\":$number,\"category\":\"error\",\"error\":\"gh pr view failed\"}")
    continue
  }

  state=$(echo "$data" | jq -r '.state')
  merge_state=$(echo "$data" | jq -r '.mergeStateStatus')
  title=$(echo "$data" | jq -r '.title')
  failed=$(echo "$data" | jq '[.statusCheckRollup[] | select(.conclusion == "FAILURE")] | length')
  pending=$(echo "$data" | jq '[.statusCheckRollup[] | select(.status == "IN_PROGRESS" or .status == "QUEUED")] | length')
  total_ci=$(echo "$data" | jq '.statusCheckRollup | length')
  failed_names=$(echo "$data" | jq -c '[.statusCheckRollup[] | select(.conclusion == "FAILURE") | .name]')

  if [[ "$state" == "CLOSED" || "$state" == "MERGED" ]]; then
    category="closed"
  elif [[ "$failed" -gt 0 ]]; then
    category="ci_failed"
  elif [[ "$pending" -gt 0 ]]; then
    category="ci_pending"
  elif [[ "$total_ci" -eq 0 ]]; then
    category="no_ci"
  elif [[ "$merge_state" == "CLEAN" ]]; then
    category="ready"
  elif [[ "$merge_state" == "CONFLICTING" || "$merge_state" == "BEHIND" ]]; then
    category="needs_rebase"
  else
    category="unknown"
  fi

  results+=("$(jq -n \
    --arg repo "$repo" \
    --argjson number "$number" \
    --arg title "$title" \
    --arg category "$category" \
    --arg mergeStateStatus "$merge_state" \
    --argjson failedChecks "$failed_names" \
    '{repo: $repo, number: $number, title: $title, category: $category, mergeStateStatus: $mergeStateStatus, failedChecks: $failedChecks}')")
done

printf '%s\n' "${results[@]}" | jq -s '.'
