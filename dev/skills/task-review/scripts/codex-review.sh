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
  # Release only a lock this process still owns: after a reclaim race the directory at that path can
  # belong to someone else, and dropping it would admit a third run.
  if [ -n "$LOCK_HELD" ] && [ -n "$LOCK_DIR" ] &&
    [ "$(cat "$LOCK_DIR/pid" 2>/dev/null || true)" = "$$" ]; then
    rm -rf "$LOCK_DIR"
  fi
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
# is localized (cp949 on a Korean host), so match on the image name rather than any message text.
#
# Flag form is load-bearing and the two halves must agree: `MSYS2_ARG_CONV_EXCL='*'` switches MSYS
# path conversion off, so the flags must be written `/NH` and reach tasklist verbatim. Writing them
# `//NH` — the form that survives conversion when it is ON — passes a literal `//NH`, which tasklist
# rejects with "invalid argument/option" and a non-zero exit; the `|| return 0` below would then
# report every PID as alive and silently disable the prune on the one platform it exists for.
#
# Fails SAFE in every direction: an unreadable probe — no `tasklist`, non-zero exit — reports alive,
# and so does a PID we cannot read at all. Both `broker-lifecycle.mjs` and `codex-companion.mjs`
# write `pid: child.pid ?? null`, so a null PID is a record whose owner we have NO evidence about;
# calling that dead would delete a possibly-live broker's endpoint out from under every other client
# on the workspace. Nothing is pruned on evidence we do not have.
native_pid_alive() {
  local pid="$1" out=""
  case "$pid" in
    "" | null | *[!0-9]*) return 0 ;;
  esac
  if [ "$CODEX_REVIEW_PLATFORM" = "windows" ]; then
    command -v tasklist >/dev/null 2>&1 || return 0
    out=$(MSYS2_ARG_CONV_EXCL='*' tasklist /NH /FI "PID eq $pid" 2>/dev/null) || return 0
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

# Basename half of the companion's state directory name, `<basename>-<sha256(realpath)[:16]>`. Only
# this half is reproducible from bash; the hash is taken over Node's canonicalized native path, which
# the shell cannot reconstruct (see the measurement in prune_stale_codex_state). Ambiguity between
# two same-basename workspaces is therefore resolved by refusing to act, not by guessing.
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
# and returns 0. The helpers it is built from follow.

# One temp root per line — the only place a broker session dir may legitimately live, since
# `createBrokerSessionDir` builds it with `fs.mkdtempSync(path.join(os.tmpdir(), "cxc-"))`.
temp_roots() {
  local root
  if [ -n "${CODEX_REVIEW_TEMP_ROOTS:-}" ]; then
    printf '%s\n' "$CODEX_REVIEW_TEMP_ROOTS"
    return 0
  fi
  for root in "${TMPDIR:-}" "${TEMP:-}" "${TMP:-}" /tmp; do
    [ -n "$root" ] || continue
    if command -v cygpath >/dev/null 2>&1; then
      root=$(cygpath -u "$root" 2>/dev/null || printf '%s' "$root")
    fi
    [ -d "$root" ] && printf '%s\n' "${root%/}"
  done
  return 0
}

# One state root per line. The override collapses the set to a single fixture tree for the test.
# The default mirrors the companion's own `resolveStateDir`: `$CLAUDE_PLUGIN_DATA/state` when that
# env var is set, otherwise `<os.tmpdir()>/codex-companion` — plus every installed marketplace copy
# under the plugins data dir. Miss these and the prune quietly finds nothing in exactly the setups
# that deviate from the default install.
state_roots() {
  local root
  if [ -n "${CODEX_REVIEW_STATE_ROOTS:-}" ]; then
    printf '%s\n' "$CODEX_REVIEW_STATE_ROOTS"
    return 0
  fi
  [ -n "${CLAUDE_PLUGIN_DATA:-}" ] && [ -d "$CLAUDE_PLUGIN_DATA/state" ] && printf '%s\n' "$CLAUDE_PLUGIN_DATA/state"
  while IFS= read -r root; do
    [ -d "$root/codex-companion" ] && printf '%s\n' "$root/codex-companion"
  done <<EOF
$(temp_roots)
EOF
  for root in "$HOME"/.claude/plugins/data/*/state; do
    [ -d "$root" ] && printf '%s\n' "$root"
  done
  return 0
}

# True when the candidate directory is an immediate child of one of the temp roots above.
#
# Identity is tested with `-ef` (same device+inode), not a string prefix: MSYS mounts the Windows
# temp dir at `/tmp`, so cygpath rewrites `C:\Users\...\AppData\Local\Temp\x` to `/tmp/x` while the
# same directory reached another way reads `/c/Users/.../Temp/x`. A prefix comparison calls those
# two different places and would wrongly refuse to clean up on Windows.
#
# Immediate child, not "anywhere below": `createBrokerSessionDir` is
# `mkdtempSync(join(os.tmpdir(), "cxc-"))`, so a real session dir's parent IS the temp root.
under_temp_root() {
  local candidate="$1" parent root
  [ -d "$candidate" ] || return 1
  parent=$(dirname "$candidate")
  while IFS= read -r root; do
    [ -n "$root" ] || continue
    [ -d "$root" ] || continue
    if [ "$parent" -ef "$root" ]; then
      return 0
    fi
  done <<EOF
$(temp_roots)
EOF
  return 1
}

prune_stale_codex_state() {
  command -v jq >/dev/null 2>&1 || { printf 'WARN: jq unavailable — skipping stale codex state prune\n' >&2; return 0; }
  local slug
  slug=$(workspace_slug) || { printf 'WARN: not a git repository — skipping stale codex state prune\n' >&2; return 0; }
  [ -n "$slug" ] || return 0

  local root ws ws_suffix job_file job_id status pid broker_pid session_dir
  local matches="" match_count=0

  # Roots are iterated, never held in one word-split string: `$HOME` on Windows routinely contains a
  # space (`/c/Users/First Last`), and splitting the default on IFS would turn it into two paths that
  # match nothing — the prune silently becoming a no-op on the platform it exists for.
  while IFS= read -r root; do
    [ -d "$root" ] || continue
    # Quoting the variable still leaves the trailing `*` to glob; it only stops the *root* from being
    # re-split or re-globbed.
    for ws in "$root"/"$slug"-*; do
      [ -d "$ws" ] || continue
      # `${slug}-*` is a prefix match, and a prefix is not an identity: from repo `foo` it also
      # matches repo `foo-bar`'s directory `foo-bar-<hash>`. What the companion actually appends is
      # `-` plus exactly 16 hex digits, so require that shape before collecting the directory.
      ws_suffix=$(basename "$ws")
      ws_suffix=${ws_suffix#"$slug"-}
      [ ${#ws_suffix} -eq 16 ] || continue
      case "$ws_suffix" in
        *[!0-9a-f]*) continue ;;
      esac
      matches="${matches}${ws}
"
      match_count=$((match_count + 1))
    done
  done <<EOF
$(state_roots)
EOF

  # Shape is not identity either. The suffix is `sha256(canonical native path)[:16]`, and that hash
  # is NOT reproducible from the shell: measured on this repo, the live directory's suffix hashes
  # `C:\Dev\agent-toolkit` — the on-disk casing `fs.realpathSync.native` returns — while git and bash
  # both report `C:/dev/agent-toolkit`. So when two checkouts share a basename (`/a/foo`, `/b/foo`)
  # there is no way here to tell which directory is ours. One match is unambiguous; more than one is
  # not, and touching either would be the cross-workspace write this prune must never do.
  if [ "$match_count" -gt 1 ]; then
    printf 'WARN: %s codex state directories share the basename "%s"; cannot identify this workspace from the shell — skipping prune\n' \
      "$match_count" "$slug" >&2
    return 0
  fi

  while IFS= read -r ws; do
    [ -d "$ws" ] || continue
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
    # Guarded, not bare: an unguarded `rm` that hits a read-only or locked file returns non-zero,
    # and under `set -e` that would abort the whole review before the companion ever launches —
    # the opposite of this function's "never fatal" contract.
    rm -f "$ws/broker.json" 2>/dev/null ||
      printf 'WARN: could not remove stale broker record %s\n' "$ws/broker.json" >&2
    # Only ever remove a directory the plugin itself created: `createBrokerSessionDir` is
    # `mkdtempSync(join(os.tmpdir(), "cxc-"))`, so BOTH halves must hold — the `cxc-` name and a
    # location under a temp root. The name alone is not evidence: a `sessionDir` of
    # `/some/project/cxc-cache`, or a relative path, would otherwise be recursively deleted.
    case "$(basename "${session_dir:-.}")" in
      cxc-?*)
        if [ -d "$session_dir" ] && under_temp_root "$session_dir"; then
          rm -rf "$session_dir" 2>/dev/null ||
            printf 'WARN: could not remove stale broker session dir %s\n' "$session_dir" >&2
        elif [ -d "$session_dir" ]; then
          printf 'WARN: broker session dir %s is outside every temp root — left in place\n' "$session_dir" >&2
        fi
        ;;
    esac
    printf 'WARN: pruned stale codex broker record (pid %s dead)\n' "${broker_pid:-none}" >&2
  done <<EOF
$matches
EOF
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
claim_workspace_lock() {
  mkdir "$LOCK_DIR" 2>/dev/null || return 1
  printf '%s\n' "$$" >"$LOCK_DIR/pid" 2>/dev/null || return 1
  LOCK_HELD=1
  return 0
}

# Take over a lock whose recorded owner is gone, WITHOUT ever deleting a directory in place.
#
# A plain `rm -rf` + `mkdir` loses mutual exclusion in exactly the case the lock exists for: stale
# locks are the common path here (SIGKILL/taskkill teardown is the documented failure mode), and two
# runs that both find one can interleave so that the second deletes the first's freshly created lock
# and both believe they hold it. `mv` is the arbiter instead — a rename of a directory that another
# process already renamed simply fails, so exactly one reclaimer proceeds.
#
# The moved-aside PID is then compared against the dead owner this run actually inspected. A
# mismatch means a live claim landed between the inspection and the rename, so the directory goes
# back untouched and this run reports contention rather than stealing a live lock.
reclaim_stale_lock() {
  local dead_owner="$1" aside="$LOCK_DIR.stale.$$" moved_owner
  mv "$LOCK_DIR" "$aside" 2>/dev/null || return 1
  moved_owner=$(cat "$aside/pid" 2>/dev/null || true)
  if [ "$moved_owner" != "$dead_owner" ]; then
    if [ -e "$LOCK_DIR" ]; then
      rm -rf "$aside"
    else
      mv "$aside" "$LOCK_DIR" 2>/dev/null || rm -rf "$aside"
    fi
    return 1
  fi
  rm -rf "$aside"
  claim_workspace_lock
}

acquire_workspace_lock() {
  local slug root lock_root lock_key owner
  slug=$(workspace_slug) || return 0
  [ -n "$slug" ] || return 0
  lock_root="${CODEX_REVIEW_LOCK_ROOT:-${TMPDIR:-/tmp}}"
  if ! mkdir -p "$lock_root" 2>/dev/null; then
    printf 'WARN: cannot create the lock root %s — running unserialized\n' "$lock_root" >&2
    return 0
  fi

  # Key on the canonical path, not the basename alone: the broker is single-flight per workspace
  # *path*, so `~/dev/foo` and `~/work/foo` do not contend and must not share a lock. `cksum` is the
  # portable digest here — `sha256sum` is absent on macOS, `shasum` on some Linux images.
  #
  # Canonicalize the way the companion does (`fs.realpathSync.native`) before hashing, or one
  # workspace reached through a symlink — or, on Windows, through a differently-cased path, which
  # `show-toplevel` echoes verbatim from the cwd — yields two locks for the single broker they share.
  root=$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$slug")
  root=$(cd "$root" 2>/dev/null && pwd -P) || root=$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$slug")
  [ "$CODEX_REVIEW_PLATFORM" = "windows" ] && root=$(printf '%s' "$root" | tr '[:upper:]' '[:lower:]')
  lock_key=$(printf '%s' "$root" | cksum | tr -d ' \t' 2>/dev/null || printf '%s' "0")
  LOCK_DIR="$lock_root/codex-review-${slug}-${lock_key}.lock"

  if claim_workspace_lock; then
    return 0
  fi

  owner=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then
    printf 'ERROR: another codex review is already running for this workspace (pid %s); skipping\n' "$owner" >&2
    LOCK_DIR=""
    return 1
  fi

  # Stale lock: the recorded owner is gone (or never got as far as writing its PID).
  if reclaim_stale_lock "$owner"; then
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
    # Lock first, prune second: the lock keeps two *review cycles* off the same state at once. It
    # says nothing about the companion's own writers — `saveState()` is a non-atomic
    # load-mutate-write — so a background codex job completing mid-prune can still interleave. The
    # PID check is what keeps each individual removal safe; the lock only narrows the window.
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
