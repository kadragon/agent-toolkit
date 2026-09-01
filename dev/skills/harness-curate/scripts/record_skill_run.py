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

Usage:
  python3 record_skill_run.py --skill-id ID --skill-version X.Y.Z \\
      --outcome {success|failure|partial} \\
      --user-feedback {accepted|corrected|rejected} \\
      [--project PATH] [--max-records N]
  python3 record_skill_run.py --test

The file is created 0o600 and re-chmod'd after every trim, so the retention rewrite cannot
silently widen the mode. On Windows the POSIX bits are only approximated; a chmod failure is
swallowed rather than costing the write.
"""

import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from overlap_state import state_path  # noqa: E402

SINK_FILE = "skill-runs.jsonl"
MAX_RECORDS = 2000  # bounded: oldest records drop out, newest kept
OUTCOMES = ("success", "failure", "partial")
FEEDBACK = ("accepted", "corrected", "rejected")
FIELDS = ("skill_id", "skill_version", "outcome", "user_feedback", "recorded_at")


def sink_path(project):
    """Beside the curator state file, in whichever project dir overlap_state resolves."""
    return os.path.join(os.path.dirname(state_path(project)), SINK_FILE)


def _chmod_600(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best-effort: Windows approximates the POSIX bits


def _append(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    _chmod_600(path)


def _trim(path, max_records):
    """Keep the newest `max_records` lines. Atomic: a crash mid-trim cannot truncate the
    sink. Unparseable lines are dropped here — appends never read the file."""
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in (ln.strip() for ln in f) if ln]
    kept = []
    for ln in lines:
        try:
            json.loads(ln)
        except ValueError:
            continue
        kept.append(ln)
    if len(kept) <= max_records and len(kept) == len(lines):
        return 0
    dropped = len(lines) - min(len(kept), max_records)
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
    return dropped


def record(project, skill_id, skill_version, outcome, user_feedback,
           max_records=MAX_RECORDS, now_ms=None):
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if user_feedback not in FEEDBACK:
        raise ValueError(f"user_feedback must be one of {FEEDBACK}, got {user_feedback!r}")
    entry = {
        "skill_id": skill_id,
        "skill_version": skill_version,
        "outcome": outcome,
        "user_feedback": user_feedback,
        "recorded_at": int(time.time() * 1000) if now_ms is None else now_ms,
    }
    path = sink_path(project)
    _append(path, entry)
    dropped = _trim(path, max_records)
    return path, dropped


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
        path, _ = record(proj, "dev:task-next", "4.6.2", "success", "accepted", now_ms=1000)
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
        cpath, _ = record(corrupt_proj, "s", "1.0.0", "success", "accepted", now_ms=1)
        with open(cpath, "a", encoding="utf-8") as f:
            f.write("{not json\n")
        record(corrupt_proj, "s", "1.0.0", "failure", "rejected", now_ms=2)
        rows = [json.loads(ln) for ln in read_lines(cpath)]
        check("corrupt line does not abort the append",
              [r["recorded_at"] for r in rows] == [1, 2])

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
    ap.add_argument("--skill-version", help="the skill's SKILL.md `version:` frontmatter")
    ap.add_argument("--outcome", choices=OUTCOMES)
    ap.add_argument("--user-feedback", choices=FEEDBACK)
    ap.add_argument("--max-records", type=int, default=MAX_RECORDS,
                    help=f"retention cap (default {MAX_RECORDS})")
    ap.add_argument("--project", default=None, help="repo path (default: cwd)")
    ap.add_argument("--test", action="store_true", help="run self-tests")
    a = ap.parse_args()

    if a.test:
        return run_tests()
    missing = [f for f in ("skill_id", "skill_version", "outcome", "user_feedback")
               if getattr(a, f) is None]
    if missing:
        ap.error("required: " + ", ".join("--" + m.replace("_", "-") for m in missing))
    if a.max_records < 1:
        ap.error("--max-records must be >= 1")

    project = os.path.abspath(a.project or os.getcwd())
    path, dropped = record(project, a.skill_id, a.skill_version, a.outcome,
                           a.user_feedback, max_records=a.max_records)
    print(f"skill run recorded: {path}")
    if dropped:
        print(f"retention cap applied: {dropped} old record(s) dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
