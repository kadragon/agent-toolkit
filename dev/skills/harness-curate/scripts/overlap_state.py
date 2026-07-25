#!/usr/bin/env python3
"""
Cross-run suppression for Signal 8 (instruction-layer overlap).

Signals 1-7 are transcript-derived, so `lastRunMs` incrementality keeps them from
re-reporting analyzed work. Signal 8 is *static*: a duplicate/conflicting rule pair
sits in the files until someone edits them, so without per-finding suppression every
run re-reports the same pairs and re-sets `lastCandidateMs` — turning the staleness
nudge into permanent noise.

A pair the user has consciously resolved OR consciously kept is dismissed here, keyed
by a hash of both quoted lines. Editing either line changes the key, so a genuinely
new divergence surfaces again — dismissal suppresses *this exact pair*, not the topic.

Usage:
  python3 overlap_state.py --check   [--project PATH] < pairs.json
  python3 overlap_state.py --dismiss [--project PATH] < pairs.json
  python3 overlap_state.py --list    [--project PATH]
  python3 overlap_state.py --test

pairs.json (stdin): [{"global": "<verbatim line>", "repo": "<verbatim line>"}, ...]

State lives in the SAME .harness-curator-state.json the Step 6 write uses, under
`dismissedOverlaps`. Read-modify-write preserves `lastRunMs` / `lastCandidateMs`;
the write is atomic (tmp + os.replace) so a crash can't truncate the run bookkeeping.
Claude-side state only — the lens reads no Codex-side dismissals.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_transcripts import encode_project, resolve_project_dir  # noqa: E402

STATE_FILE = ".harness-curator-state.json"
MAX_DISMISSED = 200  # bounded: oldest entries drop out, newest kept


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def state_path(project):
    proj_root = os.path.join(config_dir(), "projects")
    tdir = resolve_project_dir(project, proj_root)
    return os.path.join(tdir, STATE_FILE)


def _norm(s):
    """Whitespace- and case-insensitive normalization. Reflowing a line or changing
    its capitalization is not a new finding; changing its words is."""
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def pair_key(global_line, repo_line):
    raw = _norm(global_line) + "\x00" + _norm(repo_line)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def read_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def write_state(path, state):
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


def load_pairs(stream):
    data = json.load(stream)
    if not isinstance(data, list):
        raise ValueError("expected a JSON list of {global, repo} objects")
    pairs = []
    for i, d in enumerate(data):
        if not isinstance(d, dict) or "global" not in d or "repo" not in d:
            raise ValueError(f"pair {i} needs both 'global' and 'repo' keys")
        pairs.append((d["global"], d["repo"]))
    return pairs


def cmd_check(project, pairs):
    dismissed = set(read_state(state_path(project)).get("dismissedOverlaps") or [])
    new = 0
    for g, r in pairs:
        k = pair_key(g, r)
        status = "DISMISSED" if k in dismissed else "NEW"
        new += status == "NEW"
        print(f"{status}\t{k}\t{_norm(g)[:80]}")
    print(f"checked={len(pairs)} new={new} suppressed={len(pairs) - new}")
    return 0


def cmd_dismiss(project, pairs):
    p = state_path(project)
    s = read_state(p)
    keep = list(s.get("dismissedOverlaps") or [])
    added = 0
    for g, r in pairs:
        k = pair_key(g, r)
        if k in keep:
            continue
        keep.append(k)
        added += 1
    s["dismissedOverlaps"] = keep[-MAX_DISMISSED:]
    write_state(p, s)
    print(f"dismissed added={added} total={len(s['dismissedOverlaps'])} state={p}")
    return 0


def cmd_list(project):
    p = state_path(project)
    keys = read_state(p).get("dismissedOverlaps") or []
    for k in keys:
        print(k)
    print(f"dismissed_total={len(keys)} state={p}")
    return 0


def run_tests():
    import shutil

    results = []

    def check(name, cond):
        results.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    tmpdir = tempfile.mkdtemp()
    try:
        cfg = os.path.join(tmpdir, "claude")
        proj = os.path.join(tmpdir, "repo")
        os.makedirs(proj)
        os.environ["CLAUDE_CONFIG_DIR"] = cfg

        # key stability / sensitivity
        k1 = pair_key("Never commit to main", "never  COMMIT to main\n")
        k2 = pair_key("Never commit to main", "never commit to main")
        check("whitespace+case normalized to same key", k1 == k2)
        check("different text -> different key",
              pair_key("a", "b") != pair_key("a", "c"))

        # dismiss then check
        cmd_dismiss(proj, [("Never commit to main", "never commit to main")])
        sp = state_path(proj)
        check("state file created", os.path.exists(sp))
        check("dismissedOverlaps recorded",
              len(read_state(sp).get("dismissedOverlaps", [])) == 1)

        # preserves unrelated keys
        s = read_state(sp)
        s["lastRunMs"] = 12345
        write_state(sp, s)
        cmd_dismiss(proj, [("x", "y")])
        check("lastRunMs preserved across dismiss", read_state(sp).get("lastRunMs") == 12345)
        check("second dismissal appended", len(read_state(sp)["dismissedOverlaps"]) == 2)

        # idempotent
        cmd_dismiss(proj, [("x", "y")])
        check("re-dismissing same pair is a no-op",
              len(read_state(sp)["dismissedOverlaps"]) == 2)

        # cap
        s = read_state(sp)
        s["dismissedOverlaps"] = [f"k{i:04d}" for i in range(MAX_DISMISSED + 10)]
        write_state(sp, s)
        cmd_dismiss(proj, [("new", "pair")])
        capped = read_state(sp)["dismissedOverlaps"]
        check("dismissed list capped", len(capped) == MAX_DISMISSED)
        check("newest entry survives the cap",
              capped[-1] == pair_key("new", "pair"))

        # check classifies correctly
        s = read_state(sp)
        s["dismissedOverlaps"] = [pair_key("g1", "r1")]
        write_state(sp, s)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_check(proj, [("g1", "r1"), ("g2", "r2")])
        out = buf.getvalue()
        check("check marks known pair DISMISSED", "DISMISSED\t" in out)
        check("check marks unknown pair NEW", "NEW\t" in out)
        check("check prints counts, no silent drop", "checked=2 new=1 suppressed=1" in out)

        # malformed input rejected
        try:
            load_pairs(io.StringIO('[{"global": "a"}]'))
            check("malformed pair rejected", False)
        except ValueError:
            check("malformed pair rejected", True)

        # state dir resolution matches the scanner's encoding
        check("state path under encoded project dir",
              encode_project(proj) in sp)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="classify stdin pairs NEW/DISMISSED")
    g.add_argument("--dismiss", action="store_true", help="record stdin pairs as dismissed")
    g.add_argument("--list", action="store_true", help="print dismissed keys")
    g.add_argument("--test", action="store_true", help="run self-tests")
    ap.add_argument("--project", default=None, help="repo path (default: cwd)")
    a = ap.parse_args()

    if a.test:
        return run_tests()

    project = os.path.abspath(a.project or os.getcwd())
    if a.list:
        return cmd_list(project)

    pairs = load_pairs(sys.stdin)
    return cmd_check(project, pairs) if a.check else cmd_dismiss(project, pairs)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"overlap_state failed: {e}")
        sys.exit(1)
