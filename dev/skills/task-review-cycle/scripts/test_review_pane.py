#!/usr/bin/env python3
"""Regression tests for review-pane.sh — the optional Herdr side pane that tails review progress.

The pane is a convenience, never a gate: every failure mode (not inside herdr-core, no
`herdr-app`, own pane not found, split refused, a hung `herdr-app`) must exit 0 with no stdout,
so the review cycle reads "no pane" and runs exactly as it does without hc. The success case
pins the exact `herdr-app` calls: a split of the caller's OWN pane (looked up from `herdr-app ls`
by HC_TERMINAL_ID, not whatever pane happens to be focused) running a tail of a per-run log.

`herdr-app` is stubbed on PATH by a POSIX shebang script, so these cases are skipped on Windows.

Run: python3 dev/skills/task-review-cycle/scripts/test_review_pane.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "review-pane.sh"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []

LS_FIXTURE = {
    "spaces": [{
        "id": "sp1",
        "tabs": [{
            "id": "tb1",
            "terminals": [
                {"terminal": "t2", "pane": "pOTHER", "status": "idle"},
                {"terminal": "t5", "pane": "pOWN", "status": "working"},
            ],
        }],
    }],
}

STUB = """#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ["HERDR_STUB_CALLS"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("HERDR_STUB_SLEEP"):
    time.sleep(float(os.environ["HERDR_STUB_SLEEP"]))
if sys.argv[1] == "ls":
    sys.stdout.write(os.environ["HERDR_STUB_LS"])
    sys.exit(0)
if os.environ.get("HERDR_STUB_FAIL"):
    sys.stdout.write('{"error": "boom"}')
    sys.exit(1)
if sys.argv[1:3] == ["do", "pane.split"]:
    sys.stdout.write('{"pane": "pNEW", "terminal": "t9"}')
sys.exit(0)
"""


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def setup(tmp):
    repo = tmp / "repo"
    if not repo.exists():
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "herdr-app"
    stub.write_text(STUB)
    stub.chmod(0o755)
    return repo, bin_dir


def run(tmp, args, hc_id: "str | None" = "t5", with_app=True, ls=LS_FIXTURE, extra_env=None):
    """Returns (completed_process, list_of_herdr_app_argv)."""
    repo, bin_dir = setup(tmp)
    calls = tmp / "calls.jsonl"
    calls.unlink(missing_ok=True)
    path_dirs = [str(bin_dir)] if with_app else []
    # Keep the real toolchain reachable without a real herdr-app shadowing the stub's absence.
    nobin = tmp / "nobin"
    nobin.mkdir(exist_ok=True)
    for tool in ("bash", "jq", "git", "mktemp", "find", "sleep", "kill", "date", "dirname", "mkdir", "python3", "env", "cat", "rm"):
        found = shutil.which(tool)
        link = nobin / tool
        if found and not link.exists():
            link.symlink_to(found)
    env = {k: v for k, v in os.environ.items() if k != "HC_TERMINAL_ID"}
    env.update({
        "PATH": os.pathsep.join(path_dirs + [str(nobin)]),
        "HERDR_STUB_CALLS": str(calls),
        "HERDR_STUB_LS": json.dumps(ls),
    })
    if hc_id:
        env["HC_TERMINAL_ID"] = hc_id
    env.update(extra_env or {})
    proc = subprocess.run(
        [str(nobin / "bash"), str(SCRIPT), *args],
        capture_output=True, text=True, cwd=repo, env=env, timeout=60,
    )
    seen = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    return proc, seen


def case_script_parses(_tmp):
    print("\ncase: the script parses")
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    check("bash -n exits 0", proc.returncode == 0, proc.stderr)


def case_outside_hc_is_noop(tmp):
    print("\ncase: HC_TERMINAL_ID unset -> silent no-op, herdr-app never called")
    proc, seen = run(tmp, ["open"], hc_id=None)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("no stdout", proc.stdout == "", proc.stdout)
    check("herdr-app not called", seen == [], str(seen))


def case_missing_app_is_noop(tmp):
    print("\ncase: herdr-app not on PATH -> silent no-op")
    proc, _ = run(tmp, ["open"], with_app=False)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("no stdout", proc.stdout == "", proc.stdout)


def case_open_splits_own_pane(tmp):
    print("\ncase: open splits the caller's own pane with a tail of a fresh per-run log")
    proc, seen = run(tmp, ["open"])
    check("exit 0", proc.returncode == 0, proc.stderr)
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = {}
    check("prints the created pane id", out.get("pane") == "pNEW", proc.stdout)
    log = out.get("log", "")
    git_dir = (tmp / "repo" / ".git").resolve()
    check("log lives under the git dir", log.startswith(str(git_dir) + "/task-review/"), log)
    check("log file exists", bool(log) and Path(log).is_file(), log)
    split = [c for c in seen if c[:2] == ["do", "pane.split"]]
    check("exactly one split", len(split) == 1, str(seen))
    if split:
        argv = split[0]
        check("splits right", argv[argv.index("--direction") + 1] == "right", str(argv))
        check("targets own pane, not the focused one", argv[argv.index("--pane") + 1] == "pOWN", str(argv))
        tail = json.loads(argv[argv.index("--argv") + 1])
        check("pane runs tail -F on the log", tail == ["tail", "-n", "+1", "-F", log], str(tail))
    proc2, _ = run(tmp, ["open"])
    try:
        log2 = json.loads(proc2.stdout).get("log")
    except ValueError:
        log2 = None
    check("a second run gets its own log", bool(log2) and log2 != log, f"{log} vs {log2}")


def case_own_pane_missing(tmp):
    print("\ncase: own terminal absent from ls -> no split, no stdout")
    proc, seen = run(tmp, ["open"], hc_id="t77")
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("no stdout", proc.stdout == "", proc.stdout)
    check("no split attempted", not any(c[:2] == ["do", "pane.split"] for c in seen), str(seen))


def case_split_failure_fails_open(tmp):
    print("\ncase: herdr-app refuses the split -> exit 0, no stdout")
    proc, _ = run(tmp, ["open"], extra_env={"HERDR_STUB_FAIL": "1"})
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("no stdout", proc.stdout == "", proc.stdout)


def case_hung_app_is_bounded(tmp):
    print("\ncase: a hung herdr-app is cut off by the bound")
    start = time.monotonic()
    proc, _ = run(tmp, ["open"], extra_env={"HERDR_STUB_SLEEP": "30", "REVIEW_PANE_TIMEOUT": "1"})
    elapsed = time.monotonic() - start
    check("returns well before the hang ends", elapsed < 15, f"{elapsed:.1f}s")
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("no stdout", proc.stdout == "", proc.stdout)


def case_close(tmp):
    print("\ncase: close passes the pane id and never fails")
    proc, seen = run(tmp, ["close", "pNEW"])
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("pane.close called with the id", ["do", "pane.close", "--pane", "pNEW"] in seen, str(seen))
    proc, _ = run(tmp, ["close", "pNEW"], extra_env={"HERDR_STUB_FAIL": "1"})
    check("failing close still exits 0", proc.returncode == 0, proc.stderr)
    proc, seen = run(tmp, ["close", ""])
    check("empty id is a no-op", proc.returncode == 0 and seen == [], str(seen))


def main():
    if os.name == "nt":
        print("POSIX-only (the herdr-app stub uses a shebang) — skipped on Windows")
        return 0
    if not shutil.which("jq"):
        print("jq is required for these tests", file=sys.stderr)
        return 1
    if not SCRIPT.exists():
        print(f"missing script under test: {SCRIPT}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        for case in (
            case_script_parses,
            case_outside_hc_is_noop,
            case_missing_app_is_noop,
            case_open_splits_own_pane,
            case_own_pane_missing,
            case_split_failure_fails_open,
            case_hung_app_is_bounded,
            case_close,
        ):
            case(tmp)
    failed = _results.count(False)
    print(f"\n{len(_results) - failed}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
