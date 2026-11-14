#!/usr/bin/env bash
# fetch-alerts.sh — Collect GitHub security alerts for the repo in the current directory.
#
# Usage:
#   bash fetch-alerts.sh [output_dir]
#
# output_dir defaults to a fresh `mktemp -d` outside the repo, so alert data never lands in the
# working tree; the path is printed on the last line.
#
# Output:
#   ${OUTPUT_DIR}/repo.txt             — "owner/name url" of the scanned repo
#   ${OUTPUT_DIR}/dependabot.json      — Dependabot vulnerability alerts (GraphQL)
#   ${OUTPUT_DIR}/code-scanning.json   — Code scanning alerts (REST)
#   ${OUTPUT_DIR}/secret-scanning.json — Secret scanning alerts (REST, secrets redacted)
#   ${OUTPUT_DIR}/<type>.disabled      — present when that feature is not enabled (403/404)
#   ${OUTPUT_DIR}/.fetch-errors        — present when any fetch failed; zero counts are then unreliable
#
# Requirements: gh CLI authenticated (gh auth status); run inside a GitHub repo checkout.
# Exit codes: 1 = gh not authenticated, 2 = not inside a git checkout with an origin remote,
#             3 = gh could not resolve the origin remote as a GitHub repo

set -euo pipefail

OUTPUT_DIR="${1:-$(mktemp -d "${TMPDIR:-/tmp}/security-scan.XXXXXX")}"

# --- Pre-flight: auth check ---
if ! gh auth status &>/dev/null; then
  echo "ERROR: gh CLI not authenticated. Run: gh auth login" >&2
  exit 1
fi

# --- Step 1: Resolve the repo of the current directory ---
# Use the checkout's origin remote explicitly: bare `gh repo view` follows GH_REPO and
# prefers an `upstream` remote, which in a fork would scan a different repo.
if ! ORIGIN_URL=$(git remote get-url origin 2>/dev/null); then
  echo "ERROR: not inside a git checkout with an origin remote" >&2
  exit 2
fi
if ! REPO_INFO=$(env -u GH_REPO gh repo view "${ORIGIN_URL}" --json owner,name,url \
    -q '"\(.owner.login) \(.name) \(.url)"' 2>&1); then
  echo "ERROR: gh could not resolve origin (${ORIGIN_URL}) as a GitHub repo: ${REPO_INFO}" >&2
  exit 3
fi
read -r OWNER REPO REPO_URL <<< "${REPO_INFO}"
echo "Scanning: ${OWNER}/${REPO}"

mkdir -p "${OUTPUT_DIR}"
rm -f "${OUTPUT_DIR}/.fetch-errors" "${OUTPUT_DIR}"/*.disabled
echo "${OWNER}/${REPO} ${REPO_URL}" > "${OUTPUT_DIR}/repo.txt"

# --- Step 2: Dependabot alerts via GraphQL ---
echo "Fetching Dependabot alerts..."
if ! DB_ERR=$(gh api graphql -f owner="${OWNER}" -f name="${REPO}" -f query='
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
}' 2>&1 > "${OUTPUT_DIR}/dependabot.json"); then
  echo "ERROR: dependabot GraphQL query failed: ${DB_ERR}" >> "${OUTPUT_DIR}/.fetch-errors"
fi

# --- Step 3: Code Scanning + Secret Scanning via REST ---
echo "Fetching Code Scanning and Secret Scanning alerts..."

# Code Scanning (403/404 = not enabled, skip gracefully)
# NOTE: other API errors (e.g. 503) fall through to "[]" — check ${OUTPUT_DIR}/.fetch-errors.
if CS_RESP=$(gh api "repos/${OWNER}/${REPO}/code-scanning/alerts?state=open&per_page=100" 2>&1); then
  echo "${CS_RESP}" > "${OUTPUT_DIR}/code-scanning.json"
else
  HTTP_STATUS=$(echo "${CS_RESP}" | grep -oE 'HTTP [0-9]+' | grep -oE '[0-9]+' | head -1 || true)
  if [[ "${HTTP_STATUS}" == "403" || "${HTTP_STATUS}" == "404" ]]; then
    touch "${OUTPUT_DIR}/code-scanning.disabled"
  else
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
  if [[ "${HTTP_STATUS}" == "404" ]]; then
    touch "${OUTPUT_DIR}/secret-scanning.disabled"
  else
    echo "ERROR: secret-scanning fetch failed (status=${HTTP_STATUS:-unknown}): ${SS_RESP}" \
      >> "${OUTPUT_DIR}/.fetch-errors"
  fi
  echo "[]" > "${OUTPUT_DIR}/secret-scanning.json"
fi

if [[ -f "${OUTPUT_DIR}/.fetch-errors" ]]; then
  echo "WARNING: Some fetches failed. See ${OUTPUT_DIR}/.fetch-errors for details." >&2
fi

echo "Done. Results in:"
echo "${OUTPUT_DIR}"
