#!/usr/bin/env python3
"""Regression tests for commit-and-push.sh pathspec handling.

Focus: a path the cycle DELETED must not blow up the stage step. task-next's
pre-merge cleanup deletes tasks.md whenever it empties, changed-files.sh reports
the deleted path, and `git add` treats a pathspec matching neither the worktree
nor the index as fatal -- aborting the whole batch, not just that one path.

Run: python3 dev/skills/task-review/scripts/test_commit_and_push.py
Exits 0 on success, 1 on the first failure.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "commit-and-push.sh"


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def make_repo(tmp):
    """A throwaway repo with tasks.md + keep.md committed."""
    repo = Path(tempfile.mkdtemp(dir=tmp))
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    # The developer's own hooks (this repo ships a commit-guard) must not leak in.
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "tasks.md").write_text("findings\n")
    (repo / "keep.md").write_text("keep\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "[TEST] init")
    return repo


def run_script(repo, files):
    """Invoke commit-and-push.sh in --no-push mode; return (proc, parsed_json)."""
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--message", "[TEST] cycle", "--files", files, "--no-push"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = None
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None
    return proc, payload


def name_status(repo):
    """`status\tpath` lines of the HEAD commit."""
    out = git(repo, "show", "--name-status", "--format=", "HEAD").stdout
    return sorted(line for line in out.splitlines() if line.strip())


def fail(case, detail):
    print(f"FAIL: {case}\n  {detail}")
    sys.exit(1)


def case_staged_deletion(tmp):
    """The reported bug: deletion already staged, path still in the --files list."""
    repo = make_repo(tmp)
    git(repo, "rm", "-q", "tasks.md")
    (repo / "keep.md").write_text("keep\nmore\n")

    proc, payload = run_script(repo, "keep.md tasks.md")
    if proc.returncode != 0:
        fail("staged deletion in --files", f"exit {proc.returncode}: {proc.stderr.strip()}")
    if not payload or payload.get("committed") is not True:
        fail("staged deletion in --files", f"expected committed=true, got {proc.stdout!r}")
    got = name_status(repo)
    if got != ["D\ttasks.md", "M\tkeep.md"]:
        fail("staged deletion in --files", f"commit contents {got}")
    print("OK: staged deletion no longer aborts the stage step (sibling edit still committed)")


def case_deletion_only(tmp):
    """A cycle whose ONLY change is an already-staged deletion must still commit."""
    repo = make_repo(tmp)
    git(repo, "rm", "-q", "tasks.md")

    proc, payload = run_script(repo, "tasks.md")
    if proc.returncode != 0:
        fail("deletion-only stage list", f"exit {proc.returncode}: {proc.stderr.strip()}")
    if not payload or payload.get("committed") is not True:
        fail("deletion-only stage list", f"expected committed=true, got {proc.stdout!r}")
    if name_status(repo) != ["D\ttasks.md"]:
        fail("deletion-only stage list", f"commit contents {name_status(repo)}")
    print("OK: deletion-only stage list still produces a commit")


def case_unstaged_deletion(tmp):
    """Guard: a plain worktree deletion already worked -- it must keep working."""
    repo = make_repo(tmp)
    (repo / "tasks.md").unlink()

    proc, _ = run_script(repo, "tasks.md")
    if proc.returncode != 0:
        fail("unstaged worktree deletion", f"exit {proc.returncode}: {proc.stderr.strip()}")
    if name_status(repo) != ["D\ttasks.md"]:
        fail("unstaged worktree deletion", f"commit contents {name_status(repo)}")
    print("OK: unstaged worktree deletion still stages as a deletion")


def case_unknown_path(tmp):
    """Guard: a path in neither worktree nor index is skipped, not fatal."""
    repo = make_repo(tmp)
    (repo / "keep.md").write_text("keep\nmore\n")

    proc, payload = run_script(repo, "keep.md never-existed.md")
    if proc.returncode != 0:
        fail("unknown path in --files", f"exit {proc.returncode}: {proc.stderr.strip()}")
    if not payload or payload.get("committed") is not True:
        fail("unknown path in --files", f"expected committed=true, got {proc.stdout!r}")
    if name_status(repo) != ["M\tkeep.md"]:
        fail("unknown path in --files", f"commit contents {name_status(repo)}")
    print("OK: unmatched pathspec is skipped without aborting the batch")


def main():
    if not SCRIPT.is_file():
        fail("setup", f"script not found: {SCRIPT}")
    if shutil.which("jq") is None:
        fail("setup", "jq is required by commit-and-push.sh but was not found on PATH")

    tmp = tempfile.mkdtemp(prefix="commit-and-push-test-")
    try:
        case_staged_deletion(tmp)
        case_deletion_only(tmp)
        case_unstaged_deletion(tmp)
        case_unknown_path(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("OK: all commit-and-push.sh pathspec cases pass.")


if __name__ == "__main__":
    main()
