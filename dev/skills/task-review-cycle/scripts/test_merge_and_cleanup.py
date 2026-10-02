#!/usr/bin/env python3
"""Regression tests for merge-and-cleanup.sh -- local branch and worktree cleanup.

The script is the single owner of local cleanup: `hub.sh merge` merges and deletes the
remote head only, on both GitHub and Forgejo. These cases pin the outcomes: deleted by
the script, a branch that never existed, a real failure (both must warn), a worktree
holding the feature branch (removed first, so the branch delete succeeds), and a base
checkout that fails after the remote merge (JSON still printed, cleanup skipped).

The real hub.sh is replaced by a stub next to a copy of the script, so no network is touched.

Run: python3 dev/skills/task-review-cycle/scripts/test_merge_and_cleanup.py
Exits 0 on success, 1 on the first failure.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "merge-and-cleanup.sh"
HUB = Path(__file__).resolve().parent / "hub.sh"
FEATURE = "feat/x"

# Stub hub.sh: report a successful merge and leave every local ref alone, as the real one does.
HUB_STUB = """#!/usr/bin/env bash
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


def run(case, repo, script_dir, branch=FEATURE, base="main", worktree=None):
    args = ["bash", str(script_dir / "merge-and-cleanup.sh"), "1", base, branch, '{"squash":true}']
    if worktree:
        args.append(str(worktree))
    proc = subprocess.run(args, cwd=repo, check=False, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        fail(case, f"script exit {proc.returncode}, stderr: {proc.stderr.strip()!r}")
    out = json.loads(proc.stdout)
    if out["merge_ok"] is not True:
        fail(case, f"stub merge should report merge_ok true, got {out!r}")
    return out


def branch_exists(repo):
    return subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{FEATURE}"], cwd=repo
    ).returncode == 0


def fail(case, detail):
    print(f"FAIL {case}: {detail}")
    sys.exit(1)


def case_hub_never_deletes_local(_tmp):
    # Two owners raced for the local branch (PR #280): gh's --delete-branch deleted it on GitHub,
    # the Forgejo path never did. Local cleanup now has one owner -- this script.
    code = [ln for ln in HUB.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
    if any("--delete-branch" in ln for ln in code):
        fail("hub_never_deletes_local", "hub.sh still passes --delete-branch to gh pr merge")
    print("ok hub_never_deletes_local")


def case_deleted_by_script(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    out = run("deleted_by_script", repo, d)
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
    out = run("real_failure_still_warns", repo, d)
    msg = out["cleanup_message"]
    if not msg.startswith("WARNING") or not branch_exists(repo):
        fail("real_failure_still_warns", f"got {msg!r}")
    git(repo, "worktree", "remove", "--force", str(other))
    print("ok real_failure_still_warns")


def case_unknown_branch_warns(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # A mistyped name never existed locally; its absence after the merge is not a success.
    out = run("unknown_branch_warns", repo, d, branch="feat/typo")
    msg = out["cleanup_message"]
    if not msg.startswith("WARNING") or "not found" not in msg:
        fail("unknown_branch_warns", f"got {msg!r}")
    print("ok unknown_branch_warns")


def case_worktree_holding_branch(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # The worktree passed for removal holds the feature branch; deleting the branch first
    # always failed ("checked out at ..."), leaving it behind with a WARNING.
    git(repo, "checkout", "-q", "main")
    wt = Path(tempfile.mkdtemp(dir=tmp)) / "wt"
    git(repo, "worktree", "add", "-q", str(wt), FEATURE)
    out = run("worktree_holding_branch", repo, d, worktree=wt)
    msg, wmsg = out["cleanup_message"], out["worktree_message"]
    if "WARNING" in msg or "WARNING" in wmsg or branch_exists(repo) or wt.exists():
        fail("worktree_holding_branch", f"got cleanup={msg!r} worktree={wmsg!r}")
    print("ok worktree_holding_branch")


def case_base_checkout_fails(tmp):
    repo, d = make_repo(tmp), make_script_dir(tmp)
    # The remote merge already landed; a failed local checkout must not swallow the result JSON.
    out = run("base_checkout_fails", repo, d, base="no-such-base")
    msg = out["cleanup_message"]
    if not msg.startswith("WARNING") or "no-such-base" not in msg or not branch_exists(repo):
        fail("base_checkout_fails", f"got {msg!r}")
    print("ok base_checkout_fails")


def _force_remove(func, path, _exc):
    # git writes read-only object files; Windows refuses to delete them until they are writable.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main():
    tmp = tempfile.mkdtemp(prefix="merge-cleanup-")
    try:
        case_hub_never_deletes_local(tmp)
        case_deleted_by_script(tmp)
        case_real_failure_still_warns(tmp)
        case_unknown_branch_warns(tmp)
        case_worktree_holding_branch(tmp)
        case_base_checkout_fails(tmp)
    finally:
        shutil.rmtree(tmp, onerror=_force_remove)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
