#!/usr/bin/env bash
# Bump plugin and/or skill versions atomically.
# Usage: bump-version.sh <plugin> <major|minor|patch> [--skill <name> [major|minor|patch]]
#
# dev and prod carry a Claude and a Codex manifest, bumped in sync. mods is
# Claude Code only (function hooks), so it has the Claude manifest alone.
#
# Semver rules — full table: docs/conventions.md → Plugin Version Bump Rules.
#   add skill/agent/command/hook → minor
#   modify any shipped asset     → patch
#   add a bundled file to an existing skill (scripts/references/examples/evals) → patch
#     (reachable only through the skill that already shipped, so the consumer gained a
#     changed skill, not a new asset)
#   remove/rename a hook         → patch (a hook has no invocable name)
#   remove/rename skill/agent/command → major (breaks a by-name call)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat >&2 <<EOF
Usage: $0 <plugin> <major|minor|patch> [--skill <name> [major|minor|patch]]

  plugin:     dev | prod | mods | all
  bump type:  major | minor | patch

  --skill <name> [major|minor|patch]
    Also bump the version in skills/<name>/SKILL.md frontmatter.
    Defaults to 'patch' if bump type omitted.

Examples:
  $0 dev patch
  $0 dev minor --skill harness-curate patch
  $0 mods patch
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

# Plugins that ship no .codex-plugin manifest.
is_claude_only() {
  [[ "$1" == "mods" ]]
}

read_version() {
  local json="$1" version
  [[ -f "$json" ]] || { echo "Not found: $json" >&2; exit 1; }
  version=$(grep '"version"' "$json" | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/' | tr -d '\r')
  [[ -n "$version" ]] || { echo "Could not parse version from $json" >&2; exit 1; }
  echo "$version"
}

bump_plugin() {
  local plugin="$1" bump_type="$2"
  local manifests=("${REPO_ROOT}/${plugin}/.claude-plugin/plugin.json")
  is_claude_only "$plugin" || manifests+=("${REPO_ROOT}/${plugin}/.codex-plugin/plugin.json")

  # Read every manifest before rewriting any, so a missing one changes nothing.
  local json current claude_ver="" versions=()
  for json in "${manifests[@]}"; do
    current=$(read_version "$json")
    versions+=("$current")
    [[ -n "$claude_ver" ]] || claude_ver="$current"
  done

  local new_version
  new_version=$(bump_semver "$claude_ver" "$bump_type")

  local index
  for index in "${!manifests[@]}"; do
    json="${manifests[$index]}"
    current="${versions[$index]}"
    perl -pi -e "s/\"version\": *\"\Q${current}\E\"/\"version\": \"${new_version}\"/" "$json"
    # The parse above tolerates spacing the replace once did not — verify rather than trust.
    grep -q "\"version\": \"${new_version}\"" "$json" || {
      echo "Failed to rewrite version in $json" >&2
      exit 1
    }
  done

  echo "  ${plugin}: ${claude_ver} → ${new_version}"
}

bump_skill() {
  local plugin="$1" skill_name="$2" bump_type="$3"
  local skill_md="${REPO_ROOT}/${plugin}/skills/${skill_name}/SKILL.md"

  [[ -f "$skill_md" ]] || { echo "Not found: $skill_md" >&2; exit 1; }

  local current_version
  current_version=$(grep '^version:' "$skill_md" | awk '{print $2}' | tr -d '\r')

  [[ -n "$current_version" ]] || { echo "No 'version:' field in $skill_md" >&2; exit 1; }

  local new_version
  new_version=$(bump_semver "$current_version" "$bump_type")

  # \Q..\E quotes the dots; the (?=\r?$) lookahead matches CRLF checkouts (Windows
  # core.autocrlf) without consuming the \r, so the file's line endings survive.
  perl -pi -e "s/^version:[ \t]*\Q${current_version}\E(?=\r?\$)/version: ${new_version}/" "$skill_md"

  grep -q "^version: ${new_version}" "$skill_md" || {
    echo "Failed to rewrite version in $skill_md (still ${current_version})" >&2
    exit 1
  }
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

# ── Pre-flight: validate all targets before mutating any files ─────────────────

if [[ -n "$SKILL_NAME" ]]; then
  if [[ "$PLUGIN" == "all" ]]; then
    echo "Error: --skill with 'all' is ambiguous; specify the plugin explicitly" >&2
    exit 1
  fi
  _skill_md="${REPO_ROOT}/${PLUGIN}/skills/${SKILL_NAME}/SKILL.md"
  [[ -f "$_skill_md" ]] || { echo "Not found: $_skill_md" >&2; exit 1; }
  grep -q '^version:' "$_skill_md" || { echo "No 'version:' field in $_skill_md" >&2; exit 1; }
fi

# ── Execute ───────────────────────────────────────────────────────────────────

echo "Bumping versions (${BUMP_TYPE}):"

case "$PLUGIN" in
  dev|prod|mods)
    bump_plugin "$PLUGIN" "$BUMP_TYPE"
    if [[ -n "$SKILL_NAME" ]]; then
      bump_skill "$PLUGIN" "$SKILL_NAME" "$SKILL_BUMP"
    fi
    ;;
  all)
    bump_plugin "dev" "$BUMP_TYPE"
    bump_plugin "prod" "$BUMP_TYPE"
    bump_plugin "mods" "$BUMP_TYPE"
    ;;
  *) usage ;;
esac

echo "Done. Stage and commit these changes:"
echo "  git add -p"
