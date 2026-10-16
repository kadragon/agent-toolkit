#!/usr/bin/env python3
"""
Run ledger for test-prune: record what a run explored, and tell the next run which
of those records still describe the current source.

Usage:
  python3 prune_ledger.py start --target REPO [--root DIR]
  python3 prune_ledger.py record --run-dir DIR [--seed S] < units.json
  python3 prune_ledger.py --test

`start` refuses a target with tracked changes (the skill measures HEAD), reads every
prior run, then creates the next `<root>/<repo-name>/run-<N>/` with `run-metadata.json`
and prints JSON: the run dir and the newest prior record of each test file, tagged
`same_source`, `changed_source` or `removed` (test file gone from HEAD). A unit is
same_source only when every file it recorded has the same git blob at HEAD; a file
missing then or now counts as changed. A prior run whose `ledger.json` is absent or
unreadable is listed as incomplete, never read as empty coverage.

`record` reads the run's units (a JSON array, one unit per test file) on stdin,
stamps each unit's blobs at the run's `source_ref`, records the sample seed, and
writes `ledger.json`. Unit shape and reuse rules: ../references/run-ledger.md.

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


def blobs_at(target, ref, paths):
    """Map every path to its blob sha at ref, or None when ref has no such file."""
    paths = sorted(set(paths))
    blobs = dict.fromkeys(paths)
    if not paths:
        return blobs
    out = git(target, "ls-tree", "-r", "-z", ref, "--", *paths)
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        if path in blobs:
            blobs[path] = meta.split()[2]
    return blobs


def unit_paths(unit):
    paths = [unit["test_path"], *unit.get("covered", []), *unit.get("depends", [])]
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


def read_ledger(run):
    try:
        with open(os.path.join(run, "ledger.json"), encoding="utf-8") as f:
            units = json.load(f)
        if isinstance(units, list) and all(isinstance(u.get("test_path"), str) for u in units):
            return units
    except (OSError, ValueError, AttributeError):
        pass
    return None


def classify(target, prior_runs):
    """Newest prior record per test file, tagged same_source, changed_source or removed."""
    seen, units, incomplete = set(), [], []
    for run in prior_runs:
        ledger = read_ledger(run)
        if ledger is None:
            incomplete.append(run)
            continue
        for unit in ledger:
            if unit["test_path"] in seen:
                continue
            seen.add(unit["test_path"])
            recorded = unit.get("blobs") or {}
            current = blobs_at(target, "HEAD", [unit["test_path"], *recorded])
            if current[unit["test_path"]] is None:
                status = "removed"
            elif recorded and all(v is not None and current[p] == v for p, v in recorded.items()):
                status = "same_source"
            else:
                status = "changed_source"
            units.append({**unit, "prior_status": status, "from_run": run})
    return units, incomplete


def cmd_start(args):
    target = os.path.abspath(args.target)
    if git(target, "status", "--porcelain", "--untracked-files=no"):
        print("target has uncommitted changes; commit or stash first", file=sys.stderr)
        return 1
    repo_dir = os.path.join(args.root, repo_name(target))
    numbered = run_dirs(repo_dir)
    prior = [path for _, path in numbered]
    units, incomplete = classify(target, prior)
    n = numbered[0][0] + 1 if numbered else 1
    run_dir = os.path.join(repo_dir, f"run-{n}")
    os.makedirs(run_dir)
    write_json(os.path.join(run_dir, "run-metadata.json"), {
        "run_id": f"run-{n}",
        "target": target,
        "source_ref": git(target, "rev-parse", "HEAD").strip(),
        "seed": None,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "prior_runs": prior,
        "incomplete_prior_runs": incomplete,
    })
    print(json.dumps({"run_dir": run_dir, "prior_units": units,
                      "incomplete_prior_runs": incomplete}, indent=2, ensure_ascii=False))
    return 0


def cmd_record(args):
    meta_path = os.path.join(args.run_dir, "run-metadata.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    units = json.load(sys.stdin)
    for unit in units:
        status, from_run = unit.pop("prior_status", None), unit.pop("from_run", None)
        if status == "same_source":
            unit["carried_from"] = unit.get("carried_from") or from_run
        else:
            unit.pop("carried_from", None)
        # stamp the measured commit, not HEAD: HEAD may have moved since start
        unit["blobs"] = blobs_at(meta["target"], meta["source_ref"], unit_paths(unit))
    if args.seed is not None:
        meta["seed"] = args.seed
        write_json(meta_path, meta)
    write_json(os.path.join(args.run_dir, "ledger.json"), units)
    print(f"recorded {len(units)} units in {args.run_dir}/ledger.json")
    return 0


def self_test():
    import io
    import shutil
    from contextlib import redirect_stdout

    # isolate from the user's git config (gpg signing, hooks)
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    tmp = tempfile.mkdtemp()
    try:
        repo, root = os.path.join(tmp, "demo"), os.path.join(tmp, "store")
        os.makedirs(os.path.join(repo, "src"))
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")

        def write(path, body):
            with open(os.path.join(repo, path), "w") as f:
                f.write(body)

        for p in ("src/a.ts", "src/a.test.ts", "src/b.ts", "src/b.test.ts", "src/c.test.ts",
                  "src/d.ts", "src/d.test.ts", "src/e.test.ts", "src/f.ts", "src/f.test.ts"):
            write(p, p)
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "init")

        def run_start():
            buf = io.StringIO()
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                with redirect_stdout(buf):
                    code = cmd_start(argparse.Namespace(target=repo, root=root))
            finally:
                sys.stderr = stderr
            return code, buf.getvalue()

        def start():
            code, out = run_start()
            assert code == 0, code
            return json.loads(out)

        def record(run_dir, units, seed=None):
            stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(units))
            try:
                with redirect_stdout(io.StringIO()):
                    cmd_record(argparse.Namespace(run_dir=run_dir, seed=seed))
            finally:
                sys.stdin = stdin

        def statuses(out):
            return {u["test_path"]: u["prior_status"] for u in out["prior_units"]}

        first = start()
        assert first["run_dir"].endswith(os.path.join("demo", "run-1")), first["run_dir"]
        assert first["prior_units"] == []
        record(first["run_dir"], [
            {"test_path": "src/a.test.ts", "covered": ["src/a.ts"]},
            # b's mutant is also killed by c: c changing must reopen b
            {"test_path": "src/b.test.ts", "covered": ["src/b.ts"],
             "mutants": [{"id": "m1", "outcome": "KILLED",
                          "killed_by": ["src/b.test.ts::x", "src/c.test.ts::y"]}]},
            {"test_path": "src/c.test.ts"},
            {"test_path": "src/d.test.ts", "covered": ["src/d.ts"]},
            {"test_path": "src/e.test.ts"},
            # a recorded path HEAD never had: stored as None, never reads as unchanged
            {"test_path": "src/f.test.ts", "covered": ["./src/f.ts"]},
        ], seed="42")
        assert git(repo, "status", "--porcelain") == "", "record wrote into the target"
        with open(os.path.join(first["run_dir"], "run-metadata.json")) as f:
            assert json.load(f)["seed"] == "42"

        write("src/c.test.ts", "c2")          # one-file change, reaches b through killed_by
        git(repo, "rm", "-q", "src/d.ts")      # covered file deleted, test file untouched
        git(repo, "rm", "-q", "src/e.test.ts")  # test file deleted
        git(repo, "commit", "-qam", "edit")
        write("untracked-notes", "x")          # untracked files do not block start
        second = start()
        assert second["run_dir"].endswith("run-2"), second["run_dir"]
        assert statuses(second) == {
            "src/a.test.ts": "same_source", "src/b.test.ts": "changed_source",
            "src/c.test.ts": "changed_source", "src/d.test.ts": "changed_source",
            "src/e.test.ts": "removed", "src/f.test.ts": "changed_source",
        }, statuses(second)

        # HEAD moves after start: record stamps the run's source_ref, not the new HEAD
        write("src/a.ts", "a2")
        git(repo, "commit", "-qam", "move head")
        carried = next(u for u in second["prior_units"] if u["test_path"] == "src/a.test.ts")
        record(second["run_dir"], [carried])
        with open(os.path.join(second["run_dir"], "ledger.json")) as f:
            unit = json.load(f)[0]
        assert unit["carried_from"] == first["run_dir"], unit
        third = start()
        assert statuses(third)["src/a.test.ts"] == "changed_source", statuses(third)
        assert len(third["prior_units"]) == 6  # run-2 holds a; run-1 still supplies the rest

        # run-3 never recorded; a corrupt run-4 ledger: both listed incomplete, no crash
        fourth = start()
        with open(os.path.join(fourth["run_dir"], "ledger.json"), "w") as f:
            f.write("{truncated")
        fifth = start()
        assert fifth["incomplete_prior_runs"] == [fourth["run_dir"], third["run_dir"]], fifth

        write("src/a.ts", "dirty")
        assert run_start()[0] == 1
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
    s.add_argument("--root", default=DEFAULT_ROOT)
    r = sub.add_parser("record")
    r.add_argument("--run-dir", required=True)
    r.add_argument("--seed")
    args = ap.parse_args()
    return cmd_start(args) if args.cmd == "start" else cmd_record(args)


if __name__ == "__main__":
    sys.exit(main())
