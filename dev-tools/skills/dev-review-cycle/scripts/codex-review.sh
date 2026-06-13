#!/usr/bin/env bash
# Launch Codex code review against a base branch.
# Selects plugin mode (codex-companion.mjs) or CLI mode automatically.
#
# Usage: codex-review.sh <codex_mode> <base_branch> [codex_companion_path]
#   codex_mode: "plugin" | "cli"
#   codex_companion_path: path to codex-companion.mjs (required for plugin mode)
# Output: Codex review text to stdout.

set -euo pipefail

CODEX_MODE="${1:?Usage: codex-review.sh <codex_mode> <base_branch> [codex_companion_path]}"
BASE_BRANCH="${2:?Usage: codex-review.sh <codex_mode> <base_branch> [codex_companion_path]}"
CODEX_COMPANION_PATH="${3:-}"

case "$CODEX_MODE" in
  plugin)
    if [ -z "$CODEX_COMPANION_PATH" ]; then
      echo "ERROR: codex_companion_path is required for plugin mode" >&2
      exit 1
    fi
    # --json disables the companion's live reasoning stream (stderr) and the
    # reasoning section appended to the rendered text. stdout becomes a single
    # JSON object whose .codex.stdout holds the pure review (findings + verdict).
    # Capture the status without tripping `set -e`: on a non-zero review run the
    # companion writes its failure payload to stdout (RAW), so surface it before
    # propagating the exit code — otherwise the caller only sees the generic
    # fallback and loses the diagnostic detail.
    RAW=""
    status=0
    RAW=$(node "$CODEX_COMPANION_PATH" review --base "$BASE_BRANCH" --json) || status=$?
    if [ "$status" -ne 0 ]; then
      [ -n "$RAW" ] && printf '%s\n' "$RAW" >&2
      exit "$status"
    fi
    # Fall back to raw JSON if jq is missing or the field is empty, so nothing
    # is silently dropped.
    TEXT=""
    if command -v jq >/dev/null 2>&1; then
      TEXT=$(printf '%s' "$RAW" | jq -r '.codex.stdout // empty' 2>/dev/null || true)
    fi
    if [ -n "$TEXT" ]; then
      printf '%s\n' "$TEXT"
    else
      printf '%s\n' "$RAW"
    fi
    ;;
  cli)
    codex review --base "$BASE_BRANCH"
    ;;
  *)
    echo "ERROR: Unknown codex_mode '$CODEX_MODE'. Expected 'plugin' or 'cli'." >&2
    exit 1
    ;;
esac
