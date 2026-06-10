#!/usr/bin/env bash
# Pre-flight checks for dev-review-cycle
# Detects available tools and repository metadata, outputs JSON.
#
# Usage: preflight.sh [--no-hub]

set -euo pipefail

# --- jq is required for all scripts in this workflow ---
if ! command -v jq >/dev/null 2>&1; then
  echo '{"has_errors": true, "errors": ["jq is required but not installed. Install via: brew install jq"]}' >&2
  exit 1
fi

NO_HUB=false
for arg in "$@"; do
  [[ "$arg" == "--no-hub" ]] && NO_HUB=true
done

errors=()

# --- GitHub CLI ---
GH_AUTHENTICATED=false
if [ "$NO_HUB" = "false" ]; then
  if gh auth status >/dev/null 2>&1; then
    GH_AUTHENTICATED=true
  else
    errors+=("gh CLI not authenticated. Run 'gh auth login' first.")
  fi
fi

# --- Antigravity (agy) CLI ---
AGY_AVAILABLE=false
if command -v agy >/dev/null 2>&1; then
  AGY_AVAILABLE=true
  # On Windows/Git Bash, agy.exe writes output via Windows console API (text_drip renderer)
  # rather than stdout. Output is silently lost when stdout is not a TTY (e.g., piped in
  # scripts). Detect this and disable agy so the skill doesn't spin up an agy session
  # that produces no usable output.
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      if ! [ -t 1 ]; then
        AGY_AVAILABLE=false
      fi
      ;;
  esac
fi

# --- Codex ---
CODEX_AVAILABLE=false
CODEX_MODE="none"
CODEX_COMPANION_PATH=""
# Use glob instead of find for predictable plugin structure
CODEX_COMPANION=$(ls ~/.claude/plugins/*/codex/*/codex-companion.mjs ~/.claude/plugins/cache/*/codex/*/codex-companion.mjs 2>/dev/null | head -1 || true)
if [ -n "$CODEX_COMPANION" ] && command -v codex >/dev/null 2>&1; then
  CODEX_AVAILABLE=true
  CODEX_MODE="plugin"
  CODEX_COMPANION_PATH="$CODEX_COMPANION"
elif command -v codex >/dev/null 2>&1; then
  CODEX_AVAILABLE=true
  CODEX_MODE="cli"
fi

# --- Repository metadata ---
FEATURE_BRANCH=$(git branch --show-current)

OWNER_REPO=""
BASE_BRANCH=""
MERGE_INFO='{}'

if [ "$NO_HUB" = "false" ]; then
  OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
  BASE_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo "")
  [ -z "$BASE_BRANCH" ] && BASE_BRANCH="main"

  if [ -n "$OWNER_REPO" ]; then
    MERGE_INFO=$(gh api "repos/${OWNER_REPO}" --jq '{squash: .allow_squash_merge, merge: .allow_merge_commit, rebase: .allow_rebase_merge}' 2>/dev/null || echo '{}')
  fi
else
  # Detect base branch purely locally — no remote references
  BASE_BRANCH=$(git config init.defaultBranch 2>/dev/null || true)
  if [ -z "$BASE_BRANCH" ]; then
    for b in main master; do
      if git show-ref --verify --quiet "refs/heads/$b" 2>/dev/null; then
        BASE_BRANCH="$b"
        break
      fi
    done
  fi
  [ -z "$BASE_BRANCH" ] && BASE_BRANCH="main"
fi

# --- Detect installed review skills ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVIEW_CANDIDATES='{"candidates":[],"count":0}'
if [[ -f "${SCRIPT_DIR}/detect-review-skills.sh" ]]; then
  REVIEW_CANDIDATES=$(bash "${SCRIPT_DIR}/detect-review-skills.sh" 2>/dev/null) || REVIEW_CANDIDATES='{"candidates":[],"count":0}'
  jq -e . <<< "$REVIEW_CANDIDATES" >/dev/null 2>&1 || REVIEW_CANDIDATES='{"candidates":[],"count":0}'
fi

# --- Build JSON safely with jq ---
ERRORS_JSON="[]"
if [ ${#errors[@]} -gt 0 ]; then
  ERRORS_JSON=$(printf '%s\n' "${errors[@]}" | jq -R . | jq -s .)
fi

jq -n \
  --argjson no_hub "$NO_HUB" \
  --argjson gh_authenticated "$GH_AUTHENTICATED" \
  --argjson agy_available "$AGY_AVAILABLE" \
  --argjson codex_available "$CODEX_AVAILABLE" \
  --arg codex_mode "$CODEX_MODE" \
  --arg codex_companion_path "$CODEX_COMPANION_PATH" \
  --arg feature_branch "$FEATURE_BRANCH" \
  --arg base_branch "$BASE_BRANCH" \
  --arg owner_repo "$OWNER_REPO" \
  --argjson merge_strategy "$MERGE_INFO" \
  --argjson errors "$ERRORS_JSON" \
  --argjson review_candidates "$REVIEW_CANDIDATES" \
  '{
    no_hub: $no_hub,
    gh_authenticated: $gh_authenticated,
    agy_available: $agy_available,
    codex_available: $codex_available,
    codex_mode: $codex_mode,
    codex_companion_path: $codex_companion_path,
    feature_branch: $feature_branch,
    base_branch: $base_branch,
    owner_repo: $owner_repo,
    merge_strategy: $merge_strategy,
    review_candidates: $review_candidates,
    has_errors: (($errors | length) > 0),
    errors: $errors
  }'
