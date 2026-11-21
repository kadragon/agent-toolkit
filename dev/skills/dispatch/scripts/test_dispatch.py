import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from dispatch import child_argv, free_name, tallest, terminal_name

SCRIPTS = Path(__file__).resolve().parent


class TerminalTests(unittest.TestCase):
    def test_terminal_name_normalizes_and_truncates(self):
        self.assertEqual(terminal_name(" !Project.Path _- "), "project-path-_")
        self.assertEqual(terminal_name("A" * 40), "a" * 32)

    def test_terminal_name_rejects_empty_result(self):
        with self.assertRaisesRegex(SystemExit, "cannot build a terminal name"):
            terminal_name("!...!")

    def test_tallest_prefers_older_pane_when_rows_tie(self):
        panes = [
            {"address": "short", "rows": 12, "created_ms": 1},
            {"address": "tall-new", "rows": 24, "created_ms": 3},
            {"address": "tall-old", "rows": 24, "created_ms": 2},
        ]
        self.assertEqual(tallest(panes), "tall-old")

    def test_free_name_uses_available_base(self):
        self.assertEqual(free_name("repo", True, {"another-repo"}), "repo")

    def test_free_name_rejects_explicit_collision(self):
        with self.assertRaisesRegex(SystemExit, "name 'repo' is taken"):
            free_name("repo", True, {"repo"})

    def test_free_name_uses_first_available_suffix_and_truncates(self):
        base = "r" * 32
        prefix = "r" * 29
        self.assertEqual(free_name(base, False, {base, f"{prefix}-2", f"{prefix}-4"}), f"{prefix}-3")


class ChildArgvTests(unittest.TestCase):
    def test_codex_argv_and_message_guard(self):
        self.assertEqual(
            child_argv("codex", "gpt-6.2-sol", "high", None, False),
            ["codex", "--no-alt-screen", "--approve-for-me", "-m", "gpt-6.2-sol",
             "-c", "model_reasoning_effort=high"],
        )
        with self.assertRaisesRegex(SystemExit, "codex takes no first message"):
            child_argv("codex", "gpt-6.2-sol", "high", "$task-next", False)

    def test_claude_passes_message_as_one_arg_and_optionally_keeps_connectors(self):
        message = '/dev:task-new Keep "quotes"\nand a newline'
        default_settings = {
            "promptSuggestionEnabled": False,
            "awaySummaryEnabled": False,
            "disableClaudeAiConnectors": True,
            "enabledPlugins": {"cc-plugin-you-should-know@builtin": False},
        }
        for keep in (False, True):
            with self.subTest(keep=keep):
                argv = child_argv("claude", "opus", "high", message, keep)
                self.assertEqual(argv[:6], ["claude", "--model", "opus", "--effort", "high", "--settings"])
                self.assertEqual(argv[7:], [message])
                expected = default_settings.copy()
                if keep:
                    del expected["disableClaudeAiConnectors"]
                self.assertEqual(json.loads(argv[6]), expected)

        with self.assertRaisesRegex(SystemExit, "claude child needs its first message"):
            child_argv("claude", "opus", "high", None, False)


class PickTests(unittest.TestCase):
    def test_pick_reads_worktree_queue_or_base_without_plugin_registry(self):
        with tempfile.TemporaryDirectory(prefix="dispatch pick ") as directory:
            root = Path(directory)
            repo = root / "target repo"
            repo.mkdir()
            env = {**os.environ, "HOME": str(root), "USERPROFILE": str(root)}
            git = ["git", "-c", "core.hooksPath=no-hooks", "-c", "commit.gpgsign=false",
                   "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
            subprocess.run([*git, "init", "-q"], cwd=repo, env=env, check=True)
            backlog = repo / "backlog.md"
            base_section = "## Base queue\n\n- [ ] [FEAT] Base item\n"
            live_section = "## Working tree queue\n\n- [ ] [FEAT] Working tree item\n\n"
            backlog_title = "# Backlog\n\n"
            backlog.write_text(backlog_title + base_section, encoding="utf-8")
            for args in (["add", "backlog.md"], ["commit", "-q", "-m", "base"],
                         ["update-ref", "refs/remotes/origin/HEAD", "HEAD"]):
                subprocess.run([*git, *args], cwd=repo, env=env, check=True)
            backlog.write_text(backlog_title + live_section + base_section, encoding="utf-8")
            dispatch = [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "pick", str(repo)]

            for options, title in (([], "Working tree queue"), (["--tree"], "Base queue")):
                with self.subTest(options=options):
                    result = subprocess.run([*dispatch, *options], cwd=root, env=env, check=True,
                                            capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(json.loads(result.stdout)[0]["title"], title, result.stderr)


class QuotaTests(unittest.TestCase):
    def test_reader_accepts_status_line_snapshot_at_override_and_handles_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "status-line.json"
            env = {**os.environ, "QUOTA_CLAUDE_CACHE": str(snapshot), "CODEX_HOME": str(root)}
            command = [sys.executable, "-I", str(SCRIPTS / "quota.py")]
            missing = json.loads(subprocess.check_output(command, cwd=root, env=env))
            self.assertEqual(missing["claude"], {"state": "unknown"})
            self.assertEqual(missing["bias"], "none")

            now = time.time()
            snapshot.write_text(json.dumps({
                "used": 42, "reset": now + 86400, "observed": now,
                "five_hour": {"used": 91, "reset": now + 3600, "observed": now},
            }), encoding="utf-8")
            present = json.loads(subprocess.check_output(command, cwd=root, env=env))
            self.assertEqual(present["claude"]["used"], 42)
            self.assertEqual(present["claude"]["five_hour_used"], 91)
            self.assertEqual(present["claude"]["state"], "critical")
            self.assertEqual(present["bias"], "codex")


if __name__ == "__main__":
    unittest.main()
