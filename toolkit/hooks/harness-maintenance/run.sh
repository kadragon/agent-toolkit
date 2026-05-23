#!/usr/bin/env bash
# SessionStart hook: harness maintenance (B, E, F steps only)
#
# B) sync-claude-md.sh  — ensure CLAUDE.md = "@AGENTS.md"
# E) symlink-guard.sh   — ensure .agents/skills symlink
# F) check-context-size.sh — warn if AGENTS.md/CLAUDE.md > 200 lines
#
# C (reconcile-harness.py) is intentionally excluded — it mutates backlog.md
# and should only run on explicit "harness sync" request via harness-init skill.
#
# Guard: only runs in repos with AGENTS.md (harness repos)
# Debounce: daily stamp at .agents/.maintenance-stamp

set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
SCRIPTS="${PLUGIN_ROOT}/skills/harness-init/scripts"

# Guard: not a harness repo
[[ -f "AGENTS.md" ]] || exit 0

# Guard: scripts not available
[[ -f "$SCRIPTS/sync-claude-md.sh" ]] || exit 0

# Debounce: already ran today
STAMP=".agents/.maintenance-stamp"
TODAY=$(date +%Y-%m-%d)
if [[ -f "$STAMP" ]] && [[ "$(cat "$STAMP" 2>/dev/null)" == "$TODAY" ]]; then
  exit 0
fi

WARNINGS=""

# B) CLAUDE.md sync
sync_out=$(bash "$SCRIPTS/sync-claude-md.sh" 2>&1)
sync_code=$?
if [[ $sync_code -eq 1 ]]; then
  WARNINGS+="[harness:B] CLAUDE.md was missing — created with @AGENTS.md\n"
elif [[ $sync_code -eq 2 ]]; then
  WARNINGS+="[harness:B] CLAUDE.md content drift — expected @AGENTS.md. Run harness sync to fix.\n"
elif [[ $sync_code -ne 0 ]]; then
  WARNINGS+="[harness:B] sync-claude-md.sh failed (exit $sync_code): $sync_out\n"
fi

# E) Symlink guard
symlink_out=$(bash "$SCRIPTS/symlink-guard.sh" 2>&1)
symlink_code=$?
[[ $symlink_code -ne 0 ]] && WARNINGS+="[harness:E] $symlink_out\n"

# F) Context size check
size_out=$(bash "$SCRIPTS/check-context-size.sh" 2>&1) || true
[[ -n "$size_out" ]] && WARNINGS+="[harness:F] $size_out\n"

# Write debounce stamp
mkdir -p ".agents"
echo "$TODAY" > "$STAMP"

# Emit warnings into session context (stdout → systemMessage)
if [[ -n "$WARNINGS" ]]; then
  printf "Harness maintenance warnings:\n%b" "$WARNINGS"
fi

exit 0
