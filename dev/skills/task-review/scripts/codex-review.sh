#!/usr/bin/env bash
# Launch Codex code review against a base branch.
# Selects plugin mode (codex-companion.mjs) or CLI mode automatically.
#
# Usage: codex-review.sh <codex_mode> <base_branch> [codex_companion_path]
#   codex_mode: "plugin" | "cli"
#   codex_companion_path: path to codex-companion.mjs (required for plugin mode)
#
# Output contract: stdout carries the FINAL review text and nothing else.
# Codex streams its whole session transcript (measured: ~150 KB for a small diff) on stderr;
# the caller runs this script as a background Bash task, which merges both streams into one
# capped output file. So every diagnostic here is bounded to a tail excerpt that names the
# full log path — never the raw transcript, never the raw companion JSON.

set -euo pipefail

CODEX_MODE="${1:?Usage: codex-review.sh <codex_mode> <base_branch> [codex_companion_path]}"
BASE_BRANCH="${2:?Usage: codex-review.sh <codex_mode> <base_branch> [codex_companion_path]}"
CODEX_COMPANION_PATH="${3:-}"

# Bytes of review text emitted before head/tail truncation kicks in. A real review runs a few
# KB; anything past this is a transcript that leaked into the review field, and dumping it
# would blow the caller's output budget and push the findings out of view.
MAX_REVIEW_BYTES="${CODEX_REVIEW_MAX_BYTES:-40000}"
DIAG_TAIL_LINES=40
# Diagnostics are bounded by bytes as well as lines: a pretty-printed companion payload puts
# its whole reasoning trace on one physical line, so a line-only tail can still emit ~150 KB.
DIAG_TAIL_BYTES=2000

LOG_FILE=$(mktemp -t codex-review.XXXXXX) || { printf 'ERROR: mktemp failed\n' >&2; exit 1; }

# Bounded diagnostic: last N lines of a file, prefixed so the caller can tell it apart from
# review text. The full file is left on disk and named, so nothing is actually lost.
emit_log_tail() {
  local file="$1" label="$2"
  printf 'WARN: %s (last %s lines / %s bytes; full log: %s)\n' \
    "$label" "$DIAG_TAIL_LINES" "$DIAG_TAIL_BYTES" "$file" >&2
  tail -n "$DIAG_TAIL_LINES" "$file" | tail -c "$DIAG_TAIL_BYTES" >&2 || true
  printf '\n' >&2
}

# Same idea for an in-memory blob (companion JSON / failure payload). Persisted first so the
# bounded excerpt always names a file holding the discarded remainder.
emit_blob_tail() {
  local blob="$1" label="$2" file="${LOG_FILE}.payload.txt"
  printf '%s\n' "$blob" >"$file"
  printf 'WARN: %s (last %s bytes; full payload: %s)\n' "$label" "$DIAG_TAIL_BYTES" "$file" >&2
  tail -c "$DIAG_TAIL_BYTES" "$file" >&2 || true
  printf '\n' >&2
}

emit_review() {
  local text="$1"
  local size
  # Past this point the captured transcript is no longer needed on either branch: a review was
  # extracted, so the log holds nothing but Codex's own chatter.
  rm -f "$LOG_FILE"
  size=$(printf '%s' "$text" | wc -c)
  if [ "$size" -le "$MAX_REVIEW_BYTES" ]; then
    printf '%s\n' "$text"
    return
  fi
  local full="${LOG_FILE}.review.txt"
  printf '%s\n' "$text" >"$full"
  printf 'WARN: review text is %s bytes (> %s); emitting head+tail. Full text: %s\n' \
    "$size" "$MAX_REVIEW_BYTES" "$full" >&2
  head -c $((MAX_REVIEW_BYTES / 2)) "$full"
  printf '\n\n[... truncated by codex-review.sh — full text at %s ...]\n\n' "$full"
  tail -c $((MAX_REVIEW_BYTES / 2)) "$full"
}

case "$CODEX_MODE" in
  plugin)
    if [ -z "$CODEX_COMPANION_PATH" ]; then
      echo "ERROR: codex_companion_path is required for plugin mode" >&2
      rm -f "$LOG_FILE"
      exit 1
    fi
    # --json disables the companion's live reasoning stream (stderr) and the reasoning section
    # appended to the rendered text. stdout becomes a single JSON object whose .codex.stdout
    # holds the pure review (findings + verdict). stderr is still redirected: a companion that
    # dies early can fall back to the underlying CLI's chatter.
    # Capture codex_status without tripping `set -e`: on a non-zero review run the companion
    # writes its failure payload to stdout (RAW), so surface a bounded excerpt of it before
    # propagating the exit code — otherwise the caller only sees the generic fallback and
    # loses the diagnostic detail.
    RAW=""
    codex_status=0
    RAW=$(node "$CODEX_COMPANION_PATH" review --base "$BASE_BRANCH" --json 2>"$LOG_FILE") || codex_status=$?
    if [ "$codex_status" -ne 0 ]; then
      printf 'WARN: codex companion exited %s\n' "$codex_status" >&2
      [ -n "$RAW" ] && emit_blob_tail "$RAW" "companion failure payload"
      # Keep the log only when it holds something a reader was pointed at.
      if [ -s "$LOG_FILE" ]; then emit_log_tail "$LOG_FILE" "companion stderr"; else rm -f "$LOG_FILE"; fi
      exit "$codex_status"
    fi
    # Extract `.codex.stdout` and nothing else. jq is the workflow-wide requirement
    # (preflight.sh exits without it), and node is guaranteed in plugin mode — so one of the
    # two always parses. Neither a raw-JSON nor a `.rendered` fallback is offered: both carry
    # the reasoning trace (`.rendered` appends a "Reasoning:" section built from
    # `reasoningSummary`), which is precisely the flood this script exists to prevent.
    # Both parsers emit `.codex.status` on the first line and `.codex.stdout` on the rest, so
    # an empty review body can be told apart from a failed parse: status 0 with no body is the
    # companion's "review completed without any stdout output" case (a real, finding-free
    # review), while an unparseable payload or a non-zero status is a genuine failure.
    PARSED=""
    PAYLOAD=""
    JQ_ERR=""
    if command -v jq >/dev/null 2>&1; then
      _jq_err_file="${LOG_FILE}.jq"
      PAYLOAD=$(printf '%s' "$RAW" \
        | jq -r '((.codex.status // "none") | tostring), (.codex.stdout // "")' 2>"$_jq_err_file") || PAYLOAD=""
      JQ_ERR=$(cat "$_jq_err_file")
      rm -f "$_jq_err_file"
      if [ -n "$JQ_ERR" ]; then
        # A parse error means jq may have emitted only a partial parse of a
        # valid-prefix/trailing-garbage payload; the captured text is unreliable, so discard it
        # and let the node path (or the hard failure below) decide — never emit a truncated review.
        PAYLOAD=""
      elif [ -n "$PAYLOAD" ]; then
        PARSED=1
      fi
    fi
    if [ -z "$PARSED" ]; then
      PAYLOAD=$(printf '%s' "$RAW" | node -e '
        let raw = "";
        process.stdin.on("data", (c) => { raw += c; });
        process.stdin.on("end", () => {
          try {
            const p = JSON.parse(raw);
            const status = p?.codex?.status ?? "none";
            process.stdout.write(String(status) + "\n" + (p?.codex?.stdout || ""));
          } catch { process.exit(3); }
        });
      ' 2>/dev/null) && PARSED=1 || PAYLOAD=""
    fi
    PAYLOAD_STATUS=""
    TEXT=""
    if [ -n "$PARSED" ]; then
      PAYLOAD_STATUS=$(printf '%s' "$PAYLOAD" | head -n 1)
      TEXT=$(printf '%s' "$PAYLOAD" | tail -n +2)
    fi
    if [ -z "$TEXT" ] && [ "$PAYLOAD_STATUS" = "0" ]; then
      # Successful run, no review body — report it as a result, not as a dead reviewer, so
      # consolidation records "no findings" instead of "codex_review: failed".
      TEXT="Codex review completed with no findings (empty review body)."
    fi
    if [ -z "$TEXT" ]; then
      [ -n "$JQ_ERR" ] && printf 'WARN: jq parse error: %s\n' "$JQ_ERR" >&2
      printf 'ERROR: could not extract .codex.stdout from companion JSON (payload status: %s)\n' \
        "${PAYLOAD_STATUS:-unparsed}" >&2
      emit_blob_tail "$RAW" "companion stdout"
      # Keep the log only when it holds something a reader was pointed at.
      if [ -s "$LOG_FILE" ]; then emit_log_tail "$LOG_FILE" "companion stderr"; else rm -f "$LOG_FILE"; fi
      exit 1
    fi
    emit_review "$TEXT"
    ;;
  cli)
    # `codex review` prints the final review on stdout and streams the entire session
    # transcript on stderr. Redirect stderr to the log so only the review reaches the caller.
    codex_status=0
    TEXT=$(codex review --base "$BASE_BRANCH" 2>"$LOG_FILE") || codex_status=$?
    if [ "$codex_status" -ne 0 ]; then
      printf 'WARN: codex review exited %s\n' "$codex_status" >&2
      emit_log_tail "$LOG_FILE" "codex CLI transcript"
      exit "$codex_status"
    fi
    if [ -z "$TEXT" ]; then
      printf 'ERROR: codex review produced no review text on stdout\n' >&2
      emit_log_tail "$LOG_FILE" "codex CLI transcript"
      exit 1
    fi
    emit_review "$TEXT"
    ;;
  *)
    echo "ERROR: Unknown codex_mode '$CODEX_MODE'. Expected 'plugin' or 'cli'." >&2
    rm -f "$LOG_FILE"
    exit 1
    ;;
esac
