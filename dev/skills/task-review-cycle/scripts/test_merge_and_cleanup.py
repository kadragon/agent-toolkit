#!/usr/bin/env python3
"""Regression tests for merge-and-cleanup.sh -- local branch cleanup reporting.

`hub.sh merge` runs `gh pr merge --delete-branch`, which already deletes the local feature
branch when gh can switch off it. The script's own `git branch -D` then failed and reported
"WARNING: Could not delete local branch", so a clean merge (PR #279) read as a cleanup failure.
These cases pin the three outcomes: already deleted by the merge, deleted by the script, and a
real failure that must still warn.

The real hub.sh is replaced by a stub next to a copy of the script, so no network is touched.

Run: python3 dev/skills/task-review-cycle/scripts/test_merge_and_cleanup.py
Exits 0 on success, 1 on the first failure.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "merge-and-cleanup.sh"
FEATURE = "feat/x"

# Stub hub.sh: report a successful merge; with DELETE_LOCAL=1, delete the local branch the way
# `gh pr merge --delete-branch` does (switch to base, then delete).
HUB_STUB = """#!/usr/bin/env bash
if [ "${DELETE_LOCAL:-0}" = "1" ]; then
  git checkout -q main && git branch -D -q "$FEATURE_BRANCH_UNDER_TEST"
fi
echo '{"merge_ok": true, "merge_output": "stub"}'
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def make_repo(tmp):
    repo = Path(tempfile.mkdtemp(dir=tmp))
    git(repo, "init", "-q", "-b", "main", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "a.md").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "[TEST] init")
    git(repo, "checkout", "-q", "-b", FEATURE)
    return repo


def make_script_dir(tmp):
    d = Path(tempfile.mkdtemp(dir=tmp))
    shutil.copy(SCRIPT, d / "merge-and-cleanup.sh")
    (d / "hub.sh").write_text(HUB_STUB, newline="\n")
    return d


def run(repo, script_dir, delete_local):
    env = {**os.environ, "DELETE_LOCAL": "1" if delete_local else "0",
           "FEATURE_BRANCH_UNDER_TEST": FEATURE}
    proc = subprocess.run(
        ["bash", str(script_dir / "merge-and-cleanup.sh"), "1", "main", FEATURE, '{"squash":true}'],
        cwd=repo, env=env, check=False, capture_output=True, text=True,
    )
    return proc, json.loads(proc.stdout)


def branch_exists(repo):
    return subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{FEATURE}"], cwd=repo
    ).returncode == 0


def fail(case, detail):
    print(f"FAIL {case}: {detail}")
    sys.exit(1)


def case_already_deleted_by_merge(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    _, out = run(repo, d, delete_local=True)
    msg = out["cleanup_message"]
    if "WARNING" in msg or "already deleted" not in msg:
        fail("already_deleted_by_merge", f"expected an 'already deleted' note, got {msg!r}")
    print("ok already_deleted_by_merge")


def case_deleted_by_script(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    _, out = run(repo, d, delete_local=False)
    msg = out["cleanup_message"]
    if msg != f"Local branch '{FEATURE}' deleted" or branch_exists(repo):
        fail("deleted_by_script", f"got {msg!r}, branch exists={branch_exists(repo)}")
    print("ok deleted_by_script")


def case_real_failure_still_warns(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # A branch checked out in another worktree cannot be deleted -- a genuine cleanup failure.
    git(repo, "checkout", "-q", "main")
    other = Path(tempfile.mkdtemp(dir=tmp)) / "wt"
    git(repo, "worktree", "add", "-q", str(other), FEATURE)
    _, out = run(repo, d, delete_local=False)
    msg = out["cleanup_message"]
    if not msg.startswith("WARNING") or not branch_exists(repo):
        fail("real_failure_still_warns", f"got {msg!r}")
    print("ok real_failure_still_warns")


def main():
    tmp = tempfile.mkdtemp(prefix="merge-cleanup-")
    try:
        case_already_deleted_by_merge(tmp)
        case_deleted_by_script(tmp)
        case_real_failure_still_warns(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
