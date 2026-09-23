#!/usr/bin/env python3
"""
Record a harness-curate run (Step 6 bookkeeping).

Stamps `lastRunMs` in the project's `.harness-curator-state.json`, which
`scan_transcripts.py` reads to keep its PROMPTS window incremental. The state dir
is resolved through `scan_transcripts.resolve_project_dir()` so writer and reader
cannot drift apart (a raw path substitution could mint a case/underscore sibling
directory that the scanner's exact-match short-circuit then never reads).

Usage:
  python3 record_run.py [--project PATH]
  python3 record_run.py --check-due [--project PATH]
  python3 record_run.py --test

`--check-due` is the read side, called by the SessionStart maintenance hook (itself
debounced to once a day). It prints one nudge line when the last run is older than
DUE_DAYS AND at least DUE_SESSIONS transcripts are newer than it; otherwise nothing.
Both conditions, not either: a dormant repo has nothing new to mine, and a busy week
right after a run is not yet worth a second pass. Always exits 0.

Claude-side state is authoritative. The Codex mirror is best-effort: Codex may not be
installed, and its failure must never cost the Claude-side write.
"""

import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_transcripts import (  # noqa: E402
    codex_home,
    codex_state_dir,
    resolve_project_dir,
)

STATE_FILE = ".harness-curator-state.json"
DAY_MS = 86_400_000
DUE_DAYS = 14
DUE_SESSIONS = 10


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def state_path(project):
    proj_root = os.path.join(config_dir(), "projects")
    return os.path.join(resolve_project_dir(project, proj_root), STATE_FILE)


def read_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def write_state(path, state):
    """Atomic (tmp + os.replace) so a crash cannot truncate the bookkeeping."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def stamp(path, now_ms):
    """Read-modify-write so unrelated keys survive."""
    s = read_state(path)
    s["lastRunMs"] = now_ms
    write_state(path, s)
    return s


def record(project, now_ms=None):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    claude_path = state_path(project)
    stamp(claude_path, now_ms)

    codex_path = None
    try:
        codex_path = os.path.join(codex_state_dir(codex_home(), project), STATE_FILE)
        stamp(codex_path, now_ms)
    except Exception:
        codex_path = None  # best-effort; the Claude-side write already landed
    return claude_path, codex_path


def new_sessions(state_dir, since_ms):
    """Transcripts in the resolved project dir modified after `since_ms`."""
    try:
        names = [n for n in os.listdir(state_dir) if n.endswith(".jsonl")]
    except OSError:
        return 0
    count = 0
    for n in names:
        try:
            if os.path.getmtime(os.path.join(state_dir, n)) * 1000 > since_ms:
                count += 1
        except OSError:
            pass
    return count


def due_message(project, now_ms=None):
    """Return the nudge line, or None when a curate run is not due."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    path = state_path(project)
    last = read_state(path).get("lastRunMs") or 0
    if not isinstance(last, (int, float)):
        last = 0
    if last and now_ms - last <= DUE_DAYS * DAY_MS:
        return None
    sessions = new_sessions(os.path.dirname(path), last)
    if sessions < DUE_SESSIONS:
        return None
    age = f"{int((now_ms - last) // DAY_MS)}d ago" if last else "never"
    return (
        f"HARNESS-CURATE DUE: last run {age}, {sessions} sessions since. "
        "At the start of your next reply, suggest in one sentence that the user run "
        "`/dev:harness-curate`, then continue their task."
    )


def run_tests():
    import shutil

    results = []

    def check(name, cond):
        results.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    tmpdir = tempfile.mkdtemp()
    saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
    try:
        cfg = os.path.join(tmpdir, "claude")
        codex = os.path.join(tmpdir, "codex")
        proj = os.path.join(tmpdir, "repo")
        os.makedirs(proj)
        os.environ["CLAUDE_CONFIG_DIR"] = cfg
        os.environ["CODEX_HOME"] = codex

        cp, xp = record(proj, now_ms=1000)
        check("lastRunMs written", read_state(cp).get("lastRunMs") == 1000)
        check("codex mirror written", xp and read_state(xp).get("lastRunMs") == 1000)

        # unrelated keys survive a re-stamp
        s = read_state(cp)
        s["other"] = ["abc123"]
        write_state(cp, s)
        record(proj, now_ms=2000)
        claude = read_state(cp)
        check("re-stamp updates lastRunMs", claude.get("lastRunMs") == 2000)
        check("unrelated keys preserved", claude.get("other") == ["abc123"])

        # drift case: the exact encoded dir holds no transcripts, a loose-key sibling
        # does. The scanner reads the sibling — so must this.
        from scan_transcripts import encode_project

        drift_repo = os.path.join(tmpdir, "Drift_Repo")
        os.makedirs(drift_repo)
        exact = os.path.join(cfg, "projects", encode_project(drift_repo))
        os.makedirs(exact, exist_ok=True)
        # '_' vs '-' drift, not case drift: a case-insensitive filesystem would make a
        # case-only sibling the SAME directory and the test would prove nothing.
        sibling = os.path.join(cfg, "projects", encode_project(drift_repo).replace("_", "-"))
        os.makedirs(sibling, exist_ok=True)
        with open(os.path.join(sibling, "session.jsonl"), "w") as f:
            f.write("{}\n")
        dcp, _ = record(drift_repo, now_ms=3000)
        check("drift: stamps the sibling holding transcripts", os.path.dirname(dcp) == sibling)
        check("drift: does not write into the empty exact dir",
              not os.path.exists(os.path.join(exact, STATE_FILE)))

        # codex failure must not cost the claude-side write
        blocker = os.path.join(tmpdir, "blocked")
        with open(blocker, "w") as f:
            f.write("not a dir")
        os.environ["CODEX_HOME"] = blocker  # makedirs under a file -> raises
        cp2, xp2 = record(proj, now_ms=4000)
        check("codex failure swallowed", xp2 is None)
        check("claude write survives codex failure", read_state(cp2).get("lastRunMs") == 4000)

        with open(cp2, encoding="utf-8") as f:
            check("state file parses as JSON", isinstance(json.load(f), dict))

        # --check-due: both conditions must hold
        due_repo = os.path.join(tmpdir, "due")
        os.makedirs(due_repo)
        due_dir = os.path.join(cfg, "projects", encode_project(due_repo))
        os.makedirs(due_dir)
        now = int(time.time() * 1000)

        def sessions(n, mtime=None):
            for f in os.listdir(due_dir):
                if f.endswith(".jsonl"):
                    os.unlink(os.path.join(due_dir, f))
            for i in range(n):
                fp = os.path.join(due_dir, f"s{i}.jsonl")
                with open(fp, "w") as f:
                    f.write("{}\n")
                if mtime is not None:
                    os.utime(fp, (mtime, mtime))

        def last_run(ms):
            write_state(os.path.join(due_dir, STATE_FILE), {"lastRunMs": ms})

        old = now - (DUE_DAYS + 1) * DAY_MS
        sessions(DUE_SESSIONS)
        last_run(old)
        msg = due_message(due_repo, now)
        check("due: stale + enough sessions fires", msg and "/dev:harness-curate" in msg)
        last_run(0)
        check("due: never run + enough sessions fires",
              "never" in (due_message(due_repo, now) or ""))
        last_run(now - DAY_MS)
        check("due: recent run does not fire", due_message(due_repo, now) is None)
        sessions(DUE_SESSIONS - 1)
        last_run(old)
        check("due: stale but few sessions does not fire", due_message(due_repo, now) is None)
        sessions(DUE_SESSIONS, mtime=(old - DAY_MS) / 1000)
        check("due: sessions older than last run do not count",
              due_message(due_repo, now) is None)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmpdir, ignore_errors=True)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="Record a harness-curate run (Step 6).")
    ap.add_argument("--project", default=None, help="repo path (default: cwd)")
    ap.add_argument("--check-due", action="store_true",
                    help="print a nudge line when a run is due; never writes state")
    ap.add_argument("--test", action="store_true", help="run self-tests")
    a = ap.parse_args()

    if a.test:
        return run_tests()

    project = os.path.abspath(a.project or os.getcwd())
    if a.check_due:
        try:
            msg = due_message(project)
        except Exception:
            msg = None  # a reminder must never block session start
        if msg:
            print(msg)
        return 0

    claude_path, codex_path = record(project)
    print(f"harness-curate run recorded: {claude_path}")
    if codex_path is None:
        print("codex mirror skipped (not installed or unwritable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
