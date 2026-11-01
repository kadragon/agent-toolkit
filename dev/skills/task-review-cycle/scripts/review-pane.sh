#!/usr/bin/env bash
# Optional Herdr side pane that live-tails the review's progress log (SKILL.md Step 2).
#
# Usage:
#   review-pane.sh open          -> {"pane":"<id>","log":"<abs path>"} on stdout, or nothing
#   review-pane.sh close <pane>  -> closes that pane; prints nothing
#
# A pane only opens inside herdr-core (HC_TERMINAL_ID set) with herdr-app on PATH. It splits
# the caller's OWN pane, looked up from `herdr-app ls` by HC_TERMINAL_ID — the focused pane may
# belong to something else — and runs `tail -F` on a fresh per-run log under the git dir. A
# per-run path keeps a late panel source from an earlier cycle out of this cycle's view.
#
# The pane is a view, never a gate: every failure (not in hc, no herdr-app/jq, own pane not
# found, split refused, herdr-app hanging) exits 0 with empty stdout, and the caller then runs
# the review exactly as it does without hc. Each herdr-app call is bounded by
# REVIEW_PANE_TIMEOUT seconds (default 10); macOS ships no timeout(1), hence the watcher.

set -uo pipefail

ACTION="${1:-}"
LIMIT="${REVIEW_PANE_TIMEOUT:-10}"

[ -n "${HC_TERMINAL_ID:-}" ] || exit 0
command -v herdr-app >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

# Run "$@" with stdout captured into BOUNDED_OUT, killed after LIMIT seconds.
# The watcher's own output goes to /dev/null so it never holds a command substitution open.
bounded() {
  local out_file pid watcher rc
  out_file=$(mktemp -t review-pane.XXXXXX) || return 1
  "$@" >"$out_file" 2>/dev/null &
  pid=$!
  ( sleep "$LIMIT"; kill "$pid" 2>/dev/null ) >/dev/null 2>&1 &
  watcher=$!
  wait "$pid"
  rc=$?
  kill "$watcher" 2>/dev/null
  wait "$watcher" 2>/dev/null
  BOUNDED_OUT=$(cat "$out_file" 2>/dev/null)
  rm -f "$out_file"
  return "$rc"
}

case "$ACTION" in
  open)
    git_dir=$(git rev-parse --absolute-git-dir 2>/dev/null) || exit 0
    log_dir="$git_dir/task-review"
    mkdir -p "$log_dir" 2>/dev/null || exit 0
    # Logs from earlier days are finished views; drop them so the directory stays small.
    find "$log_dir" -name 'progress.*' -type f -mtime +0 -delete 2>/dev/null || true
    log=$(mktemp "$log_dir/progress.XXXXXX") || exit 0

    bounded herdr-app ls || { rm -f "$log"; exit 0; }
    own_pane=$(jq -r --arg t "$HC_TERMINAL_ID" '
      [.. | objects | select(has("terminal") and has("pane"))
          | select(.terminal == $t or (.terminal | tostring | endswith("/" + $t)))
          | .pane] | first // empty' <<<"$BOUNDED_OUT" 2>/dev/null)
    [ -n "$own_pane" ] || { rm -f "$log"; exit 0; }

    tail_argv=$(jq -cn --arg log "$log" '["tail", "-n", "+1", "-F", $log]')
    bounded herdr-app do pane.split --direction right --pane "$own_pane" --argv "$tail_argv" \
      || { rm -f "$log"; exit 0; }
    new_pane=$(jq -r '.pane // empty' <<<"$BOUNDED_OUT" 2>/dev/null)
    [ -n "$new_pane" ] || { rm -f "$log"; exit 0; }
    jq -cn --arg pane "$new_pane" --arg log "$log" '{pane: $pane, log: $log}'
    ;;
  close)
    pane="${2:-}"
    [ -n "$pane" ] || exit 0
    bounded herdr-app do pane.close --pane "$pane" || true
    ;;
esac
exit 0
