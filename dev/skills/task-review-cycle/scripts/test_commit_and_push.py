#!/usr/bin/env python3
"""Regression tests for commit-and-push.sh -- pathspec handling and commit-guard.

Pathspec: a path the cycle DELETED must not blow up the stage step. task-next's
pre-merge cleanup deletes tasks.md whenever it empties, changed-files.sh reports
the deleted path, and `git add` treats a pathspec matching neither the worktree
nor the index as fatal -- aborting the whole batch, not just that one path.

commit-guard: the script runs `git commit` internally, so the PreToolUse(Bash)
hook never saw it (the Bash tool only saw `bash <script>`) and BOTH shipped
guards were inert on the repo's primary commit path. The script now calls
guard.py's --precommit-check mode directly; these cases pin that it fires, that
the allow-main marker still opts out, and that a missing guard fails open loudly.

Run: python3 dev/skills/task-review-cycle/scripts/test_commit_and_push.py
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
    # `git init` lands on main or master depending on init.defaultBranch, and
    # commit-and-push.sh now runs commit-guard's branch guard -- which blocks
    # exactly those two. Move to a feature branch so the fixture reflects real
    # usage; the protected-branch behavior gets its own cases below.
    git(repo, "checkout", "-q", "-b", "feature/test")
    return repo


def run_script(repo, files, message="[TEST] cycle"):
    """Invoke commit-and-push.sh in --no-push mode; return (proc, parsed_json)."""
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--message", message, "--files", files, "--no-push"],
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
    """A genuinely unknown path must still abort -- only staged deletions are excused.

    Dropping every unmatched pathspec would turn a typo in an agent-built --files
    list into a quietly incomplete commit that goes on to review and merge.
    """
    repo = make_repo(tmp)
    (repo / "keep.md").write_text("keep\nmore\n")

    proc, _ = run_script(repo, "keep.md never-existed.md")
    if proc.returncode == 0:
        fail("unknown path in --files", "expected a non-zero exit, got 0 (path silently dropped)")
    if "did not match any files" not in proc.stderr:
        fail("unknown path in --files", f"expected git's pathspec fatal, got {proc.stderr.strip()!r}")
    print("OK: a genuinely unknown pathspec still aborts (only staged deletions are excused)")


def case_unknown_path_with_staged_deletion(tmp):
    """The two cases must be told apart even when they appear in the same list."""
    repo = make_repo(tmp)
    git(repo, "rm", "-q", "tasks.md")

    proc, _ = run_script(repo, "tasks.md never-existed.md")
    if proc.returncode == 0:
        fail("unknown path alongside staged deletion", "expected a non-zero exit, got 0")
    if "did not match any files" not in proc.stderr:
        fail(
            "unknown path alongside staged deletion",
            f"expected git's pathspec fatal, got {proc.stderr.strip()!r}",
        )
    print("OK: an unknown path still aborts even when a staged deletion is excused alongside it")


def head(repo):
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def case_guard_bad_type(tmp):
    """A message failing the [TYPE] contract must be refused before any commit.

    The regression this covers: commit-and-push.sh runs `git commit` inside the
    script, so the PreToolUse hook never saw it and the type guard was inert on
    the repo's primary commit path.
    """
    repo = make_repo(tmp)
    (repo / "keep.md").write_text("keep\nmore\n")
    before = head(repo)

    proc, _ = run_script(repo, "keep.md", message="wip")
    if proc.returncode == 0:
        fail("bad [TYPE] message", "expected a non-zero exit, got 0 (guard did not fire)")
    if "commit blocked by commit-guard" not in proc.stderr:
        fail("bad [TYPE] message", f"expected the guard's reason, got {proc.stderr.strip()!r}")
    if head(repo) != before:
        fail("bad [TYPE] message", "a commit was created despite the guard rejection")
    print("OK: a bad [TYPE] message is refused inside the script, with no commit created")


def case_guard_protected_branch(tmp):
    """A commit on main without the allow-main marker must be refused."""
    repo = make_repo(tmp)
    git(repo, "checkout", "-q", "-B", "main")
    (repo / "keep.md").write_text("keep\nmore\n")
    before = head(repo)

    proc, _ = run_script(repo, "keep.md")
    if proc.returncode == 0:
        fail("protected branch", "expected a non-zero exit, got 0 (branch guard did not fire)")
    if "is protected" not in proc.stderr:
        fail("protected branch", f"expected the branch-guard reason, got {proc.stderr.strip()!r}")
    if head(repo) != before:
        fail("protected branch", "a commit was created on main despite the guard rejection")
    print("OK: a commit on main is refused inside the script, with no commit created")


def case_guard_allow_main_marker(tmp):
    """The documented opt-in marker still unblocks main -- the guard is not a wall."""
    repo = make_repo(tmp)
    git(repo, "checkout", "-q", "-B", "main")
    (repo / "AGENTS.md").write_text("# repo\n\n<!-- commit-guard: allow-main -->\n")
    (repo / "keep.md").write_text("keep\nmore\n")

    proc, payload = run_script(repo, "keep.md AGENTS.md")
    if proc.returncode != 0:
        fail("allow-main marker", f"exit {proc.returncode}: {proc.stderr.strip()}")
    if not payload or payload.get("committed") is not True:
        fail("allow-main marker", f"expected committed=true, got {proc.stdout!r}")
    print("OK: the allow-main marker still permits a commit on main")


def case_guard_missing(tmp):
    """A missing guard.py fails OPEN but never silently: guard_skipped=true + a warning.

    Staged into a bare directory tree so the script's
    `$SCRIPT_DIR/../../../hooks/commit-guard/guard.py` resolves to nothing.
    """
    stand_in = Path(tmp) / "standin" / "skills" / "task-review-cycle" / "scripts"
    stand_in.mkdir(parents=True)
    shutil.copy(SCRIPT, stand_in / SCRIPT.name)

    repo = make_repo(tmp)
    (repo / "keep.md").write_text("keep\nmore\n")

    proc = subprocess.run(
        ["bash", str(stand_in / SCRIPT.name),
         "--message", "wip", "--files", "keep.md", "--no-push"],
        cwd=repo, check=False, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        fail("missing guard", f"expected fail-open, got exit {proc.returncode}: {proc.stderr.strip()}")
    payload = json.loads(proc.stdout)
    if payload.get("guard_skipped") is not True:
        fail("missing guard", f"expected guard_skipped=true, got {proc.stdout!r}")
    if "committing UNCHECKED" not in proc.stderr:
        fail("missing guard", f"expected a stderr warning, got {proc.stderr.strip()!r}")
    print("OK: a missing guard fails open with guard_skipped=true and a stderr warning")


def case_guard_reject_leaves_index_clean(tmp):
    """A rejection must not mutate the index -- the guard runs before `git add`.

    It reads only the branch and the message, so staging first would leave the
    caller's index changed by a call that did nothing else.
    """
    repo = make_repo(tmp)
    (repo / "keep.md").write_text("keep\nmore\n")
    before = git(repo, "diff", "--cached", "--name-only").stdout

    proc, _ = run_script(repo, "keep.md", message="wip")
    if proc.returncode == 0:
        fail("reject leaves index clean", "expected a non-zero exit, got 0")
    after = git(repo, "diff", "--cached", "--name-only").stdout
    if after != before:
        fail("reject leaves index clean", f"index changed: {before!r} -> {after!r}")
    print("OK: a rejected commit leaves the index exactly as it was")


def case_guard_python_fallback(tmp):
    """Windows installs often ship only `python`, not `python3`.

    dev/hooks.json's own commit-guard entry uses `commandWindows: python ...`,
    so hardcoding python3 here would silently disable BOTH guards on those
    installs while still reporting a clean commit. Simulate it with a PATH that
    exposes `python` but no `python3`.
    """
    real_python = shutil.which("python3") or shutil.which("python")
    # `bash` must be in the shim too: PATH is replaced wholesale, so the
    # interpreter that runs the script has to be reachable through it.
    needed = ["bash", "git", "jq", "sed", "tr", "dirname", "awk"]
    found = {t: shutil.which(t) for t in needed}
    missing = [t for t, p in found.items() if not p]
    if not real_python or missing:
        print(f"SKIP: python fallback case (missing on PATH: {missing or 'python'})")
        return
    resolved = {t: str(p) for t, p in found.items() if p}

    shim = Path(tmp) / "shimbin"
    shim.mkdir(exist_ok=True)
    for tool, path in resolved.items():
        target = shim / tool
        if not target.exists():
            target.symlink_to(path)
    py_shim = shim / "python"
    if not py_shim.exists():
        py_shim.symlink_to(real_python)
    if (shim / "python3").exists():
        fail("python fallback", "shim dir must not expose python3")

    repo = make_repo(tmp)
    (repo / "keep.md").write_text("keep\nmore\n")

    proc = subprocess.run(
        [resolved["bash"], str(SCRIPT), "--message", "wip", "--files", "keep.md", "--no-push"],
        cwd=repo, check=False, capture_output=True, text=True,
        env={"PATH": str(shim), "HOME": str(repo)},
    )
    if proc.returncode == 0:
        fail("python fallback", "guard did not fire with only `python` on PATH (exit 0)")
    if "commit blocked by commit-guard" not in proc.stderr:
        fail("python fallback", f"expected a guard rejection, got {proc.stderr.strip()!r}")
    print("OK: the guard still runs when only `python` (no python3) is on PATH")


def case_guard_skipped_false_normally(tmp):
    """guard_skipped must be false on the normal path, or the flag means nothing."""
    repo = make_repo(tmp)
    (repo / "keep.md").write_text("keep\nmore\n")

    _, payload = run_script(repo, "keep.md")
    if not payload or payload.get("guard_skipped") is not False:
        fail("guard_skipped on the normal path", f"expected false, got {payload!r}")
    print("OK: guard_skipped is false when the guard actually ran")


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
        case_unknown_path_with_staged_deletion(tmp)
        case_guard_bad_type(tmp)
        case_guard_protected_branch(tmp)
        case_guard_allow_main_marker(tmp)
        case_guard_missing(tmp)
        case_guard_reject_leaves_index_clean(tmp)
        case_guard_python_fallback(tmp)
        case_guard_skipped_false_normally(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("OK: all commit-and-push.sh pathspec and commit-guard cases pass.")


if __name__ == "__main__":
    main()
