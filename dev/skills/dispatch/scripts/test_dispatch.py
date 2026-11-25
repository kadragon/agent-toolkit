import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, call, patch

from dispatch import (
    POST_SEND_SETTLE_SECONDS,
    child_argv,
    codex_screen,
    collect,
    composer_draft,
    free_name,
    launch,
    lock_run,
    report_instruction,
    send,
    terminal_name,
    transcript_echoed,
)
from quota import WEEK, assess

SCRIPTS = Path(__file__).resolve().parent


class TerminalTests(unittest.TestCase):
    def test_terminal_name_normalizes_and_truncates(self):
        self.assertEqual(terminal_name(" !Project.Path _- "), "project-path-_")
        self.assertEqual(terminal_name("A" * 40), "a" * 32)

    def test_terminal_name_rejects_empty_result(self):
        with self.assertRaisesRegex(SystemExit, "cannot build a terminal name"):
            terminal_name("!...!")

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
        message = ('/dev:task-new --tree Update docs\n'
                   'Original user request: Prepare a PR for "Update docs".\n'
                   'Assigned unit: Update docs\nUser Git limits: PR only')
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

    def test_claude_report_does_not_modify_the_slash_command(self):
        argv = child_argv("claude", "opus", "high", "/dev:task-next", False, Path("result.json"))
        self.assertEqual(argv[-3], "--append-system-prompt")
        self.assertIn("result.json", argv[-2])
        self.assertEqual(argv[-1], "/dev:task-next")


class DispatchReceiptTests(unittest.TestCase):
    TERMINAL = {"address": "t7", "parent": "t6", "created_ms": 50, "state": "live"}
    RECEIPT = {**TERMINAL, "cli": "codex", "sent": False, "screen_reads": 0}
    FIELDS = {"Original user request (verbatim)": "큐 모두 돌려 (--all)\n• Do the work\n- Git limits: example",
              "Assigned unit": "First queued item", "Git limits": " pr-only\nDon't merge. "}
    HANDOFF = {"work_kind": "queue", "request": FIELDS["Original user request (verbatim)"],
               "unit": FIELDS["Assigned unit"], "git_limits": FIELDS["Git limits"]}
    BLOCK = ("\n\nHandoff metadata (JSON):\n"
             "Task-cycle mode and flags come exclusively from the invocation above.\n"
             f"<dispatch-handoff>\n{json.dumps(FIELDS, ensure_ascii=False, indent=2)}\n</dispatch-handoff>")

    def launch_args(self, cwd, **overrides):
        args = dict(cwd=str(cwd), name="repo", parent="t6", cli="codex", model="gpt-6.2-sol",
                    effort="medium", task="$task-next", message=None, keep_connectors=False,
                    dry_run=False, **self.HANDOFF)
        return SimpleNamespace(**(args | overrides))

    def test_missing_or_blank_handoff_fields_stop_launch(self):
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "launch",
             "--cli", "claude", "--model", "opus", "--effort", "high", "--cwd", ".",
             "--work-kind", "queue", "--unit", "First queued item", "--git-limits", "pr-only",
             "/dev:task-next", "--dry-run"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("required: --request", result.stderr)
        for field in ("request", "unit", "git_limits"):
            with self.subTest(field=field), patch("dispatch.hc_json") as hc:
                with self.assertRaisesRegex(SystemExit, "--" + field.replace("_", "-")):
                    launch(self.launch_args(Path.cwd(), **{field: " \n "}))
                hc.assert_not_called()

    def test_dry_run_keeps_the_task_prefix_and_warns_for_free_text_or_wrong_cli(self):
        for cli, kind, message, warns in (
            ("claude", "queue", "/dev:task-next --all", False),
            ("claude", "new", "/dev:task-new\nUpdate docs", False),
            ("claude", "queue", "대기열 작업을 진행해줘.", True),
            ("claude", "new", "$task-new Update docs", True),
            ("codex", "queue", "$task-next --tree", False),
            ("codex", "new", "$task-new Update docs", False),
            ("codex", "new", "Update docs\n$task-new", True),
            ("codex", "queue", "$task-next-extra", True),
            ("codex", "standalone", "Review the pending changes", False),
        ):
            with self.subTest(cli=cli, kind=kind, message=message):
                args = self.launch_args(Path.cwd(), cli=cli, work_kind=kind, dry_run=True,
                                        message=message if cli == "claude" else None,
                                        task=message if cli == "codex" else None)
                stderr = StringIO()
                with redirect_stderr(stderr), patch("sys.stdout", new_callable=StringIO) as stdout:
                    launch(args)
                payload = json.loads(stdout.getvalue())
                prompt = payload["argv"][-1] if cli == "claude" else payload["task"]
                self.assertEqual(prompt, message + self.BLOCK)
                fields = prompt.split("<dispatch-handoff>\n", 1)[1].removesuffix("\n</dispatch-handoff>")
                self.assertEqual(json.loads(fields), self.FIELDS)
                self.assertEqual(bool(stderr.getvalue()), warns)
                if warns:
                    self.assertIn("warning:", stderr.getvalue())
                    self.assertIn("task-next", stderr.getvalue())
                    self.assertIn("task-new", stderr.getvalue())

    def test_home_handoff_lines_follow_verbatim_fields_for_matching_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            registry = home / "repos"
            registry.mkdir()
            team_line = "팀 리뷰 체크리스트를 사용하세요."
            app_line = "Use the app review checklist."
            (registry / "handoff.json").write_text(json.dumps({
                "projects": [team_line],
                str(home / "projects" / "app"): [app_line],
            }, ensure_ascii=False), encoding="utf-8")
            for cli, invocation in (("claude", "/dev:task-next"), ("codex", "$task-next")):
                for target, extra in (
                    ("projects/app", f"\n\n{team_line}\n{app_line}"),
                    ("projects/app-sibling", f"\n\n{team_line}"),
                    ("projects-other/app", ""),
                ):
                    with self.subTest(cli=cli, target=target), patch("dispatch.Path.cwd", return_value=home):
                        args = self.launch_args(home / target, cli=cli, dry_run=True,
                                                message=invocation if cli == "claude" else None,
                                                task=invocation if cli == "codex" else None)
                        with redirect_stdout(StringIO()) as stdout:
                            launch(args)
                        payload = json.loads(stdout.getvalue())
                        prompt = payload["argv"][-1] if cli == "claude" else payload["task"]
                        self.assertEqual(prompt, invocation + self.BLOCK + extra)

    def test_invalid_home_handoff_config_stops_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            registry = home / "repos"
            registry.mkdir()
            config = registry / "handoff.json"
            for invalid in ("{", "[]", '{"projects": "single string"}',
                            json.dumps({"projects": ["multiple\nlines"]})):
                config.write_text(invalid, encoding="utf-8")
                with self.subTest(invalid=invalid), patch("dispatch.Path.cwd", return_value=home), \
                        patch("dispatch.hc_json") as hc:
                    with self.assertRaisesRegex(SystemExit, r"repos[/\\]handoff\.json"):
                        launch(self.launch_args(home))
                    hc.assert_not_called()

    def test_home_handoff_reads_repo_config_from_a_subdirectory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            subprocess.run(["git", "init", "-q", str(home)], check=True)
            (home / "tools").mkdir()
            (home / "repos").mkdir()
            (home / "repos" / "handoff.json").write_text(
                json.dumps({"projects": ["Use the team review checklist."]}), encoding="utf-8"
            )
            args = self.launch_args("../projects/app", dry_run=True)
            with patch("dispatch.Path.cwd", return_value=home / "tools"), redirect_stdout(StringIO()) as stdout:
                launch(args)
            self.assertEqual(json.loads(stdout.getvalue())["task"],
                             "$task-next" + self.BLOCK + "\n\nUse the team review checklist.")

    def test_launch_rejects_stale_parent_before_start(self):
        args = self.launch_args(Path.cwd())
        owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd().parent)}
        for replies, reason in (([{"terminals": []}], "not live"),
                                ([{"terminals": [owner]}, owner], "outside this directory")):
            with (
                self.subTest(reason=reason),
                patch("dispatch.hc_json", side_effect=replies),
                patch("dispatch.subprocess.run") as run,
            ):
                with self.assertRaisesRegex(SystemExit, reason):
                    launch(args)
                run.assert_not_called()

    def test_launch_runs_in_background_and_emits_receipt_before_send(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "repos").mkdir()
            extra_lines = ["Use the launch-time checklist."]
            (home / "repos" / "handoff.json").write_text(json.dumps({".": extra_lines}), encoding="utf-8")
            args = self.launch_args(directory)
            owner = {"address": "t6", "state": "live", "cwd": str(home.parent)}
            live_owner = {**owner, "foreground": {"cwd": str(home)}}
            child = SimpleNamespace(stdout=json.dumps(self.TERMINAL))
            calls = [{"terminals": [owner]}, live_owner, self.TERMINAL]
            with (
                patch("dispatch.Path.cwd", return_value=home),
                patch("dispatch.hc_json", side_effect=calls),
                patch("dispatch.subprocess.run", return_value=child) as run,
                patch("dispatch.tempfile.mkdtemp", return_value=directory),
                patch("dispatch.send") as submit,
                patch("builtins.print") as output,
            ):
                launch(args)
            git_call, launch_call = run.call_args_list
            self.assertEqual(git_call.args[0][0], "git")
            argv = launch_call.args[0]
            self.assertEqual(argv[:3], ["hc", "run", "--bg"])
            self.assertIn("--no-notify", argv)
            self.assertEqual(argv[argv.index("--parent") + 1], "t6")
            payload = json.loads(output.call_args.args[0])
            self.assertNotIn("shown", payload)
            self.assertNotIn("handoff", payload)
            receipt = json.loads(Path(payload["run"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["created_ms"], 50)
            self.assertFalse(receipt["sent"])
            self.assertEqual(receipt["handoff"], {**self.HANDOFF, "extra_lines": extra_lines})
            self.assertEqual(submit.call_args.args[0].run, Path(payload["run"]))
            self.assertEqual(submit.call_args.args[0].message, "$task-next")

    def test_claude_parent_mismatch_reports_that_launch_may_have_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd())}
            child = {**self.TERMINAL, "parent": "t5"}
            args = self.launch_args(directory, cli="claude", task=None, message="/dev:task-next")
            with (
                patch("dispatch.hc_json", side_effect=[{"terminals": [owner]}, owner, child]),
                patch("dispatch.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(child))) as run,
                patch("dispatch.tempfile.mkdtemp", return_value=directory),
                patch("builtins.print"),
            ):
                with self.assertRaisesRegex(SystemExit, "Claude may have received its launch prompt"):
                    launch(args)
                self.assertEqual(run.call_args.args[0][-1], "/dev:task-next" + self.BLOCK)

    def test_collect_reads_result_without_screen_and_only_closes_final_owned_child(self):
        done = {**self.TERMINAL, "status": {"state": "done"}}
        finished = {**done, "state": "finished"}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps(self.RECEIPT), encoding="utf-8")
            result = receipt.with_name("result.json")
            for status in ("ready", "merged"):
                result.write_text(json.dumps({"status": status, "phase": "review", "summary": "CI passed"}),
                                  encoding="utf-8")
                args = SimpleNamespace(run=receipt, close=True)
                with (
                    patch("dispatch.hc_json", side_effect=[done, {}, done, finished, {}]) as hc,
                    patch("dispatch.time.sleep") as sleep,
                    patch("builtins.print"),
                ):
                    if status == "ready":
                        with self.assertRaisesRegex(SystemExit, "left intact"):
                            collect(args)
                        hc.assert_called_once_with("get", "t7")
                    else:
                        collect(args)
                        self.assertEqual(hc.call_args_list, [
                            call("get", "t7"), call("kill", "t7"), call("get", "t7", timeout=ANY),
                            call("get", "t7", timeout=ANY), call("rm", "t7"),
                        ])
                        sleep.assert_called_once()
                        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["closed_reason"],
                                         "final_result")
            with patch("dispatch.hc_json", return_value={**done, "created_ms": 70}) as hc:
                with self.assertRaisesRegex(SystemExit, "terminal identity changed"):
                    collect(args)
                hc.assert_called_once_with("get", "t7")

    def test_collect_cannot_close_on_a_result_from_the_previous_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            result = receipt.with_name("result.json")
            result.write_text(json.dumps({"status": "done", "phase": "implementation", "summary": "ok"}),
                              encoding="utf-8")
            run = {**self.RECEIPT, "previous_result": result.stat().st_mtime_ns}
            receipt.write_text(json.dumps(run), encoding="utf-8")
            terminal = {**self.TERMINAL, "status": {"state": "done"}}
            with patch("dispatch.hc_json", return_value=terminal) as hc:
                with self.assertRaisesRegex(SystemExit, "no final result"):
                    collect(SimpleNamespace(run=receipt, close=True))
                hc.assert_called_once_with("get", "t7")

    def test_collect_closes_a_finished_terminal_without_a_final_result(self):
        finished = {**self.TERMINAL, "state": "finished", "status": None}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps(self.RECEIPT), encoding="utf-8")
            receipt.with_name("result.json").write_text(
                json.dumps({"status": "ready", "phase": "review", "summary": "PR open"}), encoding="utf-8")
            with patch("dispatch.hc_json", return_value=finished) as hc, patch("builtins.print"):
                collect(SimpleNamespace(run=receipt, close=True))
            self.assertEqual(hc.call_args_list, [call("get", "t7"), call("rm", "t7")])
            live = {**self.TERMINAL, "status": {"state": "idle"}}
            with patch("dispatch.hc_json", return_value=live) as hc:
                with self.assertRaisesRegex(SystemExit, "left intact"):
                    collect(SimpleNamespace(run=receipt, close=True))
                hc.assert_called_once_with("get", "t7")

    def test_collect_reads_a_result_without_status_as_working(self):
        done = {**self.TERMINAL, "status": {"state": "done"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps(self.RECEIPT), encoding="utf-8")
            result = receipt.with_name("result.json")
            result.write_text(json.dumps({"phase": "review", "pr": 779, "summary": "PR open"}), encoding="utf-8")
            with patch("dispatch.hc_json", return_value=done), patch("builtins.print") as shown:
                collect(SimpleNamespace(run=receipt, close=False))
            report = json.loads(shown.call_args.args[0])
            self.assertEqual(report["result"], {"status": "working", "phase": "review", "pr": 779,
                                                "summary": "PR open"})
            with patch("dispatch.hc_json", return_value=done) as hc:
                with self.assertRaisesRegex(SystemExit, "left intact"):
                    collect(SimpleNamespace(run=receipt, close=True))
                hc.assert_called_once_with("get", "t7")
            result.write_text(json.dumps({"status": "bogus", "phase": "review", "summary": "x"}),
                              encoding="utf-8")
            with patch("dispatch.hc_json", return_value=done):
                with self.assertRaisesRegex(SystemExit, "invalid status, phase, or summary"):
                    collect(SimpleNamespace(run=receipt, close=False))

    def test_collect_force_closes_an_owned_child_and_records_the_reason(self):
        working = {**self.TERMINAL, "status": {"state": "working"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps(self.RECEIPT), encoding="utf-8")
            receipt.with_name("result.json").write_text(
                '{"status":"working","phase":"test","summary":"Tests are running"}', encoding="utf-8",
            )
            args = SimpleNamespace(run=receipt, close=True, force=True)
            with patch("dispatch.hc_json", return_value={**working, "created_ms": 51}) as hc:
                with self.assertRaisesRegex(SystemExit, "terminal identity changed"):
                    collect(args)
                hc.assert_called_once_with("get", "t7")
            finished = {**working, "state": "finished"}
            with (
                patch("dispatch.hc_json", side_effect=[working, {}, finished, {}]) as hc,
                redirect_stdout(StringIO()) as out,
            ):
                collect(args)
            self.assertEqual(hc.call_args_list, [
                call("get", "t7"), call("kill", "t7"), call("get", "t7", timeout=ANY), call("rm", "t7"),
            ])
            self.assertEqual(json.loads(out.getvalue())["closed_reason"], "forced")
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["closed_reason"], "forced")

    def test_collect_leaves_receipt_open_when_finish_cannot_be_confirmed(self):
        replaced = {**self.TERMINAL, "state": "finished", "created_ms": 51}
        for snapshot, reason in (
            (self.TERMINAL, "did not reach state: finished"),
            (subprocess.TimeoutExpired("hc get", 9), "did not reach state: finished"),
            (replaced, "terminal identity changed"),
        ):
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "run.json"
                receipt.write_text(json.dumps(self.RECEIPT), encoding="utf-8")
                with (
                    patch("dispatch.hc_json", side_effect=[self.TERMINAL, {}, snapshot, {}]) as hc,
                    patch("dispatch.time.monotonic", side_effect=[0, 1, 10, 10]),
                    patch("dispatch.time.sleep"),
                ):
                    with self.assertRaisesRegex(SystemExit, reason):
                        collect(SimpleNamespace(run=receipt, close=True, force=True))
                self.assertEqual(hc.call_args_list, [
                    call("get", "t7"), call("kill", "t7"), call("get", "t7", timeout=9),
                ])
                self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), self.RECEIPT)

    def test_receipt_operations_do_not_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            follow_up = SimpleNamespace(address="t7", message="next", run=receipt, continuation=True)
            close = SimpleNamespace(run=receipt, close=True)
            with lock_run(receipt), patch("dispatch.hc_json") as hc:
                for operation, args in ((send, follow_up), (collect, close)):
                    with self.subTest(operation=operation.__name__):
                        with self.assertRaisesRegex(SystemExit, "cannot lock dispatch receipt"):
                            operation(args)
                hc.assert_not_called()
            with lock_run(receipt):
                pass


class PickTests(unittest.TestCase):
    def test_pick_warns_when_local_base_is_behind_origin(self):
        with tempfile.TemporaryDirectory(prefix="dispatch stale base ") as directory:
            repo = Path(directory)
            git = ["git", "-c", "core.hooksPath=no-hooks", "-c", "commit.gpgsign=false",
                   "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
            subprocess.run([*git, "init", "-q", "-b", "release"], cwd=repo, check=True)
            backlog = repo / "backlog.md"
            backlog.write_text("# Backlog\n\n## Local queue\n\n- [ ] [FEAT] Local item\n", encoding="utf-8")
            for args in (["add", "backlog.md"], ["commit", "-qm", "local queue"],
                         ["switch", "-qc", "remote-history"]):
                subprocess.run([*git, *args], cwd=repo, check=True)
            backlog.write_text("# Backlog\n\n## Remote queue\n\n- [ ] [FEAT] Remote item\n", encoding="utf-8")
            for args in (["commit", "-qam", "remote queue"], ["update-ref", "refs/remotes/origin/release", "HEAD"],
                         ["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release"],
                         ["switch", "-q", "release"]):
                subprocess.run([*git, *args], cwd=repo, check=True)

            dispatch = [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "pick", str(repo)]
            local = subprocess.run(dispatch, check=True, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual([item["title"] for item in json.loads(local.stdout)], ["Local queue"])
            self.assertIn("release is 1 commit behind origin/release", local.stderr)
            self.assertIn("local backlog may be stale", local.stderr)

            tree = subprocess.run([*dispatch, "--tree"], check=True, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual([item["title"] for item in json.loads(tree.stdout)], ["Remote queue"])
            self.assertNotIn("local backlog may be stale", tree.stderr)

            subprocess.run([*git, "switch", "-q", "remote-history"], cwd=repo, check=True)
            off_base = subprocess.run(dispatch, check=True, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual([item["title"] for item in json.loads(off_base.stdout)], ["Remote queue"])
            self.assertNotIn("local backlog may be stale", off_base.stderr)

            subprocess.run([*git, "switch", "-q", "release"], cwd=repo, check=True)
            for args in (["branch", "-m", "main"], ["symbolic-ref", "--delete", "refs/remotes/origin/HEAD"],
                         ["update-ref", "refs/remotes/origin/main", "refs/remotes/origin/release"]):
                subprocess.run([*git, *args], cwd=repo, check=True)
            fallback = subprocess.run(dispatch, check=True, capture_output=True, text=True, encoding="utf-8")
            self.assertIn("main is 1 commit behind origin/main", fallback.stderr)

            subprocess.run([*git, "merge", "-q", "--ff-only", "origin/main"], cwd=repo, check=True)
            current = subprocess.run(dispatch, check=True, capture_output=True, text=True, encoding="utf-8")
            self.assertNotIn("local backlog may be stale", current.stderr)

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
            base_section = "## Base queue\n\n- [ ] [FEAT] Base item\n\n"
            base_tail = (
                "## Base second\n\n- [ ] [DOCS] Second item\n\n"
                "## Base third\n\n- [ ] [DOCS] Third item\n\n"
                "### Base nested\n\n- [ ] [FEAT] Nested item\n"
            )
            live_title = "작업 대기열"
            live_section = (
                f"## {live_title}\n\n"
                "- [ ] [FEAT] Working tree item\n"
                "- [ ] Wait for approval\n  *(deferred: ops)*\n"
                "- [ ] Wait for API *(blocked by: 1-api)*\n"
                "- [ ] Wait for both *(deferred: ops)* *(blocked by: 1-api)*\n"
                "- [ ] Explain the `*(blocked by: <slug>)*` syntax\n"
                "- [x] Completed *(deferred: ops)*\n\n"
            )
            backlog_title = "# Backlog\n\n"
            backlog.write_text(backlog_title + base_section + base_tail, encoding="utf-8")
            for args in (["add", "backlog.md"], ["commit", "-q", "-m", "base"],
                         ["update-ref", "refs/remotes/origin/HEAD", "HEAD"]):
                subprocess.run([*git, *args], cwd=repo, env=env, check=True)
            backlog.write_text(backlog_title + live_section + base_section + base_tail, encoding="utf-8")
            dispatch = [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "pick", str(repo)]

            full_base = ["Base nested", "Base queue", "Base second", "Base third"]
            cases = (
                ([], [live_title, "Base queue"]),
                (["--tree"], ["Base queue", "Base second"]),
                (["--full-scan"], ["Base nested", live_title, *full_base[1:]]),
                (["--tree", "--full-scan"], full_base),
            )
            for options, expected in cases:
                with self.subTest(options=options):
                    result = subprocess.run([*dispatch, *options], cwd=root, env=env, check=True,
                                            capture_output=True, text=True, encoding="utf-8")
                    candidates = json.loads(result.stdout)
                    self.assertEqual([item["title"] for item in candidates], expected, result.stderr)
                    self.assertNotIn("local backlog may be stale", result.stderr)
                    for item in candidates:
                        counts = tuple(item[key] for key in ("items", "open", "deferred", "blocked"))
                        if item["title"] == live_title:
                            self.assertIn(live_title, result.stdout)
                            self.assertEqual(counts, (2, 5, 2, 2))
                        else:
                            self.assertEqual(counts, (1, 1, 0, 0))

            worktree = repo / ".worktrees" / "first"
            subprocess.run([*git, "worktree", "add", "--quiet", "--detach", str(worktree), "HEAD"],
                           cwd=repo, env=env, check=True)
            for claimed in (False, True):
                with self.subTest(claimed=claimed):
                    if claimed:
                        (worktree / "tasks.md").write_text(
                            "# Base nested\nstatus: active\n\n## Covers\n- [ ] [FEAT] Nested item\n",
                            encoding="utf-8",
                        )
                    result = subprocess.run([*dispatch, "--tree", "--full-scan"], cwd=root, env=env, check=True,
                                            capture_output=True, text=True, encoding="utf-8")
                    expected = full_base[1:] if claimed else full_base
                    self.assertEqual([item["title"] for item in json.loads(result.stdout)], expected, result.stderr)
                    self.assertEqual("claimed by in-flight worktrees" in result.stderr, claimed, result.stderr)

    def test_launch_warns_for_a_subdirectory_of_a_linked_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "main checkout"
            linked = Path(directory) / "linked checkout"
            git = ["git", "-c", "core.hooksPath=no-hooks", "-c", "commit.gpgsign=false",
                   "-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
            subprocess.run([*git, "init", "-q", repo], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], cwd=repo, check=True)
            subprocess.run([*git, "worktree", "add", "-q", "--detach", linked], cwd=repo, check=True)
            for checkout in (repo, linked):
                nested = checkout / "nested"
                nested.mkdir()
                args = [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "launch", "--dry-run",
                        "--cli", "codex", "--model", "model", "--effort", "low", "--cwd", str(nested),
                        "--work-kind", "new", "--request", "Task", "--unit", "Task", "--git-limits", "none"]
                result = subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual("inside a linked worktree" in result.stderr, checkout == linked)
                self.assertEqual("Launch from the main checkout and add --tree" in result.stderr, checkout == linked)


class WorkflowDocsTests(unittest.TestCase):
    def test_launch_and_watch_document_operational_order(self):
        skill = " ".join((SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8").split())
        layout_step = skill.split("## 2. Choose the session layout and first message", 1)[1].split("## 3.", 1)[0]
        launch_step, watch_step = skill.split("## 4. Launch", 1)[1].split("## 5. Watch and decide", 1)
        self.assertIn("read the chosen child CLI's installed `task-next/SKILL.md` or `task-new/SKILL.md`", layout_step)
        self.assertIn("Look for `Dispatch mode: parallel-worktree` and confirm that it restricts the run "
                      "to the assigned unit.", layout_step)
        self.assertIn("If the file is unreadable or lacks that handling, report the worktree layout as unsupported.",
                      layout_step)
        self.assertIn("If a required action is still unauthorized, ask once before launch "
                      "which Git actions the user authorizes", launch_step)
        self.assertIn("If an explicit full-workflow invocation grants the required Git writes and sets no narrower "
                      "limits, pass `--git-limits='none'`.", launch_step)
        self.assertIn("For work that needs no Git writes and has no user-provided limits, "
                      "pass `--git-limits='not specified'`.", launch_step)
        self.assertIn("after confirming task delivery to every new child", watch_step)
        self.assertIn("Once a parallel PR branch has been pushed, fetch and merge its PR base", watch_step)


class CodexSendTests(unittest.TestCase):
    READY = "› Ask Codex to do anything\n\n  GPT-6.2-Sol default · ~/repo"
    PASTE = "› [Pasted Content 1576 chars]\n\n  GPT-6.2-Sol default · ~/repo"
    FOOTER_0171 = (
        "  GPT-6.2-Sol high · main · weekly 54% left · Context 0% used · sample-repo\n"
        "  ← for agents · ? for shortcuts"
    )
    ARGS = SimpleNamespace(address="t7", message="a task")
    IDLE = {"turn": 0, "status": {"state": "idle"}}
    WORKING = {"turn": 0, "status": {"state": "working"}}
    HOOK_REVIEW = (
        "  Hooks need review\n  2 hooks are new or changed.\n\n"
        "› 1. Review hooks\n  2. Trust all and continue\n  3. Continue without trusting (hooks won't run)\n\n"
        "  enter confirm · esc skip"
    )
    TRUSTING_HOOKS = (
        "  Hooks need review\n  2 hooks are new or changed.\n  Trusting hooks...\n\n"
        "›    Review hooks\n     Trust all and continue\n     Continue without trusting (hooks\n     won't run)"
    )

    def setUp(self):
        self.enterContext(patch("dispatch.POST_SEND_SETTLE_SECONDS", 0))

    def test_codex_0171_two_line_footer(self):
        footer = self.FOOTER_0171
        ready = f"› Ask Codex to do anything\n\n{footer}"
        branch_first = ready.replace("GPT-6.2-Sol high · ", "")
        for screen in (ready, f"  >_ OpenAI Codex (v0.171.0)\n\n{ready}", branch_first,
                       f"{ready}       IDE context"):
            with self.subTest(screen=screen):
                self.assertEqual(codex_screen(screen), "ready")

        message = "Review this task\n\nGPT-6.2-Sol is the model in this example.\nKeep this line."
        draft = "› " + "\n  ".join(message.splitlines())
        screen = f"{draft}\n\n{footer}"
        for shown, sent, expected in (
            (screen, None, "draft"),
            (screen, message, "paste"),
            (draft, None, "waiting"),
            (f"› [Pasted Content 1576 chars]\n\n{footer}", None, "collapsed"),
        ):
            with self.subTest(shown=shown, expected=expected):
                self.assertEqual(codex_screen(shown, sent_message=sent), expected)
        with self.subTest("extract draft"):
            self.assertEqual(composer_draft(screen), message)
            self.assertEqual(composer_draft(draft), message)
        for status, hint in (
            ("main · weekly 54% left", "← for agents · ? for shortcuts"),
            ("GPT-6.2-Sol is the model", "← for agents · ? for shortcuts in this example."),
        ):
            with self.subTest(status=status, hint=hint):
                status_like_draft = f"› Summarize this\n\n  {status}\n  {hint}"
                self.assertEqual(codex_screen(status_like_draft), "waiting")
                self.assertEqual(composer_draft(status_like_draft), f"Summarize this\n\n{status}\n{hint}")

        status, hint = footer.splitlines()
        warning = "       ⚠ 1 warning · f2 to view"
        for rows in (f"{status}{warning}\n{hint}", f"{status}\n{hint}{warning}"):
            with self.subTest(rows=rows):
                self.assertEqual(codex_screen(f"› Ask Codex to do anything\n\n{rows}"), "warning")

    def launch_codex(self, directory, respond, **options):
        saved = DispatchReceiptTests()
        owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd())}

        def hc(command, *args):
            if command == "ls":
                return {"terminals": [owner]}
            if command == "get" and args == ("t6",):
                return owner
            return respond(command, *args)

        with (
            patch("dispatch.hc_json", side_effect=hc) as mocked_hc,
            patch("dispatch.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(saved.TERMINAL))),
            patch("dispatch.tempfile.mkdtemp", return_value=directory),
            patch("dispatch.time.sleep"),
            redirect_stdout(StringIO()),
        ):
            launch(saved.launch_args(directory, **options))
        return mocked_hc.call_args_list

    def test_launch_trusts_only_the_opted_in_startup_dialog(self):
        for trust, dialog in ((True, self.HOOK_REVIEW), (False, self.HOOK_REVIEW),
                              (True, "Hook failed: task is blocked\n  2. Trust all and continue")):
            with self.subTest(trust=trust, dialog=dialog), tempfile.TemporaryDirectory() as directory:
                operations = []
                approved_frames = iter([self.TRUSTING_HOOKS, self.TRUSTING_HOOKS])

                def respond(command, *args):
                    if command == "get":
                        turn = self.WORKING if "send" in operations else self.IDLE
                        return {**DispatchReceiptTests.TERMINAL, **turn}
                    if command == "read":
                        shown = dialog
                        if ("enter",) in operations:
                            shown = next(approved_frames, self.READY)
                        elif ("down",) in operations:
                            shown = dialog.replace("› 1. Review hooks\n  2.", "  1. Review hooks\n› 2.")
                        return self.screen(shown)
                    operations.append(args[1:] if command == "keys" else command)
                    return {}

                if trust and dialog == self.HOOK_REVIEW:
                    try:
                        self.launch_codex(directory, respond, trust_hooks=True)
                    except SystemExit as error:
                        self.fail(f"Launch should wait for hook trust to finish: {error}")
                    self.assertEqual(operations, [("down",), ("enter",), "send"])
                else:
                    with self.assertRaisesRegex(SystemExit, "task withheld.*?/hooks"):
                        self.launch_codex(directory, respond, trust_hooks=trust)
                    self.assertEqual(operations, [])

    def test_launch_reports_a_hook_trust_write_error(self):
        with tempfile.TemporaryDirectory() as directory:
            choices = []

            def respond(command, *args):
                if command == "get":
                    return {**DispatchReceiptTests.TERMINAL, **self.IDLE}
                if command == "read":
                    if not choices:
                        return self.screen(self.HOOK_REVIEW)
                    selected = self.HOOK_REVIEW.replace("› 1. Review hooks\n  2.", "  1. Review hooks\n› 2.")
                    if choices == ["down"]:
                        return self.screen(selected)
                    return self.screen(selected.replace("  2 hooks are new or changed.",
                                                        "  Failed to trust hooks: access denied"))
                self.assertEqual(command, "keys")
                choices.append(args[-1])
                return {}

            with self.assertRaisesRegex(SystemExit, "Failed to trust hooks: access denied"):
                self.launch_codex(directory, respond, trust_hooks=True)
            self.assertEqual(choices, ["down", "enter"])

    def test_launch_recovers_paste_when_herdr_could_not_confirm_submission(self):
        for acknowledged in (False, True):
            with self.subTest(acknowledged=acknowledged), tempfile.TemporaryDirectory() as directory:
                operations = []
                message = None

                def respond(command, *args):
                    nonlocal message
                    if command == "get":
                        turn = self.WORKING if "keys" in operations else self.IDLE
                        return {**DispatchReceiptTests.TERMINAL, **turn}
                    if command == "read":
                        if operations != ["send"]:
                            return self.screen(self.READY)
                        paste = self.PASTE if acknowledged else f"› {message}\n\n  GPT-6.2-Sol default · ~/repo"
                        return self.screen(paste)
                    operations.append(command)
                    if command == "send":
                        message = args[-1]
                        if not acknowledged:
                            raise subprocess.CalledProcessError(1, "hc", stderr="could not confirm submission")
                        return {"started": False}
                    return {}

                try:
                    calls = self.launch_codex(directory, respond)
                except SystemExit as error:
                    self.fail(f"Launch should recover the pasted task: {error}")
                self.assertEqual(operations, ["send", "keys"])
                self.assertIn(call("keys", "t7", "enter"), calls)
                self.assertTrue(json.loads((Path(directory) / "run.json").read_text(encoding="utf-8"))["sent"])

    def test_send_error_does_not_submit_an_unidentified_collapsed_paste(self):
        reads = iter([self.screen(self.READY)])

        def respond(command, *args):
            if command == "read":
                return next(reads, self.screen(self.PASTE))
            if command == "get":
                return self.IDLE
            if command == "send":
                raise subprocess.CalledProcessError(1, "hc")
            return {}

        with (patch("dispatch.hc_json", side_effect=respond) as hc, patch("dispatch.time.sleep"),
              patch("dispatch.time.monotonic", side_effect=range(1000)), redirect_stderr(StringIO())):
            with self.assertRaisesRegex(SystemExit, "could not confirm delivery"):
                send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)

    def test_send_error_and_unrelated_working_status_do_not_confirm_delivery(self):
        def respond(command, *args):
            if command == "read":
                return self.screen(self.READY)
            if command == "get":
                return self.WORKING if sent else self.IDLE
            sent.append(args)
            raise subprocess.CalledProcessError(1, "hc")

        sent = []
        with (patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"),
              patch("dispatch.time.monotonic", side_effect=range(1000)), redirect_stderr(StringIO())):
            with self.assertRaisesRegex(SystemExit, "could not confirm delivery"):
                send(self.ARGS)
        self.assertEqual(len(sent), 1)

    def test_send_error_confirms_a_new_matching_prompt_in_the_transcript(self):
        message = "a multiline\ntask"
        echoed = self.screen(
            f'› <hc from="t6">\n  {message}\n  </hc>\n\n• Working\n\n{self.READY}'
        )
        for previous, confirmed in ((self.screen(self.READY), True), (echoed, False)):
            with self.subTest(confirmed=confirmed):
                attempts = []

                def respond(command, *args):
                    if command == "read":
                        return echoed if attempts else previous
                    if command == "get":
                        return self.WORKING if attempts else self.IDLE
                    attempts.append(command)
                    raise subprocess.CalledProcessError(1, "hc")

                args = SimpleNamespace(address="t7", message=message)
                with (patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"),
                      patch("dispatch.time.monotonic", side_effect=range(1000)),
                      redirect_stdout(StringIO()) as out, redirect_stderr(StringIO())):
                    if confirmed:
                        try:
                            send(args)
                        except SystemExit as error:
                            self.fail(f"The new transcript prompt should confirm delivery: {error}")
                        self.assertIs(json.loads(out.getvalue())["submitted"], True)
                    else:
                        with self.assertRaisesRegex(SystemExit, "could not confirm delivery"):
                            send(args)
                self.assertEqual(attempts, ["send"])

    def test_send_error_rejects_a_transcript_prompt_with_only_the_same_prefix(self):
        frames = iter([self.screen(self.READY)])
        larger = self.screen(f"› a task\n  but skip the validation\n\n• Working\n\n{self.READY}")

        def respond(command, *args):
            if command == "read":
                return next(frames, larger)
            if command == "get":
                return self.WORKING if attempts else self.IDLE
            attempts.append(command)
            raise subprocess.CalledProcessError(1, "hc")

        attempts = []
        with (patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"),
              patch("dispatch.time.monotonic", side_effect=range(1000)), redirect_stderr(StringIO())):
            with self.assertRaisesRegex(SystemExit, "could not confirm delivery"):
                send(self.ARGS)
        self.assertEqual(attempts, ["send"])

    def test_screen_recognizes_composer_and_ignores_transcript_or_draft(self):
        for text, expected in (
            (self.READY, "ready"),
            ("›\n\n  ~/repo", "ready"),
            ("› Ask Codex to do anything\n\n  custom status", "ready"),
            ("›\n  a multiline draft\n\n  ~/repo", "draft"),
            ("›\n\n  a multiline draft with no status line", "waiting"),
            ("›", "ready"),
            (self.PASTE, "collapsed"),
            (f"› [Pasted Content 1576 chars]\n\n• Working\n\n{self.READY}", "ready"),
            ("› [Pasted Content 1576 chars]\n\n■ Error", "waiting"),
            ("› 1. Yes, continue\n  2. No, quit\n\n  Press enter to continue", "waiting"),
            ("› draft [Pasted Content 1576 chars]", "waiting"),
            ("› or\n\n  GPT-6.2-Sol default · ~/repo", "draft"),
            ("  >_ OpenAI Codex (v0.171.0)", "waiting"),
        ):
            with self.subTest(text=text):
                self.assertEqual(codex_screen(text), expected)

    def test_screen_markers_at_wrapped_prompt_rows_are_text(self):
        for marker in ("•", "■", "›", "─ Worked for"):
            with self.subTest(marker=marker):
                message = f"Review the checklist {marker} then run the tests."
                shown = f"› Review the checklist\n  {marker} then run the tests."
                self.assertEqual(codex_screen(f"{shown}\n\n{self.FOOTER_0171}", sent_message=message), "paste")
                self.assertTrue(transcript_echoed(f"{shown}\n\n• Completed\n\n{self.READY}", message))

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

    def test_send_reports_a_bounded_tail_of_the_last_unrecognized_screen(self):
        final_screen = self.screen(
            "older transcript\n" * 10 + "  › 1. Confirm selection\n  2. " + "x" * 500
            + "END_OF_LONG_ROW\n\n  Press enter to continue  \n\n"
        )
        with (
            patch("dispatch.hc_json", side_effect=[self.screen("previous frame"), final_screen]) as hc,
            patch("dispatch.time.monotonic", side_effect=[0, 5, 30]),
            patch("dispatch.time.sleep"),
            redirect_stderr(StringIO()) as stderr,
            redirect_stdout(StringIO()) as stdout,
        ):
            with self.assertRaisesRegex(SystemExit, "no clear Codex input line"):
                send(self.ARGS)
        self.assertEqual(hc.call_args_list, [call("read", "--lines", "0", "t7")] * 2)
        self.assertEqual(stdout.getvalue(), "")
        tail = stderr.getvalue()
        self.assertIn("› 1. Confirm selection", tail)
        self.assertIn("Press enter to continue", tail)
        self.assertNotIn("previous frame", tail)
        self.assertNotIn("END_OF_LONG_ROW", tail)
        self.assertLessEqual(len(tail.splitlines()), 7)
        self.assertLess(len(tail), 400)

    def test_send_never_reports_another_terminals_screen_for_a_stale_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            unrelated = {**DispatchReceiptTests.TERMINAL, "created_ms": 51}
            for resend in (False, True):
                with self.subTest(resend=resend):
                    run = {**DispatchReceiptTests.RECEIPT, "sent": "unconfirmed" if resend else False}
                    receipt.write_text(json.dumps(run), encoding="utf-8")
                    args = SimpleNamespace(address="t7", message="a task", run=receipt, resend=resend)
                    with (
                        patch("dispatch.hc_json", side_effect=[self.screen("Unrelated screen"), unrelated]) as hc,
                        patch("dispatch.time.monotonic", side_effect=[0, 30]),
                        redirect_stderr(StringIO()) as stderr,
                    ):
                        with self.assertRaisesRegex(SystemExit, "terminal identity changed"):
                            send(args)
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertEqual(hc.call_args_list, [call("read", "--lines", "0", "t7"), call("get", "t7")])

    @staticmethod
    def screen(text):
        return {"complete": True, "how": "screen", "text": text}

    def test_send_presses_enter_once_for_a_paste_left_in_the_composer(self):
        message = ('$task-next --tree\nOriginal user request: Review the next ticket.\n'
                   'Assigned unit: Next ticket\nUser Git limits: No push')
        responses = [
            self.screen(self.READY), self.IDLE, {"started": False},
            self.screen(self.PASTE), self.IDLE,
            self.screen(self.PASTE), self.IDLE, {},
            self.screen(self.READY), self.WORKING, self.screen(self.READY),
        ]
        with patch("dispatch.hc_json", side_effect=responses) as hc, \
                patch("dispatch.time.sleep"), patch("builtins.print") as output:
            send(SimpleNamespace(address="t7", message=message))
        self.assertEqual(hc.call_args_list, [
            call("read", "--lines", "0", "t7"), call("get", "t7"),
            call("send", "--if", "idle", "--", "t7", message),
            call("read", "--lines", "0", "t7"), call("get", "t7"),
            call("read", "--lines", "0", "t7"), call("get", "t7"), call("keys", "t7", "enter"),
            call("read", "--lines", "0", "t7"), call("get", "t7"), call("read", "--lines", "0", "t7"),
        ])
        output.assert_any_call("warning: no dispatch receipt. Use --run to carry handoff metadata",
                               file=sys.stderr)
        self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_leaves_enter_alone_once_the_turn_started(self):
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True},
            self.screen(self.PASTE), {**self.WORKING, "turn": 1},
            self.screen(self.READY), {**self.WORKING, "turn": 1}, self.screen(self.READY),
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
            ("a task", '› <hc from="t6 lead" reach="send results">\n  a task</hc>'),
            ("a task", '› <hc from="t6 lead"\n  reach="send results">a task</hc>'),
            ("a task", '› <hc from="t6">a task</hc>\n\n'),
        ):
            with self.subTest(prompt=prompt):
                expanded = self.screen(f"{prompt}\n\n  GPT-6.2-Sol default · ~/repo")
                ready = self.screen(self.READY)
                responses = {
                    "read": iter((ready, expanded, expanded, expanded, expanded, ready, ready)),
                    "get": iter((self.IDLE, working, idle, idle, idle, working)),
                }

                def respond(command, *_args):
                    return next(responses[command]) if command in responses else {}

                with patch("dispatch.hc_json", side_effect=respond) as hc, \
                        patch("dispatch.time.sleep"), patch("builtins.print") as output:
                    send(SimpleNamespace(address="t7", message=message))
                self.assertEqual(hc.call_args_list.count(call("keys", "t7", "enter")), 1)
                self.assertEqual(hc.call_count, 15)
                self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_requires_working_status_and_a_clear_composer_in_the_same_poll(self):
        idle = {**self.IDLE, "turn": 1}
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True},
            self.screen("› a task\n\n• Working"), self.WORKING,
            self.screen(self.READY), idle,
            self.screen(self.READY), self.WORKING, self.screen(self.READY),
        ]) as hc, patch("dispatch.time.sleep"), patch("builtins.print") as output:
            send(self.ARGS)
        self.assertEqual(hc.call_count, 10)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)
        self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_does_not_retry_enter_on_an_unrelated_prompt(self):
        for prompt in ("› another draft", "› a", "› a task\n  with an extra line", '› <hc from="t6">a</hc>'):
            with self.subTest(prompt=prompt):
                draft = self.screen(f"{prompt}\n\n  GPT-6.2-Sol default · ~/repo")
                ready = self.screen(self.READY)
                responses = {
                    "read": iter((ready, draft, draft, ready, ready)),
                    "get": iter((self.IDLE, self.IDLE, self.IDLE, self.WORKING)),
                }

                def respond(command, *_args):
                    return next(responses[command]) if command in responses else {}

                with patch("dispatch.hc_json", side_effect=respond) as hc, \
                        patch("dispatch.time.sleep"), patch("builtins.print"):
                    send(self.ARGS)
                self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)

    def test_send_ignores_hook_words_in_the_echoed_task(self):
        echoed = f"› Investigate the following\n  Hook failed on SessionStart\n\n{self.READY}"
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True},
            self.screen(echoed), self.WORKING, self.screen(echoed),
        ]) as hc, patch("builtins.print") as output:
            send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)
        self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_send_does_not_mistake_quoted_plugin_failure_for_the_cause(self):
        message = "Investigate this example:\nHook failed\n└ plugin contents changed; hook approval required"
        echoed = message.replace("\n", "\n  ")
        failed = f"› {echoed}\n\n• Hook failed\n  └ Policy prevented this action.\n\n{self.READY}"
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True}, self.screen(failed),
        ]), redirect_stderr(StringIO()):
            with self.assertRaisesRegex(SystemExit, "hook problem after the send"):
                send(SimpleNamespace(address="t7", message=message))

    def test_send_confirms_delivery_when_an_unrelated_warning_appears_late(self):
        warning = f"{self.READY}\n  ⚠ 1 warning · f2 to view"
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True},
            self.screen(self.READY), self.WORKING, self.screen(warning),
        ]), redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
            send(self.ARGS)
        self.assertIs(json.loads(output.getvalue())["submitted"], True)

    def test_send_reports_a_real_hook_failure_after_delivery(self):
        failed = f"› Investigate\n\n• Hook failed\n  └ plugin contents changed; hook approval required\n{self.READY}"
        with patch("dispatch.hc_json", side_effect=[
            self.screen(self.READY), self.IDLE, {"started": True}, self.screen(failed),
        ]) as hc:
            with self.assertRaisesRegex(SystemExit, "blocked after the send.*hook approval required"):
                send(self.ARGS)
        self.assertNotIn(call("keys", "t7", "enter"), hc.call_args_list)

    def test_plugin_hook_failure_can_follow_the_first_working_frame(self):
        failed = f"› a task\n\n• Hook failed\n  └ plugin contents changed; hook approval required\n\n{self.READY}"
        for launch_task in (False, True):
            with self.subTest(launch_task=launch_task), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "run.json"
                reads = iter((self.READY, self.READY, failed))
                operations = []

                def respond(command, *_args):
                    if command == "read":
                        return self.screen(next(reads))
                    if command == "get":
                        turn = self.WORKING if operations else self.IDLE
                        return {**DispatchReceiptTests.TERMINAL, **turn}
                    operations.append(command)
                    return {"started": True}

                with (patch("builtins.print", wraps=print) as output, redirect_stdout(StringIO()),
                      redirect_stderr(StringIO()), patch("dispatch.time.sleep")):
                    with self.assertRaisesRegex(SystemExit, "plugin contents changed.*hook approval required"):
                        if launch_task:
                            self.launch_codex(directory, respond)
                        else:
                            receipt.write_text(json.dumps(DispatchReceiptTests.RECEIPT), encoding="utf-8")
                            with patch("dispatch.hc_json", side_effect=respond):
                                send(SimpleNamespace(address="t7", message="a task", run=receipt))
                self.assertFalse(any('"submitted": true' in entry.args[0] for entry in output.call_args_list))
                self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["sent"], "unconfirmed")
                self.assertEqual(operations, ["send"])

    def test_send_detects_approval_failures_that_render_during_the_settle_window(self):
        reason = "plugin contents changed; hook approval required"
        for failure, shows_at in (
            (f"⚠ {reason}", 0.25),
            (f"• Hook failed\n  └ SessionStart hook\n  └ {reason}", 0.25),
            (f"• Hook failed\n  └ {reason}", 1.5),
        ):
            with self.subTest(failure=failure, shows_at=shows_at):
                now = 0.0
                sent = False

                def advance(seconds):
                    nonlocal now
                    now += seconds

                def respond(command, *_args):
                    nonlocal sent
                    if command == "read":
                        shown = f"{failure}\n\n{self.READY}" if shows_at <= now < shows_at + 0.25 else self.READY
                        return self.screen(shown)
                    if command == "get":
                        return self.WORKING if sent else self.IDLE
                    self.assertEqual(command, "send")
                    sent = True
                    return {"started": True}

                with (patch("dispatch.hc_json", side_effect=respond),
                      patch("dispatch.POST_SEND_SETTLE_SECONDS", POST_SEND_SETTLE_SECONDS),
                      patch("dispatch.time.monotonic", side_effect=lambda: now),
                      patch("dispatch.time.sleep", side_effect=advance), redirect_stderr(StringIO()),
                      redirect_stdout(StringIO()) as output):
                    with self.assertRaisesRegex(SystemExit, "plugin contents changed.*hook approval required"):
                        send(self.ARGS)
                self.assertEqual(output.getvalue(), "")

    def test_lost_send_does_not_retry_when_an_indented_hook_blocker_appears(self):
        reads = iter((self.READY, self.READY))
        sends = []

        def respond(command, *_args):
            if command == "read":
                return self.screen(next(reads, f"  └ hook approval required\n\n{self.READY}"))
            if command == "get":
                return self.IDLE
            sends.append(command)
            return {"started": False}

        with (patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"),
              patch("dispatch.time.monotonic", side_effect=range(0, 120, 6)), redirect_stderr(StringIO())):
            with self.assertRaisesRegex(SystemExit, "hook problem after the send"):
                send(self.ARGS)
        self.assertEqual(sends, ["send"])

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

    def test_owned_startup_turn_one_preserves_multiline_handoff_in_expanded_paste(self):
        ready = f"› Ask Codex to do anything\n\n{self.FOOTER_0171}"
        startup = self.screen(f"  >_ OpenAI Codex (v0.171.0)\n\n{ready}")
        owner = DispatchReceiptTests.TERMINAL
        idle = {**owner, "turn": 1, "status": {"state": "idle"}}
        busy = {**idle, "turn": 2, "status": {"state": "working"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            extra_lines = ["Use the team review checklist.", "• Confirm the target branch.",
                           "■ Follow the local workflow.", "› Run the tests.", "─ Worked for the dry run.",
                           "Hook approval required for the local workflow."]
            handoff = {**DispatchReceiptTests.HANDOFF, "extra_lines": extra_lines}
            run = {**DispatchReceiptTests.RECEIPT, "handoff": handoff}
            receipt.write_text(json.dumps(run), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="a task", run=receipt)
            expected = ("a task" + DispatchReceiptTests.BLOCK + "\n\n" + extra_lines[0] + "\n"
                        + "\n".join(f"> {line}" for line in extra_lines[1:]) + "\n\n"
                        + report_instruction(receipt.resolve().with_name("result.json")))
            stderr = StringIO()
            with patch("dispatch.hc_json", side_effect=[
                startup, idle, startup, {"started": True}, self.screen(ready), busy, self.screen(ready),
            ]) as hc, redirect_stderr(stderr), patch("sys.stdout", new_callable=StringIO):
                send(args)
            prompt = next(c.args[-1] for c in hc.call_args_list if c.args[0] == "send")
            rows = prompt.replace("\n", "\n  ")
            self.assertEqual(codex_screen(f"› {rows}\n\n{self.FOOTER_0171}", sent_message=prompt),
                             "paste")
            echoed = f"› {rows}\n\n• Completed\n\n{ready}"
            self.assertTrue(transcript_echoed(echoed, prompt))
            self.assertEqual(codex_screen(echoed), "ready")
            self.assertEqual(prompt, expected)
            self.assertIn("warning:", stderr.getvalue())
            self.assertTrue(json.loads(receipt.read_text(encoding="utf-8"))["sent"])
            with self.assertRaisesRegex(SystemExit, "only after the first task"):
                send(args)

    def test_owned_startup_turn_one_with_prior_prompt_is_refused(self):
        startup = self.screen(f"  >_ OpenAI Codex (v0.171.0)\n\n› Someone else's task\n\n{self.READY}")
        idle = {**DispatchReceiptTests.TERMINAL, "turn": 1, "status": {"state": "idle"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            run = {**DispatchReceiptTests.RECEIPT, "handoff": DispatchReceiptTests.HANDOFF}
            receipt.write_text(json.dumps(run), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="$task-next", run=receipt)
            with patch("dispatch.hc_json", side_effect=[startup, idle, startup]) as hc:
                with self.assertRaisesRegex(SystemExit, "already started a turn"):
                    send(args)
            self.assertNotIn("send", [c.args[0] for c in hc.call_args_list])

    def test_unconfirmed_delivery_is_persisted_and_never_resent(self):
        owner = DispatchReceiptTests.TERMINAL
        idle = {**owner, "turn": 0, "status": {"state": "idle"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps(DispatchReceiptTests.RECEIPT), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="a task", run=receipt)
            stderr = StringIO()
            paste_still_in_composer = self.screen(self.PASTE)
            with (patch("dispatch.hc_json", side_effect=[
                self.screen(self.READY), idle, OSError(), paste_still_in_composer, idle, idle,
            ]) as hc, patch("dispatch.time.monotonic", side_effect=[0, 1, 6]), redirect_stderr(stderr)):
                with self.assertRaisesRegex(SystemExit, "could not confirm delivery"):
                    send(args)
                with self.assertRaisesRegex(SystemExit, "previous delivery is unconfirmed"):
                    send(args)
            self.assertEqual([c.args[0] for c in hc.call_args_list].count("send"), 1)
            self.assertEqual(hc.call_count, 6)
            self.assertIn("warning: legacy receipt has no handoff metadata", stderr.getvalue())

    def test_resend_keeps_the_original_phase_and_requires_a_clear_idle_composer(self):
        owner = DispatchReceiptTests.TERMINAL
        for phase in (False, True):
            with self.subTest(continuation=phase), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory).resolve() / "run.json"
                run = {**DispatchReceiptTests.RECEIPT, "sent": "unconfirmed", "sent_turn": int(phase),
                       "sent_continuation": phase, "handoff": DispatchReceiptTests.HANDOFF}
                receipt.write_text(json.dumps(run), encoding="utf-8")
                args = SimpleNamespace(address="t7", message="$task-next", run=receipt, resend=True)
                idle = {**owner, **self.IDLE, "turn": int(phase)}
                working = {**owner, **self.WORKING, "turn": int(phase)}
                ready = self.screen("›\n\n  ~/repo")
                draft = self.screen("›\n  a multiline draft\n\n  GPT-6.2-Sol default · ~/repo")
                dialog = self.screen("› 1. Yes\n  Press enter to continue")
                for frames, reason in (([draft], "composer is not clear"),
                                       ([self.screen(self.PASTE)], "composer is not clear"),
                                       ([dialog, idle], "composer is not clear"),
                                       ([ready, working], "terminal is not idle")):
                    with patch("dispatch.hc_json", side_effect=frames) as hc, redirect_stderr(StringIO()) as stderr:
                        with self.assertRaisesRegex(SystemExit, reason):
                            send(args)
                        self.assertFalse(any(c.args[0] in {"keys", "send"} for c in hc.call_args_list))
                        self.assertEqual("Press enter to continue" in stderr.getvalue(), frames[0] == dialog)
                with patch("dispatch.hc_json", side_effect=[ready, idle, {}, ready, working, ready]) as hc, \
                        redirect_stdout(StringIO()):
                    send(args)
                prompt = hc.call_args_list[2].args
                self.assertEqual(prompt[:-1], ("send", "--if", "idle", "--", "t7"))
                expected = "$task-next" + ("" if phase else DispatchReceiptTests.BLOCK)
                self.assertEqual(prompt[-1], expected + "\n\n" + report_instruction(receipt.with_name("result.json")))
                self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["sent"], True)

    def test_resend_retries_a_followup_on_the_same_completed_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            run = {**DispatchReceiptTests.RECEIPT, "sent": "unconfirmed", "sent_turn": 3, "sent_continuation": True}
            receipt.write_text(json.dumps(run), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="next phase", run=receipt, resend=True)
            done = {**DispatchReceiptTests.TERMINAL, "turn": 3, "status": {"state": "done"}}
            ready = self.screen(self.READY)
            later = {**done, "turn": 4}
            working = {**done, "turn": 4, "status": {"state": "working"}}
            for advanced in (later, {**later, "status": {"state": "idle"}}):
                with (
                    patch("dispatch.hc_json", side_effect=[ready, advanced, advanced, {}, ready, working]) as hc,
                    redirect_stdout(StringIO()),
                ):
                    with self.assertRaisesRegex(SystemExit, "the recorded turn no longer matches"):
                        send(args)
                    self.assertEqual(hc.call_count, 2)

            with patch("dispatch.hc_json", side_effect=[ready, done, done, {}, ready, working, ready]) as hc, \
                    redirect_stdout(StringIO()):
                send(args)
            self.assertEqual(hc.call_args_list[3].args[:3], ("send", "--", "t7"))
            self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["sent"], True)

    def test_resend_preserves_handoff_for_a_legacy_startup_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory).resolve() / "run.json"
            run = {**DispatchReceiptTests.RECEIPT, "sent": "unconfirmed", "sent_turn": 1,
                   "handoff": DispatchReceiptTests.HANDOFF}
            receipt.write_text(json.dumps(run), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="$task-next", run=receipt, resend=True)
            idle = {**DispatchReceiptTests.TERMINAL, **self.IDLE, "turn": 1}
            working = {**idle, "status": {"state": "working"}}
            ready = self.screen(self.READY)
            with patch("dispatch.hc_json", side_effect=[ready, idle, {}, ready, working]) as hc, \
                    redirect_stdout(StringIO()):
                with self.assertRaisesRegex(SystemExit, "first task phase is ambiguous"):
                    send(args)
                self.assertEqual(hc.call_count, 2)
            startup = self.screen(f"  >_ OpenAI Codex (v0.171.0)\n\n{self.READY}")
            with patch("dispatch.hc_json", side_effect=[startup, idle, {}, ready, working, ready]) as hc, \
                    redirect_stdout(StringIO()):
                send(args)
            expected = "$task-next" + DispatchReceiptTests.BLOCK
            self.assertEqual(hc.call_args_list[2].args[-1],
                             expected + "\n\n" + report_instruction(receipt.with_name("result.json")))

    def test_resend_refuses_a_message_already_visible_in_the_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory).resolve() / "run.json"
            run = {**DispatchReceiptTests.RECEIPT, "sent": "unconfirmed", "sent_turn": 3, "sent_continuation": True}
            receipt.write_text(json.dumps(run), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="next phase", run=receipt, resend=True)
            message = args.message + "\n\n" + report_instruction(receipt.with_name("result.json"))
            echoed = self.screen(f"› {message}\n\n• Working\n\n{self.READY}")
            done = {**DispatchReceiptTests.TERMINAL, "turn": 3, "status": {"state": "done"}}
            working = {**done, "status": {"state": "working"}}
            with patch("dispatch.hc_json", side_effect=[echoed, done, done, {}, self.screen(self.READY), working]) as hc, \
                    redirect_stdout(StringIO()):
                with self.assertRaisesRegex(SystemExit, "already appears in the Codex transcript"):
                    send(args)
                self.assertEqual(hc.call_count, 2)
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), run)

    def test_continue_does_not_confirm_a_failed_send_from_unrelated_work(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            saved = {**DispatchReceiptTests.RECEIPT, "handoff": DispatchReceiptTests.HANDOFF}
            receipt.write_text(json.dumps(saved), encoding="utf-8")
            attempts = []
            unrelated = self.screen(f"› an unrelated message\n\n• Working\n\n{self.READY}")

            def respond(command, *args):
                if command == "read":
                    return unrelated if attempts else self.screen(self.READY)
                if command == "get":
                    state = self.WORKING if attempts else self.IDLE
                    return {**DispatchReceiptTests.TERMINAL, **state}
                attempts.append(command)
                raise subprocess.CalledProcessError(1, "hc")

            with (patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"),
                  patch("dispatch.time.monotonic", side_effect=range(1000))):
                with self.assertRaisesRegex(SystemExit, "could not confirm delivery"):
                    send(SimpleNamespace(address="t7", message="$task-next", run=receipt))
                with self.assertRaisesRegex(SystemExit, "previous delivery is unconfirmed"):
                    send(SimpleNamespace(address="t7", message="next", run=receipt, continuation=True))
            self.assertEqual(attempts, ["send"])
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["sent"], "unconfirmed")

    def test_owned_first_task_clears_a_stray_draft_once(self):
        owner = DispatchReceiptTests.TERMINAL
        idle = {**owner, "turn": 0, "status": {"state": "idle"}}
        working = {**owner, "turn": 1, "status": {"state": "working"}}
        draft = self.screen("› or\n\n  GPT-6.2-Sol default · ~/repo")
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps({**DispatchReceiptTests.RECEIPT, "handoff": DispatchReceiptTests.HANDOFF}),
                               encoding="utf-8")
            with patch("dispatch.hc_json", side_effect=[
                draft, idle, {}, self.screen(self.READY), idle, {"started": True}, self.screen(self.READY), working,
                self.screen(self.READY),
            ]) as hc, patch("dispatch.time.sleep"), patch("builtins.print") as output:
                send(SimpleNamespace(address="t7", message="$task-next", run=receipt))
            self.assertIn(call("keys", "t7", "ctrl+u"), hc.call_args_list)
            self.assertEqual([c.args[0] for c in hc.call_args_list].count("send"), 1)
            output.assert_any_call("warning: cleared a stray draft from the composer: 'or'", file=sys.stderr)
            self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["sent"], True)

    def test_cleared_draft_survives_a_stale_frame_and_spans_several_rows(self):
        owner = DispatchReceiptTests.TERMINAL
        idle = {**owner, "turn": 0, "status": {"state": "idle"}}
        working = {**owner, "turn": 1, "status": {"state": "working"}}
        two_rows = self.screen("› foo\n  bar\n\n  GPT-6.2-Sol default · ~/repo")
        one_row = self.screen("› foo\n\n  GPT-6.2-Sol default · ~/repo")
        ready = self.screen(self.READY)
        reads = iter((two_rows, two_rows, one_row, ready, ready, ready))
        gets = iter((idle, idle, idle, idle, working))

        def respond(command, *_args):
            return next(reads) if command == "read" else next(gets) if command == "get" else {}

        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps({**DispatchReceiptTests.RECEIPT, "handoff": DispatchReceiptTests.HANDOFF}),
                               encoding="utf-8")
            clock = [0.0]
            with patch("dispatch.hc_json", side_effect=respond) as hc, \
                    patch("dispatch.time.sleep", side_effect=lambda _: clock.__setitem__(0, clock[0] + 0.6)), \
                    patch("dispatch.time.monotonic", side_effect=lambda: clock[0]), \
                    patch("builtins.print") as output:
                send(SimpleNamespace(address="t7", message="$task-next", run=receipt))
        self.assertEqual(hc.call_args_list.count(call("keys", "t7", "ctrl+u")), 2)
        output.assert_any_call("warning: cleared a stray draft from the composer: 'foo\\nbar'", file=sys.stderr)

    def test_draft_after_a_real_turn_is_not_cleared(self):
        busy = self.screen("› earlier task\n\n• Done\n\n› note\n\n  GPT-6.2-Sol default · ~/repo")
        idle = {**DispatchReceiptTests.TERMINAL, "turn": 1, "status": {"state": "idle"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps({**DispatchReceiptTests.RECEIPT, "handoff": DispatchReceiptTests.HANDOFF}),
                               encoding="utf-8")
            with patch("dispatch.hc_json", side_effect=[busy, idle]) as hc:
                with self.assertRaisesRegex(SystemExit, "already started a turn"):
                    send(SimpleNamespace(address="t7", message="$task-next", run=receipt))
        self.assertNotIn("keys", [c.args[0] for c in hc.call_args_list])

    def test_submission_echoed_in_the_transcript_is_not_resent(self):
        sends = []
        echoed = self.screen(f"› a task\n\n{self.READY}")

        def respond(command, *args):
            if command == "read":
                return self.screen(self.READY) if not sends else echoed
            if command == "get":
                return self.IDLE
            sends.append(args)
            raise subprocess.CalledProcessError(1, "hc")

        with patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"), \
                patch("dispatch.time.monotonic", side_effect=range(1000)), redirect_stderr(StringIO()):
            with self.assertRaisesRegex(SystemExit, "could not confirm delivery"):
                send(self.ARGS)
        self.assertEqual(len(sends), 1)

    def test_draft_without_an_owned_first_task_is_reported_not_cleared(self):
        draft = self.screen("› or\n\n  GPT-6.2-Sol default · ~/repo")
        with patch("dispatch.hc_json", side_effect=[draft]) as hc:
            with self.assertRaisesRegex(SystemExit, "composer holds a draft: 'or'"):
                send(self.ARGS)
        self.assertNotIn("keys", [c.args[0] for c in hc.call_args_list])

    def test_lost_submission_is_sent_once_more(self):
        for failure in (None, subprocess.CalledProcessError(1, "hc")):
            with self.subTest(failure=failure):
                sends = []

                def respond(command, *args):
                    if command == "read":
                        return self.screen(self.READY)
                    if command == "get":
                        return self.WORKING if len(sends) == 2 else self.IDLE
                    sends.append(args)
                    if failure is not None and len(sends) == 1:
                        raise failure
                    return {"started": False}

                with patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"), \
                        patch("dispatch.time.monotonic", side_effect=range(1000)), \
                        patch("builtins.print") as output:
                    send(self.ARGS)
                self.assertEqual(len(sends), 2)
                output.assert_any_call("warning: the submission left no trace; sending it once more", file=sys.stderr)
                self.assertTrue(json.loads(output.call_args.args[0])["submitted"])

    def test_submission_with_a_trace_after_the_send_is_not_resent(self):
        sends = []
        reads = iter([self.screen(self.READY), self.screen(self.PASTE), self.screen(self.PASTE)])

        def respond(command, *args):
            if command == "read":
                return next(reads, self.screen(self.READY))
            if command == "get":
                return self.IDLE
            if command == "send":
                sends.append(args)
            return {}

        with patch("dispatch.hc_json", side_effect=respond) as hc, patch("dispatch.time.sleep"), \
                patch("dispatch.time.monotonic", side_effect=range(1000)), redirect_stderr(StringIO()):
            with self.assertRaisesRegex(SystemExit, "could not confirm submission"):
                send(self.ARGS)
        self.assertEqual(len(sends), 1)
        self.assertIn(call("keys", "t7", "enter"), hc.call_args_list)

    def test_lost_submission_is_not_sent_a_third_time(self):
        sends = []

        def respond(command, *args):
            if command == "read":
                return self.screen(self.READY)
            if command == "get":
                return self.IDLE
            sends.append(args)
            return {}

        with patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"), \
                patch("dispatch.time.monotonic", side_effect=range(1000)), redirect_stderr(StringIO()):
            with self.assertRaisesRegex(SystemExit, "could not confirm submission"):
                send(self.ARGS)
        self.assertEqual(len(sends), 2)

    def test_unconfirmed_receipt_is_accepted_once_the_child_started_a_turn(self):
        owner = DispatchReceiptTests.TERMINAL
        saved = {**DispatchReceiptTests.RECEIPT, "sent": "unconfirmed", "sent_turn": 0,
                 "handoff": DispatchReceiptTests.HANDOFF}
        transcript = self.screen(f"› $task-next\n\n• Working\n\n{self.READY}")
        startup = self.screen(f"  >_ OpenAI Codex (v0.171.0)\n\n{self.READY}")
        for terminal, screen, accepted in (
            ({**owner, "turn": 1, "status": {"state": "done"}}, transcript, True),
            ({**owner, "turn": 0, "status": {"state": "working"}}, transcript, True),
            ({**owner, "turn": 1, "status": {"state": "idle"}}, startup, False),
            ({**owner, "turn": 1, "status": {"state": "idle"}}, self.screen(self.PASTE), False),
            ({**owner, "turn": 0, "status": {"state": "idle"}}, transcript, False),
            ({**owner, "turn": 1, "status": {"state": "idle"}}, transcript, False),
        ):
            with self.subTest(terminal=terminal, screen=screen), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "run.json"
                receipt.write_text(json.dumps(saved), encoding="utf-8")
                args = SimpleNamespace(address="t7", message="next", run=receipt)
                with patch("dispatch.hc_json", side_effect=lambda command, *_: screen if command == "read" else terminal):
                    expected = "only after the first task" if accepted else "previous delivery is unconfirmed"
                    with self.assertRaisesRegex(SystemExit, expected):
                        send(args)
                self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["sent"],
                                 True if accepted else "unconfirmed")

    def test_continuation_rechecks_that_the_child_still_has_the_same_completed_turn(self):
        owner = DispatchReceiptTests.TERMINAL
        done = {**owner, "turn": 1, "status": {"state": "done"}}
        working = {**owner, "turn": 2, "status": {"state": "working"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            saved = {**DispatchReceiptTests.RECEIPT, "sent": True, "handoff": DispatchReceiptTests.HANDOFF}
            receipt.write_text(json.dumps(saved), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="next", run=receipt, continuation=True)
            with patch("dispatch.hc_json", side_effect=[self.screen(self.READY), done, working]) as hc:
                with self.assertRaisesRegex(SystemExit, "started another turn"):
                    send(args)
            self.assertNotIn("send", [entry.args[0] for entry in hc.call_args_list])
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), saved)
            with patch("dispatch.hc_json", side_effect=[
                self.screen(self.READY), done, done, {}, self.screen(self.READY), working, self.screen(self.READY),
            ]) as hc, patch("builtins.print"):
                send(args)
            prompts = [entry.args[-1] for entry in hc.call_args_list if entry.args[0] == "send"]
            self.assertEqual(len(prompts), 1)
            self.assertNotIn("<dispatch-handoff>", prompts[0])

    def test_continuation_accepts_a_result_without_status(self):
        owner = DispatchReceiptTests.TERMINAL
        done = {**owner, "turn": 1, "status": {"state": "done"}}
        working = {**owner, "turn": 2, "status": {"state": "working"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            saved = {**DispatchReceiptTests.RECEIPT, "sent": True, "handoff": DispatchReceiptTests.HANDOFF}
            receipt.write_text(json.dumps(saved), encoding="utf-8")
            receipt.with_name("result.json").write_text(
                json.dumps({"phase": "review", "pr": 779, "summary": "PR open"}), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="next", run=receipt, continuation=True)
            with patch("dispatch.hc_json", side_effect=[
                self.screen(self.READY), done, done, {}, self.screen(self.READY), working, self.screen(self.READY),
            ]) as hc, patch("builtins.print"):
                send(args)
            self.assertEqual(len([entry for entry in hc.call_args_list if entry.args[0] == "send"]), 1)
            self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["sent"], True)


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
