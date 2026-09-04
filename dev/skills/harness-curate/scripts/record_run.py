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
  python3 record_run.py --test

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
    ap.add_argument("--test", action="store_true", help="run self-tests")
    a = ap.parse_args()

    if a.test:
        return run_tests()

    project = os.path.abspath(a.project or os.getcwd())
    claude_path, codex_path = record(project)
    print(f"harness-curate run recorded: {claude_path}")
    if codex_path is None:
        print("codex mirror skipped (not installed or unwritable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
