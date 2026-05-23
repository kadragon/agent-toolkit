#!/usr/bin/env bash
# fetch-alerts.sh — Collect all GitHub security alerts for the authenticated user's repos.
#
# Usage:
#   bash fetch-alerts.sh [output_dir]
#
# Output:
#   ${OUTPUT_DIR}/dependabot.json   — Dependabot vulnerability alerts (GraphQL)
#   ${OUTPUT_DIR}/code-scanning/    — Per-repo code scanning alerts (REST)
#   ${OUTPUT_DIR}/secret-scanning/  — Per-repo secret scanning alerts (REST, secrets redacted)
#   ${OUTPUT_DIR}/repos.txt         — List of all owned repos (name url)
#
# Requirements: gh CLI authenticated (gh auth status)
# Exit codes: 1 = gh not authenticated

set -euo pipefail

OUTPUT_DIR="${1:-.security-scan}"
mkdir -p "${OUTPUT_DIR}/code-scanning" "${OUTPUT_DIR}/secret-scanning"

# --- Pre-flight: auth check ---
if ! gh auth status &>/dev/null; then
  echo "ERROR: gh CLI not authenticated. Run: gh auth login" >&2
  exit 1
fi

GH_USER=$(gh api user --jq '.login')
echo "Authenticated as: ${GH_USER}"

# --- Step 1: List all owned repos ---
echo "Listing repos..."
gh repo list "${GH_USER}" --json name,url --limit 300 -q '.[] | "\(.name) \(.url)"' \
  > "${OUTPUT_DIR}/repos.txt"

REPO_COUNT=$(wc -l < "${OUTPUT_DIR}/repos.txt" | tr -d ' ')
echo "Found ${REPO_COUNT} repos."

if [[ $REPO_COUNT -eq 300 ]]; then
  echo "WARNING: repo list may be truncated at 300 — accounts with 300+ repos may have missing results" >&2
fi

# --- Step 2: Dependabot alerts via GraphQL (paginated) ---
echo "Fetching Dependabot alerts via GraphQL..."
gh api graphql --paginate -f query='
{
  viewer {
    repositories(first: 100, ownerAffiliations: OWNER) {
      nodes {
        name
        url
        vulnerabilityAlerts(first: 100, states: OPEN) {
          totalCount
          nodes {
            securityVulnerability {
              package { name ecosystem }
              severity
              advisory { summary ghsaId }
              firstPatchedVersion { identifier }
            }
          }
        }
      }
    }
  }
}' > "${OUTPUT_DIR}/dependabot.json" 2>/dev/null || {
  echo "WARNING: GraphQL query failed (may lack permissions). Continuing..." >&2
}

# --- Step 3: Code Scanning + Secret Scanning via REST ---
echo "Fetching Code Scanning and Secret Scanning alerts..."

while read -r REPO _URL; do
  # Code Scanning (403/404 = not enabled, skip gracefully)
  # NOTE: API errors (e.g. 503) fall through to "[]" — treat zero results as potentially
  # incomplete if combined with network issues. Check ${OUTPUT_DIR}/.fetch-errors for details.
  if CS_RESP=$(gh api "repos/${GH_USER}/${REPO}/code-scanning/alerts?state=open&per_page=100" 2>&1); then
    echo "${CS_RESP}" > "${OUTPUT_DIR}/code-scanning/${REPO}.json"
  else
    HTTP_STATUS=$(echo "${CS_RESP}" | grep -oE 'HTTP [0-9]+' | grep -oE '[0-9]+' | head -1)
    if [[ "${HTTP_STATUS}" == "403" || "${HTTP_STATUS}" == "404" ]]; then
      echo "[]" > "${OUTPUT_DIR}/code-scanning/${REPO}.json"
    else
      echo "ERROR: code-scanning fetch failed for ${REPO} (status=${HTTP_STATUS:-unknown}): ${CS_RESP}" \
        >> "${OUTPUT_DIR}/.fetch-errors"
      echo "[]" > "${OUTPUT_DIR}/code-scanning/${REPO}.json"
    fi
  fi

  # Secret Scanning (404 = disabled, skip gracefully; strip secret values)
  # NOTE: API errors (e.g. 503) fall through to "[]" — check ${OUTPUT_DIR}/.fetch-errors.
  if SS_RESP=$(gh api "repos/${GH_USER}/${REPO}/secret-scanning/alerts?state=open&per_page=100" \
      --jq '[.[] | del(.secret)]' 2>&1); then
    echo "${SS_RESP}" > "${OUTPUT_DIR}/secret-scanning/${REPO}.json"
  else
    HTTP_STATUS=$(echo "${SS_RESP}" | grep -oE 'HTTP [0-9]+' | grep -oE '[0-9]+' | head -1)
    if [[ "${HTTP_STATUS}" == "404" ]]; then
      echo "[]" > "${OUTPUT_DIR}/secret-scanning/${REPO}.json"
    else
      echo "ERROR: secret-scanning fetch failed for ${REPO} (status=${HTTP_STATUS:-unknown}): ${SS_RESP}" \
        >> "${OUTPUT_DIR}/.fetch-errors"
      echo "[]" > "${OUTPUT_DIR}/secret-scanning/${REPO}.json"
    fi
  fi
done < "${OUTPUT_DIR}/repos.txt"

if [[ -f "${OUTPUT_DIR}/.fetch-errors" ]]; then
  echo "WARNING: Some fetches failed. See ${OUTPUT_DIR}/.fetch-errors for details." >&2
fi

echo "Done. Results in ${OUTPUT_DIR}/"
