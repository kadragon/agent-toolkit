#!/usr/bin/env python3
"""
Run ledger for test-prune: record what a run explored, and tell the next run which
of those records still describe the current source.

Usage:
  python3 prune_ledger.py start --target REPO [--seed S] [--root DIR]
  python3 prune_ledger.py record --run-dir DIR < units.json
  python3 prune_ledger.py --test

`start` refuses a dirty target (the skill measures HEAD), creates the next
`<root>/<repo-name>/run-<N>/`, writes `run-metadata.json`, and prints JSON: the run dir
and, for every unit the newest prior ledger holds, `same_source` or `changed_source`.
A unit is same_source only when every file it recorded has the same git blob at HEAD;
a missing file is changed. Prior runs without a `ledger.json` are listed as incomplete,
never read as empty coverage.

`record` reads the run's units (a JSON array, one unit per test file) on stdin,
stamps each unit's blobs from the target's HEAD, and writes `ledger.json`. Unit shape
and reuse rules: ../references/run-ledger.md.

The default root is ~/.test-prune, outside the target, so the target tree stays clean.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

DEFAULT_ROOT = os.path.expanduser("~/.test-prune")
RUN_RE = re.compile(r"^run-(\d+)$")


def git(target, *args):
    return subprocess.run(
        ["git", "-C", target, *args], check=True, capture_output=True, text=True
    ).stdout


def repo_name(target):
    try:
        url = git(target, "remote", "get-url", "origin").strip()
    except subprocess.CalledProcessError:
        url = ""
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1] if url else ""
    if name.endswith(".git"):
        name = name[:-4]
    return name or os.path.basename(git(target, "rev-parse", "--show-toplevel").strip())


def head_blobs(target, paths):
    """Map each path to its blob sha at HEAD; paths absent from HEAD are left out."""
    paths = sorted(set(paths))
    if not paths:
        return {}
    out = git(target, "ls-tree", "-r", "-z", "HEAD", "--", *paths)
    blobs = {}
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        blobs[path] = meta.split()[2]
    return blobs


def unit_paths(unit):
    paths = [unit["test_path"], *unit.get("covered", [])]
    for m in unit.get("mutants", []):
        paths += [k.split("::", 1)[0] for k in m.get("killed_by", [])]
    return paths


def run_dirs(repo_dir):
    """Existing (N, run-<N> dir) pairs, newest first."""
    if not os.path.isdir(repo_dir):
        return []
    runs = [(int(m.group(1)), n) for n in os.listdir(repo_dir) if (m := RUN_RE.match(n))]
    return [(i, os.path.join(repo_dir, n)) for i, n in sorted(runs, reverse=True)]


def write_json(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def classify(target, prior_runs):
    """Newest prior record per test file, tagged same_source or changed_source."""
    seen, units, incomplete = set(), [], []
    for run in prior_runs:
        ledger = os.path.join(run, "ledger.json")
        if not os.path.isfile(ledger):
            incomplete.append(run)
            continue
        with open(ledger, encoding="utf-8") as f:
            for unit in json.load(f):
                if unit["test_path"] in seen:
                    continue
                seen.add(unit["test_path"])
                recorded = unit.get("blobs", {})
                current = head_blobs(target, recorded)
                same = bool(recorded) and current == recorded
                units.append({**unit, "prior_status": "same_source" if same else "changed_source",
                              "from_run": run})
    return units, incomplete


def cmd_start(args):
    target = os.path.abspath(args.target)
    if git(target, "status", "--porcelain"):
        print("target has uncommitted changes; commit or stash first", file=sys.stderr)
        return 1
    repo_dir = os.path.join(args.root, repo_name(target))
    numbered = run_dirs(repo_dir)
    prior = [path for _, path in numbered]
    n = numbered[0][0] + 1 if numbered else 1
    run_dir = os.path.join(repo_dir, f"run-{n}")
    os.makedirs(run_dir)
    units, incomplete = classify(target, prior)
    write_json(os.path.join(run_dir, "run-metadata.json"), {
        "run_id": f"run-{n}",
        "target": target,
        "source_ref": git(target, "rev-parse", "HEAD").strip(),
        "seed": args.seed,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "prior_runs": prior,
        "incomplete_prior_runs": incomplete,
    })
    print(json.dumps({"run_dir": run_dir, "prior_units": units,
                      "incomplete_prior_runs": incomplete}, indent=2, ensure_ascii=False))
    return 0


def cmd_record(args):
    with open(os.path.join(args.run_dir, "run-metadata.json"), encoding="utf-8") as f:
        target = json.load(f)["target"]
    units = json.load(sys.stdin)
    for unit in units:
        unit.pop("prior_status", None)
        unit.pop("from_run", None)
        unit["blobs"] = head_blobs(target, unit_paths(unit))
    write_json(os.path.join(args.run_dir, "ledger.json"), units)
    print(f"recorded {len(units)} units in {args.run_dir}/ledger.json")
    return 0


def self_test():
    import io
    import shutil
    from contextlib import redirect_stdout

    tmp = tempfile.mkdtemp()
    try:
        repo, root = os.path.join(tmp, "demo"), os.path.join(tmp, "store")
        os.makedirs(os.path.join(repo, "src"))
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        files = {"src/a.ts": "a", "src/a.test.ts": "ta", "src/b.ts": "b",
                 "src/b.test.ts": "tb", "src/c.test.ts": "tc"}
        for p, body in files.items():
            with open(os.path.join(repo, p), "w") as f:
                f.write(body)
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "init")

        def start():
            buf = io.StringIO()
            with redirect_stdout(buf):
                assert cmd_start(argparse.Namespace(target=repo, seed=7, root=root)) == 0
            return json.loads(buf.getvalue())

        def record(run_dir, units):
            stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(units))
            try:
                with redirect_stdout(io.StringIO()):
                    cmd_record(argparse.Namespace(run_dir=run_dir))
            finally:
                sys.stdin = stdin

        first = start()
        assert first["run_dir"].endswith(os.path.join("demo", "run-1")), first["run_dir"]
        assert first["prior_units"] == []
        record(first["run_dir"], [
            {"test_path": "src/a.test.ts", "covered": ["src/a.ts"]},
            # b's mutant is also killed by c: c changing must reopen b
            {"test_path": "src/b.test.ts", "covered": ["src/b.ts"],
             "mutants": [{"id": "m1", "outcome": "KILLED",
                          "killed_by": ["src/b.test.ts::x", "src/c.test.ts::y"]}]},
            {"test_path": "src/c.test.ts", "covered": ["src/gone.ts"]},
        ])
        assert git(repo, "status", "--porcelain") == "", "record wrote into the target"

        with open(os.path.join(repo, "src/c.test.ts"), "w") as f:
            f.write("tc2")
        git(repo, "commit", "-qam", "edit c")
        second = start()
        assert second["run_dir"].endswith("run-2"), second["run_dir"]
        status = {u["test_path"]: u["prior_status"] for u in second["prior_units"]}
        assert status == {"src/a.test.ts": "same_source", "src/b.test.ts": "changed_source",
                          "src/c.test.ts": "changed_source"}, status
        # run-2 has no ledger yet: the next start lists it as incomplete and still reads run-1
        third = start()
        assert third["run_dir"].endswith("run-3")
        assert third["incomplete_prior_runs"] == [second["run_dir"]]
        assert len(third["prior_units"]) == 3

        with open(os.path.join(repo, "dirty"), "w") as f:
            f.write("x")
        with redirect_stdout(io.StringIO()):
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                assert cmd_start(argparse.Namespace(target=repo, seed=None, root=root)) == 1
            finally:
                sys.stderr = stderr
    finally:
        shutil.rmtree(tmp)
    print("prune_ledger self-test: ok")
    return 0


def main():
    if "--test" in sys.argv[1:]:
        return self_test()
    ap = argparse.ArgumentParser(description="test-prune run ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--target", required=True)
    s.add_argument("--seed")
    s.add_argument("--root", default=DEFAULT_ROOT)
    r = sub.add_parser("record")
    r.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    return cmd_start(args) if args.cmd == "start" else cmd_record(args)


if __name__ == "__main__":
    sys.exit(main())
