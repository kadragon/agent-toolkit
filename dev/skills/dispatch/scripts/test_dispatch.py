import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from dispatch import child_argv, codex_screen, free_name, send, tallest, terminal_name
from quota import WEEK, assess

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
            ["codex", "--no-daemon", "--no-alt-screen", "--approve-for-me", "-m", "gpt-6.2-sol",
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


class CodexSendTests(unittest.TestCase):
    READY = "› Ask Codex to do anything\n\n  GPT-6.2-Sol default · ~/repo"
    PASTE = "› [Pasted Content 1576 chars]\n\n  GPT-6.2-Sol default · ~/repo"
    ARGS = SimpleNamespace(address="t7", message="a task")
    IDLE = {"turn": 0, "status": {"state": "idle"}}
    WORKING = {"turn": 0, "status": {"state": "working"}}

    def test_screen_recognizes_composer_and_ignores_transcript_or_draft(self):
        for text, expected in (
            (self.READY, "ready"),
            ("›", "ready"),
            (self.PASTE, "paste"),
            (f"› [Pasted Content 1576 chars]\n\n• Working\n\n{self.READY}", "ready"),
            ("› [Pasted Content 1576 chars]\n\n■ Error", "waiting"),
            ("› 1. Yes, continue\n  2. No, quit\n\n  Press enter to continue", "waiting"),
            ("› draft [Pasted Content 1576 chars]", "waiting"),
            ("  >_ OpenAI Codex (v0.171.0)", "waiting"),
        ):
            with self.subTest(text=text):
                self.assertEqual(codex_screen(text), expected)

    def test_send_withholds_task_on_visible_hook_or_warning(self):
        for text, reason in (
            ("Hooks need review\n› 1. Review hooks", "/hooks"),
            ("⚠\ufe0f 1 hook needs review before it can run.", "/hooks"),
            (f"• Hook failed\n  └ plugin contents changed; hook approval required\n{self.READY}", "/hooks"),
            (f"• Blocked by hook\n  └ Policy prevented this action.\n{self.READY}", "/hooks"),
            (f"• Hook stopped\n  └ Policy prevented this action.\n{self.READY}", "/hooks"),
            (f"{self.READY}\n  ⚠ 1 warning · f2 to view", "F2"),
            (f"{self.READY}\n  ← for agents · ? for shortcuts       ⚠ 2 warnings · F2 to view", "F2"),
        ):
            with self.subTest(text=text), patch("dispatch.hc_json", return_value=self.screen(text)) as hc:
                with self.assertRaisesRegex(SystemExit, reason):
                    send(self.ARGS)
                hc.assert_called_once_with("read", "--lines", "0", "t7")

    @staticmethod
    def screen(text):
        return {"complete": True, "how": "screen", "text": text}

    def test_send_presses_enter_once_for_a_paste_left_in_the_composer(self):
        responses = [
            self.screen(self.READY), self.IDLE, {"started": False},
            self.screen(self.PASTE), self.IDLE,
            self.screen(self.PASTE), self.IDLE, {},
            self.screen(self.READY), self.WORKING,
        ]
        with patch("dispatch.hc_json", side_effect=responses) as hc, \
                patch("dispatch.time.sleep"), patch("builtins.print") as output:
            send(self.ARGS)
        self.assertEqual(hc.call_args_list, [
            call("read", "--lines", "0", "t7"), call("get", "t7"),
            call("send", "--if", "idle", "--", "t7", "a task"),
            call("read", "--lines", "0", "t7"), call("get", "t7"),
            call("read", "--lines", "0", "t7"), call("get", "t7"), call("keys", "t7", "enter"),
            call("read", "--lines", "0", "t7"), call("get", "t7"),
        ])
        self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_leaves_enter_alone_once_the_turn_started(self):
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True},
            self.screen(self.PASTE), {**self.WORKING, "turn": 1},
            self.screen(self.READY), {**self.WORKING, "turn": 1},
        ]) as hc, patch("builtins.print"):
            send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)

    def test_send_retries_an_expanded_paste_once_even_if_herdr_counted_a_turn(self):
        idle = {**self.IDLE, "turn": 1}
        working = {**self.WORKING, "turn": 1}
        for message, prompt in (
            ("a task", "› a task"),
            ("a task", '› <hc from="t6">a task</hc>'),
            ("a task with a long first line", '› <hc from="t6">a task with\n  a long first line</hc>'),
        ):
            with self.subTest(prompt=prompt):
                expanded = self.screen(f"{prompt}\n\n  GPT-6.2-Sol default · ~/repo")
                with patch("dispatch.hc_json", side_effect=[
                    self.screen(self.READY), self.IDLE, {"started": True},
                    expanded, working,
                    expanded, idle,
                    expanded, idle, {},
                    expanded, idle,
                    self.screen(self.READY), working,
                ]) as hc, patch("dispatch.time.sleep"), patch("builtins.print") as output:
                    send(SimpleNamespace(address="t7", message=message))
                self.assertEqual(hc.call_args_list.count(call("keys", "t7", "enter")), 1)
                self.assertEqual(hc.call_count, 14)
                self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_requires_working_status_and_a_clear_composer_in_the_same_poll(self):
        idle = {**self.IDLE, "turn": 1}
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True},
            self.screen("› a task\n\n• Working"), self.WORKING,
            self.screen(self.READY), idle,
            self.screen(self.READY), self.WORKING,
        ]) as hc, patch("dispatch.time.sleep"), patch("builtins.print") as output:
            send(self.ARGS)
        self.assertEqual(hc.call_count, 9)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)
        self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_does_not_retry_enter_on_an_unrelated_prompt(self):
        draft = self.screen("› another draft")
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": False},
            draft, self.IDLE,
            draft, self.IDLE,
            self.screen(self.READY), self.WORKING,
        ]) as hc, patch("dispatch.time.sleep"), patch("builtins.print"):
            send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)

    def test_send_ignores_hook_words_in_the_echoed_task(self):
        echoed = f"› Investigate the following\n  Hook failed on SessionStart\n\n{self.READY}"
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True},
            self.screen(echoed), self.WORKING,
        ]) as hc, patch("builtins.print") as output:
            send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)
        self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_reports_a_real_hook_failure_after_delivery(self):
        failed = f"› Investigate\n\n• Hook failed\n  └ plugin contents changed; hook approval required\n{self.READY}"
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True}, self.screen(failed),
        ]) as hc:
            with self.assertRaisesRegex(SystemExit, "hook problem after the send"):
                send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)

    def test_send_withholds_enter_when_dialog_opens_after_reading_a_paste(self):
        blocked = {"turn": 0, "status": {"state": "blocked"}}
        responses = [
            self.screen(self.READY), self.IDLE, {"started": False},
            self.screen(self.PASTE), self.IDLE,
            self.screen(self.PASTE), blocked, {},
            self.screen(self.READY), {"turn": 1},
        ]
        with patch("dispatch.hc_json", side_effect=responses) as hc, \
                patch("dispatch.time.sleep"), patch("builtins.print"):
            with self.assertRaisesRegex(SystemExit, "blocked after the send"):
                send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)


class QuotaTests(unittest.TestCase):
    def test_critical_when_weekly_runway_ends_before_reset(self):
        now = 1_800_000_000
        result = assess({"used": 83, "reset": now + WEEK * 0.554, "observed": now}, now)
        self.assertEqual(result["state"], "critical")
        self.assertEqual(result["elapsed"], 44.6)
        self.assertEqual(result["runway_h"], 15.3)
        self.assertEqual(result["reset_in_h"], 93.1)

    def test_weekly_runway_compares_unrounded_values(self):
        now = 1_800_000_000
        for used, state in ((49.99, "ok"), (50, "ok"), (50.01, "critical")):
            with self.subTest(used=used):
                result = assess({"used": used, "reset": now + WEEK / 2, "observed": now}, now)
                self.assertEqual(result["state"], state)
                self.assertEqual(result["runway_h"], 84)

    def test_weekly_runway_without_a_measurable_pace(self):
        now = 1_800_000_000
        for used, reset, expected in (
            (0, now + WEEK / 2, None),
            (1, now + WEEK, None),
            (100, now + WEEK, 0),
            (100, now, None),
        ):
            with self.subTest(used=used, reset=reset):
                result = assess({"used": used, "reset": reset, "observed": now}, now)
                self.assertEqual(result["runway_h"], expected)

    def test_five_hour_window_can_raise_state_until_it_resets(self):
        now = 1_800_000_000
        for used, reset, state in (
            (79, now + 3600, "ok"),
            (80, now + 3600, "hot"),
            (90, now + 3600, "critical"),
            (90, now, "ok"),
        ):
            with self.subTest(used=used, reset=reset):
                snapshot = {"used": 10, "reset": now + WEEK / 2, "observed": now,
                            "five_hour": {"used": used, "reset": reset, "observed": now}}
                self.assertEqual(assess(snapshot, now)["state"], state)

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
