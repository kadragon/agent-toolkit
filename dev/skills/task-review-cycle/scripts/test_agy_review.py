#!/usr/bin/env python3
"""Regression tests for agy-review.sh's prompt scope and durable result sidecar.

The cycle launches agy in the background and never waits for it (references/review-sources.md).
A run that finished after the reviewer returned was recorded as skipped and its stdout was never
read, so its findings were lost. Measured on agy 1.2.9: a review of a 4-file diff took 4m12s,
most of it spent running the repo's test suite and validate-harness.sh in the background —
work the prompt never asked for.

Two fixes, one case group each:
- The prompt scopes agy to a read-only review (git + file reads, no tests/builds/background
  commands). `case_prompt_is_read_only` fails if that section is removed.
- Every finished run leaves `<key>.pending` → `<key>.review.txt` + `<key>.meta` under
  AGY_REVIEW_RESULT_DIR, the same layout codex-review.sh uses, so the pre-merge reclaim
  (references/late-source-reclaim.md) can collect a late agy review.

The `agy` CLI is stubbed on PATH by a POSIX shebang script, so these cases are skipped on
Windows; CI runs them on ubuntu.

Run: python3 dev/skills/task-review-cycle/scripts/test_agy_review.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "agy-review.sh"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []

# Captures the prompt (the argument after -p) and a snapshot of the `.pending` file taken while
# agy is "running" — proof the marker exists before the run finishes, not only after.
STUB = """#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  if [ "$1" = "-p" ]; then printf '%s' "$2" >"$AGY_STUB_CAPTURE"; shift; fi
  shift
done
cat "$AGY_STUB_PENDING" >"$AGY_STUB_PENDING_SNAPSHOT" 2>/dev/null || true
printf '%s' "$AGY_STUB_STDOUT"
exit "$AGY_STUB_EXIT"
"""

BRANCH = "feat/agy-x"
KEY = "feat-agy-x"


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def make_repo(tmp):
    """A repo whose BRANCH differs from main by one file, so the empty-diff gate passes."""
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "change")
    return repo


def run(tmp, stdout="", exit_code=0):
    """Run agy-review.sh against main with a stubbed `agy`. Returns (proc, prompt, snapshot, dir)."""
    repo = make_repo(tmp)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "agy"
    stub.write_text(STUB)
    stub.chmod(0o755)
    result_dir = tmp / "results"
    capture = tmp / "prompt.txt"
    snapshot = tmp / "pending.txt"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "AGY_REVIEW_RESULT_DIR": str(result_dir),
        "AGY_STUB_CAPTURE": str(capture),
        "AGY_STUB_PENDING": str(result_dir / f"{KEY}.pending"),
        "AGY_STUB_PENDING_SNAPSHOT": str(snapshot),
        "AGY_STUB_STDOUT": stdout,
        "AGY_STUB_EXIT": str(exit_code),
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), "main"],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        timeout=60,
    )
    prompt = capture.read_text() if capture.exists() else ""
    pending = snapshot.read_text() if snapshot.exists() else ""
    return proc, prompt, pending, result_dir


def meta(result_dir):
    path = result_dir / f"{KEY}.meta"
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def case_script_parses(_tmp):
    print("\ncase: the script parses")
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    check("bash -n exits 0", proc.returncode == 0, proc.stderr)


def case_prompt_is_read_only(tmp):
    print("\ncase: the prompt scopes agy to a read-only review")
    proc, prompt, _, _ = run(tmp, stdout="LGTM\n")
    check("script exits 0", proc.returncode == 0, proc.stderr)
    check("prompt forbids running tests", "Do NOT run tests" in prompt, prompt[:300])
    check("prompt forbids background commands", "in the background" in prompt, prompt[:300])


def case_ok_run_persists_review(tmp):
    print("\ncase: a finished run leaves review + meta, and pending existed while it ran")
    proc, _, pending, result_dir = run(tmp, stdout="[P1] Fix x\nOverall verdict: LGTM\n")
    m = meta(result_dir)
    review = result_dir / f"{KEY}.review.txt"
    check("script exits 0", proc.returncode == 0, proc.stderr)
    check("stdout still carries the review", "[P1] Fix x" in proc.stdout, proc.stdout)
    check("pending existed during the run", f"branch={BRANCH}" in pending, pending)
    check("pending removed after the run", not (result_dir / f"{KEY}.pending").exists())
    check("meta status=ok", m.get("status") == "ok", str(m))
    check("meta carries branch and base", m.get("branch") == BRANCH and m.get("base") == "main", str(m))
    check("meta names the review file", m.get("review_file") == str(review), str(m))
    check("review file holds the text", review.exists() and "[P1] Fix x" in review.read_text())


def case_failed_run_records_failure(tmp):
    print("\ncase: a non-zero exit with partial output is recorded as failed")
    proc, _, _, result_dir = run(tmp, stdout="partial", exit_code=3)
    m = meta(result_dir)
    check("script exits non-zero", proc.returncode != 0)
    check("meta status=failed", m.get("status") == "failed", str(m))
    check("meta exit_code=3", m.get("exit_code") == "3", str(m))
    check("no review file", not (result_dir / f"{KEY}.review.txt").exists())


def case_empty_run_records_empty(tmp):
    print("\ncase: empty output is recorded as empty")
    proc, _, _, result_dir = run(tmp, stdout="  \n")
    m = meta(result_dir)
    check("script exits non-zero", proc.returncode != 0)
    check("meta status=empty", m.get("status") == "empty", str(m))
    check("meta review_file is blank", m.get("review_file") == "", str(m))


def case_stale_trio_cleared(tmp):
    print("\ncase: a previous run's result is cleared before the new run")
    result_dir = tmp / "results"
    result_dir.mkdir()
    (result_dir / f"{KEY}.review.txt").write_text("OLD REVIEW\n")
    (result_dir / f"{KEY}.meta").write_text("status=ok\n")
    run(tmp, stdout="  \n")
    check("meta is this run's (empty), not the stale ok", meta(result_dir).get("status") == "empty")
    check("stale review file removed", not (result_dir / f"{KEY}.review.txt").exists())


def main():
    if os.name == "nt":
        print("POSIX-only (the agy stub uses a shebang) — skipped on Windows")
        return 0
    if not SCRIPT.exists():
        print(f"missing script under test: {SCRIPT}", file=sys.stderr)
        return 1
    cases = (
        case_script_parses,
        case_prompt_is_read_only,
        case_ok_run_persists_review,
        case_failed_run_records_failure,
        case_empty_run_records_empty,
        case_stale_trio_cleared,
    )
    for case in cases:
        with tempfile.TemporaryDirectory() as raw:
            case(Path(raw))
    failed = _results.count(False)
    print(f"\n{len(_results) - failed}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
