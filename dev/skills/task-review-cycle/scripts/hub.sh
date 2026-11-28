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
#   ci-status <pr_number>                   → {status: "pending"|"success"|"failure"|"none", checks: n, head_sha?}
#   ci-logs <pr_number> [--expected-head <sha>]
#                                            → {failed_checks:[{name,run_id,logs}], count, logs_available, reason?}
#   merge <pr_number> <squash|merge|rebase> [authority_branch] [expected_head]
#                                            → {merge_ok, queued, unconfirmed, merge_output, head_sha?}
#   --expected-head requires GitHub.
#
# Auth:
#   github  — gh CLI must be authenticated (gh auth login)
#   forgejo — FORGEJO_TOKEN or GITEA_TOKEN env var (personal access token)
#   DRC_HUB_API_URL overrides the derived API base URL (e.g. non-standard port).

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/git-authority.sh"

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

github_push_url_for_pr() (
  local pr_url="$1" pr_number="$2" push_url repo_path
  local url_pattern='^(git@github\.com:|ssh://git@github\.com(:22)?/|https://([^/@[:space:]]+@)?github\.com(:443)?/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$'
  push_url=$(git remote get-url --push --all origin) || return 1
  shopt -s nocasematch
  [[ "$push_url" =~ $url_pattern ]] || return 1
  repo_path="${BASH_REMATCH[5]}"
  [[ "$pr_url" == "https://github.com/${repo_path%.git}/pull/$pr_number" ]] || return 1
  printf '%s\n' "$push_url"
)

# head_sha (ci-status only) names the commit the checks describe; omitted when unknown.
emit_status() {
  jq -n --arg s "$1" --argjson n "${2:-0}" --arg sha "${HEAD_SHA:-}" \
    '{status: $s, checks: $n} + (if $sha == "" then {} else {head_sha: $sha} end)'
}

github_ci_snapshot() {
  # Separate GitHub requests could pair a new head SHA with the previous commit's failure.
  local pr_number="$1" pr_url repo view
  if pr_url=$(gh pr view "$pr_number" --json url --jq .url 2>/dev/null) &&
     [[ "$pr_url" =~ ^https://github\.com/([^/]+/[^/]+)/pull/[0-9]+$ ]]; then
    repo="${BASH_REMATCH[1]}"
  else
    printf '%s\n' '{"repository": null, "oids": [], "checks": []}'
    return
  fi
  view=$(gh api graphql --paginate -F number="$pr_number" \
    -f owner="${repo%%/*}" -f name="${repo#*/}" -f query='
    query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
      repository(owner: $owner, name: $name) { nameWithOwner pullRequest(number: $number) {
        commits(last: 1) { nodes { commit { oid statusCheckRollup {
          contexts(first: 100, after: $endCursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              __typename
              ... on StatusContext { context state createdAt link: targetUrl }
              ... on CheckRun { name status conclusion startedAt databaseId link: detailsUrl
                checkSuite { app { id } workflowRun { event workflow { name } } } }
            } } } } } } } } }' 2>/dev/null) || view=""
  # Collect the streamed pages with jq for gh versions without --slurp.
  jq -sc --arg repo "$repo" '[.[].data.repository] as $repositories
    | [$repositories[].pullRequest.commits.nodes[0].commit] as $c
    | {repository: ($repositories[0].nameWithOwner // $repo),
       oids: ([$c[].oid | strings] | unique),
       checks: [[$c[].statusCheckRollup.contexts.nodes[]?]
         | group_by(if .__typename == "CheckRun"
             then [.name, .checkSuite.app.id, .checkSuite.workflowRun.workflow.name, .checkSuite.workflowRun.event]
             else [.context] end)[]
         | max_by(if .__typename == "CheckRun" then [.databaseId // 0, .startedAt // ""]
                  else .createdAt // "" end)
         | (if .__typename == "CheckRun" then (if .status == "COMPLETED" then .conclusion else "PENDING" end)
            else .state end) as $s
         | {name: (.name // .context), link: .link, state: $s,
            bucket: (if $s == "SUCCESS" or $s == "SKIPPED" or $s == "NEUTRAL" then "pass"
              elif $s == "FAILURE" or $s == "ERROR" or $s == "TIMED_OUT" or $s == "ACTION_REQUIRED"
                or $s == "STARTUP_FAILURE" or $s == "CANCELLED" or $s == "STALE" then "fail"
              else "pending" end)}]}' <<<"$view" 2>/dev/null ||
    jq -nc --arg repo "$repo" '{repository: $repo, oids: [], checks: []}'
}

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
    require_git_authority --action pr-write
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
      SNAPSHOT=$(github_ci_snapshot "$PR_NUMBER")
      HEAD_SHA=$(jq -r 'if (.oids | length) == 1 then .oids[0] // empty else empty end' <<<"$SNAPSHOT")
      BUCKETS=$(jq -c '.checks | map(.bucket)' <<<"$SNAPSHOT")
      TOTAL=$(jq 'length' <<<"$BUCKETS")
      if [ "$(jq '.oids | length' <<<"$SNAPSHOT")" -gt 1 ]; then
        # The head moved between pages: no single commit to judge, so poll again.
        emit_status "pending" "$TOTAL"
      elif [ "$TOTAL" -eq 0 ]; then
        # No checks reported (or the query failed): "none" lets the caller apply its grace logic.
        emit_status "none" 0
      elif jq -e 'any(. == "pending")' <<<"$BUCKETS" >/dev/null; then emit_status "pending" "$TOTAL"
      elif jq -e 'any(. == "fail")' <<<"$BUCKETS" >/dev/null; then emit_status "failure" "$TOTAL"
      else emit_status "success" "$TOTAL"; fi
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
    PR_NUMBER="${1:?Usage: hub.sh ci-logs <pr_number> [--expected-head <sha>]}"
    EXPECTED_HEAD=""
    if [ "$#" -gt 1 ]; then
      if [[ "$HUB_TYPE" != "github" || "$#" -ne 3 || "$2" != "--expected-head" ||
            ! "${3:-}" =~ ^[0-9a-f]{40}$ ]]; then
        echo "Usage: hub.sh ci-logs <pr_number> [--expected-head <sha> (GitHub only)]" >&2
        exit 1
      fi
      EXPECTED_HEAD="$3"
    fi
    if [ "$HUB_TYPE" = "github" ]; then
      SNAPSHOT=$(github_ci_snapshot "$PR_NUMBER")
      HEAD_PROBLEM=$(jq -r --arg expected "$EXPECTED_HEAD" '
        if (.oids | length) == 0 then "head-unavailable"
        elif (.oids | length) > 1 or ($expected != "" and .oids[0] != $expected) then "head-changed"
        else empty end' <<<"$SNAPSHOT")
      if [ -n "$HEAD_PROBLEM" ]; then
        jq -nc --arg reason "$HEAD_PROBLEM" '{failed_checks: [], count: 0, logs_available: true, reason: $reason}'
        exit 0
      fi
      CHECK_REPO=$(jq -r '.repository' <<<"$SNAPSHOT")
      FAILED_CHECKS=$(jq -c '[.checks[] | select(.bucket == "fail")]' <<<"$SNAPSHOT")
      if [ "$FAILED_CHECKS" = "[]" ]; then
        echo '{"failed_checks": [], "count": 0, "logs_available": true, "message": "No failed checks found"}'
        exit 0
      fi
      RESULTS="[]"
      while IFS= read -r check; do
        NAME=$(jq -r '.name' <<<"$check")
        LINK=$(jq -r '.link // empty' <<<"$check")
        CHECK_STATE=$(jq -r '.state' <<<"$check")
        RUN_ID=$(jq -r --arg prefix "https://github.com/${CHECK_REPO}/actions/runs/" '
          (.link // "" | ascii_downcase)
          | select(startswith($prefix | ascii_downcase))
          | ltrimstr($prefix | ascii_downcase)
          | capture("^(?<id>[0-9]+)([/?#]|$)").id' <<<"$check")
        LOGS=""
        if [ -n "$RUN_ID" ]; then
          # Limit to last 200 lines per job to avoid context/memory overflow
          LOGS=$(gh run view "$RUN_ID" --repo "$CHECK_REPO" --log-failed 2>&1 | tail -200 || echo "Failed to fetch logs for run $RUN_ID")
        else
          LOGS="Could not extract run ID from link: $LINK"
        fi
        RESULTS=$(jq --arg name "$NAME" --arg state "$CHECK_STATE" --arg run_id "${RUN_ID:-unknown}" --arg logs "$LOGS" \
          '. + [{name: $name, state: $state, run_id: $run_id, logs: $logs}]' <<<"$RESULTS")
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
    AUTHORITY_BRANCH="${3:-$(git branch --show-current)}"
    require_git_authority --branch "$AUTHORITY_BRANCH" --action base-merge
    PR_NUMBER="${1:?Usage: hub.sh merge <pr_number> <squash|merge|rebase>}"
    STRATEGY="${2:?Usage: hub.sh merge <pr_number> <squash|merge|rebase>}"
    EXPECTED_HEAD="${4:-}"
    MERGED_HEAD=""
    if [ "$HUB_TYPE" = "github" ]; then
      MERGE_ARGS=(pr merge "$PR_NUMBER" "--${STRATEGY}")
      if [ -n "$EXPECTED_HEAD" ]; then
        MERGE_ARGS+=(--match-head-commit "$EXPECTED_HEAD")
      fi
      MERGE_OK=true
      QUEUED=false
      UNCONFIRMED=false
      MERGE_OUTPUT=$(gh "${MERGE_ARGS[@]}" 2>&1) || MERGE_OK=false
      # Under a merge queue gh exits 0 on enqueue, so exit 0 alone is not a merge: only a MERGED
      # state is. Anything else is merge_ok=false, so merge-and-cleanup.sh keeps the local branch:
      # OPEN is reported as queued, a state gh could not report (after retries) as unconfirmed.
      if [ "$MERGE_OK" = "true" ]; then
        HEAD_INFO='{}'
        for attempt in 1 2 3; do
          HEAD_INFO=$(gh pr view "$PR_NUMBER" \
            --json state,headRefName,isCrossRepository,headRefOid,url 2>/dev/null) && break
          HEAD_INFO='{}'
          [ "$attempt" -lt 3 ] && sleep 1
        done
        PR_STATE=$(jq -r '.state // ""' <<<"$HEAD_INFO")
        if [ "$PR_STATE" != "MERGED" ]; then
          MERGE_OK=false
          if [ "$PR_STATE" = "OPEN" ]; then
            QUEUED=true
            MERGE_OUTPUT="${MERGE_OUTPUT}"$'\n'"PR is OPEN after gh pr merge (enqueued in a merge queue); not merged yet"
          else
            UNCONFIRMED=true
            MERGE_OUTPUT="${MERGE_OUTPUT}"$'\n'"Could not confirm the PR merged (state: '${PR_STATE:-unknown}'); check the hub"
          fi
        fi
      fi
      # Delete only the merged tip of a same-repository branch. The explicit
      # lease makes the deletion conditional on that tip at the remote, even
      # when another push lands between confirming the merge and cleanup.
      if [ "$MERGE_OK" = "true" ]; then
        MERGED_HEAD=$(jq -r '.headRefOid // empty' <<<"$HEAD_INFO")
        HEAD_BRANCH=$(jq -r 'select(.isCrossRepository == false) | .headRefName // empty' <<<"$HEAD_INFO")
        HEAD_REF="refs/heads/$HEAD_BRANCH"
        PR_URL=$(jq -r '.url // empty' <<<"$HEAD_INFO")
        if [ -n "$HEAD_BRANCH" ] \
          && [[ "$MERGED_HEAD" =~ ^[0-9a-f]{40}$ ]] \
          && [[ -z "$EXPECTED_HEAD" || "$EXPECTED_HEAD" == "$MERGED_HEAD" ]]; then
          if ! PUSH_URL=$(github_push_url_for_pr "$PR_URL" "$PR_NUMBER"); then
            MERGE_OUTPUT="${MERGE_OUTPUT}"$'\n'"Remote head kept: origin's push target does not match the merged PR repository"
          elif ! DELETE_ERR=$(GIT_TERMINAL_PROMPT=0 git push --porcelain --no-follow-tags \
            --force-with-lease="$HEAD_REF:$MERGED_HEAD" \
            -- origin ":$HEAD_REF" 2>&1); then
            # A repository's auto-delete setting can remove the ref first.
            REF_STATUS=0
            GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code --refs -- "$PUSH_URL" "$HEAD_REF" >/dev/null 2>&1 || REF_STATUS=$?
            if [ "$REF_STATUS" -ne 2 ]; then
              MERGE_OUTPUT="${MERGE_OUTPUT}"$'\n'"Remote head delete failed: ${DELETE_ERR}"
            fi
          fi
        fi
      fi
      jq -n --argjson ok "$MERGE_OK" --argjson queued "$QUEUED" --argjson unconfirmed "$UNCONFIRMED" \
        --arg out "$MERGE_OUTPUT" --arg sha "$MERGED_HEAD" \
        '{merge_ok: $ok, queued: $queued, unconfirmed: $unconfirmed, merge_output: $out}
         + (if $sha == "" then {} else {head_sha: $sha} end)'
    elif [ -n "$EXPECTED_HEAD" ]; then
      jq -n '{merge_ok: false, queued: false, unconfirmed: false, merge_output: "Head matching requires GitHub"}'
    else
      require_forgejo_token
      PAYLOAD=$(jq -n --arg do "$STRATEGY" '{Do: $do, delete_branch_after_merge: true}')
      MERGE_OK=true
      MERGE_OUTPUT=$(fj_api POST "/repos/${OWNER_REPO}/pulls/${PR_NUMBER}/merge" "$PAYLOAD" 2>&1) || MERGE_OK=false
      if [ "$MERGE_OK" = "false" ]; then
        MERGE_OUTPUT="HTTP $(fj_code): ${MERGE_OUTPUT}"
      elif HEAD_INFO=$(fj_api GET "/repos/${OWNER_REPO}/pulls/${PR_NUMBER}" 2>/dev/null); then
        MERGED_HEAD=$(jq -r 'select(.merged == true) | .head.sha // empty' <<<"$HEAD_INFO" 2>/dev/null) || MERGED_HEAD=""
      fi
      jq -n --argjson ok "$MERGE_OK" --arg out "$MERGE_OUTPUT" --arg sha "$MERGED_HEAD" \
        '{merge_ok: $ok, queued: false, unconfirmed: false, merge_output: $out}
         + (if $sha == "" then {} else {head_sha: $sha} end)'
    fi
    ;;

  *)
    echo "ERROR: Unknown subcommand: $SUBCOMMAND" >&2
    exit 1
    ;;
esac
