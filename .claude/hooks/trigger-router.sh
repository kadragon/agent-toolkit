#!/usr/bin/env bash
# UserPromptSubmit hook: route prompts to skills/agents via explicit instruction.
#
# stdin: JSON payload {"prompt": "...", "session_id": "..."}
# stdout: instruction appended to prompt context (or empty)
# Contract: exit 0 always — never block. No set -e: bad route regex must not kill the hook.

set -u

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
ROUTES_FILE="${PROJECT_ROOT}/.claude/trigger-routes.json"
[[ -f "$ROUTES_FILE" ]] || exit 0

payload=$(cat)
prompt=$(jq -r '.prompt // empty' <<<"$payload" 2>/dev/null || true)
[[ -z "$prompt" ]] && exit 0

# Parse all routes in one jq fork — avoids 3N forks per prompt.
# Fields joined with ASCII Unit Separator (0x1F) — safe delimiter that never appears in JSON strings.
US=$'\x1f'
routes=$(jq -r --arg us "$US" '
    .[] | [
      (.pattern // ""),
      (.skip_if_prompt_matches // ""),
      (.instruction // "")
    ] | join($us)
' "$ROUTES_FILE" 2>/dev/null || true)
[[ -z "$routes" ]] && exit 0

# First match wins. nocasematch set once outside loop.
shopt -s nocasematch
matched=""
while IFS="$US" read -r pattern skip instr; do
    [[ -z "$pattern" ]] && continue
    if [[ "$prompt" =~ $pattern ]] 2>/dev/null; then
        if [[ -n "$skip" ]] && [[ "$prompt" =~ $skip ]] 2>/dev/null; then
            continue
        fi
        matched="$instr"
        break
    fi
done <<< "$routes"
shopt -u nocasematch

[[ -n "$matched" ]] && echo "INSTRUCTION (auto-delegation router): $matched"
exit 0
