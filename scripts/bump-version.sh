#!/usr/bin/env bash
# Bump plugin and/or skill versions atomically.
# Usage: bump-version.sh <plugin> <major|minor|patch> [--skill <name> [major|minor|patch]]
#
# Semver rules (from AGENTS.md):
#   add skill/agent → minor
#   modify          → patch
#   remove/rename   → major
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat >&2 <<EOF
Usage: $0 <plugin> <major|minor|patch> [--skill <name> [major|minor|patch]]

  plugin:     dev-tools | productivity | all
  bump type:  major | minor | patch

  --skill <name> [major|minor|patch]
    Also bump the version in skills/<name>/SKILL.md frontmatter.
    Defaults to 'patch' if bump type omitted.

Examples:
  $0 dev-tools patch
  $0 productivity minor --skill harness-curator patch
  $0 all patch
EOF
  exit 1
}

bump_semver() {
  local version="$1" bump_type="$2"
  local major minor patch
  IFS='.' read -r major minor patch <<< "$version"
  case "$bump_type" in
    major) echo "$((major + 1)).0.0" ;;
    minor) echo "${major}.$((minor + 1)).0" ;;
    patch) echo "${major}.${minor}.$((patch + 1))" ;;
    *)     echo "Unknown bump type: $bump_type" >&2; exit 1 ;;
  esac
}

bump_plugin() {
  local plugin="$1" bump_type="$2"
  local claude_json="${REPO_ROOT}/${plugin}/.claude-plugin/plugin.json"
  local codex_json="${REPO_ROOT}/${plugin}/.codex-plugin/plugin.json"

  [[ -f "$claude_json" ]] || { echo "Not found: $claude_json" >&2; exit 1; }
  [[ -f "$codex_json"  ]] || { echo "Not found: $codex_json"  >&2; exit 1; }

  local current_version
  current_version=$(grep '"version"' "$claude_json" | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/')

  local new_version
  new_version=$(bump_semver "$current_version" "$bump_type")

  for f in "$claude_json" "$codex_json"; do
    sed -i '' "s/\"version\": \"${current_version}\"/\"version\": \"${new_version}\"/" "$f"
  done

  echo "  ${plugin}: ${current_version} → ${new_version}"
}

bump_skill() {
  local plugin="$1" skill_name="$2" bump_type="$3"
  local skill_md="${REPO_ROOT}/${plugin}/skills/${skill_name}/SKILL.md"

  [[ -f "$skill_md" ]] || { echo "Not found: $skill_md" >&2; exit 1; }

  local current_version
  current_version=$(grep '^version:' "$skill_md" | awk '{print $2}')

  [[ -n "$current_version" ]] || { echo "No 'version:' field in $skill_md" >&2; exit 1; }

  local new_version
  new_version=$(bump_semver "$current_version" "$bump_type")

  sed -i '' "s/^version: ${current_version}$/version: ${new_version}/" "$skill_md"
  echo "    skill ${skill_name}: ${current_version} → ${new_version}"
}

# ── Arg parsing ───────────────────────────────────────────────────────────────

[[ $# -lt 2 ]] && usage

PLUGIN="$1"
BUMP_TYPE="$2"
shift 2

SKILL_NAME=""
SKILL_BUMP="patch"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skill)
      [[ $# -ge 2 ]] || { echo "Missing skill name after --skill" >&2; usage; }
      SKILL_NAME="$2"
      shift 2
      if [[ $# -gt 0 && "$1" =~ ^(major|minor|patch)$ ]]; then
        SKILL_BUMP="$1"
        shift
      fi
      ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

[[ "$BUMP_TYPE" =~ ^(major|minor|patch)$ ]] || usage

# ── Execute ───────────────────────────────────────────────────────────────────

echo "Bumping versions (${BUMP_TYPE}):"

case "$PLUGIN" in
  dev-tools|productivity)
    bump_plugin "$PLUGIN" "$BUMP_TYPE"
    if [[ -n "$SKILL_NAME" ]]; then
      bump_skill "$PLUGIN" "$SKILL_NAME" "$SKILL_BUMP"
    fi
    ;;
  all)
    bump_plugin "dev-tools" "$BUMP_TYPE"
    bump_plugin "productivity" "$BUMP_TYPE"
    if [[ -n "$SKILL_NAME" ]]; then
      echo "Warning: --skill with 'all' is ambiguous; skipping skill bump" >&2
    fi
    ;;
  *) usage ;;
esac

echo "Done. Stage and commit these changes:"
echo "  git add -p"
