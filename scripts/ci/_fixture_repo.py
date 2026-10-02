"""
Throwaway git repos for the scripts/ci tests that need real commits and an `origin/main` ref.

`git()` neutralizes `core.hooksPath` and signing and sets an identity, so neither a global
hooks directory nor `commit.gpgsign=true` reaches the fixture (`--no-verify` does not cover
signing). `make_repo_with_base()` commits `base_files`, points `refs/remotes/origin/main` at
that commit, then applies `head_files` (a `None` value deletes the path) and commits again,
so `git diff origin/main...HEAD` reports exactly the intended change set.

Imported by the tests in this directory; running one as `python3 scripts/ci/test_*.py`
puts this directory on `sys.path`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            *args,
        ],
        cwd=root,
        check=True,
    )


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo_with_base(
    root: Path, base_files: dict, head_files: dict, message: str = "head"
) -> Path:
    git(root, "init", "-q")
    for rel, content in base_files.items():
        _write(root, rel, content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    for rel, content in head_files.items():
        if content is None:
            (root / rel).unlink()
        else:
            _write(root, rel, content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", message)
    return root
