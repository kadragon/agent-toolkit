#!/usr/bin/env bash
# Enable auto-merge for a single repo.
# Usage: enable-automerge.sh "owner/repo"
# Output: JSON {repo, allow_auto_merge, protection_action, contexts}
#   protection_action: created | already_present | skipped | unsupported_plan

set -euo pipefail

repo="$1"

# Step 1: Enable allow_auto_merge at repo level
patch_err=$(gh api -X PATCH "repos/$repo" -F allow_auto_merge=true --silent 2>&1) || {
  echo "ERROR: failed to enable allow_auto_merge on $repo: ${patch_err:-unknown}" >&2
  exit 1
}

# Step 2: Check existing branch protection
default_branch=$(gh api "repos/$repo" --jq '.default_branch')
protection_raw=$(gh api "repos/$repo/branches/$default_branch/protection" 2>/dev/null) || protection_raw=""

if [[ -n "$protection_raw" ]]; then
  # Already has protection — don't overwrite
  contexts=$(echo "$protection_raw" | jq -c '[.required_status_checks.contexts // [] | .[]]' 2>/dev/null || echo '[]')
  jq -n \
    --arg repo "$repo" \
    --arg default_branch "$default_branch" \
    --argjson contexts "$contexts" \
    '{repo: $repo, allow_auto_merge: true, default_branch: $default_branch,
      protection_action: "already_present", contexts: $contexts}'
  exit 0
fi

# Step 3: No protection — collect check names from most recent dependabot PR
contexts_json='[]'
recent_pr=$(gh pr list --repo "$repo" --author app/dependabot --state all --limit 5 \
  --json number,statusCheckRollup 2>/dev/null \
  | jq -r '[.[] | select(.statusCheckRollup | length > 0)] | first | .number // empty')

if [[ -n "$recent_pr" ]]; then
  contexts_json=$(gh pr view "$recent_pr" --repo "$repo" \
    --json statusCheckRollup \
    --jq '[.statusCheckRollup[].name] | unique' 2>/dev/null || echo '[]')
fi

if [[ "$(echo "$contexts_json" | jq 'length')" -eq 0 ]]; then
  # No CI signal — skip protection creation, report skipped
  jq -n \
    --arg repo "$repo" \
    --arg default_branch "$default_branch" \
    '{repo: $repo, allow_auto_merge: true, default_branch: $default_branch,
      protection_action: "skipped", contexts: [],
      note: "no CI signal found — branch protection not created; auto-merge may fire immediately"}'
  exit 0
fi

# Step 4: Create minimal branch protection with required status checks
protection_payload=$(jq -n \
  --argjson contexts "$contexts_json" \
  '{
    required_status_checks: {strict: false, contexts: $contexts},
    enforce_admins: false,
    required_pull_request_reviews: null,
    restrictions: null
  }')

put_err=$(echo "$protection_payload" | gh api -X PUT "repos/$repo/branches/$default_branch/protection" \
  --input - --silent 2>&1) || {
  # Plan limitation: branch protection on private repos needs GitHub Pro.
  # Not a script failure — report and exit 0 so batch runs survive.
  if echo "$put_err" | grep -qiE "Upgrade to GitHub Pro|make this repository public"; then
    jq -n \
      --arg repo "$repo" \
      --arg default_branch "$default_branch" \
      '{repo: $repo, allow_auto_merge: true, default_branch: $default_branch,
        protection_action: "unsupported_plan", contexts: [],
        note: "branch protection unavailable (private repo on free plan); auto-merge may fire immediately"}'
    exit 0
  fi
  echo "ERROR: failed to set branch protection on $repo/$default_branch: ${put_err:-unknown}" >&2
  exit 1
}

jq -n \
  --arg repo "$repo" \
  --arg default_branch "$default_branch" \
  --argjson contexts "$contexts_json" \
  '{repo: $repo, allow_auto_merge: true, default_branch: $default_branch,
    protection_action: "created", contexts: $contexts}'
