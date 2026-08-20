#!/usr/bin/env python3
"""
Record a harness-curate run (Step 6 bookkeeping).

Stamps `lastRunMs` — which `scan_transcripts.py` reads to keep PROMPTS incremental —
and sets or clears `lastCandidateMs`, which the session-start nudge
(`dev/hooks/session-start/task-audit-nudge.py`) reads to decide between "analysis is
stale" and "candidates are pending". An empty or Watch-only report must CLEAR
`lastCandidateMs`, or the nudge nags about candidates nobody produced.

Usage:
  python3 record_run.py --pending {0|1} [--project PATH]
  python3 record_run.py --test

  --pending 1   the report had >=1 non-Watch candidate row
  --pending 0   the report was empty or Watch-only

This lived as an inline snippet in SKILL.md until it grew its own copy of the
project-dir encoding. Three components write or read this file — this script, the
nudge hook, and `scan_transcripts.py` — so the resolution is imported from
`overlap_state.state_path()` (itself `resolve_project_dir()`) rather than re-derived:
a raw substitution here can mint a case/underscore sibling directory that then
poisons the scanner's exact-match short-circuit, hiding real transcript data.

Claude-side state is authoritative. The Codex mirror is best-effort: Codex may not be
installed, and its failure must never cost the Claude-side write.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from overlap_state import read_state, state_path, write_state  # noqa: E402
from scan_transcripts import codex_home, codex_state_dir  # noqa: E402

STATE_FILE = ".harness-curator-state.json"


def stamp(path, now_ms, pending):
    """Read-modify-write so `dismissedOverlaps` and any other key survive."""
    s = read_state(path)
    s["lastRunMs"] = now_ms
    if pending:
        s["lastCandidateMs"] = now_ms
    else:
        s.pop("lastCandidateMs", None)
    write_state(path, s)
    return s


def record(project, pending, now_ms=None):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    claude_path = state_path(project)
    stamp(claude_path, now_ms, pending)

    codex_path = None
    try:
        codex_path = os.path.join(codex_state_dir(codex_home(), project), STATE_FILE)
        stamp(codex_path, now_ms, pending)
    except Exception:
        codex_path = None  # best-effort; the Claude-side write already landed
    return claude_path, codex_path


def run_tests():
    import json
    import shutil
    import tempfile

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

        # pending=1 sets both stamps, on both sides
        cp, xp = record(proj, True, now_ms=1000)
        claude = read_state(cp)
        check("lastRunMs written", claude.get("lastRunMs") == 1000)
        check("pending=1 sets lastCandidateMs", claude.get("lastCandidateMs") == 1000)
        check("codex mirror written", xp and read_state(xp).get("lastCandidateMs") == 1000)

        # unrelated keys survive; pending=0 clears only lastCandidateMs
        s = read_state(cp)
        s["dismissedOverlaps"] = ["abc123"]
        write_state(cp, s)
        record(proj, False, now_ms=2000)
        claude = read_state(cp)
        check("pending=0 clears lastCandidateMs", "lastCandidateMs" not in claude)
        check("pending=0 still stamps lastRunMs", claude.get("lastRunMs") == 2000)
        check("dismissedOverlaps preserved", claude.get("dismissedOverlaps") == ["abc123"])
        check("codex mirror cleared too", "lastCandidateMs" not in read_state(xp))

        # writes where overlap_state reads
        check("path agrees with overlap_state.state_path", cp == state_path(proj))

        # drift case: the exact encoded dir holds no transcripts, a loose-key sibling
        # does. The scanner and the nudge both read the sibling — so must this.
        drift_repo = os.path.join(tmpdir, "Drift_Repo")
        os.makedirs(drift_repo)
        from scan_transcripts import encode_project

        exact = os.path.join(cfg, "projects", encode_project(drift_repo))
        os.makedirs(exact, exist_ok=True)
        # '_' vs '-' drift, not case drift: a case-insensitive filesystem would make a
        # case-only sibling the SAME directory and the test would prove nothing.
        sibling = os.path.join(cfg, "projects", encode_project(drift_repo).replace("_", "-"))
        os.makedirs(sibling, exist_ok=True)
        with open(os.path.join(sibling, "session.jsonl"), "w") as f:
            f.write("{}\n")
        dcp, _ = record(drift_repo, True, now_ms=3000)
        check("drift: stamps the sibling holding transcripts",
              os.path.dirname(dcp) == sibling)
        check("drift: does not write into the empty exact dir",
              not os.path.exists(os.path.join(exact, STATE_FILE)))

        # codex failure must not cost the claude-side write
        os.environ["CODEX_HOME"] = os.path.join(tmpdir, "claude", "projects")
        blocker = os.path.join(tmpdir, "blocked")
        with open(blocker, "w") as f:
            f.write("not a dir")
        os.environ["CODEX_HOME"] = blocker  # makedirs under a file -> raises
        cp2, xp2 = record(proj, True, now_ms=4000)
        check("codex failure swallowed", xp2 is None)
        check("claude write survives codex failure",
              read_state(cp2).get("lastRunMs") == 4000)

        # file is valid JSON on disk (atomic write, not truncated)
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
    ap.add_argument("--pending", choices=["0", "1"],
                    help="1 = report had >=1 non-Watch candidate row; 0 = empty/Watch-only")
    ap.add_argument("--project", default=None, help="repo path (default: cwd)")
    ap.add_argument("--test", action="store_true", help="run self-tests")
    a = ap.parse_args()

    if a.test:
        return run_tests()
    if a.pending is None:
        ap.error("--pending {0|1} is required (or --test)")

    project = os.path.abspath(a.project or os.getcwd())
    claude_path, codex_path = record(project, a.pending == "1")
    print(f"harness-curate run recorded: {claude_path}")
    if codex_path is None:
        print("codex mirror skipped (not installed or unwritable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
