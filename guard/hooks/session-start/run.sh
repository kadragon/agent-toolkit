#!/usr/bin/env bash
# SessionStart dispatcher: global CLAUDE.md sync + daily-debounced harness maintenance.
# Best-effort — never blocks startup.

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)

GLOBAL_SYNC="$SCRIPT_DIR/sync-global-claude-md.sh"
MAINTENANCE="$SCRIPT_DIR/harness-maintenance.sh"

if [[ -f "$GLOBAL_SYNC" ]]; then
  bash "$GLOBAL_SYNC" || true
fi

if [[ -f "$MAINTENANCE" ]]; then
  bash "$MAINTENANCE" || true
fi

PY=$(command -v python3 || command -v python || true)
if [[ -n "$PY" ]]; then
  "$PY" -I -X utf8 "$SCRIPT_DIR/worktree_sweep.py" "$PWD" 2>&1 || true
fi

exit 0
