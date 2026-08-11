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

# One private directory per run holds the captured transcript and every diagnostic sidecar.
# `mktemp -d` is 0700, so the payloads — which carry repo content and reasoning traces — are
# never left world-readable in a shared /tmp the way plain redirection under umask 022 would.
# The trap covers abnormal exits (the caller runs this as a long-lived background task, so an
# interrupt is a realistic path); paths that deliberately point the reader at a file set
# KEEP_RUN_DIR first.
RUN_DIR=$(mktemp -d -t codex-review.XXXXXX) || { printf 'ERROR: mktemp failed\n' >&2; exit 1; }
LOG_FILE="$RUN_DIR/codex-stderr.log"
: >"$LOG_FILE"
KEEP_RUN_DIR=""
LOCK_DIR=""
LOCK_HELD=""
cleanup() {
  [ -n "$LOCK_HELD" ] && [ -n "$LOCK_DIR" ] && rm -rf "$LOCK_DIR"
  [ -n "$KEEP_RUN_DIR" ] || rm -rf "$RUN_DIR"
}
trap cleanup EXIT INT TERM

# Exit status for "another cycle already owns this workspace's Codex slot". Distinct from 1 so the
# caller can record a skipped reviewer instead of a dead one — a failed review and a review that
# never ran are different states, and only the latter is retryable as-is.
EX_LOCKED=75

# Windows/MINGW is the only platform where the two PID spaces below diverge, so the selector is
# resolved once. Overridable purely so both branches stay reachable from test_codex_review.py,
# which runs on a Linux CI runner (same device test_ci_wait.sh's timing constants use).
CODEX_REVIEW_PLATFORM="${CODEX_REVIEW_PLATFORM:-$(
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*) printf 'windows' ;;
    *) printf 'posix' ;;
  esac
)}"

# Liveness of a *native* PID — companion and broker PIDs are written by Node, so on MINGW they are
# Windows PIDs that `kill -0` cannot see (Git Bash keeps its own MSYS PID space). `tasklist` output
# is localized (cp949 on a Korean host), so match the PID column rather than any message text, and
# pass the flags in `//X` form so MSYS path conversion leaves them alone.
#
# Fails SAFE: an unreadable probe — no `tasklist`, non-zero exit — reports alive, so nothing is
# pruned on evidence we do not have.
native_pid_alive() {
  local pid="$1" out=""
  case "$pid" in
    "" | *[!0-9]*) return 1 ;;
  esac
  if [ "$CODEX_REVIEW_PLATFORM" = "windows" ]; then
    command -v tasklist >/dev/null 2>&1 || return 0
    out=$(MSYS2_ARG_CONV_EXCL='*' tasklist //NH //FI "PID eq $pid" 2>/dev/null) || return 0
    # The filter already narrows output to this PID, so presence of any image name means alive;
    # the not-found case is a localized sentence with no image name. Matching `.exe` rather than
    # the PID column avoids a false hit on a digit run inside the memory column.
    if printf '%s' "$out" | grep -qi '\.exe'; then
      return 0
    fi
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

# Slug the companion builds its state directory from: `<basename>-<sha256(realpath)[:16]>`. Only the
# basename half is reproducible from bash (the hash is taken over Node's canonicalized path), which
# is enough to scope the prune to this workspace — the PID check is what makes each individual
# removal safe.
workspace_slug() {
  local root
  root=$(git rev-parse --show-toplevel 2>/dev/null) || return 1
  basename "$root" | sed -e 's/[^a-zA-Z0-9._-][^a-zA-Z0-9._-]*/-/g' -e 's/^-*//' -e 's/-*$//'
}

# Rewrite one orphaned job record and mirror it into the workspace index. Separated from the scan so
# a malformed record fails alone instead of aborting the sweep.
prune_job_record() {
  local job_file="$1" ws="$2" job_id="$3" pid="$4" tmp="$RUN_DIR/job.json"
  local msg="Orphaned: owning process $pid exited without completing the job (pruned by codex-review.sh)."
  jq --arg m "$msg" \
    '.status = "failed" | .phase = "failed" | .pid = null | .errorMessage = $m' \
    "$job_file" >"$tmp" 2>/dev/null || return 1
  mv "$tmp" "$job_file" || return 1
  local index="$ws/state.json"
  [ -f "$index" ] || return 0
  jq --arg id "$job_id" \
    '.jobs = [(.jobs // [])[] | if .id == $id and (.status == "running" or .status == "queued")
       then .status = "failed" | .phase = "failed" | .pid = null else . end]' \
    "$index" >"$tmp" 2>/dev/null || return 1
  mv "$tmp" "$index"
}

# Clear codex-companion state left behind by a killed process before launching a new review.
#
# Why this exists: on Windows the shared broker is spawned as a *child* of whichever companion first
# needed it (`detached: true` does not sever the parent-child link there), and every teardown path
# runs `taskkill /PID x /T /F`. So killing any companion — SessionEnd, /codex:cancel, or Claude Code
# stopping a background Bash task — takes the shared broker with it. What survives is metadata: job
# records frozen at `running` and a `broker.json` naming a dead PID, which the next run happily
# reuses and then dies against mid-turn with no JSON on stdout.
#
# Never fatal: a review that cannot pre-clean is still worth running, so every failure here warns
# and returns 0.
prune_stale_codex_state() {
  command -v jq >/dev/null 2>&1 || { printf 'WARN: jq unavailable — skipping stale codex state prune\n' >&2; return 0; }
  local slug
  slug=$(workspace_slug) || { printf 'WARN: not a git repository — skipping stale codex state prune\n' >&2; return 0; }
  [ -n "$slug" ] || return 0

  local roots ws ws_suffix job_file job_id status pid broker_pid session_dir
  # Default covers every installed marketplace copy of the plugin's data dir; the override collapses
  # it to one fixture tree for the test.
  roots="${CODEX_REVIEW_STATE_ROOTS:-$HOME/.claude/plugins/data/*/state}"

  # shellcheck disable=SC2086  # both halves are globs on purpose: the root list and the slug suffix
  for ws in ${roots}/${slug}-*; do
    [ -d "$ws" ] || continue
    # `${slug}-*` is a prefix match, and a prefix is not an identity: from repo `foo` it also
    # matches repo `foo-bar`'s directory `foo-bar-<hash>`. What the companion actually appends is
    # `-` plus exactly 16 hex digits, so require that shape before touching anything inside.
    ws_suffix=$(basename "$ws")
    ws_suffix=${ws_suffix#"$slug"-}
    [ ${#ws_suffix} -eq 16 ] || continue
    case "$ws_suffix" in
      *[!0-9a-f]*) continue ;;
    esac
    for job_file in "$ws"/jobs/*.json; do
      [ -f "$job_file" ] || continue
      status=$(jq -r '.status // ""' "$job_file" 2>/dev/null) || continue
      case "$status" in
        running | queued) ;;
        *) continue ;;
      esac
      pid=$(jq -r '.pid // ""' "$job_file" 2>/dev/null) || continue
      if native_pid_alive "$pid"; then
        continue
      fi
      job_id=$(jq -r '.id // ""' "$job_file" 2>/dev/null) || continue
      if prune_job_record "$job_file" "$ws" "$job_id" "$pid"; then
        printf 'WARN: pruned orphaned codex job %s (pid %s dead)\n' "${job_id:-$job_file}" "${pid:-none}" >&2
      else
        printf 'WARN: could not prune codex job record %s\n' "$job_file" >&2
      fi
    done

    [ -f "$ws/broker.json" ] || continue
    broker_pid=$(jq -r '.pid // ""' "$ws/broker.json" 2>/dev/null) || continue
    native_pid_alive "$broker_pid" && continue
    session_dir=$(jq -r '.sessionDir // ""' "$ws/broker.json" 2>/dev/null) || session_dir=""
    # broker.json records the session dir as the plugin's *native* path, so on MINGW it arrives as
    # `C:\Users\...\Temp\cxc-xxxxxx` — a string no bash test or `rm` can resolve until cygpath
    # rewrites it. Elsewhere the path is already POSIX and cygpath is absent.
    if [ -n "$session_dir" ] && command -v cygpath >/dev/null 2>&1; then
      session_dir=$(cygpath -u "$session_dir" 2>/dev/null || printf '%s' "$session_dir")
    fi
    rm -f "$ws/broker.json"
    # Only ever remove a directory the plugin itself created: `createBrokerSessionDir` names it
    # `cxc-XXXXXX` under the OS temp dir. Anything else is not ours to delete.
    case "$(basename "${session_dir:-.}")" in
      cxc-?*) [ -d "$session_dir" ] && rm -rf "$session_dir" ;;
    esac
    printf 'WARN: pruned stale codex broker record (pid %s dead)\n' "${broker_pid:-none}" >&2
  done
  return 0
}

# Serialize review runs per workspace. The shared broker is single-flight per workspace
# (`app-server-broker.mjs` rejects a second client with -32001), so two overlapping cycles push the
# loser onto a second app-server and double the orphan surface this script just cleaned up.
#
# `mkdir` is the lock primitive: atomic on every filesystem that matters and, unlike flock, present
# in Git Bash. The owner PID recorded inside is *this bash process*, so it is probed with `kill -0`
# and NOT with native_pid_alive — on MINGW `$$` is an MSYS PID that `tasklist` cannot see, and
# probing it there would report every live holder as dead and steal the lock from under it.
acquire_workspace_lock() {
  local slug lock_root owner
  slug=$(workspace_slug) || return 0
  [ -n "$slug" ] || return 0
  lock_root="${CODEX_REVIEW_LOCK_ROOT:-${TMPDIR:-/tmp}}"
  if ! mkdir -p "$lock_root" 2>/dev/null; then
    printf 'WARN: cannot create the lock root %s — running unserialized\n' "$lock_root" >&2
    return 0
  fi
  LOCK_DIR="$lock_root/codex-review-${slug}.lock"

  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_HELD=1
    printf '%s\n' "$$" >"$LOCK_DIR/pid"
    return 0
  fi

  owner=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then
    printf 'ERROR: another codex review is already running for this workspace (pid %s); skipping\n' "$owner" >&2
    LOCK_DIR=""
    return 1
  fi

  # Stale lock: the recorded owner is gone (or never got as far as writing its PID).
  rm -rf "$LOCK_DIR"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_HELD=1
    printf '%s\n' "$$" >"$LOCK_DIR/pid"
    printf 'WARN: reclaimed stale codex review lock (owner %s gone)\n' "${owner:-unknown}" >&2
    return 0
  fi

  printf 'ERROR: could not acquire the codex review lock for this workspace; skipping\n' >&2
  LOCK_DIR=""
  return 1
}

# Bounded diagnostic: last N lines of a file, prefixed so the caller can tell it apart from
# review text. The full file is left on disk and named, so nothing is actually lost.
emit_log_tail() {
  local file="$1" label="$2"
  KEEP_RUN_DIR=1
  printf 'WARN: %s (last %s lines / %s bytes; full log: %s)\n' \
    "$label" "$DIAG_TAIL_LINES" "$DIAG_TAIL_BYTES" "$file" >&2
  tail -n "$DIAG_TAIL_LINES" "$file" | tail -c "$DIAG_TAIL_BYTES" >&2 || true
  printf '\n' >&2
}

# Same idea for an in-memory blob (companion JSON / failure payload). Persisted first so the
# bounded excerpt always names a file holding the discarded remainder.
emit_blob_tail() {
  local blob="$1" label="$2" file="$RUN_DIR/payload.txt"
  KEEP_RUN_DIR=1
  printf '%s\n' "$blob" >"$file"
  printf 'WARN: %s (last %s bytes; full payload: %s)\n' "$label" "$DIAG_TAIL_BYTES" "$file" >&2
  tail -c "$DIAG_TAIL_BYTES" "$file" >&2 || true
  printf '\n' >&2
}

emit_review() {
  local text="$1"
  local size
  size=$(printf '%s' "$text" | wc -c)
  if [ "$size" -le "$MAX_REVIEW_BYTES" ]; then
    printf '%s\n' "$text"
    return
  fi
  local full="$RUN_DIR/review.txt"
  KEEP_RUN_DIR=1
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
      exit 1
    fi
    # Lock first, prune second: the prune reads state another live cycle is actively writing, and
    # taking the lock is what makes "this PID is dead" a safe conclusion rather than a race.
    acquire_workspace_lock || exit "$EX_LOCKED"
    prune_stale_codex_state
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
      # Point at the log only when it holds something; emit_log_tail is what pins the run dir.
      [ -s "$LOG_FILE" ] && emit_log_tail "$LOG_FILE" "companion stderr"
      exit "$codex_status"
    fi
    # Extract `.codex.stdout` and nothing else. jq is the workflow-wide requirement
    # (preflight.sh exits without it), and node is guaranteed in plugin mode — so one of the
    # two always parses. Neither a raw-JSON nor a `.rendered` fallback is offered: both carry
    # the reasoning trace (`.rendered` appends a "Reasoning:" section built from
    # `reasoningSummary`), which is precisely the flood this script exists to prevent.
    # Both parsers emit `.codex.status` on the first line and `.codex.stdout` on the rest, so
    # an empty review body can be told apart from a failed parse: status 0 with no body is the
    # companion's "review completed without any stdout output" case (inconclusive — see below),
    # while an unparseable payload or a non-zero status is a genuine failure.
    PARSED=""
    PAYLOAD=""
    JQ_ERR=""
    if command -v jq >/dev/null 2>&1; then
      _jq_err_file="$RUN_DIR/jq.err"
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
      # Split with parameter expansion, never `printf ... | head -n 1`: under `pipefail` the
      # early-exiting `head` SIGPIPEs the writer once the payload passes the pipe buffer
      # (~64 KB), and `set -e` then kills the script with 141 — silently, and precisely on the
      # oversized payloads the truncation path below exists to handle.
      PAYLOAD_STATUS=${PAYLOAD%%$'\n'*}
      case "$PAYLOAD" in
        *$'\n'*) TEXT=${PAYLOAD#*$'\n'} ;;
        *) TEXT="" ;;
      esac
    fi
    if [ -z "$TEXT" ] && [ "$PAYLOAD_STATUS" = "0" ]; then
      # Companion ran to completion but carried no review body. `buildResultStatus` returns 0
      # for any completed turn, and `reviewText` is only filled from an `exitedReviewMode`
      # item — so this means the review item arrived empty, NOT that Codex found nothing.
      # Exit 0 so the source isn't recorded as a dead reviewer, but keep the companion's own
      # neutral wording: consolidation must read this as inconclusive, not as a clean bill.
      TEXT="Codex review completed without any review output (empty review body) — inconclusive, not a finding-free review."
    fi
    if [ -z "$TEXT" ]; then
      [ -n "$JQ_ERR" ] && printf 'WARN: jq parse error: %s\n' "$JQ_ERR" >&2
      printf 'ERROR: could not extract .codex.stdout from companion JSON (payload status: %s)\n' \
        "${PAYLOAD_STATUS:-unparsed}" >&2
      emit_blob_tail "$RAW" "companion stdout"
      # Point at the log only when it holds something; emit_log_tail is what pins the run dir.
      [ -s "$LOG_FILE" ] && emit_log_tail "$LOG_FILE" "companion stderr"

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
    exit 1
    ;;
esac
