#!/usr/bin/env bash
# SessionStart hook: harness maintenance (B, E, F, G steps only)
#
# B) sync-claude-md.sh  — ensure CLAUDE.md = "@AGENTS.md"
# E) symlink-guard.sh   — ensure .agents/skills symlink
# F) check-context-size.sh — warn if AGENTS.md/CLAUDE.md > 200 lines
# G) curate_due.py — nudge when a harness-curate run is due
#
# Run C (reconcile-harness.py) during explicit harness sync.
#
# Guard: only runs in repos with AGENTS.md (harness repos)
# Debounce: daily stamp at .agents/.maintenance-stamp

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)

# Guard: not a harness repo
[[ -f "AGENTS.md" ]] || exit 0

# Debounce: already ran today
STAMP=".agents/.maintenance-stamp"
TODAY=$(date +%Y-%m-%d)
if [[ -f "$STAMP" ]] && [[ "$(cat "$STAMP" 2>/dev/null)" == "$TODAY" ]]; then
  exit 0
fi

WARNINGS=""

# B) CLAUDE.md sync
sync_out=$(bash "$SCRIPT_DIR/sync-claude-md.sh" 2>&1)
sync_code=$?
if [[ $sync_code -eq 1 ]]; then
  WARNINGS+="[harness:B] CLAUDE.md was missing — created with @AGENTS.md\n"
elif [[ $sync_code -eq 2 ]]; then
  WARNINGS+="[harness:B] CLAUDE.md content drift — expected @AGENTS.md. Run harness sync to fix.\n"
elif [[ $sync_code -ne 0 ]]; then
  WARNINGS+="[harness:B] sync-claude-md.sh failed (exit $sync_code): $sync_out\n"
fi

# E) Symlink guard
symlink_out=$(bash "$SCRIPT_DIR/symlink-guard.sh" 2>&1)
symlink_code=$?
[[ $symlink_code -ne 0 ]] && WARNINGS+="[harness:E] $symlink_out\n"

# F) Context size check
size_out=$(bash "$SCRIPT_DIR/check-context-size.sh" 2>&1) || true
[[ -n "$size_out" ]] && WARNINGS+="[harness:F] $size_out\n"

# G) harness-curate due check (>14d since last run AND >=10 new sessions)
CURATE_DUE="$SCRIPT_DIR/curate_due.py"
PY=$(command -v python3 || command -v python || true)
if [[ -n "$PY" ]] && [[ -f "$CURATE_DUE" ]]; then
  due_out=$("$PY" -B "$CURATE_DUE" 2>/dev/null) || true
  [[ -n "$due_out" ]] && WARNINGS+="[harness:G] $due_out\n"
fi

# Write debounce stamp
mkdir -p ".agents"
echo "$TODAY" > "$STAMP"

# Emit warnings into session context (stdout → systemMessage)
if [[ -n "$WARNINGS" ]]; then
  printf "Harness maintenance warnings:\n%b" "$WARNINGS"
fi

exit 0
