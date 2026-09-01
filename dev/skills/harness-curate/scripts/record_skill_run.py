#!/usr/bin/env python3
"""
Record one skill run to the per-project telemetry sink.

`harness-curate` Signal 3 ("Underperforming asset") infers underperformance by re-reading
transcripts every run, so the judgment cannot be trended. This script is the write half of
the fix: one bounded JSONL record per completed cycle, which a later Signal 3 revision reads
as a 7d-vs-30d success-rate delta.

`outcome` and `user_feedback` are judgments about how a cycle went — no PostToolUse payload
carries them — so the writer is this CLI, invoked from `harness-capture` cycle-tail mode,
never an ambient hook. That is also the lesson of PR #181, which retired the `failure-log` /
`delegation-log` hooks for writing a sink nobody read.

The sink sits beside `.harness-curator-state.json` and resolves through
`overlap_state.state_path()` rather than re-deriving the encoded project dir: a raw
substitution here can mint a case/underscore sibling directory, which is the drift
`record_run.py` documents.

That resolution is data-dependent, though — it ranks sibling project dirs by their
`*.jsonl` count — so the directory is decided once and then PINNED in the state file
(`skillRunSinkDir`). See `resolve_sink_dir()`: without the pin, a sibling gaining a
transcript re-points the sink and strands every earlier row, and Signal 3 would report
`insufficient-data` with no sign that the history exists elsewhere.

Usage:
  record_skill_run.py --skill-id ID [--skill-version X.Y.Z] \
      --outcome {success|failure|partial} \
      --user-feedback {accepted|corrected|rejected} \
      [--project PATH] [--max-records N]
  record_skill_run.py --test

`--skill-version` is optional: some skills ship no `version:` frontmatter (`dev:task-review`
is one). Omitting it records the `unknown` sentinel — a caller must never invent a number to
fill the field. Resolve the interpreter at the call site (`python3` or `python`); a bare
`python3` is absent on many Windows installs, where a `|| true` call site would then drop
every row while still reporting success.

The file is created 0o600 and re-chmod'd after every trim, so the retention rewrite cannot
silently widen the mode. On Windows the POSIX bits are only approximated; a chmod failure is
swallowed rather than costing the write.

Append and trim run under one exclusive sidecar lock (`_sink_lock`), because the trim is a
read-modify-replace and concurrent agents in one repo share a single sink.
"""

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from overlap_state import (  # noqa: E402
    STATE_FILE,
    config_dir,
    read_state,
    state_path,
    write_state,
)
from scan_transcripts import _loose_key, encode_project  # noqa: E402

# Dot-prefixed on purpose. The sink shares a directory with Claude Code session
# transcripts, and `scan_transcripts.py` counts and parses `*.jsonl` there — both to
# rank sibling project dirs (`_jsonl_count`) and to read sessions (`scan_dir`). A
# visible `skill-runs.jsonl` would be counted as a transcript, and glob() does not
# match a leading dot, so the name is what keeps the two apart. `--test` asserts it.
SINK_FILE = ".skill-runs.jsonl"
# Sidecar for the append+trim lock. Deliberately NOT `*.jsonl`, for the same reason the
# sink is dot-prefixed: `scan_transcripts.py` must not count or parse it.
LOCK_SUFFIX = ".lock"
# The lock wait is bounded, and deliberately short. `harness-capture` calls this script as
# "Best-effort — never block the merge" and wraps it in `|| true`, which catches a non-zero
# exit but not a hang: an unbounded `LOCK_EX` behind a peer stalled inside `_trim` (a wedged
# network mount, a stopped process) would hang the cycle tail on a write that is only
# telemetry. On the deadline we proceed unlocked and warn — the pre-lock behaviour.
LOCK_TIMEOUT_S = 2.0
LOCK_POLL_S = 0.02
# The chosen sink dir, recorded in that dir's own .harness-curator-state.json. Pinning is
# what makes the sink location stable across runs; see resolve_sink_dir().
SINK_DIR_KEY = "skillRunSinkDir"
# The project the pinned sink belongs to, as encode_project() spells it. Candidate dirs
# include loose-key siblings and _loose_key collapses '-' and '_', so two different repos
# can be each other's candidates; this key is what stops one claiming the other's pin.
SINK_PROJECT_KEY = "skillRunSinkProject"
# The situation last warned about, so a permanent-and-correct divergence is reported once
# rather than on every cycle tail forever.
SINK_WARNED_KEY = "skillRunSinkWarnedFor"
MAX_RECORDS = 2000  # bounded: oldest records drop out, newest kept
OUTCOMES = ("success", "failure", "partial")
FEEDBACK = ("accepted", "corrected", "rejected")
FIELDS = ("skill_id", "skill_version", "outcome", "user_feedback", "recorded_at")
UNKNOWN_VERSION = "unknown"  # sentinel: some skills ship no `version:` frontmatter


def _projects_root():
    return os.path.join(config_dir(), "projects")


def _candidate_dirs(project):
    """Every project dir `resolve_project_dir` could pick for `project`: the exact
    encoding first, then loose-key siblings. Same membership rule as the resolver, so the
    pin search covers exactly the set the resolution can wander across."""
    root = _projects_root()
    exact = os.path.join(root, encode_project(project))
    dirs = [exact]
    if os.path.isdir(root):
        key = _loose_key(encode_project(project))
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d) and _loose_key(name) == key and d not in dirs:
                dirs.append(d)
    return dirs


def _usable_pin(pin):
    """True when `pin` still names an existing dir inside this machine's projects root.

    A state file travels — a synced or copied `~/.claude`, a renamed home, a moved
    CLAUDE_CONFIG_DIR — and an absolute path from elsewhere would otherwise be recreated
    by `_append` and written to, orphaning the very history the pin exists to protect.
    """
    if not isinstance(pin, str) or not pin:
        return False
    root = os.path.abspath(_projects_root())
    p = os.path.abspath(pin)
    if not os.path.isdir(p):
        return False
    try:
        return os.path.commonpath([p, root]) == root
    except ValueError:  # different drives on Windows
        return False


def _sink_owner(d):
    """The project a dir's sink is recorded as belonging to, or None for a sink written
    before the owner was tracked."""
    owner = read_state(os.path.join(d, STATE_FILE)).get(SINK_PROJECT_KEY)
    return owner if isinstance(owner, str) and owner else None


def _pinned_dir(dirs, project):
    """The pin recorded for THIS project, or None.

    `_candidate_dirs` includes loose-key siblings, and `_loose_key` collapses '-' and '_',
    so `/dev/foo-bar` and `/dev/foo_bar` are each other's candidates while being genuinely
    different repos. Honouring any sibling's pin would let whichever recorded first claim
    the other's telemetry permanently, mixing two repos into the per-project rate Signal 3
    exists to trend. So a pin counts only when the state file also names this project.
    A pin written before that key existed carries no owner and is honoured only from
    `dirs[0]`, the exactly-encoded dir, which by construction is this project's own.
    """
    want = encode_project(project)
    for i, d in enumerate(dirs):
        state = read_state(os.path.join(d, STATE_FILE))
        pin = state.get(SINK_DIR_KEY)
        owner = state.get(SINK_PROJECT_KEY)
        if owner != want and not (owner is None and i == 0):
            continue
        if _usable_pin(pin):
            return pin
    return None


def resolve_sink_dir(project):
    """Pick the directory the sink lives in, and say what was surprising about it.

    `state_path()` -> `resolve_project_dir()` ranks sibling project dirs by their `*.jsonl`
    count, which is data-dependent: a dir that stops holding transcripts, or a sibling that
    gains one, silently re-points the sink and orphans every earlier row. So the directory
    is decided once, in this order:

      1. a pin recorded for this project — it wins even when today's ranking would resolve
         elsewhere, which is the whole point;
      2. else a candidate dir that already holds this project's sink data — adopt the
         history rather than start a second sink beside it;
      3. else whatever the resolver picks today, which is the genuine first write.

    Returns (dir, warning, warn_key). `warning` names both dirs whenever the choice
    diverged from today's resolution, and names any sink left unread. `warn_key` identifies
    the situation so `_pin_dir` can stamp it: the divergence a pin protects against is
    permanent, so without the stamp the same warning would print on every cycle tail
    forever and train the reader to ignore it.
    """
    resolved = os.path.dirname(state_path(project))
    dirs = _candidate_dirs(project)
    want = encode_project(project)
    warning = warn_key = None

    chosen = _pinned_dir(dirs, project)
    if chosen:
        if os.path.abspath(chosen) != os.path.abspath(resolved):
            warn_key = f"pinned:{resolved}"
            warning = (f"skill-run sink is pinned to {chosen}; today's project-dir "
                       f"resolution would have used {resolved}")
    else:
        # A sibling whose state names a different project is that repo's sink, not ours.
        holding = [d for d in dirs
                   if os.path.exists(os.path.join(d, SINK_FILE))
                   and (_sink_owner(d) or want) == want]
        if not holding or resolved in holding:
            chosen = resolved
        else:
            chosen = max(holding,
                         key=lambda d: os.path.getsize(os.path.join(d, SINK_FILE)))
            warn_key = f"adopted:{resolved}"
            warning = (f"existing skill-run history found in {chosen}; today's project-dir "
                       f"resolution would have used {resolved} — appending to the existing "
                       f"sink instead of orphaning it")
        others = sorted(d for d in holding if d != chosen)
        if others:
            # Only one sink is ever read. Naming the rest is the difference between
            # history that is merged by hand and history nobody knows is there.
            warn_key = f"others:{chosen}:{','.join(others)}"
            warning = (warning + "; " if warning else "") + (
                "other skill-run sinks exist and are NOT being read: " + ", ".join(others)
                + " — merge them by hand or Signal 3 sees only " + chosen)

    if warn_key and read_state(os.path.join(chosen, STATE_FILE)).get(SINK_WARNED_KEY) == warn_key:
        warning = None  # already reported: this is the steady state, not news
    return chosen, warning, warn_key


def _pin_dir(directory, project, warn_key):
    """Record the chosen dir, the project it belongs to, and the situation last warned
    about. Read-modify-write, so `lastRunMs` / `dismissedOverlaps` survive; a no-op once
    all three already read the same."""
    path = os.path.join(directory, STATE_FILE)
    state = read_state(path)
    want = {SINK_DIR_KEY: directory,
            SINK_PROJECT_KEY: encode_project(project),
            SINK_WARNED_KEY: warn_key}
    if all(state.get(k) == v for k, v in want.items()):
        return
    state.update(want)
    if warn_key is None:
        state.pop(SINK_WARNED_KEY, None)  # the situation cleared; warn again if it returns
    write_state(path, state)


def sink_path(project):
    """Beside the curator state file, in the pinned (or newly chosen) project dir."""
    return os.path.join(resolve_sink_dir(project)[0], SINK_FILE)


def _chmod_600(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best-effort: Windows approximates the POSIX bits


def _try_lock(fd):
    """One non-blocking acquisition attempt. False when another holder has it.

    Non-blocking on BOTH platforms on purpose: `fcntl.LOCK_EX` waits forever while
    `msvcrt.LK_LOCK` gives up after ~10s and raises, so the two blocking primitives sit at
    opposite extremes and neither matches the caller's contract. One bounded retry loop
    over the non-blocking forms makes the behaviour identical everywhere.
    """
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def _sink_lock(path, timeout=None):
    """Hold one exclusive lock for the whole append+trim on `path`.

    `_trim` is a read-modify-replace: it snapshots the sink, then `os.replace`s over it,
    so an append landing inside that window is written to a file that is about to be
    swapped away. Concurrent agents in one repo — which the global instructions
    explicitly anticipate — share one sink, so the row is simply lost. Serializing the
    two closes the window.

    The lock lives in a sidecar file, never the sink itself: `os.replace` swaps the
    inode out from under any waiter holding a lock on the old one, so a lock on the sink
    would stop excluding at exactly the moment it matters.

    Best-effort by design, and bounded by `LOCK_TIMEOUT_S`. A platform with neither
    `fcntl` nor `msvcrt`, a filesystem that refuses the lock (a network mount), or a peer
    still holding it at the deadline all yield unlocked rather than costing the caller its
    record — the pre-lock behaviour, no worse than before, and never a hang.
    """
    if timeout is None:
        timeout = LOCK_TIMEOUT_S
    lock_path = path + LOCK_SUFFIX
    fd = None
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        if fcntl is None and msvcrt is None:
            raise OSError("no file-locking primitive on this platform")
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise OSError(f"still held by another writer after {timeout:g}s")
            time.sleep(LOCK_POLL_S)
    except OSError as e:
        if fd is not None:
            os.close(fd)
            fd = None
        print(f"warning: could not lock the skill-run sink ({e}); "
              "a concurrent append may be lost", file=sys.stderr)
    try:
        yield
    finally:
        if fd is not None:
            if fcntl is None and msvcrt is not None:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass  # closing the fd releases it anyway
            os.close(fd)  # releases the flock too


def _append(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    _chmod_600(path)


def _trim(path, max_records):
    """Keep the newest `max_records` records. Atomic: a crash mid-trim cannot truncate
    the sink.

    Rewrites ONLY when the record count is over the cap. An earlier version also
    rewrote whenever any line failed to parse, which turned one corrupt line into a
    read-modify-replace on every subsequent append — widening the window in which a
    concurrent append is read, then replaced away. Corrupt lines are still purged, but
    now only on the runs that were going to rewrite anyway.

    Returns (aged, corrupt): records dropped for age, and unparseable lines purged.
    They are counted separately because "1 dropped" means something different in each
    case, and only the first is the retention cap doing its job.
    """
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in (ln.strip() for ln in f) if ln]
    if len(lines) <= max_records:
        return 0, 0
    kept = []
    for ln in lines:
        try:
            json.loads(ln)
        except ValueError:
            continue
        kept.append(ln)
    corrupt = len(lines) - len(kept)
    aged = max(0, len(kept) - max_records)
    kept = kept[-max_records:]
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in kept:
                f.write(ln + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _chmod_600(path)
    return aged, corrupt


def record(project, skill_id, skill_version, outcome, user_feedback,
           max_records=MAX_RECORDS, now_ms=None):
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if user_feedback not in FEEDBACK:
        raise ValueError(f"user_feedback must be one of {FEEDBACK}, got {user_feedback!r}")
    entry = {
        "skill_id": skill_id,
        "skill_version": skill_version or UNKNOWN_VERSION,
        "outcome": outcome,
        "user_feedback": user_feedback,
        "recorded_at": int(time.time() * 1000) if now_ms is None else now_ms,
    }
    sink_dir, warning, warn_key = resolve_sink_dir(project)
    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    path = os.path.join(sink_dir, SINK_FILE)
    with _sink_lock(path):
        _append(path, entry)
        try:
            _pin_dir(sink_dir, project, warn_key)  # after the append: _append made the dir
        except OSError as e:
            # Best-effort bookkeeping. Raising here would skip the trim below on a row that
            # is already written, so the sink would grow past the cap while this fails.
            print(f"warning: could not record the sink pin ({e})", file=sys.stderr)
        aged, corrupt = _trim(path, max_records)
    return path, aged, corrupt


def run_tests():
    import shutil
    import stat

    results = []

    def check(name, cond):
        results.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    def read_lines(p):
        with open(p, encoding="utf-8") as f:
            return [ln for ln in (ln.strip() for ln in f) if ln]

    tmpdir = tempfile.mkdtemp()
    saved = os.environ.get("CLAUDE_CONFIG_DIR")
    try:
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(tmpdir, "claude")
        proj = os.path.join(tmpdir, "repo")
        os.makedirs(proj)

        # append writes the full schema, beside the curator state file
        path, _, _ = record(proj, "dev:task-next", "4.6.2", "success", "accepted", now_ms=1000)
        check("sink sits beside .harness-curator-state.json",
              os.path.dirname(path) == os.path.dirname(state_path(proj)))
        rows = [json.loads(ln) for ln in read_lines(path)]
        check("one record appended", len(rows) == 1)
        check("record carries exactly the five fields",
              tuple(sorted(rows[0])) == tuple(sorted(FIELDS)))
        check("field values round-trip",
              rows[0]["skill_id"] == "dev:task-next"
              and rows[0]["skill_version"] == "4.6.2"
              and rows[0]["outcome"] == "success"
              and rows[0]["user_feedback"] == "accepted"
              and rows[0]["recorded_at"] == 1000)

        # the sink must not look like a session transcript to scan_transcripts
        import glob as _glob
        check("sink is invisible to the *.jsonl transcript glob",
              _glob.glob(os.path.join(os.path.dirname(path), "*.jsonl")) == [])

        # a skill with no `version:` frontmatter records the sentinel, not a guess
        sent_proj = os.path.join(tmpdir, "sentinel")
        os.makedirs(sent_proj)
        spath, _, _ = record(sent_proj, "dev:task-review", None, "success", "accepted",
                             now_ms=1)
        check("missing skill_version records the unknown sentinel",
              json.loads(read_lines(spath)[0])["skill_version"] == UNKNOWN_VERSION)

        # append does not rewrite history
        record(proj, "dev:task-review", "1.0.0", "partial", "corrected", now_ms=2000)
        rows = [json.loads(ln) for ln in read_lines(path)]
        check("second append preserves the first", len(rows) == 2 and rows[0]["recorded_at"] == 1000)

        # owner-only mode (POSIX only; Windows approximates the bits)
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(path).st_mode)
            check("file mode is 0o600", mode == 0o600)
        else:
            check("file mode check skipped (non-POSIX)", True)

        # retention cap keeps the NEWEST records
        cap_proj = os.path.join(tmpdir, "capped")
        os.makedirs(cap_proj)
        cap_path = sink_path(cap_proj)
        for i in range(7):
            record(cap_proj, "s", "1.0.0", "success", "accepted", max_records=3, now_ms=i)
        rows = [json.loads(ln) for ln in read_lines(cap_path)]
        check("cap trims to max_records", len(rows) == 3)
        check("cap keeps the newest", [r["recorded_at"] for r in rows] == [4, 5, 6])
        check("trimmed file still parses line-by-line",
              all(isinstance(json.loads(ln), dict) for ln in read_lines(cap_path)))
        if os.name == "posix":
            check("mode survives the trim rewrite",
                  stat.S_IMODE(os.stat(cap_path).st_mode) == 0o600)
        else:
            check("mode-after-trim check skipped (non-POSIX)", True)

        # a corrupt pre-existing line does not abort the append
        corrupt_proj = os.path.join(tmpdir, "corrupt")
        os.makedirs(corrupt_proj)
        cpath, _, _ = record(corrupt_proj, "s", "1.0.0", "success", "accepted", now_ms=1)
        with open(cpath, "a", encoding="utf-8") as f:
            f.write("{not json\n")
        _, aged, corrupt = record(corrupt_proj, "s", "1.0.0", "failure", "rejected",
                                  now_ms=2)
        rows = [json.loads(ln) for ln in read_lines(cpath) if not ln.startswith("{not")]
        check("corrupt line does not abort the append",
              [r["recorded_at"] for r in rows] == [1, 2])
        check("under the cap, a corrupt line triggers no rewrite",
              (aged, corrupt) == (0, 0) and any(ln.startswith("{not")
                                                for ln in read_lines(cpath)))
        # over the cap, the same corrupt line is purged and counted apart from aged.
        # Assert on the FIRST trim that fires: later appends see an already-clean file.
        first = None
        for i in range(3, 8):
            _, aged, corrupt = record(corrupt_proj, "s", "1.0.0", "success", "accepted",
                                      max_records=3, now_ms=i)
            if first is None and (aged or corrupt):
                first = (aged, corrupt)
        check("trim purges the corrupt line and counts it apart", first[1] == 1)
        # 4 lines, 1 of them corrupt, cap 3 -> 3 valid records survive, none aged out.
        # The old single `dropped` counter reported 1 here and called it a retention drop.
        check("a corrupt-only purge reports aged=0", first[0] == 0)
        check("aged is non-zero once records really age out",
              record(corrupt_proj, "s", "1.0.0", "success", "accepted",
                     max_records=3, now_ms=9)[1] == 1)
        check("no corrupt line survives the trim",
              all(isinstance(json.loads(ln), dict) for ln in read_lines(cpath)))

        # --- sink dir pinning -------------------------------------------------
        # The pin is written on the first record, into the sink dir's own state file.
        pin_proj = os.path.join(tmpdir, "pinned")
        os.makedirs(pin_proj)
        ppath, _, _ = record(pin_proj, "s", "1.0.0", "success", "accepted", now_ms=1)
        pin_dir = os.path.dirname(ppath)
        pstate = os.path.join(pin_dir, STATE_FILE)
        check("first write pins the sink dir in the state file",
              read_state(pstate).get(SINK_DIR_KEY) == pin_dir)

        # A sibling project dir gaining transcripts re-points resolve_project_dir(); the
        # pin must keep the sink where the history already is.
        root = os.path.join(config_dir(), "projects")
        sibling = os.path.join(root, encode_project(pin_proj).replace("-", "_", 1))
        os.makedirs(sibling)
        for i in range(3):
            open(os.path.join(sibling, f"s{i}.jsonl"), "w").close()
        check("resolution really moved without the pin",
              os.path.dirname(state_path(pin_proj)) == sibling)
        check("pinned sink path ignores the moved resolution",
              sink_path(pin_proj) == ppath)
        import io as _io
        from contextlib import redirect_stderr
        errbuf = _io.StringIO()
        with redirect_stderr(errbuf):
            again, _, _ = record(pin_proj, "s", "1.0.0", "success", "accepted", now_ms=2)
        check("second record appends to the pinned sink, not the sibling", again == ppath)
        check("history is not orphaned", len(read_lines(ppath)) == 2)
        check("the divergence is warned about, naming both dirs",
              sibling in errbuf.getvalue() and pin_dir in errbuf.getvalue())
        check("no sink was started in the sibling",
              not os.path.exists(os.path.join(sibling, SINK_FILE)))

        # Unpinned: a sibling already holding sink data is adopted, not orphaned.
        adopt_proj = os.path.join(tmpdir, "adopt")
        os.makedirs(adopt_proj)
        adopt_exact = os.path.join(root, encode_project(adopt_proj))
        os.makedirs(adopt_exact)
        open(os.path.join(adopt_exact, "t.jsonl"), "w").close()  # makes exact win
        adopt_sib = os.path.join(root, encode_project(adopt_proj).replace("-", "_", 1))
        os.makedirs(adopt_sib)
        with open(os.path.join(adopt_sib, SINK_FILE), "w", encoding="utf-8") as f:
            f.write(json.dumps({"skill_id": "old", "skill_version": "1.0.0",
                                "outcome": "success", "user_feedback": "accepted",
                                "recorded_at": 0}) + "\n")
        check("resolution points away from the existing sink",
              os.path.dirname(state_path(adopt_proj)) == adopt_exact)
        errbuf = _io.StringIO()
        with redirect_stderr(errbuf):
            apath, _, _ = record(adopt_proj, "s", "1.0.0", "success", "accepted", now_ms=5)
        check("an existing sibling sink is adopted", os.path.dirname(apath) == adopt_sib)
        check("adopted sink keeps its earlier row",
              [json.loads(ln)["recorded_at"] for ln in read_lines(apath)] == [0, 5])
        check("adoption warns, naming both dirs",
              adopt_sib in errbuf.getvalue() and adopt_exact in errbuf.getvalue())
        check("adoption pins the dir it adopted",
              read_state(os.path.join(adopt_sib, STATE_FILE)).get(SINK_DIR_KEY) == adopt_sib)

        # The pin write must not clobber the state keys overlap_state owns.
        keep_state = read_state(pstate)
        keep_state["lastRunMs"] = 4242
        write_state(pstate, keep_state)
        with redirect_stderr(_io.StringIO()):  # the pin-divergence warning is expected here
            record(pin_proj, "s", "1.0.0", "success", "accepted", now_ms=3)
        check("pinning preserves unrelated state keys",
              read_state(pstate).get("lastRunMs") == 4242
              and read_state(pstate).get(SINK_DIR_KEY) == pin_dir)

        # Two genuinely different repos can be each other's loose-key candidates
        # ('-' and '_' collapse), so a pin must not travel across them.
        hj = os.path.join(tmpdir, "hijack")
        os.makedirs(hj)
        repo_a, repo_b = os.path.join(hj, "foo-bar"), os.path.join(hj, "foo_bar")
        for r in (repo_a, repo_b):
            os.makedirs(r)
            d = os.path.join(root, encode_project(r))
            os.makedirs(d)
            open(os.path.join(d, "t.jsonl"), "w").close()  # each repo resolves to its own
        apath, _, _ = record(repo_a, "s", "1.0.0", "success", "accepted", now_ms=1)
        bpath, _, _ = record(repo_b, "s", "1.0.0", "success", "accepted", now_ms=1)
        check("a sibling repo's pin does not capture this project's sink", apath != bpath)
        check("each repo pins its own dir",
              read_state(os.path.join(os.path.dirname(bpath), STATE_FILE))
              .get(SINK_PROJECT_KEY) == encode_project(repo_b))

        # A sibling's sink is not adopted when its state names a different project.
        check("a foreign sibling sink is not adopted",
              os.path.dirname(sink_path(repo_b)) == os.path.join(root,
                                                                 encode_project(repo_b)))

        # A pin written before the owner key existed is honoured only from the exactly
        # encoded dir, which cannot belong to another repo.
        legacy = os.path.join(tmpdir, "legacy")
        os.makedirs(legacy)
        legacy_exact = os.path.join(root, encode_project(legacy))
        os.makedirs(legacy_exact)
        write_state(os.path.join(legacy_exact, STATE_FILE), {SINK_DIR_KEY: legacy_exact})
        check("an ownerless pin in the exact dir is still honoured",
              os.path.dirname(sink_path(legacy)) == legacy_exact)
        legacy_sib = os.path.join(root, encode_project(legacy).replace("-", "_", 1))
        os.makedirs(legacy_sib)
        write_state(os.path.join(legacy_sib, STATE_FILE), {SINK_DIR_KEY: legacy_sib})
        os.remove(os.path.join(legacy_exact, STATE_FILE))
        check("an ownerless pin in a sibling is ignored",
              os.path.dirname(sink_path(legacy)) != legacy_sib)

        # A pin that no longer names a real dir under this machine's projects root is
        # ignored rather than recreated somewhere unrelated.
        stray = os.path.join(tmpdir, "stray")
        os.makedirs(stray)
        stray_exact = os.path.join(root, encode_project(stray))
        os.makedirs(stray_exact)
        elsewhere = os.path.join(tmpdir, "elsewhere")
        os.makedirs(elsewhere)
        write_state(os.path.join(stray_exact, STATE_FILE),
                    {SINK_DIR_KEY: elsewhere, SINK_PROJECT_KEY: encode_project(stray)})
        check("a pin outside the projects root is ignored",
              os.path.dirname(sink_path(stray)) == stray_exact)
        write_state(os.path.join(stray_exact, STATE_FILE),
                    {SINK_DIR_KEY: os.path.join(root, "gone-missing"),
                     SINK_PROJECT_KEY: encode_project(stray)})
        check("a pin naming a deleted dir is ignored",
              os.path.dirname(sink_path(stray)) == stray_exact)

        # A permanent divergence is reported once, not on every cycle tail forever.
        errbuf = _io.StringIO()
        with redirect_stderr(errbuf):
            record(pin_proj, "s", "1.0.0", "success", "accepted", now_ms=10)
        check("a divergence already warned about is not repeated",
              "warning:" not in errbuf.getvalue())

        # A second sink nobody is reading must be named, not silently orphaned.
        two = os.path.join(tmpdir, "twosinks")
        os.makedirs(two)
        two_exact = os.path.join(root, encode_project(two))
        os.makedirs(two_exact)
        open(os.path.join(two_exact, "t.jsonl"), "w").close()
        record(two, "s", "1.0.0", "success", "accepted", now_ms=1)  # sink in the exact dir
        two_sib = os.path.join(root, encode_project(two).replace("-", "_", 1))
        os.makedirs(two_sib)
        with open(os.path.join(two_sib, SINK_FILE), "w", encoding="utf-8") as f:
            for i in range(20):
                f.write(json.dumps({"skill_id": "old", "skill_version": "1.0.0",
                                    "outcome": "success", "user_feedback": "accepted",
                                    "recorded_at": i}) + "\n")
        # clear the pin so the holding-list branch is the one under test
        st = read_state(os.path.join(two_exact, STATE_FILE))
        st.pop(SINK_DIR_KEY, None)
        st.pop(SINK_WARNED_KEY, None)
        write_state(os.path.join(two_exact, STATE_FILE), st)
        errbuf = _io.StringIO()
        with redirect_stderr(errbuf):
            tpath, _, _ = record(two, "s", "1.0.0", "success", "accepted", now_ms=2)
        check("the resolved dir keeps the sink when it already holds one",
              os.path.dirname(tpath) == two_exact)
        check("the unread sibling sink is named in the warning",
              two_sib in errbuf.getvalue() and "NOT being read" in errbuf.getvalue())

        # A failing pin write must not cost the append its retention trim.
        fail_proj = os.path.join(tmpdir, "pinfail")
        os.makedirs(fail_proj)
        saved_write = write_state

        def boom(*_a, **_k):
            raise OSError("read-only state file")

        globals()["write_state"] = boom
        try:
            errbuf = _io.StringIO()
            with redirect_stderr(errbuf):
                for i in range(5):
                    fpath, aged, _ = record(fail_proj, "s", "1.0.0", "success", "accepted",
                                            max_records=2, now_ms=i)
        finally:
            globals()["write_state"] = saved_write
        check("a failing pin write is reported, not raised", "could not record" in errbuf.getvalue())
        check("the retention trim still runs when pinning fails",
              len(read_lines(fpath)) == 2 and aged == 1)

        # The append+trim window is serialized: a second writer cannot slip a record in
        # between the snapshot and the os.replace. flock/msvcrt locks are per open file
        # description, so a fresh fd in this same process contends exactly like another
        # process would.
        def _lock_taken(sink):
            lock_path = sink + LOCK_SUFFIX
            if not os.path.exists(lock_path):
                return False
            fd = os.open(lock_path, os.O_WRONLY)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                elif msvcrt is not None:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    return None  # no lock primitive on this platform
                return False
            except OSError:
                return True
            finally:
                os.close(fd)

        lock_proj = os.path.join(tmpdir, "locked")
        os.makedirs(lock_proj)
        seen = []
        real_trim = _trim

        def probing_trim(sink, cap):
            seen.append(_lock_taken(sink))
            return real_trim(sink, cap)

        globals()["_trim"] = probing_trim
        try:
            lpath, _, _ = record(lock_proj, "s", "1.0.0", "success", "accepted", now_ms=1)
        finally:
            globals()["_trim"] = real_trim
        check("the sink lock is held across the trim",
              seen == [True] if seen[:1] != [None] else True)
        check("the lock sidecar exists and is invisible to the *.jsonl transcript glob",
              os.path.exists(lpath + LOCK_SUFFIX)
              and _glob.glob(os.path.join(os.path.dirname(lpath), "*.jsonl")) == [])

        # A peer still holding the lock at the deadline costs the wait, not the cycle: the
        # writer proceeds unlocked and warns. Guards the caller's "never block the merge"
        # contract (dev/skills/harness-capture/SKILL.md, "Record the run").
        if fcntl is not None or msvcrt is not None:
            busy_proj = os.path.join(tmpdir, "busy")
            os.makedirs(busy_proj)
            record(busy_proj, "s", "1.0.0", "success", "accepted", now_ms=1)  # makes the sink
            bpath = sink_path(busy_proj)
            holder = os.open(bpath + LOCK_SUFFIX, os.O_WRONLY)
            saved_timeout = LOCK_TIMEOUT_S
            globals()["LOCK_TIMEOUT_S"] = 0.05
            try:
                check("the test holder actually owns the lock", _try_lock(holder))
                errbuf = _io.StringIO()
                started = time.monotonic()
                with redirect_stderr(errbuf):
                    record(busy_proj, "s", "1.0.0", "success", "accepted", now_ms=2)
                waited = time.monotonic() - started
            finally:
                globals()["LOCK_TIMEOUT_S"] = saved_timeout
                os.close(holder)
            check("a contended lock does not block the writer", waited < 1.0)
            check("a contended write still records the row", len(read_lines(bpath)) == 2)
            check("a contended lock warns about the possible loss",
                  "could not lock" in errbuf.getvalue())

        # A sink that cannot be locked still records the row: the lock is best-effort.
        nolock_proj = os.path.join(tmpdir, "nolock")
        os.makedirs(nolock_proj)
        saved_open = os.open

        def refuse_lock_file(fpath, *a, **kw):
            if str(fpath).endswith(LOCK_SUFFIX):
                raise OSError("no lock here")
            return saved_open(fpath, *a, **kw)

        os.open = refuse_lock_file
        try:
            errbuf = _io.StringIO()
            with redirect_stderr(errbuf):
                npath, _, _ = record(nolock_proj, "s", "1.0.0", "success", "accepted", now_ms=1)
        finally:
            os.open = saved_open
        check("an unlockable sink still records the row", len(read_lines(npath)) == 1)
        check("the failed lock is warned about", "could not lock" in errbuf.getvalue())

        # invalid values are rejected, and nothing is written
        bad_proj = os.path.join(tmpdir, "bad")
        os.makedirs(bad_proj)
        for field, outcome, feedback in (("outcome", "ok", "accepted"),
                                         ("user_feedback", "success", "meh")):
            try:
                record(bad_proj, "s", "1.0.0", outcome, feedback)
                raised = False
            except ValueError:
                raised = True
            check(f"invalid {field} raises", raised)
        check("invalid value writes nothing", not os.path.exists(sink_path(bad_proj)))
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved
        shutil.rmtree(tmpdir, ignore_errors=True)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="Record one skill run to the telemetry sink.")
    ap.add_argument("--skill-id", help="e.g. dev:task-next")
    ap.add_argument("--skill-version", default=None,
                    help="the skill's SKILL.md `version:` frontmatter; omit when it "
                         f"ships none and the row records {UNKNOWN_VERSION!r}")
    ap.add_argument("--outcome", choices=OUTCOMES)
    ap.add_argument("--user-feedback", choices=FEEDBACK)
    ap.add_argument("--max-records", type=int, default=MAX_RECORDS,
                    help=f"retention cap (default {MAX_RECORDS})")
    ap.add_argument("--project", default=None, help="repo path (default: cwd)")
    ap.add_argument("--test", action="store_true", help="run self-tests")
    a = ap.parse_args()

    if a.test:
        return run_tests()
    missing = [f for f in ("skill_id", "outcome", "user_feedback")
               if getattr(a, f) is None]
    if missing:
        ap.error("required: " + ", ".join("--" + m.replace("_", "-") for m in missing))
    if a.max_records < 1:
        ap.error("--max-records must be >= 1")

    project = os.path.abspath(a.project or os.getcwd())
    path, aged, corrupt = record(project, a.skill_id, a.skill_version, a.outcome,
                                 a.user_feedback, max_records=a.max_records)
    print(f"skill run recorded: {path}")
    if aged:
        print(f"retention cap applied: {aged} old record(s) dropped")
    if corrupt:
        print(f"purged {corrupt} unparseable line(s) during the trim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
