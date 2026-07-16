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

# --- Hub detection (GitHub via gh, Forgejo/Gitea via REST) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB_TYPE="none"
HUB_AUTHENTICATED=false
if [ "$NO_HUB" = "false" ]; then
  DETECT=$(bash "${SCRIPT_DIR}/hub.sh" detect 2>/dev/null || echo '{}')
  HUB_TYPE=$(jq -r '.hub_type // "none"' <<<"$DETECT")
  HUB_AUTHENTICATED=$(jq -r '.token_present // false' <<<"$DETECT")
  DETECT_ERRORS=$(jq -r '(.errors // [])[]' <<<"$DETECT")
  if [ -n "$DETECT_ERRORS" ]; then
    while IFS= read -r e; do errors+=("$e"); done <<<"$DETECT_ERRORS"
  fi
fi

# --- Antigravity (agy) CLI ---
AGY_AVAILABLE=false
if command -v agy >/dev/null 2>&1; then
  AGY_AVAILABLE=true
  # On Windows/Git Bash, agy.exe writes output via Windows console API (text_drip renderer)
  # rather than stdout. agy-review.sh always invokes agy in a pipeline (agy ... | tee),
  # so agy's stdout is always a pipe — never a TTY — and the output is silently lost
  # regardless of whether the outer terminal is interactive. Disable unconditionally on
  # Windows rather than using a TTY heuristic that would incorrectly report
  # agy_available=true when preflight is run in an interactive shell.
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) AGY_AVAILABLE=false ;;
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

# --- Native runtime engine + Claude CLI (cross-runtime Claude review) ---
# CLAUDECODE is set only when Claude Code is the driver; it does NOT leak into
# Codex sessions. (The inverse test is unreliable: the codex plugin sets
# CODEX_COMPANION_SESSION_ID even under Claude Code, so only the positive Claude
# test can be trusted.) Step 2-1 uses this: driver is Claude → in-process Agent
# (inherits the live session model); otherwise → `claude` CLI companion, so the
# review panel keeps a Claude engine no matter which runtime drives the cycle.
NATIVE_ENGINE="other"
[ -n "${CLAUDECODE:-}" ] && NATIVE_ENGINE="claude"
CLAUDE_CLI_AVAILABLE=false
command -v claude >/dev/null 2>&1 && CLAUDE_CLI_AVAILABLE=true

# --- Repository metadata ---
FEATURE_BRANCH=$(git branch --show-current)

OWNER_REPO=""
BASE_BRANCH=""
MERGE_INFO='{}'

if [ "$NO_HUB" = "false" ]; then
  REPO_INFO=$(bash "${SCRIPT_DIR}/hub.sh" repo-info 2>/dev/null || echo '{}')
  OWNER_REPO=$(jq -r '.owner_repo // ""' <<<"$REPO_INFO")
  BASE_BRANCH=$(jq -r '.default_branch // ""' <<<"$REPO_INFO")
  [ -z "$BASE_BRANCH" ] && BASE_BRANCH="main"
  MERGE_INFO=$(jq -c '.merge_strategy // {}' <<<"$REPO_INFO")

  # --- Keep local base branch current so downstream `git diff base...HEAD` isn't
  # --- scoped against a stale ref (picks up already-merged commits otherwise).
  # --- Only fast-forward: skip if it's checked out, has diverged, or fetch fails.
  if [ "$BASE_BRANCH" != "$FEATURE_BRANCH" ] \
    && git show-ref --verify --quiet "refs/heads/${BASE_BRANCH}" 2>/dev/null \
    && git fetch -q origin "${BASE_BRANCH}" 2>/dev/null; then
    LOCAL_SHA=$(git rev-parse "refs/heads/${BASE_BRANCH}" 2>/dev/null || true)
    REMOTE_SHA=$(git rev-parse "FETCH_HEAD" 2>/dev/null || true)
    if [ -n "$LOCAL_SHA" ] && [ -n "$REMOTE_SHA" ] && [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
      MERGE_BASE=$(git merge-base "$LOCAL_SHA" "$REMOTE_SHA" 2>/dev/null || true)
      if [ "$MERGE_BASE" = "$LOCAL_SHA" ]; then
        git fetch -q origin "${BASE_BRANCH}:${BASE_BRANCH}" 2>/dev/null || true
      fi
    fi
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
  --arg hub_type "$HUB_TYPE" \
  --argjson hub_authenticated "$HUB_AUTHENTICATED" \
  --argjson agy_available "$AGY_AVAILABLE" \
  --argjson codex_available "$CODEX_AVAILABLE" \
  --arg codex_mode "$CODEX_MODE" \
  --arg codex_companion_path "$CODEX_COMPANION_PATH" \
  --arg native_engine "$NATIVE_ENGINE" \
  --argjson claude_cli_available "$CLAUDE_CLI_AVAILABLE" \
  --arg feature_branch "$FEATURE_BRANCH" \
  --arg base_branch "$BASE_BRANCH" \
  --arg owner_repo "$OWNER_REPO" \
  --argjson merge_strategy "$MERGE_INFO" \
  --argjson errors "$ERRORS_JSON" \
  --argjson review_candidates "$REVIEW_CANDIDATES" \
  '{
    no_hub: $no_hub,
    hub_type: $hub_type,
    hub_authenticated: $hub_authenticated,
    agy_available: $agy_available,
    codex_available: $codex_available,
    codex_mode: $codex_mode,
    codex_companion_path: $codex_companion_path,
    native_engine: $native_engine,
    claude_cli_available: $claude_cli_available,
    feature_branch: $feature_branch,
    base_branch: $base_branch,
    owner_repo: $owner_repo,
    merge_strategy: $merge_strategy,
    review_candidates: $review_candidates,
    has_errors: (($errors | length) > 0),
    errors: $errors
  }'
