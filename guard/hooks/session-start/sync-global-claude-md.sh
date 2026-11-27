#!/usr/bin/env bash
# SessionStart hook step: sync the GLOBAL CLAUDE.md from a canonical remote URL.
#
# Opt-in. Does nothing unless CLAUDE_MD_SYNC_URL is set (settings.json -> env).
# The remote is the single source of truth: on drift the local file is backed
# up, then overwritten.
#
# Env:
#   CLAUDE_MD_SYNC_URL  - raw URL of the canonical CLAUDE.md (required)
#   CLAUDE_CONFIG_DIR   - config dir, default $HOME/.claude
#
# Runs in every session, in any directory — not repo-scoped, not debounced.
# Best-effort: network failure, empty body, or any error exits 0 silently.

set -uo pipefail

URL="${CLAUDE_MD_SYNC_URL:-}"
[[ -n "$URL" ]] || exit 0
command -v curl >/dev/null 2>&1 || exit 0

CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
TARGET="$CONFIG_DIR/CLAUDE.md"
BACKUP_DIR="$CONFIG_DIR/backups"

# Cache-bust: gist raw URLs sit behind a CDN.
SEP='?'
[[ "$URL" == *"?"* ]] && SEP='&'
FETCH_URL="${URL}${SEP}t=$(date +%s)"

TMP=$(mktemp 2>/dev/null) || exit 0
trap 'rm -f "$TMP"' EXIT

curl -fsSL --max-time 3 -H 'Cache-Control: no-cache' -o "$TMP" "$FETCH_URL" 2>/dev/null || exit 0
[[ -s "$TMP" ]] || exit 0

# Normalize CRLF and trailing blank lines on both sides before comparing.
normalize() {
  tr -d '\r' < "$1" | sed -e ':a' -e '/^[[:space:]]*$/{$d;N;ba' -e '}'
}

REMOTE_NORM=$(normalize "$TMP")
[[ -n "$REMOTE_NORM" ]] || exit 0

if [[ -f "$TARGET" ]]; then
  LOCAL_NORM=$(normalize "$TARGET")
  [[ "$LOCAL_NORM" == "$REMOTE_NORM" ]] && exit 0
  mkdir -p "$BACKUP_DIR" || exit 0
  BACKUP="$BACKUP_DIR/CLAUDE.md.$(date +%Y%m%d-%H%M%S)"
  cp "$TARGET" "$BACKUP" || exit 0
else
  BACKUP=""
fi

printf '%s\n' "$REMOTE_NORM" > "$TARGET" || exit 0

if [[ -n "$BACKUP" ]]; then
  printf 'Global CLAUDE.md synced from %s\n' "$URL"
  printf '  previous version backed up to: %s\n' "$BACKUP"
  printf '  the copy loaded into this session may be stale — re-read %s if a rule matters.\n' "$TARGET"
else
  printf 'Global CLAUDE.md created from %s\n' "$URL"
fi

exit 0
