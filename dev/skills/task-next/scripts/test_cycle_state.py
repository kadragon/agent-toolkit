#!/usr/bin/env python3
"""Exercise recovery using real staged, committed, and isolated Git state."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("cycle_state.py")


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        (self.repo / "code.txt").write_text("base\n")
        self.git("add", ".")
        self.commit()
        self.git("checkout", "-qb", "fix/example")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def commit(self):
        self.git("-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                 "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                 "commit", "--no-verify", "-qm", "fixture")

    def state(self, *args, text=None, cwd=None, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or self.repo,
                                input=text, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        return json.loads(result.stdout) if ok else result.stderr

    def test_staged_and_unstaged_are_candidates_not_completion(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                (self.repo / "code.txt").write_text("partial\n")
                if staged:
                    self.git("add", "code.txt")
                result = self.state("inspect")
                self.assertEqual(result["changes"], "M  code.txt" if staged else " M code.txt")
                self.assertNotIn("stage", result)
                self.assertIsNone(result["contract"])

    def test_bump_and_commit_do_not_prove_completion(self):
        (self.repo / "plugin.json").write_text('{"version":"2.0.0"}')
        self.git("add", ".")
        self.commit()
        result = self.state("inspect")
        self.assertEqual(result["changes"], "")
        self.assertNotIn("stage", result)
        self.assertIsNone(result["contract"])

    def test_untracked_is_visible(self):
        (self.repo / "new.txt").write_text("partial")
        self.assertIn("new.txt", self.state("inspect")["changes"])

    def test_contract_survives_cleanup_and_new_process(self):
        contract = "# Example\n- [ ] complete the feature\n"
        path = self.repo / "tasks.md"
        path.write_text(contract)
        saved = self.state("save", "--file", str(path))
        path.unlink()
        self.assertEqual(self.state("inspect")["contract"], contract)
        self.assertTrue(Path(saved["contract_path"]).is_file())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_branch_contracts_do_not_overwrite(self):
        self.state("save", text="first")
        self.state("save", text="different", ok=False)
        self.assertEqual(self.state("inspect")["contract"], "first")
        self.git("checkout", "-qb", "fix/second")
        self.assertIsNone(self.state("inspect")["contract"])
        self.state("save", text="second")
        self.git("checkout", "fix/example")
        self.assertEqual(self.state("inspect")["contract"], "first")

    def test_worktree_removal_keeps_contract(self):
        worktree = self.repo / "isolated"
        self.git("worktree", "add", "-qb", "fix/isolated", str(worktree))
        self.state("save", text="worktree contract", cwd=worktree)
        self.git("worktree", "remove", str(worktree))
        self.git("checkout", "fix/isolated")
        self.assertEqual(self.state("inspect")["contract"], "worktree contract")

    def test_clean_review_resume_verifies_head_without_committing(self):
        """The clean-tree branch of review-cycle Step 1 must still reach commit-guard.

        It may not attempt a commit (nothing to commit), but it may not skip the
        helper either: `--verify-head` is what judges an existing HEAD that was
        committed outside this harness before it is pushed or merged.
        """
        (self.repo / "code.txt").write_text("completed\n")
        self.git("add", ".")
        self.commit()
        review = SCRIPT.parents[2] / "task-review-cycle" / "SKILL.md"
        section = review.read_text().split("## Step 1: Commit, route, PR", 1)[1]
        block = section.split("```bash\n", 1)[1].split("```", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "scripts").mkdir()
            helper = skill / "scripts" / "commit-and-push.sh"
            # Fails the run on any invocation that is not the no-commit verification.
            helper.write_text(
                'for a in "$@"; do [ "$a" = "--verify-head" ] && '
                '{ echo verified; exit 0; }; done\n'
                "echo 'unexpected commit attempt' >&2\nexit 1\n"
            )
            block = block.replace("<absolute parent directory of the loaded SKILL.md>", str(skill))
            result = subprocess.run(["bash", "-e", "-c", block], cwd=self.repo,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("unexpected commit", result.stderr)
            # The clean branch must call the helper, not fabricate a sentinel.
            silent = block.replace(
                'RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --verify-head)',
                "RESULT='{\"committed\":false,\"resumed\":true}'")
            self.assertNotEqual(silent, block, "the clean branch no longer calls the helper")
            # And the dirty branch must still attempt a real commit: force it and
            # watch the stub reject anything that is not --verify-head.
            dirty_path = block.replace('if [[ -n "$DIRTY" ]]; then', 'if true; then')
            result = subprocess.run(["bash", "-e", "-c", dirty_path], cwd=self.repo,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected commit", result.stderr)

    def test_save_refused_on_base_branch(self):
        # A --tree run's archive heredoc executes from the main checkout unless it cds
        # into the worktree; keying that contract to `main` blocks the next cycle's save.
        self.git("checkout", "-q", "main")
        error = self.state("save", text="from main", ok=False)
        self.assertIn("base branch", error)
        self.assertIsNone(self.state("inspect")["contract"])

    def test_evidence_records_tree_and_invalidates_on_change(self):
        self.state("save", text="contract")
        recorded = self.state("evidence", "--command", "pytest -q", "--exit", "0",
                              "--log", "/tmp/run.log", "--env", "python 3.12")
        self.assertEqual(recorded["command"], "pytest -q")
        self.assertEqual(recorded["exit_code"], 0)
        seen = self.state("inspect")
        self.assertEqual(seen["evidence"]["log"], "/tmp/run.log")
        self.assertEqual(seen["evidence"]["environment"], "python 3.12")
        self.assertTrue(seen["tree_matches_current"])
        (self.repo / "code.txt").write_text("changed after the checks ran\n")
        self.git("add", "code.txt")
        self.assertFalse(self.state("inspect")["tree_matches_current"])

    def test_evidence_requires_an_archived_contract(self):
        self.assertIn("save it before evidence",
                      self.state("evidence", "--command", "pytest", "--exit", "0", ok=False))

    def test_retire_frees_a_reused_branch_name(self):
        self.state("save", text="first cycle")
        retired = self.state("retire")
        self.assertTrue(retired["retired"])
        self.assertIsNone(self.state("inspect")["contract"])
        # A later cycle deriving the same branch name now saves without --replace.
        self.state("save", text="second cycle")
        self.assertEqual(self.state("inspect")["contract"], "second cycle")

    def test_retire_is_idempotent(self):
        self.assertFalse(self.state("retire")["retired"])

    def test_empty_contract_refused(self):
        self.state("save", text=" \n", ok=False)
        self.assertIsNone(self.state("inspect")["contract"])


if __name__ == "__main__":
    unittest.main()
