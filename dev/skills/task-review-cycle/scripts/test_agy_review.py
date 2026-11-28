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
- Every invocation owns its pending marker, review text and metadata under AGY_REVIEW_RESULT_DIR,
  so the pre-merge reclaim can collect late reviews across resyncs and overlapping launches.
- Every finished run also appends a `timings.log` line (elapsed + diff size), so the
  `--print-timeout` cap can be argued from data, as codex's is.

The `agy` CLI is stubbed on PATH by a POSIX shebang script, so these cases are skipped on
Windows; CI runs them on ubuntu.

Run: python3 dev/skills/task-review-cycle/scripts/test_agy_review.py
"""

import os
import re
import subprocess
import sys
import tempfile
import time
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
for pending in "$AGY_STUB_RESULTS"/*/run.*/review.pending; do
  if [ -f "$pending" ]; then
    cat "$pending" >"$AGY_STUB_PENDING_SNAPSHOT"
  fi
done
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


def make_repo(tmp, review_guidance=None):
    """A repo whose BRANCH differs from main by one file, so the empty-diff gate passes."""
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    if review_guidance is not None:
        (repo / "REVIEW.md").write_text(review_guidance, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "change")
    return repo


def run(tmp, stdout="", exit_code=0, review_guidance=None, base="main"):
    """Run agy-review.sh against main with a stubbed `agy`. Returns (proc, prompt, snapshot, dir)."""
    repo = make_repo(tmp, review_guidance)
    if review_guidance is not None:
        (repo / "REVIEW.md").write_text("Private working copy should stay local.", encoding="utf-8")
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
        "AGY_STUB_RESULTS": str(result_dir),
        "AGY_STUB_PENDING_SNAPSHOT": str(snapshot),
        "AGY_STUB_STDOUT": stdout,
        "AGY_STUB_EXIT": str(exit_code),
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), base],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        timeout=60,
    )
    prompt = capture.read_text() if capture.exists() else ""
    pending = snapshot.read_text() if snapshot.exists() else ""
    return proc, prompt, pending, result_dir


def result_metadata(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def meta(result_dir):
    paths = list(result_dir.glob("*/run.*/review.meta"))
    return result_metadata(paths[0]) if paths else {}


def case_script_parses(_tmp):
    print("\ncase: the script parses")
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    check("bash -n exits 0", proc.returncode == 0, proc.stderr)


def case_base_ref_is_distinguished_from_empty_diff(tmp):
    print("\ncase: an unknown comparison ref fails, an empty diff skips")
    (tmp / "bad").mkdir()
    proc, prompt, _, result_dir = run(tmp / "bad", stdout="LGTM\n", base="no-such-ref")
    check("unknown ref exits non-zero", proc.returncode != 0, proc.stdout + proc.stderr)
    check("unknown ref names the ref", "no-such-ref" in proc.stderr, proc.stderr)
    check("unknown ref is not reported as an empty diff", "No changes detected" not in proc.stderr, proc.stderr)
    check("agy is not launched for an unknown ref", prompt == "")
    check("no result trio is written", not list(result_dir.rglob("*.meta")))
    (tmp / "same").mkdir()
    proc, prompt, _, _ = run(tmp / "same", stdout="LGTM\n", base=BRANCH)
    check("empty diff exits 0", proc.returncode == 0, proc.stderr)
    check("empty diff is reported as such", "No changes detected" in proc.stderr, proc.stderr)
    check("agy is not launched for an empty diff", prompt == "")


def case_failing_diff_is_an_error_not_an_empty_diff(tmp):
    print("\ncase: a diff that cannot be computed fails instead of skipping as empty")
    repo = make_repo(tmp)
    tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "main^{tree}"], check=True, capture_output=True, text=True
    ).stdout.strip()
    obj = repo / ".git" / "objects" / tree[:2] / tree[2:]
    check("main's tree is a loose object the case can remove", obj.exists(), str(obj))
    obj.chmod(0o600)
    obj.unlink()
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "agy"
    stub.write_text(STUB)
    stub.chmod(0o755)
    capture = tmp / "prompt.txt"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "AGY_REVIEW_RESULT_DIR": str(tmp / "results"),
        "AGY_STUB_CAPTURE": str(capture),
        "AGY_STUB_RESULTS": str(tmp / "results"),
        "AGY_STUB_PENDING_SNAPSHOT": str(tmp / "snap"),
        "AGY_STUB_STDOUT": "LGTM\n",
        "AGY_STUB_EXIT": "0",
    }
    proc = subprocess.run(["bash", str(SCRIPT), "main"], capture_output=True, text=True, cwd=repo, env=env, timeout=60)
    check("failing diff exits non-zero", proc.returncode != 0, proc.stdout + proc.stderr)
    check("failing diff is not reported as an empty diff", "No changes detected" not in proc.stderr, proc.stderr)
    check("failing diff names the ref", "main" in proc.stderr, proc.stderr)
    check("agy is not launched", not capture.exists())


def case_prompt_is_read_only(tmp):
    print("\ncase: the prompt scopes agy to a read-only review")
    proc, prompt, _, _ = run(tmp, stdout="LGTM\n")
    check("script exits 0", proc.returncode == 0, proc.stderr)
    check("prompt forbids running tests", "Do NOT run tests" in prompt, prompt[:300])
    check("prompt forbids background commands", "in the background" in prompt, prompt[:300])


def case_repo_guidance_and_pre_existing(tmp):
    print("\ncase: repository guidance and advisory severity")
    guidance = "Require file:line evidence for migration bugs."
    proc, prompt, _, _ = run(tmp, stdout="LGTM\n", review_guidance=guidance)
    check("script exits 0", proc.returncode == 0, proc.stderr)
    check("guidance appended once", prompt.count(guidance) == 1)
    check("working copy is excluded", "Private working copy should stay local." not in prompt)
    check("pre-existing bugs are advisory", "[pre_existing] Advisory" in prompt)
    check("only P0/P1 affect the verdict", "LGTM\" if no P0/P1 issues" in prompt)


def case_ok_run_persists_review(tmp):
    print("\ncase: a finished run leaves review + meta, and pending existed while it ran")
    proc, _, pending, result_dir = run(tmp, stdout="[P1] Fix x\nOverall verdict: LGTM\n")
    m = meta(result_dir)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp / "repo", text=True).strip()
    review_paths = list(result_dir.glob(f"{head}/run.*/review.txt"))
    review = review_paths[0] if review_paths else result_dir / "missing.txt"
    check("script exits 0", proc.returncode == 0, proc.stderr)
    check("stdout still carries the review", "[P1] Fix x" in proc.stdout, proc.stdout)
    check("pending existed during the run", f"branch={BRANCH}" in pending, pending)
    check("pending removed after the run", not list(result_dir.rglob("*.pending")))
    check("meta status=ok", m.get("status") == "ok", str(m))
    check("meta carries branch and base", m.get("branch") == BRANCH and m.get("base") == "main", str(m))
    check("meta carries the full reviewed head", m.get("head_sha") == head, str(m))
    check("meta names the review file", m.get("review_file") == str(review), str(m))
    check("review file holds the text", review.exists() and "[P1] Fix x" in review.read_text())


def case_failed_run_records_failure(tmp):
    print("\ncase: a non-zero exit with partial output is recorded as failed")
    proc, _, _, result_dir = run(tmp, stdout="partial", exit_code=3)
    m = meta(result_dir)
    check("script exits non-zero", proc.returncode != 0)
    check("meta status=failed", m.get("status") == "failed", str(m))
    check("meta exit_code=3", m.get("exit_code") == "3", str(m))
    check("no review file", not list(result_dir.rglob("*.txt")))


def case_empty_run_records_empty(tmp):
    print("\ncase: empty output is recorded as empty")
    proc, _, _, result_dir = run(tmp, stdout="  \n")
    m = meta(result_dir)
    check("script exits non-zero", proc.returncode != 0)
    check("meta status=empty", m.get("status") == "empty", str(m))
    check("meta review_file is blank", m.get("review_file") == "", str(m))


def case_legacy_trio_is_not_reused(tmp):
    print("\ncase: a previous branch-keyed result is not reused")
    result_dir = tmp / "results"
    result_dir.mkdir()
    (result_dir / f"{KEY}.review.txt").write_text("OLD REVIEW\n")
    (result_dir / f"{KEY}.meta").write_text("status=ok\n")
    run(tmp, stdout="  \n")
    check("meta is this run's (empty), not the stale ok", meta(result_dir).get("status") == "empty")
    check("the new invocation has no review text", not list(result_dir.glob("*/run.*/review.txt")))
    check("the legacy artifact is preserved", (result_dir / f"{KEY}.review.txt").read_text() == "OLD REVIEW\n")


def case_every_run_appends_timing(tmp):
    print("\ncase: every finished run appends one timings.log line sized against the reviewed HEAD")
    for stdout, code, status in (("LGTM\n", 0, "ok"), ("partial", 3, "failed"), ("  \n", 0, "empty")):
        sub = tmp / status
        sub.mkdir()
        _, _, _, result_dir = run(sub, stdout=stdout, exit_code=code)
        log = result_dir / "timings.log"
        lines = log.read_text().splitlines() if log.exists() else []
        check(f"{status}: exactly one line", len(lines) == 1, str(lines))
        line = lines[0] if lines else ""
        check(f"{status}: status recorded", f" status={status} " in line, line)
        check(f"{status}: elapsed recorded", re.search(r" elapsed=\d+s ", line) is not None, line)
        check(f"{status}: one-file fixture sized", " files=1 lines=1 " in line, line)
        check(f"{status}: raw branch recorded", line.endswith(f" branch={BRANCH}"), line)


def check_overlapping_runs(tmp, *, resync):
    print(f"\ncase: an older run finishes while a newer run is pending (resync={resync})")
    repo = make_repo(tmp)
    old_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    stub = tmp / "agy"
    stub.write_text("""#!/usr/bin/env bash
printf '%s\n' "$*" >"$AGY_STUB_READY"
while [ ! -f "$AGY_STUB_RELEASE" ]; do
  sleep 0.02
done
printf '%s\n' "$AGY_STUB_STDOUT"
""")
    stub.chmod(0o755)
    results = tmp / "results"
    env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ['PATH']}",
           "AGY_REVIEW_RESULT_DIR": str(results)}
    runs = []

    def start(label):
        ready = tmp / f"{label}.ready"
        release = tmp / f"{label}.release"
        proc = subprocess.Popen(
            ["bash", str(SCRIPT), "main"], cwd=repo,
            env={**env, "AGY_STUB_READY": str(ready), "AGY_STUB_RELEASE": str(release),
                 "AGY_STUB_STDOUT": f"{label} review"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        runs.append((proc, release))
        deadline = time.monotonic() + 10
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not ready.exists():
            raise RuntimeError(f"{label} agy invocation did not start")
        return proc, release

    def finish(run):
        proc, release = run
        release.touch()
        _, stderr = proc.communicate(timeout=10)
        check("review exits 0", proc.returncode == 0, stderr)

    def records(pattern):
        return [result_metadata(path) for path in results.rglob(pattern)]

    try:
        old = start("old")
        if resync:
            (repo / "b.txt").write_text("new\n")
            git(repo, "add", "b.txt")
            git(repo, "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "resync")
        new_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        new = start("new")
        base = subprocess.check_output(["git", "rev-parse", "main"], cwd=repo, text=True).strip()
        check("the older prompt pins both revisions",
              f"{base}...{old_head}" in (tmp / "old.ready").read_text())
        check("the newer prompt pins both revisions",
              f"{base}...{new_head}" in (tmp / "new.ready").read_text())
        finish(old)
        published = records("*.meta")
        pending = records("*.pending")
        check("only the older head has published while the newer run is pending",
              [record.get("head_sha") for record in published] == [old_head], str(published))
        check("the newer run's pending marker survives",
              [record.get("head_sha") for record in pending] == [new_head], str(pending))
        finish(new)
        actual = {(record.get("head_sha"), Path(record["review_file"]).read_text().strip())
                  for record in records("*.meta") if record.get("review_file")}
        check("both review texts match their own heads",
              actual == {(old_head, "old review"), (new_head, "new review")}, str(actual))
        check("all completed runs retired their pending markers", not records("*.pending"))
    finally:
        for proc, release in runs:
            if proc.poll() is None:
                release.touch()
                proc.communicate(timeout=10)


def case_overlapping_runs_keep_their_own_sidecars(tmp):
    for name, resync in (("same-head", False), ("resync", True)):
        case_dir = tmp / name
        case_dir.mkdir()
        check_overlapping_runs(case_dir, resync=resync)

def main():
    if os.name == "nt":
        print("POSIX-only (the agy stub uses a shebang) — skipped on Windows")
        return 0
    if not SCRIPT.exists():
        print(f"missing script under test: {SCRIPT}", file=sys.stderr)
        return 1
    cases = (
        case_script_parses,
        case_base_ref_is_distinguished_from_empty_diff,
        case_failing_diff_is_an_error_not_an_empty_diff,
        case_prompt_is_read_only,
        case_repo_guidance_and_pre_existing,
        case_ok_run_persists_review,
        case_failed_run_records_failure,
        case_empty_run_records_empty,
        case_legacy_trio_is_not_reused,
        case_every_run_appends_timing,
        case_overlapping_runs_keep_their_own_sidecars,
    )
    for case in cases:
        with tempfile.TemporaryDirectory() as raw:
            case(Path(raw))
    failed = _results.count(False)
    print(f"\n{len(_results) - failed}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
