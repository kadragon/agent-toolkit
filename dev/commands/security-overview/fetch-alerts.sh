#!/usr/bin/env bash
# fetch-alerts.sh — Collect GitHub security alerts for the repo in the current directory.
#
# Usage:
#   bash fetch-alerts.sh [output_dir]
#
# Output:
#   ${OUTPUT_DIR}/repo.txt             — "owner/name url" of the scanned repo
#   ${OUTPUT_DIR}/dependabot.json      — Dependabot vulnerability alerts (GraphQL)
#   ${OUTPUT_DIR}/code-scanning.json   — Code scanning alerts (REST)
#   ${OUTPUT_DIR}/secret-scanning.json — Secret scanning alerts (REST, secrets redacted)
#
# Requirements: gh CLI authenticated (gh auth status); run inside a GitHub repo checkout.
# Exit codes: 1 = gh not authenticated, 2 = current directory is not a GitHub repo

set -euo pipefail

OUTPUT_DIR="${1:-.security-scan}"

# --- Pre-flight: auth check ---
if ! gh auth status &>/dev/null; then
  echo "ERROR: gh CLI not authenticated. Run: gh auth login" >&2
  exit 1
fi

# --- Step 1: Resolve the repo of the current directory ---
if ! REPO_INFO=$(gh repo view --json owner,name,url -q '"\(.owner.login) \(.name) \(.url)"' 2>/dev/null); then
  echo "ERROR: current directory is not a GitHub repository (gh repo view failed)" >&2
  exit 2
fi
read -r OWNER REPO REPO_URL <<< "${REPO_INFO}"
echo "Scanning: ${OWNER}/${REPO}"

mkdir -p "${OUTPUT_DIR}"
rm -f "${OUTPUT_DIR}/.fetch-errors"
echo "${OWNER}/${REPO} ${REPO_URL}" > "${OUTPUT_DIR}/repo.txt"

# --- Step 2: Dependabot alerts via GraphQL ---
echo "Fetching Dependabot alerts..."
gh api graphql -F owner="${OWNER}" -F name="${REPO}" -f query='
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
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
}' > "${OUTPUT_DIR}/dependabot.json" 2>/dev/null || {
  echo "WARNING: GraphQL query failed (may lack permissions). Continuing..." >&2
}

# --- Step 3: Code Scanning + Secret Scanning via REST ---
echo "Fetching Code Scanning and Secret Scanning alerts..."

# Code Scanning (403/404 = not enabled, skip gracefully)
# NOTE: other API errors (e.g. 503) fall through to "[]" — check ${OUTPUT_DIR}/.fetch-errors.
if CS_RESP=$(gh api "repos/${OWNER}/${REPO}/code-scanning/alerts?state=open&per_page=100" 2>&1); then
  echo "${CS_RESP}" > "${OUTPUT_DIR}/code-scanning.json"
else
  HTTP_STATUS=$(echo "${CS_RESP}" | grep -oE 'HTTP [0-9]+' | grep -oE '[0-9]+' | head -1 || true)
  if [[ "${HTTP_STATUS}" != "403" && "${HTTP_STATUS}" != "404" ]]; then
    echo "ERROR: code-scanning fetch failed (status=${HTTP_STATUS:-unknown}): ${CS_RESP}" \
      >> "${OUTPUT_DIR}/.fetch-errors"
  fi
  echo "[]" > "${OUTPUT_DIR}/code-scanning.json"
fi

# Secret Scanning (404 = disabled, skip gracefully; strip secret values)
if SS_RESP=$(gh api "repos/${OWNER}/${REPO}/secret-scanning/alerts?state=open&per_page=100" \
    --jq '[.[] | del(.secret)]' 2>&1); then
  echo "${SS_RESP}" > "${OUTPUT_DIR}/secret-scanning.json"
else
  HTTP_STATUS=$(echo "${SS_RESP}" | grep -oE 'HTTP [0-9]+' | grep -oE '[0-9]+' | head -1 || true)
  if [[ "${HTTP_STATUS}" != "404" ]]; then
    echo "ERROR: secret-scanning fetch failed (status=${HTTP_STATUS:-unknown}): ${SS_RESP}" \
      >> "${OUTPUT_DIR}/.fetch-errors"
  fi
  echo "[]" > "${OUTPUT_DIR}/secret-scanning.json"
fi

if [[ -f "${OUTPUT_DIR}/.fetch-errors" ]]; then
  echo "WARNING: Some fetches failed. See ${OUTPUT_DIR}/.fetch-errors for details." >&2
fi

echo "Done. Results in ${OUTPUT_DIR}/"
