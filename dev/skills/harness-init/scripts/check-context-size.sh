#!/usr/bin/env bash
# F) Context Size Check
#
# Warns if the file that Claude loads every message exceeds LIMIT lines.
# - If CLAUDE.md is a pointer (exactly "@AGENTS.md"), the effective file is AGENTS.md.
# - Otherwise, CLAUDE.md itself is the effective file.
#
# Exit codes:
#   0  Always — overflow is signaled via stdout only, not exit code
#
# Rationale: CLAUDE.md / AGENTS.md is re-loaded with every user message.
# Past ~200 lines the per-message token cost starts dominating the context budget
# (5k+ tokens wasted per message on instructions the agent has already internalized).

set -euo pipefail

LIMIT="${CONTEXT_SIZE_LIMIT:-200}"
POINTER="@AGENTS.md"

effective=""
if [ -f CLAUDE.md ]; then
  trimmed=$(tr -d '[:space:]' < CLAUDE.md)
  expected=$(printf '%s' "$POINTER" | tr -d '[:space:]')
  if [ "$trimmed" = "$expected" ]; then
    [ -f AGENTS.md ] && effective="AGENTS.md"
  else
    effective="CLAUDE.md"
  fi
elif [ -f AGENTS.md ]; then
  effective="AGENTS.md"
fi

[ -z "$effective" ] && exit 0

lines=$(wc -l < "$effective" | tr -d ' ')

if [ "$lines" -gt "$LIMIT" ]; then
  printf 'context-size: %s is %s lines (>%s) — consider splitting into docs/*.md and leaving pointers\n' \
    "$effective" "$lines" "$LIMIT"

  # Heuristic bloat hints: most common causes of oversize AGENTS.md/CLAUDE.md.
  code_lines=$(awk '/^```/{f=!f;next} f' "$effective" | wc -l | tr -d ' ')
  if [ "$code_lines" -gt $((lines / 5)) ]; then
    printf '  hint: ~%s lines are inside fenced code blocks — AGENTS.md is a map, move examples to docs/\n' "$code_lines"
  fi

  h2_dup=$(grep -c '^## ' "$effective" 2>/dev/null || echo 0)
  h2_uniq=$(grep '^## ' "$effective" 2>/dev/null | sort -u | wc -l | tr -d ' ')
  if [ "$h2_dup" -gt "$h2_uniq" ]; then
    printf '  hint: duplicate ## headings detected (%s total, %s unique) — merge redundant sections\n' \
      "$h2_dup" "$h2_uniq"
  fi

  # Informational warning only — exit 0 so parallel siblings are not cancelled.
fi

exit 0
