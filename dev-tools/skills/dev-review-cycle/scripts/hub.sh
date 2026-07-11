#!/usr/bin/env bash
# Hub adapter: routes PR/CI/merge operations to the right backend.
#   - github  → gh CLI (github.com remotes)
#   - forgejo → Forgejo/Gitea REST API via curl (any other remote host)
#
# Usage: hub.sh <subcommand> [args]
#   detect                                  → {hub_type, host, api_url, owner_repo, token_present, errors[]}
#   repo-info                               → {default_branch, merge_strategy:{squash,merge,rebase}}
#   pr-create --base <b> --title <t> --body <body> → {pr_number, pr_url}
#   pr-get                                  → {pr_number, pr_url}   (open PR for current branch)
#   ci-status <pr_number>                   → {status: "pending"|"success"|"failure"|"none", checks: n}
#   ci-logs <pr_number>                     → {failed_checks:[{name,run_id,logs}], count, logs_available}
#   merge <pr_number> <squash|merge|rebase> → {merge_ok, merge_output}
#
# Auth:
#   github  — gh CLI must be authenticated (gh auth login)
#   forgejo — FORGEJO_TOKEN or GITEA_TOKEN env var (personal access token)
#   DRC_HUB_API_URL overrides the derived API base URL (e.g. non-standard port).

set -euo pipefail

SUBCOMMAND="${1:?Usage: hub.sh <detect|repo-info|pr-create|pr-get|ci-status|ci-logs|merge> [args]}"
shift

# --- Remote parsing (no network) ---
REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
HOST=""
OWNER_REPO=""
if [ -n "$REMOTE_URL" ]; then
  case "$REMOTE_URL" in
    git@*)      # git@host:owner/repo(.git)
      HOST="${REMOTE_URL#git@}"; HOST="${HOST%%:*}"
      OWNER_REPO="${REMOTE_URL#*:}" ;;
    ssh://*)    # ssh://git@host[:port]/owner/repo(.git)
      STRIPPED="${REMOTE_URL#ssh://}"; STRIPPED="${STRIPPED#*@}"
      HOST="${STRIPPED%%/*}"; HOST="${HOST%%:*}"
      OWNER_REPO="${STRIPPED#*/}" ;;
    http://*|https://*)  # http(s)://host[:port]/owner/repo(.git)
      STRIPPED="${REMOTE_URL#*://}"; STRIPPED="${STRIPPED#*@}"
      HOST="${STRIPPED%%/*}"; HOST="${HOST%%:*}"
      OWNER_REPO="${STRIPPED#*/}" ;;
  esac
  OWNER_REPO="${OWNER_REPO%.git}"
fi

HUB_TYPE="none"
if [ "$HOST" = "github.com" ]; then
  HUB_TYPE="github"
elif [ -n "$HOST" ]; then
  HUB_TYPE="forgejo"
fi

# --- Forgejo helpers ---
API_URL="${DRC_HUB_API_URL:-https://${HOST}/api/v1}"
TOKEN="${FORGEJO_TOKEN:-${GITEA_TOKEN:-}}"

# fj_api <method> <path> [json_body] — prints body; returns non-zero on HTTP >= 400.
# fj_api is almost always invoked inside command substitution or a pipeline —
# both subshells, where a plain variable assignment cannot reach the parent.
# The HTTP code is persisted to a temp file instead; read it with fj_code.
FJ_CODE_FILE="$(mktemp)"
trap 'rm -f "$FJ_CODE_FILE"' EXIT
fj_code() { cat "$FJ_CODE_FILE" 2>/dev/null || printf '000'; }
fj_api() {
  local method="$1" path="$2" body="${3:-}"
  local resp code body_file
  # Non-ASCII (e.g. Korean) passed via -d "$body" gets mangled by this
  # environment's native curl.exe through an ANSI codepage reencode.
  # Route the body through a temp file + --data-binary to preserve raw UTF-8 bytes.
  if [ -n "$body" ]; then
    body_file="$(mktemp)"
    printf '%s' "$body" >"$body_file"
    resp=$(curl -sS -X "$method" \
      -H "Authorization: token ${TOKEN}" \
      -H "Content-Type: application/json" \
      --data-binary "@${body_file}" \
      -w $'\n%{http_code}' \
      "${API_URL}${path}") || { rm -f "$body_file"; printf '000' >"$FJ_CODE_FILE"; return 1; }
    rm -f "$body_file"
  else
    resp=$(curl -sS -X "$method" \
      -H "Authorization: token ${TOKEN}" \
      -H "Content-Type: application/json" \
      -w $'\n%{http_code}' \
      "${API_URL}${path}") || { printf '000' >"$FJ_CODE_FILE"; return 1; }
  fi
  code="${resp##*$'\n'}"
  printf '%s' "$code" >"$FJ_CODE_FILE"
  printf '%s' "${resp%$'\n'*}"
  [ "$code" -lt 400 ]
}

require_forgejo_token() {
  if [ -z "$TOKEN" ]; then
    echo '{"error": "Forgejo remote detected but no token. Set FORGEJO_TOKEN or GITEA_TOKEN."}' >&2
    exit 1
  fi
}

current_branch() { git branch --show-current; }

# Map gh `pr checks` exit/buckets and Forgejo combined status to one vocabulary.
emit_status() { jq -n --arg s "$1" --argjson n "${2:-0}" '{status: $s, checks: $n}'; }

case "$SUBCOMMAND" in

  detect)
    errors=()
    TOKEN_PRESENT=false
    if [ "$HUB_TYPE" = "none" ]; then
      errors+=("No usable git remote 'origin' found.")
    elif [ "$HUB_TYPE" = "github" ]; then
      if gh auth status >/dev/null 2>&1; then
        TOKEN_PRESENT=true
      else
        errors+=("gh CLI not authenticated. Run 'gh auth login' first.")
      fi
    else
      if [ -n "$TOKEN" ]; then
        TOKEN_PRESENT=true
        # Probe the API to confirm a Forgejo/Gitea-compatible server.
        if ! fj_api GET "/version" >/dev/null 2>&1; then
          errors+=("Remote host '${HOST}' did not answer ${API_URL}/version (HTTP $(fj_code)). Set DRC_HUB_API_URL if the API base differs.")
        fi
      else
        errors+=("Forgejo/Gitea remote '${HOST}' detected but no token. Set FORGEJO_TOKEN or GITEA_TOKEN.")
      fi
    fi
    ERRORS_JSON="[]"
    if [ ${#errors[@]} -gt 0 ]; then
      ERRORS_JSON=$(printf '%s\n' "${errors[@]}" | jq -R . | jq -s .)
    fi
    jq -n \
      --arg hub_type "$HUB_TYPE" \
      --arg host "$HOST" \
      --arg api_url "$API_URL" \
      --arg owner_repo "$OWNER_REPO" \
      --argjson token_present "$TOKEN_PRESENT" \
      --argjson errors "$ERRORS_JSON" \
      '{hub_type: $hub_type, host: $host, api_url: (if $hub_type == "forgejo" then $api_url else null end), owner_repo: $owner_repo, token_present: $token_present, errors: $errors}'
    ;;

  repo-info)
    if [ "$HUB_TYPE" = "github" ]; then
      DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo "")
      NWO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
      MERGE_INFO='{}'
      if [ -n "$NWO" ]; then
        MERGE_INFO=$(gh api "repos/${NWO}" --jq '{squash: .allow_squash_merge, merge: .allow_merge_commit, rebase: .allow_rebase_merge}' 2>/dev/null || echo '{}')
      fi
      jq -n --arg db "$DEFAULT_BRANCH" --arg or "$NWO" --argjson ms "$MERGE_INFO" \
        '{default_branch: (if $db == "" then null else $db end), owner_repo: $or, merge_strategy: $ms}'
    else
      require_forgejo_token
      REPO_JSON=$(fj_api GET "/repos/${OWNER_REPO}") || {
        echo "{\"error\": \"Failed to fetch repo info (HTTP $(fj_code))\"}" >&2; exit 1; }
      printf '%s' "$REPO_JSON" | jq --arg or "$OWNER_REPO" \
        '{default_branch: .default_branch, owner_repo: $or, merge_strategy: {squash: .allow_squash_merge, merge: .allow_merge_commits, rebase: .allow_rebase}}'
    fi
    ;;

  pr-create)
    BASE=""; TITLE=""; BODY=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --base)  BASE="$2";  shift 2 ;;
        --title) TITLE="$2"; shift 2 ;;
        --body)  BODY="$2";  shift 2 ;;
        *) echo "ERROR: Unknown flag: $1" >&2; exit 1 ;;
      esac
    done
    : "${BASE:?--base required}" "${TITLE:?--title required}"
    if [ "$HUB_TYPE" = "github" ]; then
      PR_URL=$(gh pr create --title "$TITLE" --body "$BODY" --base "$BASE" 2>&1 \
        | grep -E '^https://' | head -1 || true)
      if [ -z "$PR_URL" ]; then
        # gh pr create fails when a PR already exists for this branch (re-run).
        PR_URL=$(gh pr view --json url --jq '.url' 2>/dev/null || true)
      fi
      PR_NUMBER=$(printf '%s' "$PR_URL" | grep -oE '[0-9]+$' || true)
      jq -n --arg n "$PR_NUMBER" --arg u "$PR_URL" \
        '{pr_number: (if $n == "" then null else $n end), pr_url: (if $u == "" then null else $u end)}'
    else
      require_forgejo_token
      HEAD_BRANCH=$(current_branch)
      PAYLOAD=$(jq -n --arg head "$HEAD_BRANCH" --arg base "$BASE" --arg title "$TITLE" --arg body "$BODY" \
        '{head: $head, base: $base, title: $title, body: $body}')
      PR_JSON=$(fj_api POST "/repos/${OWNER_REPO}/pulls" "$PAYLOAD") || true
      if [ "$(fj_code)" = "409" ] || [ -z "$PR_JSON" ] || ! jq -e '.number' <<<"$PR_JSON" >/dev/null 2>&1; then
        # PR already exists (or create failed) — look up the open PR for this branch.
        PR_JSON=$(fj_api GET "/repos/${OWNER_REPO}/pulls?state=open&limit=50" \
          | jq --arg head "$HEAD_BRANCH" '[.[] | select(.head.ref == $head)] | first // empty') || true
      fi
      if [ -z "$PR_JSON" ] || ! jq -e '.number' <<<"$PR_JSON" >/dev/null 2>&1; then
        echo "{\"error\": \"PR create failed (HTTP $(fj_code)) and no existing PR found for branch ${HEAD_BRANCH}\"}" >&2
        exit 1
      fi
      printf '%s' "$PR_JSON" | jq '{pr_number: (.number | tostring), pr_url: .html_url}'
    fi
    ;;

  pr-get)
    if [ "$HUB_TYPE" = "github" ]; then
      PR_JSON=$(gh pr view --json number,url 2>/dev/null || echo '{}')
      printf '%s' "$PR_JSON" | jq '{pr_number: (if .number then (.number | tostring) else null end), pr_url: (.url // null)}'
    else
      require_forgejo_token
      HEAD_BRANCH=$(current_branch)
      PR_JSON=$(fj_api GET "/repos/${OWNER_REPO}/pulls?state=open&limit=50" \
        | jq --arg head "$HEAD_BRANCH" '[.[] | select(.head.ref == $head)] | first // {}') || PR_JSON='{}'
      printf '%s' "$PR_JSON" | jq '{pr_number: (if .number then (.number | tostring) else null end), pr_url: (.html_url // null)}'
    fi
    ;;

  ci-status)
    PR_NUMBER="${1:?Usage: hub.sh ci-status <pr_number>}"
    if [ "$HUB_TYPE" = "github" ]; then
      EXIT=0
      CHECKS=$(gh pr checks "$PR_NUMBER" --json bucket 2>/dev/null) || EXIT=$?
      # gh pr checks exits 1 when any check FAILED — while still printing the
      # check JSON. Trust the JSON over the exit code: parse buckets whenever a
      # non-empty array came back, regardless of exit status.
      if jq -e 'type == "array" and length > 0' <<<"${CHECKS:-null}" >/dev/null 2>&1; then
        TOTAL=$(jq 'length' <<<"$CHECKS")
        PENDING=$(jq '[.[] | select(.bucket == "pending")] | length' <<<"$CHECKS")
        FAILED=$(jq '[.[] | select(.bucket == "fail" or .bucket == "cancel")] | length' <<<"$CHECKS")
        if [ "$PENDING" -gt 0 ]; then emit_status "pending" "$TOTAL"
        elif [ "$FAILED" -gt 0 ]; then emit_status "failure" "$TOTAL"
        else emit_status "success" "$TOTAL"; fi
      elif [ "$EXIT" -eq 8 ]; then
        emit_status "pending" 0
      else
        # No parseable checks: gh exits 1 with empty stdout when no checks are
        # reported on the branch ("none" lets the caller apply its grace logic).
        emit_status "none" 0
      fi
    else
      require_forgejo_token
      HEAD_SHA=$(fj_api GET "/repos/${OWNER_REPO}/pulls/${PR_NUMBER}" | jq -r '.head.sha // empty') || true
      if [ -z "$HEAD_SHA" ]; then
        echo "{\"error\": \"Could not resolve head SHA for PR ${PR_NUMBER} (HTTP $(fj_code))\"}" >&2
        exit 1
      fi
      COMBINED=$(fj_api GET "/repos/${OWNER_REPO}/commits/${HEAD_SHA}/status") || COMBINED='{}'
      TOTAL=$(jq '.statuses | length' <<<"$COMBINED" 2>/dev/null || echo 0)
      STATE=$(jq -r '.state // empty' <<<"$COMBINED")
      if [ "$TOTAL" -eq 0 ]; then
        emit_status "none" 0
      else
        case "$STATE" in
          success)        emit_status "success" "$TOTAL" ;;
          failure|error)  emit_status "failure" "$TOTAL" ;;
          *)              emit_status "pending" "$TOTAL" ;;
        esac
      fi
    fi
    ;;

  ci-logs)
    PR_NUMBER="${1:?Usage: hub.sh ci-logs <pr_number>}"
    if [ "$HUB_TYPE" = "github" ]; then
      FAILED_CHECKS=$(gh pr checks "$PR_NUMBER" --json name,state,link \
        --jq '[.[] | select(.state == "FAILURE")]' 2>/dev/null || echo '[]')
      if [ "$FAILED_CHECKS" = "[]" ] || [ -z "$FAILED_CHECKS" ]; then
        echo '{"failed_checks": [], "count": 0, "logs_available": true, "message": "No failed checks found"}'
        exit 0
      fi
      RESULTS="[]"
      while IFS= read -r check; do
        NAME=$(jq -r '.name' <<<"$check")
        LINK=$(jq -r '.link' <<<"$check")
        RUN_ID=$(printf '%s' "$LINK" | grep -oE '/runs/[0-9]+' | grep -oE '[0-9]+' | head -1 || true)
        LOGS=""
        if [ -n "$RUN_ID" ]; then
          # Limit to last 200 lines per job to avoid context/memory overflow
          LOGS=$(gh run view "$RUN_ID" --log-failed 2>&1 | tail -200 || echo "Failed to fetch logs for run $RUN_ID")
        else
          LOGS="Could not extract run ID from link: $LINK"
        fi
        RESULTS=$(jq --arg name "$NAME" --arg run_id "${RUN_ID:-unknown}" --arg logs "$LOGS" \
          '. + [{"name": $name, "run_id": $run_id, "logs": $logs}]' <<<"$RESULTS")
      done < <(jq -c '.[]' <<<"$FAILED_CHECKS")
      jq '{failed_checks: ., count: length, logs_available: true}' <<<"$RESULTS"
    else
      require_forgejo_token
      # Forgejo ≤ v15 exposes no job-log API. Return failed status contexts with
      # their target URLs so the orchestrator can surface links to the user.
      HEAD_SHA=$(fj_api GET "/repos/${OWNER_REPO}/pulls/${PR_NUMBER}" | jq -r '.head.sha // empty') || true
      if [ -z "$HEAD_SHA" ]; then
        echo "{\"error\": \"Could not resolve head SHA for PR ${PR_NUMBER} (HTTP $(fj_code))\"}" >&2
        exit 1
      fi
      COMBINED=$(fj_api GET "/repos/${OWNER_REPO}/commits/${HEAD_SHA}/status") || COMBINED='{}'
      jq '{
        failed_checks: [(.statuses // [])[] | select(.status == "failure" or .status == "error")
          | {name: .context, run_id: null, logs: ("Logs unavailable via Forgejo API — inspect: " + (.target_url // "no URL"))}],
        logs_available: false
      } | .count = (.failed_checks | length)' <<<"$COMBINED"
    fi
    ;;

  merge)
    PR_NUMBER="${1:?Usage: hub.sh merge <pr_number> <squash|merge|rebase>}"
    STRATEGY="${2:?Usage: hub.sh merge <pr_number> <squash|merge|rebase>}"
    if [ "$HUB_TYPE" = "github" ]; then
      MERGE_OK=true
      MERGE_OUTPUT=$(gh pr merge "$PR_NUMBER" "--${STRATEGY}" --delete-branch 2>&1) || MERGE_OK=false
      jq -n --argjson ok "$MERGE_OK" --arg out "$MERGE_OUTPUT" '{merge_ok: $ok, merge_output: $out}'
    else
      require_forgejo_token
      PAYLOAD=$(jq -n --arg do "$STRATEGY" '{Do: $do, delete_branch_after_merge: true}')
      MERGE_OK=true
      MERGE_OUTPUT=$(fj_api POST "/repos/${OWNER_REPO}/pulls/${PR_NUMBER}/merge" "$PAYLOAD" 2>&1) || MERGE_OK=false
      [ "$MERGE_OK" = "false" ] && MERGE_OUTPUT="HTTP $(fj_code): ${MERGE_OUTPUT}"
      jq -n --argjson ok "$MERGE_OK" --arg out "$MERGE_OUTPUT" '{merge_ok: $ok, merge_output: $out}'
    fi
    ;;

  *)
    echo "ERROR: Unknown subcommand: $SUBCOMMAND" >&2
    exit 1
    ;;
esac
