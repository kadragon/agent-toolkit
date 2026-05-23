#!/usr/bin/env bash
# detect-review-skills.sh — Scan installed plugins for review-related skills/commands.
#
# Output: {"candidates": [{"id":..., "kind":..., "description":...}], "count": N}
# Skips: codex plugins, dev-review-cycle itself.
# Includes: built-in review skills not discoverable via file system.

set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo '{"candidates":[],"count":0,"error":"jq not installed"}' >&2
  exit 1
fi

PLUGINS_CACHE="${HOME}/.claude/plugins/cache"
# Temp file tracks seen IDs for deduplication (bash 3-compatible, no assoc arrays)
SEEN_FILE=$(mktemp)
trap 'rm -f "$SEEN_FILE"' EXIT

candidates_json="[]"

# ──────────────────────────────────────────────
# Helper: check if id already seen; if not, mark it and return 0 (ok to add)
# ──────────────────────────────────────────────
is_new() {
  local id="$1"
  if grep -qxF "$id" "$SEEN_FILE" 2>/dev/null; then
    return 1  # already seen
  fi
  echo "$id" >> "$SEEN_FILE"
  return 0
}

# ──────────────────────────────────────────────
# Helper: extract frontmatter description from a markdown file.
# Returns first non-empty value of "description:" in YAML frontmatter.
# Output truncated to 500 chars.
# ──────────────────────────────────────────────
extract_description() {
  local file="$1"
  awk '
    BEGIN { in_front=0; found=0; text="" }
    /^---$/ {
      if (++n == 1) { in_front=1; next }
      if (n == 2) exit
    }
    in_front && /^description:/ {
      found=1
      sub(/^description:[[:space:]]*/, "")
      sub(/^[>|][[:space:]]*/, "")
      sub(/^[[:space:]]+/, "")
      text=$0
      next
    }
    in_front && found && /^[[:space:]]/ {
      sub(/^[[:space:]]+/, "")
      text=text " " $0
      next
    }
    found { exit }
    END {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", text)
      gsub(/^["'"'"']|["'"'"']$/, "", text)
      print substr(text, 1, 500)
    }
  ' "$file" 2>/dev/null | tr -s ' '
}

# ──────────────────────────────────────────────
# Helper: add a candidate if not already seen
# ──────────────────────────────────────────────
add_candidate() {
  local id="$1" kind="$2" desc="$3"
  is_new "$id" || return 0
  local entry
  entry=$(jq -cn --arg id "$id" --arg kind "$kind" --arg description "$desc" \
    '{id: $id, kind: $kind, description: $description}') || return 0
  local updated
  updated=$(printf '%s' "$candidates_json" | jq --argjson e "$entry" '. + [$e]') || return 0
  candidates_json="$updated"
}

# ──────────────────────────────────────────────
# 1. Built-in review skills (not in plugin cache)
# ──────────────────────────────────────────────
add_candidate "review" "builtin" \
  "Review a pull request. Use when user asks to review a PR."

add_candidate "security-review" "builtin" \
  "Complete a security review of the pending changes on the current branch."

# ──────────────────────────────────────────────
# 2. Scan plugin cache for skills (dir name contains "review")
# Path: $PLUGINS_CACHE/<source>/<plugin>/<version>/skills/<skill>/SKILL.md
# plugin_name = component just before /version/ = $(NF-1) of path up to /skills/
# ──────────────────────────────────────────────
if [[ -d "$PLUGINS_CACHE" ]]; then
  while IFS= read -r skill_md; do
    skill_dir=$(dirname "$skill_md")
    skill_name=$(basename "$skill_dir")

    [[ "$skill_name" =~ review ]] || continue
    [[ "$skill_md" =~ /codex/ ]]  && continue
    [[ "$skill_name" == "dev-review-cycle" ]] && continue

    plugin_name=$(echo "$skill_md" | awk -F'/skills/' '{print $1}' | awk -F'/' '{print $(NF-1)}')
    [[ -z "$plugin_name" ]] && continue

    local_id="${plugin_name}:${skill_name}"
    desc=$(extract_description "$skill_md" 2>/dev/null || echo "")
    add_candidate "$local_id" "skill" "$desc"
  done < <(find "$PLUGINS_CACHE" -maxdepth 7 -name "SKILL.md" -path "*/skills/*" 2>/dev/null | sort -rV 2>/dev/null || find "$PLUGINS_CACHE" -maxdepth 7 -name "SKILL.md" -path "*/skills/*" 2>/dev/null | sort -r)

  # ──────────────────────────────────────────────
  # 3. Scan plugin cache for commands (file stem contains "review")
  # plugin_name = component just before /version/ = $(NF-1) of path up to /commands/
  # ──────────────────────────────────────────────
  while IFS= read -r cmd_md; do
    cmd_stem=$(basename "$cmd_md" .md)

    [[ "$cmd_stem" =~ review ]] || continue
    [[ "$cmd_md" =~ /codex/ ]]  && continue

    plugin_name=$(echo "$cmd_md" | awk -F'/commands/' '{print $1}' | awk -F'/' '{print $(NF-1)}')
    [[ -z "$plugin_name" ]] && continue

    # id: bare if cmd_stem == plugin_name, else plugin:cmd
    if [[ "$cmd_stem" == "$plugin_name" ]]; then
      local_id="$cmd_stem"
    else
      local_id="${plugin_name}:${cmd_stem}"
    fi

    desc=$(extract_description "$cmd_md" 2>/dev/null || echo "")
    add_candidate "$local_id" "command" "$desc"
  done < <(find "$PLUGINS_CACHE" -maxdepth 7 -name "*.md" -path "*/commands/*" 2>/dev/null | sort -rV 2>/dev/null || find "$PLUGINS_CACHE" -maxdepth 7 -name "*.md" -path "*/commands/*" 2>/dev/null | sort -r)
fi

count=$(printf '%s' "$candidates_json" | jq 'length')
printf '%s' "$candidates_json" | jq -c --argjson count "$count" '{candidates: ., count: $count}'
