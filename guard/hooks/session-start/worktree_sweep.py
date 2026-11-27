"""Remove idle task worktrees whose exact head was merged into the GitHub default branch."""

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def run(args, repo, timeout=5):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False)


def git(repo, *args):
    result = run(["git", *args], repo)
    return result.stdout.rstrip("\n") if not result.returncode else None


def beneath(path, root):
    return path == root or root in path.parents


def linux_holder(root):
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            for link in [proc / "cwd", *(proc / "fd").iterdir()]:
                try:
                    if beneath(Path(os.readlink(link)), root):
                        name = (proc / "comm").read_text().strip()
                        return f"{name} (PID {proc.name}) holds {link.name} under {root}"
                except (OSError, UnicodeError):
                    continue
        except OSError:
            continue
    return None


def windows_holder(root):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_path = kernel.CreateFileW
    open_path.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_path.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid = ctypes.c_void_p(-1).value

    # A cwd or file opened without FILE_SHARE_DELETE prevents Windows from removing it.
    # Probe the same access Git needs without changing the checkout.
    for path in [root, *root.rglob("*")]:
        handle = open_path(str(path), 0x10000, 7, None, 3, 0x02200000, None)
        if handle == invalid:
            error = ctypes.get_last_error()
            if error not in {2, 3}:
                return f"Windows denied delete access to {path} (error {error})"
        else:
            kernel.CloseHandle(handle)
    return None


def holder(root):
    try:
        root = root.resolve(strict=True)
        if sys.platform == "linux":
            return linux_holder(root)
        if os.name == "nt":
            return windows_holder(root)
        result = run(["lsof", "-Fpcn", "+D", str(root)], root.parent)
        fields = result.stdout.splitlines()
        if fields and fields[0].startswith("p"):
            name = next((line[1:] for line in fields if line.startswith("c")), "process")
            return f"{name} (PID {fields[0][1:]}) holds a path under {root}"
        if result.returncode == 1 and not result.stderr:
            return None  # lsof's status for a readable directory with zero matches
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not check process use: {exc}"
    return f"could not check process use under {root}"


def merged_pr(main, slug, branch, head, base, timeout):
    result = run(["gh", "pr", "list", "--repo", slug, "--state", "all", "--head", branch,
                  "--json", "number,state,isCrossRepository,headRefName,headRefOid,baseRefName"],
                 main, timeout=timeout)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "gh pr list failed")
    prs = [pr for pr in json.loads(result.stdout) if pr["headRefName"] == branch and pr["isCrossRepository"] is False]
    if any(pr["state"] == "OPEN" for pr in prs):
        return None
    return next((pr["number"] for pr in prs if pr["state"] == "MERGED"
                 and (pr["headRefOid"], pr["baseRefName"]) == (head, base)), None)


def clean(path, *, include_ignored=False):
    args = ["status", "--porcelain", "--untracked-files=all"]
    if include_ignored:
        args.append("--ignored=matching")
    return git(path, *args) == ""


def warn_main(main, base):
    branch = git(main, "branch", "--show-current")
    if not branch or branch == base:
        return
    ref = f"refs/heads/{branch}"
    upstream = git(main, "for-each-ref", "--format=%(upstream)", ref)
    if upstream and git(main, "show-ref", "--verify", upstream) is None and clean(main):
        print(f"Worktree sweep: main checkout is clean on {branch}, whose upstream {upstream} is gone."
              f" Switch back with git -C \"{main}\" switch {base} when ready.", file=sys.stderr)


def sweep(repo):
    inventory = git(repo, "worktree", "list", "--porcelain", "-z")
    if not inventory:
        return
    worktrees = [dict(field.partition(" ")[::2] for field in entry.split("\0"))
                 for entry in inventory.split("\0\0") if entry]
    main = Path(worktrees[0]["worktree"]).resolve()
    base = git(main, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD") or ""
    if not base.startswith("refs/remotes/origin/"):
        return
    base = base.removeprefix("refs/remotes/origin/")
    warn_main(main, base)
    origin = git(main, "remote", "get-url", "origin") or ""
    remote = re.fullmatch(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                          r"([\w.-]+/[\w.-]+?)(?:\.git)?/?", origin)
    if not remote:
        return

    deadline = time.monotonic() + 8
    reserved = main / ".worktrees"
    for tree in worktrees[1:]:
        path = Path(tree["worktree"])
        if not path.is_dir() or path.resolve().parent != reserved or path.is_symlink() or "locked" in tree:
            continue
        ref = tree.get("branch", "")
        head = tree.get("HEAD", "")
        if not ref.startswith("refs/heads/") or not head or not clean(path, include_ignored=True):
            continue
        time_left = deadline - time.monotonic()
        if time_left <= 0:
            return
        branch = ref.removeprefix("refs/heads/")
        try:
            pr = merged_pr(main, remote[1], branch, head, base, time_left)
        except (KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as exc:
            print(f"Worktree sweep: could not verify merged PR for {branch}: {exc}", file=sys.stderr)
            return
        if pr is None:
            continue
        busy = holder(path)
        if busy:
            print(f"Worktree sweep: kept {path}: {busy}", file=sys.stderr)
            continue
        if git(path, "symbolic-ref", "--quiet", "HEAD") != ref or git(path, "rev-parse", "HEAD") != head:
            continue
        if not clean(path, include_ignored=True):
            continue
        result = run(["git", "worktree", "remove", "--", str(path)], main)
        if result.returncode:
            print(f"Worktree sweep: kept {path}: {result.stderr.strip()}", file=sys.stderr)
            continue
        # Squash merges do not make the original PR head an ancestor of the base.
        # branch -D still refuses to delete a branch checked out in another worktree.
        if git(main, "rev-parse", "--verify", ref) == head:
            result = run(["git", "branch", "-D", "--", branch], main)
            if result.returncode:
                print(f"Worktree sweep: removed {path} but kept {branch}: {result.stderr.strip()}", file=sys.stderr)
                continue
        print(f"Worktree sweep: removed {path} (merged PR #{pr}).", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--holder", action="store_true", help="Report process use for one directory")
    args = parser.parse_args()
    if args.holder:
        busy = holder(args.repo)
        if busy:
            print(busy)
    else:
        try:
            sweep(args.repo)
        except (KeyError, OSError, subprocess.SubprocessError) as exc:
            print(f"Worktree sweep: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
