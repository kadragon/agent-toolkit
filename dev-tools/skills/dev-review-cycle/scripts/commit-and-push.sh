#!/usr/bin/env bash
# Commit files and optionally push / create a PR.
#
# Usage:
#   commit-and-push.sh --message <text> [--files "f1 f2 ..."] [--no-push] [--pr] [--base <branch>]
#
# Flags:
#   --message <text>   Commit message (required)
#   --files <list>     Space-separated file paths to stage (default: auto-detect via changed-files.sh)
#   --no-push          Commit locally only; skip push and PR creation
#   --pr               Create a PR after pushing
#   --base <branch>    Base branch for the PR (default: main)
#
# Output: JSON to stdout
#   {commit_hash, committed, pushed, pr_number, pr_url}
#   committed=false means the tree was clean and HEAD was pushed/PR'd as-is
#   (re-run against an already-committed branch).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MESSAGE=""
FILES=""
NO_PUSH=false
CREATE_PR=false
BASE_BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --message) MESSAGE="$2"; shift 2 ;;
    --files)   FILES="$2";   shift 2 ;;
    --no-push) NO_PUSH=true; shift ;;
    --pr)      CREATE_PR=true; shift ;;
    --base)    BASE_BRANCH="$2"; shift 2 ;;
    *) echo "ERROR: Unknown flag: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$MESSAGE" ]; then
  echo "ERROR: --message is required" >&2
  exit 1
fi

# --- Resolve file list ---
if [ -z "$FILES" ]; then
  FILES=$(bash "$SCRIPT_DIR/changed-files.sh" | tr '\n' ' ')
fi
FILES=$(echo "$FILES" | tr -s '[:space:]' ' ' | sed 's/^ //;s/ $//')

# --- Stage and commit ---
# A clean tree on a push/PR run means the branch is already committed (e.g. a
# re-run of the review cycle) — skip the commit and push/PR the existing HEAD.
# A clean tree on a --no-push run has nothing to do at all, so that stays fatal.
COMMITTED=false
if [ -n "$FILES" ]; then
  # Word-split is intentional here: FILES is a space-separated list of paths.
  # shellcheck disable=SC2086
  git add -- $FILES
  git commit -m "$MESSAGE"
  COMMITTED=true
elif [ "$NO_PUSH" = "true" ]; then
  echo '{"error": "No changed files detected — nothing to commit"}' >&2
  exit 1
fi
COMMIT_HASH=$(git rev-parse HEAD)

if [ "$NO_PUSH" = "true" ]; then
  jq -n --arg hash "$COMMIT_HASH" --argjson committed "$COMMITTED" \
    '{commit_hash: $hash, committed: $committed, pushed: false, pr_number: null, pr_url: null}'
  exit 0
fi

# --- Push ---
git push -u origin HEAD

PR_NUMBER=""
PR_URL=""

if [ "$CREATE_PR" = "true" ]; then
  TITLE=$(printf '%s' "$MESSAGE" | head -n 1)
  BODY=$(printf '%s' "$MESSAGE" | tail -n +3)

  # hub.sh routes to gh (GitHub) or the Forgejo/Gitea REST API, and falls back
  # to the existing PR when one already exists for this branch (re-run).
  PR_JSON=$(bash "$SCRIPT_DIR/hub.sh" pr-create \
    --base "$BASE_BRANCH" \
    --title "$TITLE" \
    --body "$BODY" 2>/dev/null || echo '{}')
  PR_NUMBER=$(jq -r '.pr_number // ""' <<<"$PR_JSON")
  PR_URL=$(jq -r '.pr_url // ""' <<<"$PR_JSON")
fi

jq -n \
  --arg hash "$COMMIT_HASH" \
  --argjson committed "$COMMITTED" \
  --arg pr_number "$PR_NUMBER" \
  --arg pr_url "$PR_URL" \
  '{
    commit_hash: $hash,
    committed: $committed,
    pushed: true,
    pr_number: ($pr_number | if . == "" then null else . end),
    pr_url: ($pr_url | if . == "" then null else . end)
  }'
