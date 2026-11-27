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
#   ${OUTPUT_DIR}/visibility.txt       — visibility of the scanned repo from gh repo view
#   ${OUTPUT_DIR}/dependabot.json      — Dependabot vulnerability alerts (GraphQL)
#   ${OUTPUT_DIR}/code-scanning.json   — Code scanning alerts (REST)
#   ${OUTPUT_DIR}/secret-scanning.json — Secret scanning alerts (REST, secrets redacted)
#   ${OUTPUT_DIR}/<type>.disabled      — present when GitHub explicitly says a feature is disabled
#   ${OUTPUT_DIR}/<type>.truncated     — present when a result may omit alerts
#   ${OUTPUT_DIR}/.fetch-errors        — one diagnostic naming each type that failed
#
# Requirements: jq and authenticated gh CLI; run inside a GitHub repo checkout.
# Exit codes: 1 = missing prerequisite, 2 = not inside a git checkout with an origin remote,
#             3 = gh could not resolve the origin remote as a GitHub repo

set -euo pipefail

OUTPUT_DIR="${1:-$(mktemp -d "${TMPDIR:-/tmp}/security-scan.XXXXXX")}"

# --- Pre-flight: auth check ---
if ! gh auth status &>/dev/null; then
  echo "ERROR: gh CLI not authenticated. Run: gh auth login" >&2
  exit 1
fi
if ! command -v jq >/dev/null; then
  echo "ERROR: jq is required to validate scan results" >&2
  exit 1
fi

# --- Step 1: Resolve the repo of the current directory ---
# Use the checkout's origin remote explicitly: bare `gh repo view` follows GH_REPO and
# prefers an `upstream` remote, which in a fork would scan a different repo.
if ! ORIGIN_URL=$(git remote get-url origin 2>/dev/null); then
  echo "ERROR: not inside a git checkout with an origin remote" >&2
  exit 2
fi
if ! REPO_INFO=$(env -u GH_REPO gh repo view "${ORIGIN_URL}" --json owner,name,url,visibility \
    -q '"\(.owner.login) \(.name) \(.url) \(.visibility)"' 2>&1); then
  echo "ERROR: gh could not resolve origin (${ORIGIN_URL}) as a GitHub repo: ${REPO_INFO}" >&2
  exit 3
fi
read -r OWNER REPO REPO_URL REPO_VISIBILITY <<< "${REPO_INFO}"
REPO_HOST=${REPO_URL#*://}
REPO_HOST=${REPO_HOST%%/*}
echo "Scanning: ${OWNER}/${REPO}"

mkdir -p "${OUTPUT_DIR}"
for alert_type in dependabot code-scanning secret-scanning; do
  rm -f "${OUTPUT_DIR}/${alert_type}.disabled" "${OUTPUT_DIR}/${alert_type}.truncated"
done
rm -f "${OUTPUT_DIR}/.fetch-errors"
echo "${OWNER}/${REPO} ${REPO_URL}" > "${OUTPUT_DIR}/repo.txt"
printf '%s\n' "${REPO_VISIBILITY}" > "${OUTPUT_DIR}/visibility.txt"

# --- Step 2: Dependabot alerts via GraphQL ---
echo "Fetching Dependabot alerts..."
if ! DB_ERR=$(gh api --hostname "${REPO_HOST}" graphql -f owner="${OWNER}" -f name="${REPO}" -f query='
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    name
    url
    vulnerabilityAlerts(first: 100, states: OPEN) {
      totalCount
      nodes {
        number
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
elif ! DB_UNREAD=$(jq -ser '
  if length != 1 then error("expected one GraphQL result")
  elif (.[0].errors // [] | length) != 0 then error("GraphQL returned errors")
  else .[0].data.repository.vulnerabilityAlerts |
    if (.nodes | type) != "array" or (.totalCount | type) != "number"
       or .totalCount < (.nodes | length) or .totalCount != (.totalCount | floor)
    then error("missing or inconsistent alert count")
    else .totalCount - (.nodes | length)
    end
  end' "${OUTPUT_DIR}/dependabot.json" 2>&1); then
  echo "ERROR: dependabot response incomplete: ${DB_UNREAD}" >> "${OUTPUT_DIR}/.fetch-errors"
elif (( DB_UNREAD > 0 )); then
  touch "${OUTPUT_DIR}/dependabot.truncated"
fi

# --- Step 3: Code Scanning + Secret Scanning via REST ---
echo "Fetching Code Scanning and Secret Scanning alerts..."

fetch_rest_alerts() {
  local alert_type="$1" disabled_feature="$2"
  local response count diagnostic diagnostics_path status=0
  diagnostics_path=$(mktemp "${TMPDIR:-/tmp}/security-scan-diagnostics.XXXXXX")
  response=$(
    gh api --hostname "${REPO_HOST}" \
      "repos/${OWNER}/${REPO}/${alert_type}/alerts?state=open&per_page=100" 2>"${diagnostics_path}" |
      jq -cs --arg alert_type "${alert_type}" '
        if length != 1 or (.[0] | type) != "array" then error("expected one alert array")
        elif $alert_type == "secret-scanning" then .[0] | map(del(.secret))
        else .[0] end' 2>/dev/null
    pipeline_status=("${PIPESTATUS[@]}")
    if (( pipeline_status[0] != 0 )); then exit 2; fi
    if (( pipeline_status[1] != 0 )); then exit 3; fi
  ) || status=$?
  diagnostic=$(<"${diagnostics_path}")
  rm -f "${diagnostics_path}"
  if (( status == 0 )); then
    count=$(jq -er length <<<"${response}")
    printf '%s\n' "${response}" > "${OUTPUT_DIR}/${alert_type}.json"
    if (( count >= 100 )); then
      touch "${OUTPUT_DIR}/${alert_type}.truncated"
    fi
    return
  elif (( status == 3 )); then
    echo "ERROR: ${alert_type} returned invalid alert JSON" >> "${OUTPUT_DIR}/.fetch-errors"
  elif grep -Eiq "^gh: (${disabled_feature}) is (not enabled|disabled) for this repository[.]? \(HTTP (403|404)\)$" \
      <<<"${diagnostic}"; then
    touch "${OUTPUT_DIR}/${alert_type}.disabled"
  else
    printf 'ERROR: %s fetch failed: %s\n' "${alert_type}" "${diagnostic}" >> "${OUTPUT_DIR}/.fetch-errors"
  fi
  echo "[]" > "${OUTPUT_DIR}/${alert_type}.json"
}

fetch_rest_alerts code-scanning 'code scanning|GitHub (Advanced Security|Code Security)'
fetch_rest_alerts secret-scanning 'secret scanning'

if [[ -f "${OUTPUT_DIR}/.fetch-errors" ]]; then
  echo "WARNING: Some fetches failed. See ${OUTPUT_DIR}/.fetch-errors for details." >&2
fi

echo "Done. Results in:"
echo "${OUTPUT_DIR}"
