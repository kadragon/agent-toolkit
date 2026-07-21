#!/usr/bin/env bash
# B) CLAUDE.md Deterministic Sync
#
# Exit codes:
#   0  Already contains exactly "@AGENTS.md" — nothing to do
#   1  Did not exist → created with "@AGENTS.md"
#   2  Exists but differs → original content printed to stdout for Claude to process

set -euo pipefail

CLAUDE_MD="${1:-CLAUDE.md}"
EXPECTED="@AGENTS.md"

if [ ! -f "$CLAUDE_MD" ]; then
  printf '%s\n' "$EXPECTED" > "$CLAUDE_MD"
  exit 1
fi

# Trim all whitespace to compare
trimmed=$(tr -d '[:space:]' < "$CLAUDE_MD")
expected_trimmed=$(printf '%s' "$EXPECTED" | tr -d '[:space:]')

if [ "$trimmed" = "$expected_trimmed" ]; then
  exit 0
fi

# Differs: print original content for Claude to extract and merge
cat "$CLAUDE_MD"
exit 2
