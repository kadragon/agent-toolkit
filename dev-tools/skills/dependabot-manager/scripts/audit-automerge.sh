#!/usr/bin/env bash
# Audit auto-merge readiness for one or more repos.
# Usage: audit-automerge.sh "owner/repo1" "owner/repo2" ...
# Output: JSON array [{repo, allow_auto_merge, default_branch, has_protection,
#                      required_checks, ready_for_auto_merge, missing}]

set -euo pipefail

results=()

audit_repo() {
  local repo="$1"

  # Fetch repo metadata
  local meta
  meta=$(gh api "repos/$repo" --jq '{allow_auto_merge: .allow_auto_merge, default_branch: .default_branch}' 2>/dev/null) || {
    echo "{\"repo\":\"$repo\",\"error\":\"gh api failed — check auth/permissions\"}" >&2
    echo "{\"repo\":\"$repo\",\"error\":\"gh api failed\"}"
    return
  }

  local allow_auto_merge default_branch
  allow_auto_merge=$(echo "$meta" | jq -r '.allow_auto_merge')
  default_branch=$(echo "$meta" | jq -r '.default_branch')

  # Fetch branch protection (may 404 if none exists)
  local protection_raw has_protection required_checks
  protection_raw=$(gh api "repos/$repo/branches/$default_branch/protection" 2>/dev/null) || protection_raw=""

  if [[ -z "$protection_raw" ]]; then
    has_protection=false
    required_checks='[]'
  else
    has_protection=true
    required_checks=$(echo "$protection_raw" \
      | jq -c '[.required_status_checks.contexts // [] | .[]]' 2>/dev/null || echo '[]')
  fi

  # Build missing list
  local missing='[]'
  if [[ "$allow_auto_merge" != "true" ]]; then
    missing=$(echo "$missing" | jq '. + ["allow_auto_merge"]')
  fi
  if [[ "$has_protection" == "false" ]]; then
    missing=$(echo "$missing" | jq '. + ["branch_protection"]')
  elif [[ "$(echo "$required_checks" | jq 'length')" -eq 0 ]]; then
    missing=$(echo "$missing" | jq '. + ["required_checks"]')
  fi

  local ready
  if [[ "$(echo "$missing" | jq 'length')" -eq 0 ]]; then
    ready=true
  else
    ready=false
  fi

  jq -n \
    --arg repo "$repo" \
    --argjson allow_auto_merge "$([ "$allow_auto_merge" = "true" ] && echo true || echo false)" \
    --arg default_branch "$default_branch" \
    --argjson has_protection "$([ "$has_protection" = "true" ] && echo true || echo false)" \
    --argjson required_checks "$required_checks" \
    --argjson ready_for_auto_merge "$ready" \
    --argjson missing "$missing" \
    '{repo: $repo, allow_auto_merge: $allow_auto_merge, default_branch: $default_branch,
      has_protection: $has_protection, required_checks: $required_checks,
      ready_for_auto_merge: $ready_for_auto_merge, missing: $missing}'
}

for repo in "$@"; do
  results+=("$(audit_repo "$repo")")
done

printf '%s\n' "${results[@]}" | jq -s '.'
