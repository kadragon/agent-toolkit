#!/usr/bin/env bash
# E) Skills Symlink Guard
#
# Ensures .agents/skills resolves to ../.claude/skills.
# Two valid materializations:
#   - Real symlink (POSIX, or Windows with core.symlinks=true + Developer Mode)
#   - Regular text file containing "../../.claude/skills" (git core.symlinks=false checkout)
# Silent on success; prints one line if a change is made; exits non-zero on ambiguous state.

set -euo pipefail

TARGET="../.claude/skills"
LINK=".agents/skills"

# Case 1: valid symlink
if [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$TARGET" ]; then
  exit 0
fi

# Case 2: git-text-symlink (Windows, core.symlinks=false) — correct representation, leave alone
if [ -f "$LINK" ] && [ ! -L "$LINK" ]; then
  content=$(cat "$LINK")
  if [ "$content" = "$TARGET" ]; then
    exit 0
  fi
fi

# Case 3: wrong-target symlink — safe to replace (just a pointer, no data)
if [ -L "$LINK" ]; then
  rm "$LINK"
fi

# Case 4: missing — create and verify
if [ ! -e "$LINK" ]; then
  mkdir -p .claude/skills .agents
  ln -sfn "$TARGET" "$LINK"
  if [ -L "$LINK" ]; then
    echo "Symlink updated: $LINK → $TARGET"
    exit 0
  fi
  # ln -s fell back to a directory copy (Windows without symlink support).
  # Auto-recover by writing the git mode-120000 text form — works on POSIX peers.
  rm -rf "$LINK"
  printf '%s' "$TARGET" > "$LINK"
  echo "symlink-guard: wrote text-form pointer at $LINK (Windows without symlink support)"
  exit 0
fi

# Case 5: unexpected state (wrong-content file, directory, etc.) — do not destroy, report
echo "symlink-guard: .agents/skills is in an unexpected state (not a symlink or git text-symlink)."
echo "  Current: $(ls -ld "$LINK" 2>&1 || true)"
echo "  Manual fix: rm -rf .agents/skills && bash \$CLAUDE_PLUGIN_ROOT/skills/harness-init/scripts/symlink-guard.sh"
exit 1
