"""Regressions for recovering merged worktrees with real Git and live process holders."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import worktree_sweep as sweep


class WorktreeSweepTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="sweep test ")
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.repo / "no-hooks"))
        (self.repo / ".git/info/exclude").write_text(".worktrees/\n", encoding="utf-8")
        self.git("commit", "--allow-empty", "-qm", "base")
        self.git("remote", "add", "origin", "https://github.com/owner/repo.git")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    def git(self, *args, repo=None):
        return subprocess.check_output(["git", *args], cwd=repo or self.repo, text=True).strip()

    def tree(self, branch):
        path = self.repo / ".worktrees" / f"{branch} checkout"
        self.git("worktree", "add", "-qb", branch, str(path))
        (path / branch).write_text("own change\n", encoding="utf-8")
        self.git("add", branch, repo=path)
        self.git("commit", "-qm", branch, repo=path)
        return path

    def test_sweep_requires_an_exact_merged_pr_and_an_idle_clean_worktree(self):
        merged = self.tree("merged")
        self.git("merge", "--squash", "merged")
        self.git("commit", "-qm", "squash")
        merged_head = self.git("rev-parse", "merged")
        open_tree = self.tree("open")
        dirty = self.tree("dirty")
        (dirty / "untracked").touch()
        ignored = self.tree("ignored")
        with (self.repo / ".git/info/exclude").open("a", encoding="utf-8") as excludes:
            excludes.write("ignored-data\n")
        (ignored / "ignored-data").touch()
        locked = self.tree("locked")
        self.git("worktree", "lock", str(locked))
        advanced = self.tree("advanced")
        held = self.tree("held")
        records = {
            "merged": (merged_head, "MERGED"),
            "open": (self.git("rev-parse", "open"), "OPEN"),
            "advanced": (merged_head, "MERGED"),
            "held": (self.git("rev-parse", "held"), "MERGED"),
        }

        def fake_gh(args, repo, timeout=5):
            if args[0] != "gh":
                return real_run(args, repo, timeout)
            branch = args[args.index("--head") + 1]
            self.assertEqual(args[args.index("--repo") + 1], "owner/repo")
            head, state = records[branch]
            row = {"number": 42, "state": state, "isCrossRepository": False,
                   "headRefName": branch, "headRefOid": head, "baseRefName": "main"}
            return subprocess.CompletedProcess(args, 0, json.dumps([row]), "")

        real_run = sweep.run
        diagnostics = io.StringIO()
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", "print('ready'); import time; time.sleep(90)"],
            cwd=held, stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            with patch.object(sweep, "run", side_effect=fake_gh), redirect_stderr(diagnostics):
                sweep.sweep(self.repo)
            self.assertFalse(merged.exists())
            self.assertNotIn("merged", self.git("branch", "--format=%(refname:short)").splitlines())
            for path in (open_tree, dirty, ignored, locked, advanced, held):
                self.assertTrue(path.exists(), path)
            self.assertIn(str(held), diagnostics.getvalue())
            expected = "Windows denied delete access" if sys.platform == "win32" else f"PID {child.pid}"
            self.assertIn(expected, diagnostics.getvalue())
        finally:
            child.kill()
            child.communicate(timeout=10)

    def test_keeps_supplied_worktree_and_compares_before_deleting_branch(self):
        supplied = self.tree("supplied")
        candidate = self.tree("racing")
        head = self.git("rev-parse", "racing")
        branch = "refs/heads/racing"
        tree = self.git("rev-parse", "racing^{tree}")
        advanced = self.git("commit-tree", tree, "-p", head, "-m", "local advance")
        real_run = sweep.run

        def fake_run(args, repo, timeout=5):
            if args[:3] == ["git", "update-ref", "--no-deref"]:
                self.git("update-ref", branch, advanced, head)
            return real_run(args, repo, timeout)

        def merged_pr(_repo, _slug, picked, _head, _base, _timeout):
            self.assertEqual(picked, "racing", "the caller still needs its own path")
            return 42

        diagnostics = io.StringIO()
        with (patch.object(sweep, "merged_pr", side_effect=merged_pr),
              patch.object(sweep, "run", side_effect=fake_run), redirect_stderr(diagnostics)):
            sweep.sweep(supplied)
        self.assertFalse(candidate.exists())
        self.assertTrue(supplied.exists())
        self.assertEqual(self.git("rev-parse", branch), advanced)
        self.assertIn("kept racing", diagnostics.getvalue())

    def test_reports_gone_upstream_without_switching_the_checkout(self):
        self.git("switch", "-qc", "feature")
        self.git("config", "branch.feature.remote", "origin")
        self.git("config", "branch.feature.merge", "refs/heads/feature")
        diagnostics = io.StringIO()
        with redirect_stderr(diagnostics):
            sweep.sweep(self.repo)
        self.assertIn("is gone", diagnostics.getvalue())
        self.assertIn("switch main", diagnostics.getvalue())
        self.assertEqual(self.git("branch", "--show-current"), "feature")


if __name__ == "__main__":
    unittest.main()
