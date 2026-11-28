import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, call, patch

import phase_timing
import pinned_wave
import shared_codex
from dispatch import (
    POST_SEND_SETTLE_SECONDS,
    QUEUE_BACKEND,
    child_argv,
    child_name,
    codex_models_cache,
    codex_screen,
    collect,
    composer_draft,
    filtered_transcript,
    first_prompt,
    free_name,
    launch,
    lock_run,
    main,
    peek,
    pick,
    prepare_codex,
    release,
    report_instruction,
    resolve_codex_model,
    send,
    terminal_name,
    timing,
    transcript_echoed,
    transcript_offset,
    verify_delivery_turn,
    verify_pinned_delivery,
    verify_terminal,
    wait,
    write_json,
)
from quota import WEEK, assess, claude_snapshot
from quota import main as quota_main

SCRIPTS = Path(__file__).resolve().parent
QUOTA_OK = {"claude": {"state": "ok"}, "codex": {"state": "ok"},
            "bias": "none", "effective_bias": "none", "prefer_expiring_passes": False}


def setUpModule():
    home = Path(unittest.enterModuleContext(tempfile.TemporaryDirectory()))
    unittest.enterModuleContext(patch.dict(os.environ, {
        "CODEX_HOME": str(home / "codex"), "CLAUDE_CONFIG_DIR": str(home / "claude"),
        "QUOTA_CLAUDE_CACHE": str(home / "quota.json"),
    }))


class DispatchTestCase(unittest.TestCase):
    def setUp(self):
        self.quota = self.enterContext(patch("dispatch.read_quota_snapshot", return_value=QUOTA_OK))


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
        for model in ("gpt-6-luna", "gpt-6.1-terra", "gpt-6.2-sol"):
            with self.subTest(model=model):
                self.assertEqual(
                    child_argv("codex", model, "high", None, False),
                    ["codex", "--no-daemon", "--no-alt-screen", "--approve-for-me", "-m", model,
                     "-c", "model_reasoning_effort=high"],
                )
                with self.assertRaisesRegex(SystemExit, "codex takes no first message"):
                    child_argv("codex", model, "high", "$task-next", False)

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
        self.assertIn("timing run.json delivered", argv[-2])
        self.assertEqual(argv[-1], "/dev:task-next")


class DispatchReceiptTests(DispatchTestCase):
    TERMINAL = {"address": "t7", "parent": "t6", "created_ms": 50, "state": "live"}
    RECEIPT = {**TERMINAL, "cli": "codex", "sent": False, "screen_reads": 0}
    FIELDS = {"Original user request (verbatim)": "큐 모두 돌려 (--all)\n• Do the work\n- Git limits: example",
              "Assigned unit": "First queued item", "Git limits": " pr-only\nDon't merge. "}
    REVIEW_APPROVAL = '이 PR diff를 Claude와 agy에 보내도 됩니다.\n"Codex"도 승인합니다.'
    HANDOFF = {"work_kind": "queue", "request": FIELDS["Original user request (verbatim)"],
               "unit": FIELDS["Assigned unit"], "git_limits": FIELDS["Git limits"]}
    BLOCK = ("\n\nHandoff metadata (JSON):\n"
             "Task-cycle mode and flags come exclusively from the invocation above.\n"
             f"<dispatch-handoff>\n{json.dumps(FIELDS, ensure_ascii=False, indent=2)}\n</dispatch-handoff>")

    def test_parallel_queue_worktree_prompt_adds_phase_reading_guide(self):
        for cli, command in (("codex", "$task-next"), ("claude", "/dev:task-next")):
            with self.subTest(cli=cli):
                message = f"{command} --tree #511\nDispatch mode: parallel-worktree. Work only on #511."
                prompt = first_prompt(cli, message, self.HANDOFF)
                self.assertTrue(prompt.startswith(message + self.BLOCK))
                guide = prompt.removeprefix(message + self.BLOCK)
                for section in (
                    "Phase index", "outside code fences", "rg -n '^#{2,3} '", "tree.md → --tree mode",
                    "cycle.md → Branch", "cycle.md → Version bump, Cleanup, and Validation evidence",
                    "Step 4 and cycle.md → Hand off", "task-review-cycle → Caller gate",
                ):
                    self.assertIn(section, guide)

    def test_other_prompts_keep_existing_handoff(self):
        for message in (
            "$task-next",
            "$task-next --tree #511",
            "$task-next --all\nDispatch mode: parallel-worktree",
        ):
            with self.subTest(message=message):
                self.assertEqual(first_prompt("codex", message, self.HANDOFF), message + self.BLOCK)

    def launch_args(self, cwd, **overrides):
        args = dict(cwd=str(cwd), name="repo", parent="t6", cli="codex", model="gpt-6.1-terra",
                    effort="medium", task="$task-next", message=None, keep_connectors=False,
                    dry_run=False, git_grant_recorded=True, **self.HANDOFF)
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
                with (patch("dispatch.warn_linked_worktree"), redirect_stderr(stderr),
                      patch("sys.stdout", new_callable=StringIO) as stdout):
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

    def test_launch_requires_git_authority(self):
        for kind in ("queue", "new"):
            for limits in (
                None, "", " \n ", "  Not   Specified.  ", "N/A", "TBD", "unknown", "unknown limits",
                "unspecified", "none specified", "(none)", "?", "미지정", "없음", "implementation-only",
            ):
                with self.subTest(kind=kind, limits=limits), patch("dispatch.hc_json") as hc:
                    with self.assertRaisesRegex(SystemExit, "--no-git-writes"):
                        launch(self.launch_args(Path.cwd(), work_kind=kind, git_limits=limits))
                    hc.assert_not_called()
            with self.subTest(kind=kind), patch("dispatch.hc_json") as hc:
                with self.assertRaisesRegex(SystemExit, "--git-grant-recorded"):
                    launch(self.launch_args(Path.cwd(), work_kind=kind, git_limits="Do not push",
                                            git_grant_recorded=False))
                hc.assert_not_called()
        with self.assertRaisesRegex(SystemExit, "--no-git-writes.*--git-limits"):
            launch(self.launch_args(Path.cwd(), git_limits="pr-only", git_grant_recorded=False, no_git_writes=True))

    def test_launch_preserves_git_grant_or_marks_no_writes(self):
        grant = "2026-11-27, repository owner: Commit, push the branch and open a PR.\n"
        for kind, limits, no_writes, expected in (
            ("queue", grant, False, grant),
            ("new", "no-push", False, "no-push"),
            ("new", "pr-only", False, "pr-only"),
            ("queue", "none", False, "none"),
            ("queue", "", True, "implementation-only"),
            ("queue", "not specified", True, "implementation-only"),
            ("new", None, True, "implementation-only"),
            ("standalone", "not specified", False, "not specified"),
        ):
            with self.subTest(kind=kind, limits=limits, no_writes=no_writes):
                task = "$task-new Update docs" if kind == "new" else "$task-next --tree"
                args = self.launch_args(Path.cwd(), work_kind=kind, git_limits=limits, task=task,
                                        git_grant_recorded=limits == grant, no_git_writes=no_writes, dry_run=True)
                with patch("dispatch.warn_linked_worktree"), redirect_stdout(StringIO()) as stdout:
                    launch(args)
                prompt = json.loads(stdout.getvalue())["task"]
                handoff = prompt.split("<dispatch-handoff>\n", 1)[1].split("\n</dispatch-handoff>", 1)[0]
                self.assertEqual(json.loads(handoff)["Git limits"], expected)

        restrictions = "구현만 진행해 주세요.\n로컬 main도 갱신하지 마세요. "
        args = self.launch_args(Path.cwd(), git_limits=restrictions, git_grant_recorded=False,
                                no_git_writes=True, review_transfer_approval=self.REVIEW_APPROVAL, dry_run=True)
        with patch("dispatch.warn_linked_worktree"), redirect_stdout(StringIO()) as stdout:
            launch(args)
        prompt = json.loads(stdout.getvalue())["task"]
        handoff = prompt.split("<dispatch-handoff>\n", 1)[1].split("\n</dispatch-handoff>", 1)[0]
        self.assertEqual(json.loads(handoff), {
            **self.FIELDS,
            "Git limits": "implementation-only",
            "Additional Git limits (verbatim)": restrictions,
            "Review transfer approval (verbatim)": self.REVIEW_APPROVAL,
        })
        self.assertIn("including worktree preparation", prompt)
        self.assertIn("Quote them in a separate section of the Sprint Contract for handoff and resume.", prompt)

    def test_review_transfer_approval_survives_launch_and_first_send(self):
        grant = self.REVIEW_APPROVAL
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "launch",
                 "--cli", "codex", "--model", "gpt-6.1-terra", "--effort", "medium",
                 "--cwd", directory, "--work-kind", "standalone", "--request", "Review the PR",
                 "--unit", "PR review", "--git-limits", "pr-only", "--task", "Review the PR",
                 "--review-transfer-approval", grant, "--dry-run"],
                capture_output=True, text=True, encoding="utf-8",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = json.loads(result.stdout)["task"]
        fields = prompt.split("<dispatch-handoff>\n", 1)[1].split("\n</dispatch-handoff>", 1)[0]
        self.assertEqual(json.loads(fields), {
            "Original user request (verbatim)": "Review the PR",
            "Assigned unit": "PR review",
            "Git limits": "pr-only",
            "Review transfer approval (verbatim)": grant,
        })

    def test_title_labels_the_child_and_names_it_when_it_slugifies_to_ascii(self):
        cwd = Path(tempfile.gettempdir()) / "myrepo"
        for raw, name, title, expected in (
            ("Fix login timeout", None, "Fix login timeout", "myrepo-fix-login-timeout"),
            ("  Fix\nlogin  timeout ", None, "Fix login timeout", "myrepo-fix-login-timeout"),
            ("로그인 시간 초과 수정", None, "로그인 시간 초과 수정", "myrepo"),
            ("API 토큰 갱신", None, "API 토큰 갱신", "myrepo-api"),
            ("Update dispatch receipts title handling", None, "Update dispatch receipts title handling",
             "myrepo-update-dispatch-receipts"),
            ("Fix login timeout", "custom", "Fix login timeout", "custom"),
            (None, None, None, "myrepo"),
        ):
            with self.subTest(raw=raw, name=name), patch("dispatch.hc_json") as hc:
                args = self.launch_args(cwd, cli="claude", task=None, message="/dev:task-new Fix login",
                                        dry_run=True, name=name, title=raw)
                with patch("sys.stdout", new_callable=StringIO) as stdout:
                    launch(args)
                hc.assert_not_called()
                payload = json.loads(stdout.getvalue())
                argv = payload["argv"]
                self.assertEqual(payload["name"], expected)
                self.assertEqual(argv[argv.index("--name") + 1], expected)
                self.assertLessEqual(len(expected), 32)
                if title is None:
                    self.assertNotIn("--label", argv)
                    self.assertNotIn("title", payload)
                else:
                    label = argv.index("--label")
                    self.assertEqual(argv[label + 1], f"title={title}")
                    self.assertLess(label, argv.index("claude"))
                    self.assertEqual(payload["title"], title)

    def test_child_name_keeps_the_repo_when_the_title_cannot_fit(self):
        self.assertEqual(child_name("_" * 40, "Fix login timeout"), "_" * 32)

    def test_blank_title_stops_launch(self):
        with patch("dispatch.hc_json") as hc, self.assertRaisesRegex(SystemExit, "--title must not be blank"):
            launch(self.launch_args(Path.cwd(), title=" \n "))
        hc.assert_not_called()

    def test_cli_title_reaches_the_dry_run_preview(self):
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "launch",
             "--cli", "claude", "--model", "sonnet", "--effort", "medium", "--cwd", str(SCRIPTS),
             "--work-kind", "new", "--request", "요청", "--unit", "단위", "--git-limits", "none",
             "--title", "제목 Fix", "--dry-run", "/dev:task-new 단위"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["title"], "제목 Fix")
        self.assertEqual(payload["name"], "scripts-fix")
        self.assertIn("title=제목 Fix", payload["argv"])

    def test_cli_hook_trust_bypass_is_opt_in_for_both_single_and_idle_codex_launches(self):
        base = [sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "launch",
                "--cli", "codex", "--model", "gpt-6.2-sol", "--effort", "medium", "--cwd", str(SCRIPTS),
                "--work-kind", "queue", "--request", "request", "--unit", "unit", "--git-limits", "none",
                "--dry-run"]
        for trust in (False, True):
            for task in ([], ["--task", "$task-next"]):
                with self.subTest(trust=trust, single=bool(task)):
                    flags = ["--trust-hooks"] if trust else []
                    result = subprocess.run([*base, *flags, *task], capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout)
                    argv = payload["argv"]
                    native = "--dangerously-bypass-hook-trust"
                    self.assertEqual(argv.count(native), int(trust))
                    if trust:
                        self.assertGreater(argv.index(native), argv.index("codex"))
                    self.assertEqual("task" in payload, bool(task))

    def test_claude_rejects_hook_trust_bypass_before_start(self):
        args = self.launch_args(Path.cwd(), cli="claude", model="sonnet", task=None,
                                message="/dev:task-next", trust_hooks=True)
        with patch("dispatch.hc_json") as hc, patch("dispatch.subprocess.run") as run:
            with self.assertRaisesRegex(SystemExit, "--trust-hooks is only supported for Herdr Codex launches"):
                launch(args)
            hc.assert_not_called()
            run.assert_not_called()

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

    def test_launch_directory_config_takes_priority_over_an_ancestor_repo(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            home = outer / "home"
            (home / "repos").mkdir(parents=True)
            (home / "repos" / "handoff.json").write_text(
                json.dumps({"projects": ["Use the team review checklist."]}), encoding="utf-8"
            )
            args = self.launch_args("projects/app", dry_run=True)
            with patch("dispatch.Path.cwd", return_value=home), redirect_stdout(StringIO()) as stdout:
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
            args = self.launch_args(directory, user_pinned=True, trust_hooks=True)
            snapshot = {**QUOTA_OK, "bias": "claude", "effective_bias": "claude"}
            self.quota.return_value = snapshot
            owner = {"address": "t6", "state": "live", "cwd": str(home.parent)}
            live_owner = {**owner, "foreground": {"cwd": str(home)}}
            child = SimpleNamespace(stdout=json.dumps(self.TERMINAL))
            sibling = {"address": "t9", "state": "live", "parent": "t6"}
            calls = [{"terminals": [owner, sibling]}, live_owner, {"terminals": [sibling]}, self.TERMINAL]
            with (
                patch("dispatch.Path.cwd", return_value=home),
                patch("dispatch.verify_shared_cache_versions") as verify_versions,
                patch("dispatch.hc_json", side_effect=calls),
                patch("dispatch.subprocess.run", return_value=child) as run,
                patch("dispatch.tempfile.mkdtemp", return_value=directory),
                patch("dispatch.send") as submit,
                patch("builtins.print") as output,
            ):
                launch(args)
            verify_versions.assert_called_once()
            git_call, launch_call = run.call_args_list
            self.assertEqual(git_call.args[0][0], "git")
            argv = launch_call.args[0]
            self.assertEqual(argv[:3], ["hc", "run", "--bg"])
            self.assertIn("--no-notify", argv)
            self.assertTrue(any(arg.startswith(f"{shared_codex.LABEL}=") for arg in argv))
            self.assertEqual(argv[argv.index("--parent") + 1], "t6")
            self.assertIn("--dangerously-bypass-hook-trust", argv[argv.index("codex") + 1:])
            payload = json.loads(output.call_args.args[0])
            self.assertNotIn("shown", payload)
            self.assertNotIn("handoff", payload)
            receipt = json.loads(Path(payload["run"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["created_ms"], 50)
            self.assertTrue(receipt["require_review_sources"])
            self.assertFalse(receipt["sent"])
            self.assertEqual(receipt["quota_snapshot"], snapshot)
            self.assertEqual(receipt["bias"], "claude")
            self.assertIn("explicitly selected", receipt["user_pin_reason"])
            self.assertEqual(receipt["handoff"], {**self.HANDOFF, "extra_lines": extra_lines})
            self.assertEqual(submit.call_args.args[0].run, Path(payload["run"]))
            self.assertEqual(submit.call_args.args[0].message, "$task-next")

    def test_launch_keeps_the_receipt_when_terminal_lookup_fails_after_run(self):
        claude = {"task": None, "message": "/dev:task-next", "model": "opus"}
        for cli, overrides, lookup, detail in (
            ("codex", {}, subprocess.CalledProcessError(1, ["hc", "get"]), "task withheld: deliver it with send"),
            ("claude", claude, subprocess.TimeoutExpired(["hc", "get"], 30), "do not retry the launch"),
            ("claude", claude, {"address": "t7"}, "no created_ms"),
        ):
            with self.subTest(cli=cli, lookup=lookup), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                args = self.launch_args(directory, cli=cli, **overrides)
                owner = {"address": "t6", "state": "live", "cwd": str(home.parent),
                         "foreground": {"cwd": str(home)}}
                with (
                    patch("dispatch.Path.cwd", return_value=home),
                    patch("dispatch.hc_json", side_effect=[{"terminals": [owner]}, owner,
                                                               *([{"terminals": []}] if cli == "codex" else []), lookup]),
                    patch("dispatch.subprocess.run",
                          return_value=SimpleNamespace(stdout=json.dumps(self.TERMINAL))),
                    patch("dispatch.tempfile.mkdtemp", return_value=directory),
                    patch("dispatch.send") as submit,
                    patch("builtins.print") as output,
                ):
                    with self.assertRaisesRegex(SystemExit, f"t7: launched, but hc get failed.*{detail}"):
                        launch(args)
                submit.assert_not_called()
                payload = json.loads(output.call_args.args[0])
                self.assertEqual(payload["address"], "t7")
                receipt = json.loads(Path(payload["run"]).read_text(encoding="utf-8"))
                self.assertIsNone(receipt["created_ms"])
                with self.assertRaisesRegex(SystemExit, "identity unconfirmed"):
                    verify_terminal(dict(receipt), self.TERMINAL)  # created before the launch
                fresh = {**self.TERMINAL, "name": receipt["name"], "created_ms": receipt["launched_ms"] + 5}
                for other in ({"parent": "t9"}, {"name": "sibling"}):
                    with self.assertRaisesRegex(SystemExit, "identity unconfirmed"):
                        verify_terminal(dict(receipt), {**fresh, **other})
                verify_terminal(receipt, fresh)
                self.assertEqual(receipt["created_ms"], fresh["created_ms"])

    def test_collect_saves_the_identity_adopted_after_a_failed_launch_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            path.write_text(json.dumps({
                "name": "repo", "address": "t7", "parent": "t6", "created_ms": None, "launched_ms": 100,
                "cli": "claude", "model": "opus", "effort": "high", "sent": True, "screen_reads": 0,
            }), encoding="utf-8")
            terminal = {**self.TERMINAL, "name": "repo", "created_ms": 150,
                        "status": {"state": "working"}}
            with patch("dispatch.hc_json", return_value=terminal), redirect_stdout(StringIO()):
                collect(SimpleNamespace(run=str(path), close=False, force=False, stall_minutes=30))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["created_ms"], 150)

    def test_launch_without_an_address_from_hc_run_says_not_to_retry(self):
        args = self.launch_args(Path.cwd())
        owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd().parent),
                 "foreground": {"cwd": str(Path.cwd())}}
        with tempfile.TemporaryDirectory() as directory, (
            patch("dispatch.hc_json", side_effect=[{"terminals": [owner]}, owner, {"terminals": []}])
        ), patch("dispatch.subprocess.run", return_value=SimpleNamespace(stdout="{}")), (
            patch("dispatch.tempfile.mkdtemp", return_value=directory)
        ), patch("dispatch.send") as submit:
            with self.assertRaisesRegex(SystemExit, "no terminal address.*do not retry"):
                launch(args)
            submit.assert_not_called()
        failed = subprocess.TimeoutExpired(["hc", "run"], 30)
        with tempfile.TemporaryDirectory() as directory, (
            patch("dispatch.hc_json", side_effect=[{"terminals": [owner]}, owner, {"terminals": []}])
        ), patch("dispatch.subprocess.run", side_effect=[SimpleNamespace(stdout=""), failed]), (
            patch("dispatch.tempfile.mkdtemp", return_value=directory)
        ):
            with self.assertRaisesRegex(SystemExit, "hc run failed.*do not retry.*'repo'"):
                launch(args)

    def test_launch_records_the_title_in_the_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            title = "대시보드 제목 정리"
            args = self.launch_args(directory, name=None, title=title)
            owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd().parent),
                     "foreground": {"cwd": str(Path.cwd())}}
            child = SimpleNamespace(stdout=json.dumps(self.TERMINAL))
            with (
                patch("dispatch.hc_json", side_effect=[{"terminals": [owner]}, owner, {"terminals": []}, self.TERMINAL]),
                patch("dispatch.subprocess.run", return_value=child) as run,
                patch("dispatch.tempfile.mkdtemp", return_value=directory),
                patch("dispatch.send"),
                patch("builtins.print") as output,
            ):
                launch(args)
            argv = run.call_args_list[-1].args[0]
            self.assertEqual(argv[argv.index("--label") + 1], f"title={title}")
            self.assertEqual(argv[argv.index("--name") + 1], terminal_name(Path(directory).name))
            payload = json.loads(output.call_args.args[0])
            self.assertEqual(payload["title"], title)
            receipt = json.loads(Path(payload["run"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["title"], title)

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
                        self.assertEqual(hc.call_args_list, [
                            call("get", "t7"), call("read", "--lines", "0", "t7", timeout=ANY),
                        ])
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

    def test_collect_close_after_drift(self):
        change = ["dev 5.0.1 -> 5.0.4"]
        composer = "\n\n› Ask Codex to do anything"
        missing_hook = "• Hook failed\n  └ failed to spawn hook (os error 2)"
        cases = (
            ("idle", "ready", change, ["dev"], None, None, "hooks_broken"),
            ("idle", "ready", change, [], None, None, "plugin_drift"),
            ("idle", "ready", [], [], missing_hook + composer, ("idle", 10), "hooks_broken"),
            ("idle", "ready", [], [], missing_hook + composer, ("working", 11), None),
            ("idle", "ready", [], [], missing_hook + composer, ("idle", 12), None),
            ("idle", "ready", [], [], missing_hook + "\n\n• Review finished" + composer, None, None),
            ("idle", "ready", [], [], "• Hook failed\n  └ hook exited 1" + composer, None, None),
            ("done", "merged", change, ["dev"], None, None, "hooks_broken"),
            ("working", "ready", change, ["dev"], None, None, None),
            ("idle", "working", change, ["dev"], None, None, None),
            ("idle", None, change, ["dev"], None, None, None),
        )
        for state, status, changed, removed, screen, next_state, reason in cases:
            with self.subTest(state=state, result=status, screen=screen, next_state=next_state, reason=reason), \
                 tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "run.json"
                write_json(receipt, self.RECEIPT)
                if status:
                    write_json(receipt.with_name("result.json"), {
                        "status": status, "phase": "review", "summary": "Review result",
                    })
                terminal = {**self.TERMINAL, "status": {"state": state}, "status_ms": 10}
                replies = [terminal]
                calls = [call("get", "t7")]
                if screen:
                    replies.append({"how": "screen", "text": screen})
                    calls.append(call("read", "--lines", "0", "t7", timeout=ANY))
                if next_state:
                    current_state, status_ms = next_state
                    replies.append({**terminal, "status": {"state": current_state}, "status_ms": status_ms})
                    calls.append(call("get", "t7"))
                if reason or screen:
                    replies.extend([{}, {**terminal, "state": "finished"}, {}])
                if reason:
                    calls.extend([call("kill", "t7"), call("get", "t7", timeout=ANY), call("rm", "t7")])
                output = StringIO()
                with (
                    patch("dispatch.plugin_drift", return_value=(changed, removed)),
                    patch("dispatch.hc_json", side_effect=replies) as hc,
                    redirect_stderr(StringIO()),
                    redirect_stdout(output),
                ):
                    if reason:
                        try:
                            collect(SimpleNamespace(run=receipt, close=True))
                        except SystemExit as error:
                            self.fail(str(error))
                        self.assertEqual(json.loads(output.getvalue())["closed_reason"], reason)
                    else:
                        with self.assertRaisesRegex(SystemExit, "left intact"):
                            collect(SimpleNamespace(run=receipt, close=True))
                    self.assertEqual(hc.call_args_list, calls)
                self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")).get("closed_reason"), reason)

    def test_collect_close_does_not_treat_unverifiable_wave_as_drift(self):
        terminal = {**self.TERMINAL, "status": {"state": "idle"}}
        screen = {"how": "screen", "text": "› Ask Codex to do anything"}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            write_json(receipt, {**self.RECEIPT, "wave": str(Path(directory) / "wave.json")})
            write_json(receipt.with_name("result.json"), {
                "status": "ready", "phase": "review", "summary": "Review result",
            })
            with (
                patch("dispatch.pinned_wave.wave_path", return_value=Path(directory) / "wave.json"),
                patch("dispatch.pinned_wave.read_wave", side_effect=OSError("unreadable wave")),
                patch("dispatch.hc_json", side_effect=[terminal, screen, {**terminal, "state": "finished"}, {}]) as hc,
                redirect_stderr(StringIO()),
            ):
                with self.assertRaisesRegex(SystemExit, "left intact"):
                    collect(SimpleNamespace(run=receipt, close=True))
            self.assertEqual(hc.call_args_list, [
                call("get", "t7"), call("read", "--lines", "0", "t7", timeout=ANY),
            ])
            self.assertNotIn("closed_reason", json.loads(receipt.read_text(encoding="utf-8")))

    def test_collect_gates_ready_and_warns_on_completed_reports(self):
        terminal = {**self.TERMINAL, "status": {"state": "done"}}
        cases = (
            (None, ("claude", "agy", "codex", "no completed result")),
            ({"claude": "approval denied", "agy": "still running", "codex": "complete"},
             ("claude", "approval denied", "agy", "still running")),
            ({"claude": "complete", "agy": "complete", "codex": "complete"}, ()),
        )
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps({**self.RECEIPT, "require_review_sources": True}), encoding="utf-8")
            for status in ("ready", "done", "merged"):
                for sources, blockers in cases:
                    with self.subTest(status=status, sources=sources):
                        result = {"status": status, "phase": "review", "summary": "CI passed", "pr": "example-pr"}
                        if sources is not None:
                            result["review_sources"] = sources
                        write_json(receipt.with_name("result.json"), result)
                        output = StringIO()
                        with patch("dispatch.hc_json", return_value=terminal), redirect_stdout(output):
                            collect(SimpleNamespace(run=receipt, close=False))
                        reported = json.loads(output.getvalue())["result"]
                        expected = "blocked" if blockers and status == "ready" else status
                        self.assertEqual(reported["status"], expected)
                        self.assertEqual(reported["pr"], "example-pr")
                        if status != "ready":
                            self.assertEqual(reported["summary"], "CI passed")
                            self.assertEqual(reported["phase"], "review")
                        warning = reported["summary"] if status == "ready" else reported.get("review_warning", "")
                        for blocker in blockers:
                            self.assertIn(blocker, warning)

    def test_collect_warns_about_missing_reviews_without_blocking_done(self):
        with tempfile.TemporaryDirectory() as directory:
            for details, warning in (
                ({"head": "a" * 40}, True),
                ({"summary": "Opened PR #123"}, True),
                ({"summary": "PR #123을 열었습니다."}, True),
                ({"evidence": {"review": "https://github.com/acme/widget/pull/123을 열었습니다."}}, True),
                ({"summary": "No eligible work. PR #123 already merged."}, False),
                ({"summary": "처리할 이슈가 없습니다. PR #123은 이미 병합되었습니다."}, False),
                ({}, False),
            ):
                with self.subTest(details=details):
                    report, _ = self.collect_report(
                        directory, {"state": "done"}, receipt_fields={"require_review_sources": True},
                        result={"status": "done", "phase": "review", "summary": "Cycle completed", **details},
                    )
                    self.assertEqual(report["result"]["status"], "done")
                    self.assertEqual(report["result"]["summary"], details.get("summary", "Cycle completed"))
                    if warning:
                        self.assertIn("review_warning", report["result"])
                        self.assertIn("codex: no completed result", report["result"]["review_warning"])
                    else:
                        self.assertNotIn("review_warning", report["result"])

    def test_collect_can_close_a_merged_child_with_missing_review_evidence(self):
        terminal = {**self.TERMINAL, "status": {"state": "done"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            write_json(receipt, {**self.RECEIPT, "require_review_sources": True})
            write_json(receipt.with_name("result.json"), {
                "status": "merged", "phase": "merge", "summary": "Merged", "pr": "example-pr",
            })
            output = StringIO()
            with (
                patch("dispatch.hc_json", side_effect=[terminal, {}, {**terminal, "state": "finished"}, {}]),
                redirect_stdout(output),
            ):
                collect(SimpleNamespace(run=receipt, close=True, brief=True))
            self.assertIn("merged · merge · Merged", output.getvalue())
            self.assertIn("codex: no completed result", output.getvalue())
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["closed_reason"], "final_result")

    def test_report_review_writes_missing_source_reason_to_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            result = {
                "status": "ready", "phase": "review", "summary": "CI passed",
                "review_sources": {"claude": "complete", "agy": "리뷰 진행 중", "codex": "complete"},
                "ci": "success",
            }
            for outcome, status, phase, summary in (
                ("리뷰 진행 중", "blocked", "review-sources", "agy: 리뷰 진행 중"),
                ("complete", "ready", "review", "CI passed"),
            ):
                with self.subTest(outcome=outcome):
                    result["review_sources"]["agy"] = outcome
                    completed = subprocess.run(
                        [sys.executable, "-I", "-X", "utf8=0", str(SCRIPTS / "dispatch.py"), "report-review", str(path)],
                        env={**os.environ, "LC_ALL": "C"},
                        input=json.dumps(result, ensure_ascii=False).encode("utf-8"),
                        check=False, capture_output=True,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                                     {**result, "status": status, "phase": phase, "summary": summary})
                    self.assertEqual(list(path.parent.iterdir()), [path])

    def test_report_review_preserves_a_near_limit_blocked_result(self):
        result = {
            "status": "ready", "phase": "review", "summary": "CI passed",
            "review_sources": {"claude": "complete", "agy": "리뷰 진행 중" * 25, "codex": "complete"},
            "evidence": "",
        }
        base_size = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        result["evidence"] = "x" * (8192 - base_size)
        raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(raw), 8192)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, {"status": "working", "phase": "review", "summary": "CI passed"})
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "dispatch.py"), "report-review", str(path)],
                input=raw, check=False, capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
            self.assertLessEqual(path.stat().st_size, 8192)
            blocked = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(blocked["status"], "blocked")
            self.assertIn("agy:", blocked["summary"])
            details = json.loads((path.parent / blocked["evidence"]).read_text(encoding="utf-8"))
            self.assertEqual(details["review_sources"], result["review_sources"])
            self.assertEqual(details["evidence"], result["evidence"])

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
            screen = {"how": "screen", "text": "› Ask Codex to do anything"}
            with patch("dispatch.hc_json", side_effect=[live, screen]) as hc:
                with self.assertRaisesRegex(SystemExit, "left intact"):
                    collect(SimpleNamespace(run=receipt, close=True))
                self.assertEqual(hc.call_args_list, [
                    call("get", "t7"), call("read", "--lines", "0", "t7", timeout=ANY),
                ])

    def test_collect_reads_a_result_without_status_as_working(self):
        done = {**self.TERMINAL, "status": {"state": "done"}}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps(self.RECEIPT), encoding="utf-8")
            result = receipt.with_name("result.json")
            result.write_text(json.dumps({"phase": "review", "pr": 779, "summary": "PR open"}), encoding="utf-8")
            screen = {"how": "screen", "text": "› Ask Codex to do anything"}
            with patch("dispatch.hc_json", side_effect=[done, screen]), patch("builtins.print") as shown:
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

    def collect_report(self, directory, status, *, screen="", result=None, cli="codex", receipt_fields=None,
                       **terminal_fields):
        receipt = Path(directory) / "run.json"
        receipt.write_text(json.dumps({**self.RECEIPT, "sent": True, "cli": cli, **(receipt_fields or {})}),
                           encoding="utf-8")
        if result is not None:
            receipt.with_name("result.json").write_text(json.dumps(result), encoding="utf-8")
        terminal = {**self.TERMINAL, "status": status, **terminal_fields}
        snapshot = {"how": "screen", "text": screen}
        with patch("dispatch.hc_json", side_effect=[terminal, snapshot]) as hc, redirect_stdout(StringIO()) as out:
            collect(SimpleNamespace(run=receipt, close=False, stall_minutes=5))
        output = out.getvalue()
        self.assertEqual(len(output.splitlines()), 1)
        return json.loads(output), hc.call_args_list

    def test_collect_flags_a_codex_hook_failure_event_but_not_quoted_text(self):
        failure = ("• Hook failed\n  └ failed to spawn ~/.codex/plugins/cache/kadragon/dev/4.12.23/hooks/guard.sh"
                   " (os error 2)\n\n› Ask Codex to do anything")
        quoted = ("› Report '• Hook failed … os error 2' as hooks_broken. Sample:\n"
                  "  • Hook failed\n    └ os error 2\n\n"
                  "• Ran rg -n 'Hook failed' dev\n  └ dispatch.py:51:• Hook failed … os error 2\n"
                  "    • Hook failed\n    └ quoted again\n\n› Ask Codex to do anything")
        with tempfile.TemporaryDirectory() as directory:
            for state in ("idle", "done", "error"):
                with self.subTest(state=state):
                    report, calls = self.collect_report(directory, {"state": state}, screen=failure)
                    self.assertEqual(report["stop_reason"], "hooks_broken")
                    self.assertEqual(report["collect_screen_reads"], 1)
                    report, _ = self.collect_report(directory, {"state": state}, screen=quoted)
                    self.assertNotEqual(report["stop_reason"], "hooks_broken")
            report, _ = self.collect_report(directory, {"state": "idle"}, screen=failure, cli="claude")
            self.assertIsNone(report["stop_reason"])

    def test_collect_flags_a_child_whose_plugin_directory_was_removed(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as home:
            cache = Path(home) / "plugins" / "cache" / "kadragon"
            (cache / "dev" / "4.12.23").mkdir(parents=True)
            (cache / "prod" / "3.2.17").mkdir(parents=True)
            started = {"plugin_versions": {"dev": "4.12.23", "prod": "3.2.17"}}
            working = {"state": "working"}
            with patch.dict(os.environ, {"CODEX_HOME": home}):
                with redirect_stderr(StringIO()) as err:
                    report, calls = self.collect_report(directory, working, receipt_fields=started)
                self.assertIsNone(report["stop_reason"])
                self.assertNotIn("plugin_drift", report)
                self.assertEqual(calls, [call("get", "t7")])
                self.assertEqual(err.getvalue(), "")

                (cache / "dev" / "4.12.24").mkdir()
                with redirect_stderr(StringIO()) as err:
                    report, calls = self.collect_report(directory, working, receipt_fields=started,
                                                        screen="• Working (1m)")
                self.assertIsNone(report["stop_reason"])
                self.assertEqual(report["plugin_drift"], ["dev 4.12.23 -> 4.12.24"])
                self.assertEqual(calls[1:], [call("read", "--lines", "0", "t7", timeout=ANY)])
                self.assertIn("stop the child before its next Git write", err.getvalue())

                (cache / "dev" / "4.12.23").rmdir()
                with redirect_stderr(StringIO()) as err:
                    report, calls = self.collect_report(directory, working, receipt_fields=started)
                self.assertEqual(report["stop_reason"], "hooks_broken")
                self.assertEqual(calls, [call("get", "t7")])
                self.assertIn("dev 4.12.23 -> 4.12.24", err.getvalue())

                with redirect_stderr(StringIO()):
                    report, _ = self.collect_report(
                        directory, {"state": "done"}, receipt_fields=started,
                        result={"status": "merged", "phase": "merge", "summary": "Merged"})
                self.assertIsNone(report["stop_reason"])

    def test_another_home_cannot_launch_into_a_live_shared_codex_wave(self):
        args = self.launch_args(Path.cwd(), parent="t8")
        owner = {"address": "t8", "state": "live", "cwd": str(Path.cwd())}
        first_home_child = {"address": "t7", "state": "live", "parent": "t6"}
        with patch("dispatch.hc_json", side_effect=[
            {"terminals": [owner, first_home_child]}, owner, {"terminals": [first_home_child]},
        ]) as hc, patch("dispatch.subprocess.run") as run:
            with self.assertRaisesRegex(SystemExit, r"live wave uses this cache \(t7\)"):
                launch(args)
        self.assertEqual(hc.call_args.args[:2], ("ls", "--label"))
        self.assertTrue(hc.call_args.args[2].startswith(f"{shared_codex.LABEL}="))
        self.assertTrue(all(entry.args[0][0] != "hc" for entry in run.call_args_list))

    def test_same_home_launch_checks_the_fresh_remote_versions(self):
        owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd())}
        sibling = {"address": "t7", "state": "live", "parent": "t6"}
        versions = {"guard": "1.0.0"}
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            write_json(home / "dispatch-prepared-cache.json", {"repo": str(home), "versions": versions})
            with (
                patch.dict(os.environ, {"CODEX_HOME": directory}),
                patch("dispatch.hc_json", side_effect=[
                    {"terminals": [owner, sibling]}, owner, {"terminals": [sibling]},
                ]),
                patch("dispatch.installed_plugin_versions", return_value=versions),
                patch("shared_codex.remote_versions", return_value={"guard": "1.1.0"}) as remote,
                patch("dispatch.subprocess.run") as run,
            ):
                with self.assertRaisesRegex(SystemExit, "marketplace versions changed"):
                    launch(self.launch_args(Path.cwd()))
            remote.assert_called_once_with(home, versions)
            self.assertTrue(all(entry.args[0][0] != "hc" for entry in run.call_args_list))

    def test_launch_records_the_installed_codex_plugin_versions(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as home:
            cache = Path(home) / "plugins" / "cache" / "kadragon"
            for version in ("4.12.9", "4.12.23"):
                (cache / "dev" / version).mkdir(parents=True)
            (cache / "prod" / "3.2.17").mkdir(parents=True)
            owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd().parent),
                     "foreground": {"cwd": str(Path.cwd())}}
            child = SimpleNamespace(stdout=json.dumps(self.TERMINAL))
            with (
                patch.dict(os.environ, {"CODEX_HOME": home}),
                patch("dispatch.hc_json", side_effect=[{"terminals": [owner]}, owner, {"terminals": []}, self.TERMINAL]),
                patch("dispatch.subprocess.run", return_value=child),
                patch("dispatch.tempfile.mkdtemp", return_value=directory),
                patch("dispatch.send"),
                patch("builtins.print") as output,
            ):
                launch(self.launch_args(directory))
            receipt = json.loads(Path(json.loads(output.call_args.args[0])["run"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["plugin_versions"], {"dev": "4.12.23", "prod": "3.2.17"})

    def test_collect_reports_stop_reasons_in_one_line(self):
        with tempfile.TemporaryDirectory() as directory:
            for status, screen, expected, reads in (
                ({"state": "error", "msg": "You've hit your usage limit"}, "", "Usage limit reached", 0),
                ({"state": "done"}, "› task\n\nⓘ This content can’t be shown\n\n› Ask Codex to do anything",
                 "Stopped by a safety or usage-policy filter", 1),
                ({"state": "error"}, "■ Unexpected disconnection", "Child stopped on an error", 1),
                ({"state": "blocked", "kind": "permission"}, "Approve this operation?", "Waiting for a dialog", 0),
            ):
                with self.subTest(expected=expected):
                    report, calls = self.collect_report(directory, status, screen=screen)
                    self.assertEqual(report["stop_reason"], expected)
                    self.assertEqual(report["screen_reads"], self.RECEIPT["screen_reads"])
                    self.assertEqual(report["collect_screen_reads"], reads)
                    self.assertEqual(calls[0], call("get", "t7"))
                    self.assertEqual(calls[1:], [call("read", "--lines", "0", "t7", timeout=ANY)] if reads else [])

    def test_collect_uses_only_current_cli_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            for screen in (
                "ⓘ This content can’t be shown\n\n› new question\n\n› Ask Codex to do anything",
                "› question\n\n• Ran cat example.txt\n    This content can’t be shown\n\n› Ask Codex to do anything",
                "› question\n\n• Report: 'This content can’t be shown'\n\n› Ask Codex to do anything",
            ):
                with self.subTest(screen=screen):
                    report, _ = self.collect_report(directory, {"state": "done"}, screen=screen)
                    self.assertIsNone(report["stop_reason"])
            report, _ = self.collect_report(directory, {"state": "error"}, screen="■ API Error: Usage Policy")
            self.assertEqual(report["stop_reason"], "Stopped by a safety or usage-policy filter")
            report, _ = self.collect_report(directory, {"state": "done"}, screen="■ You've hit your usage limit")
            self.assertEqual(report["stop_reason"], "Usage limit reached")
            report, calls = self.collect_report(
                directory, {"state": "done"}, screen="ⓘ This content can’t be shown",
                result={"status": "merged", "phase": "merge", "summary": "Merged"},
            )
            self.assertIsNone(report["stop_reason"])
            self.assertEqual(calls, [call("get", "t7")])

    def test_collect_reports_terminal_errors_even_with_a_child_result(self):
        with tempfile.TemporaryDirectory() as directory:
            for status in ("ready", "blocked", "done"):
                with self.subTest(status=status):
                    result = {"status": status, "phase": "review", "summary": "Review status"}
                    report, calls = self.collect_report(directory, None, result=result, state="finished", exit_code=1)
                    self.assertEqual(report["stop_reason"], "Child exited with an error")
                    self.assertEqual(calls, [call("get", "t7")])
                    report, _ = self.collect_report(directory, {"state": "error"}, result=result)
                    self.assertEqual(report["stop_reason"], "Child stopped on an error")

    def test_collect_detects_a_resumed_child_stopping_after_a_previous_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            now_ms = time.time_ns() // 1_000_000
            screen = "› Next task\n\nⓘ This content can’t be shown\n\n› Ask Codex to do anything"
            for status in ("ready", "blocked"):
                with self.subTest(status=status):
                    result = {"status": status, "phase": "review", "summary": "Previous pause"}
                    report, _ = self.collect_report(directory, {"state": "done"}, result=result, screen=screen)
                    self.assertEqual(report["stop_reason"], "Stopped by a safety or usage-policy filter")
                    with patch("dispatch.time.time_ns", return_value=(now_ms + 6 * 60_000) * 1_000_000):
                        report, _ = self.collect_report(directory, {"state": "working"}, result=result,
                                                        status_ms=now_ms)
                        self.assertEqual(report["stop_reason"], "No new turn or commit for 5 minutes")

    def test_collect_reads_notices_above_codex_composer_with_unrelated_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            notice = "› task\n\nⓘ This content can’t be shown\n\n"
            for screen in (
                f"{notice}› Ask Codex to do anything\n\n  ⚠ 1 warning · f2 to view",
                f"• Hook failed in the previous turn\n\n{notice}› Ask Codex to do anything",
                f"{notice}› [Pasted Content 150 chars]",
            ):
                with self.subTest(screen=screen):
                    report, _ = self.collect_report(directory, {"state": "done"}, screen=screen)
                    self.assertEqual(report["stop_reason"], "Stopped by a safety or usage-policy filter")

    def test_collect_reads_indented_claude_policy_error(self):
        with tempfile.TemporaryDirectory() as directory:
            screen = "❯ task\n\n  ⎿  API Error: Usage Policy\n\n❯ "
            report, _ = self.collect_report(directory, {"state": "error"}, screen=screen, cli="claude")
            self.assertEqual(report["stop_reason"], "Stopped by a safety or usage-policy filter")

    def test_collect_reports_stall_after_both_turn_and_commit_are_old(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit",
                            "-qm", "initial", "--allow-empty"], cwd=repo, check=True)
            now_ms = time.time_ns() // 1_000_000
            activity = {"cwd": "/wrong-launch-path", "foreground": {"cwd": str(repo)},
                        "status_ms": now_ms - 6 * 60_000}
            report, calls = self.collect_report(directory, {"state": "working"}, **activity)
            self.assertIsNone(report["stop_reason"])
            self.assertEqual(calls, [call("get", "t7")])
            with patch("dispatch.time.time_ns", return_value=(now_ms + 6 * 60_000) * 1_000_000):
                report, _ = self.collect_report(directory, {"state": "working"}, **activity)
                self.assertEqual(report["stop_reason"], "No new turn or commit for 5 minutes")
                report, _ = self.collect_report(directory, {"state": "done"}, **activity)
                self.assertEqual(report["stop_reason"], "No new turn or commit for 5 minutes")
                report, _ = self.collect_report(directory, {"state": "working"}, **activity,
                                                screen="ⓘ This content can’t be shown")
                self.assertEqual(report["stop_reason"], "Stopped by a safety or usage-policy filter")
                report, calls = self.collect_report(directory, {"state": "working"},
                                                    **(activity | {"status_ms": now_ms + 5 * 60_000}))
                self.assertIsNone(report["stop_reason"])
                self.assertEqual(calls, [call("get", "t7")])

    def test_collect_only_flags_shared_categories_in_consecutive_sendbacks_for_the_same_change(self):
        earlier = {"change": "/archive/contract.md", "round": 1, "categories": ["input-validation", "atomicity"]}
        later = {**earlier, "round": 2, "categories": ["atomicity", "retry-safety"]}
        with tempfile.TemporaryDirectory() as directory:
            for history, expected in (
                ([earlier, later], ["atomicity"]),
                ([earlier, {**later, "categories": ["retry-safety"]}], []),
                ([earlier, {**later, "change": "/other/contract.md"}], []),
                ([earlier, earlier], []),
                ([earlier, {**later, "round": 3}], []),
                ([earlier, later, {**later, "round": 3, "categories": ["documentation"]}], []),
                ([earlier, {**later, "categories": "atomicity"}], []),
                ([later], []),
            ):
                with self.subTest(history=history):
                    result = {"status": "blocked", "phase": "review", "summary": "Review findings",
                              "review_sendbacks": history}
                    report, calls = self.collect_report(directory, {"state": "done"}, result=result)
                    self.assertEqual(report["scope_decision_categories"], expected)
                    self.assertEqual(calls, [call("get", "t7"), call("read", "--lines", "0", "t7", timeout=ANY)])
            report, _ = self.collect_report(directory, {"state": "done"}, result={
                "status": "ready", "phase": "review", "summary": "Review passed", "review_sendbacks": [earlier, later],
            })
            self.assertEqual(report["scope_decision_categories"], [])

    def test_collect_keeps_review_history_without_escalating_missing_sources_as_sendbacks(self):
        first = {"change": "/archive/contract.md", "round": 1, "categories": ["atomicity"]}
        history = [first, {**first, "round": 2}]
        with tempfile.TemporaryDirectory() as directory:
            report, _ = self.collect_report(directory, {"state": "done"},
                                            receipt_fields={"require_review_sources": True}, result={
                "status": "ready", "phase": "review", "summary": "Review passed", "review_sendbacks": history,
                "review_sources": {"claude": "complete", "agy": "still running", "codex": "complete"},
            })
        self.assertEqual(report["result"]["status"], "blocked")
        self.assertEqual(report["result"]["review_sendbacks"], history)
        self.assertEqual(report["scope_decision_categories"], [])

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
            candidates_script = QUEUE_BACKEND.with_name("backlog_candidates.py")
            for options, expected in cases:
                with self.subTest(options=options):
                    result = subprocess.run([*dispatch, *options], cwd=root, env=env, check=True,
                                            capture_output=True, text=True, encoding="utf-8")
                    candidates = json.loads(result.stdout)
                    self.assertEqual([item["title"] for item in candidates], expected, result.stderr)
                    direct = subprocess.run(
                        [sys.executable, "-I", "-X", "utf8", str(candidates_script), "--tasks", "tasks.md",
                         "--backlog", "backlog.md", "--json", "--counts",
                         *(["--ref", "origin/HEAD"] if "--tree" in options else []),
                         *(["--full-scan"] if "--full-scan" in options else [])],
                        cwd=repo, env=env, check=True, capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(candidates, json.loads(direct.stdout), "pick output is unchanged off GitHub")
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

    def test_pick_without_backlog_md_stops_only_on_the_file_queue(self):
        with tempfile.TemporaryDirectory(prefix="dispatch no queue ") as directory:
            root = Path(directory)
            repo = root / "plain"
            repo.mkdir()
            env = {**os.environ, "HOME": str(root), "USERPROFILE": str(root), "XDG_CONFIG_HOME": str(root)}
            env.pop("AGENT_QUEUE_BACKEND", None)
            subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
            subprocess.run(["git", "remote", "add", "origin", "https://git.example.org/owner/plain.git"],
                           cwd=repo, env=env, check=True)
            result = subprocess.run([sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "pick", str(repo)],
                                    env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("has no backlog.md: no queue", result.stderr)
            self.assertEqual(result.stdout, "")

    def test_pick_lists_issues_on_a_github_repo_without_backlog_md(self):
        sys.path.insert(0, str(QUEUE_BACKEND.parent))
        import queue_backend

        def connection(nodes=()):
            return {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(nodes)}

        repository = {"nameWithOwner": "owner/repo"}

        def issue(number, title, author="OWNER", parent=None, subs=(), prs=()):
            return {
                "number": number, "title": title, "body": "", "url": f"https://github.com/owner/repo/issues/{number}",
                "state": "OPEN", "authorAssociation": author, "repository": repository,
                "parent": parent and {"number": parent, "repository": repository},
                "labels": connection([{"name": "task-queue"}]), "blockedBy": connection(),
                "subIssues": connection({"number": n, "title": t, "state": "OPEN", "repository": repository}
                                        for n, t in subs),
                "closedByPullRequestsReferences": connection(prs),
            }

        issues = [
            issue(1, "[FEAT] Single issue"),
            issue(2, "[FEAT] Stranger's issue", author="NONE"),
            issue(3, "Parent", subs=[(4, "[DOCS] Child one"), (6, "[DOCS] Child two")]),
            issue(4, "[DOCS] Child one", parent=3),
            issue(5, "[FIX] Claimed issue", prs=[{"number": 9, "url": "https://github.com/owner/repo/pull/9",
                                                  "state": "OPEN", "authorAssociation": "OWNER"}]),
            issue(6, "[DOCS] Child two", parent=3),
        ]
        calls = []

        def runner(args):
            query = next(a for a in args if a.startswith("query="))
            calls.append(query)
            if "issues(first" in query:
                return 0, json.dumps({"data": {"repository": {
                    "isPrivate": True, "issues": {**connection(issues)}}}}), ""
            return 0, json.dumps({"data": {"repository": {"visibility": "PRIVATE"}}}), ""

        def queue_op(op, request):
            code, data = queue_backend.handle(op, json.loads(json.dumps(request)), {}, runner)
            self.assertEqual(code, 0)
            return data

        with tempfile.TemporaryDirectory(prefix="dispatch github ") as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"],
                           cwd=repo, check=True)
            (repo / "tasks.md").write_text("# Sprint\nstatus: active\n", encoding="utf-8")
            out, err = StringIO(), StringIO()
            with patch("dispatch.queue_op", side_effect=queue_op), redirect_stdout(out), redirect_stderr(err):
                pick(SimpleNamespace(repo=str(repo), tree=False, full_scan=True))

        self.assertTrue(any("visibility } }" in q for q in calls), "the missing backlog.md asks for the backend")
        candidates = json.loads(out.getvalue())
        self.assertEqual([(c["ref"], c["title"], c["items"], c["open"]) for c in candidates],
                         [("#1", "[FEAT] Single issue", 1, 1), ("#3", "Parent", 2, 2)])
        self.assertEqual({c["source"] for c in candidates}, {"issues"})
        self.assertEqual(candidates[0]["url"], "https://github.com/owner/repo/issues/1")
        self.assertIn("skipped #2", err.getvalue())
        self.assertIn("#5 claimed by https://github.com/owner/repo/pull/9", err.getvalue())
        self.assertNotIn("no queue", err.getvalue())
        self.assertIn("tasks.md exists, but this repo's queue backend does not list its sprint blocks", err.getvalue())

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
                        "--cli", "codex", "--model", "gpt-6-luna", "--effort", "low", "--cwd", str(nested),
                        "--work-kind", "new", "--request", "Task", "--unit", "Task", "--git-limits", "none"]
                result = subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual("inside a linked worktree" in result.stderr, checkout == linked)
                self.assertEqual("Launch from the main checkout and add --tree" in result.stderr, checkout == linked)


class CodexModelTests(DispatchTestCase):
    CACHE = {"models": [
        {"slug": "gpt-6.2-sol", "visibility": "list", "upgrade": None},
        {"slug": "gpt-6.10-sol", "visibility": "hide", "upgrade": None},
        {"slug": "gpt-6.1-sol", "visibility": "list", "upgrade": None},
        {"slug": "gpt-7-sol", "visibility": "list", "upgrade": {"model": "gpt-6.2-sol"}},
        {"slug": "gpt-6.1-terra", "visibility": "list", "upgrade": None},
        {"slug": "gpt-5.6-terra", "visibility": "list", "upgrade": {"model": "gpt-6.1-terra"}},
        {"slug": "gpt-5.6-luna", "visibility": "list", "upgrade": None},
        {"slug": "gpt-6-luna", "visibility": "list", "upgrade": None},
        {"slug": "gpt-6.2-astra", "visibility": "list", "upgrade": None},
        {"slug": "gpt-reserve", "visibility": "hide", "upgrade": None},
        {"slug": "codex-auto-review", "visibility": "hide"},
    ]}

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        (self.home / "models_cache.json").write_text(json.dumps(self.CACHE), encoding="utf-8")
        environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)

    def launch_args(self, model, cli="codex", dry_run=True):
        return DispatchReceiptTests().launch_args(Path.cwd(), cli=cli, model=model, dry_run=dry_run,
                                                  task="$task-next" if cli == "codex" else None,
                                                  message="/dev:task-next" if cli == "claude" else None)

    def test_family_resolves_to_newest_listed_non_retiring_slug(self):
        for family, slug in (("sol", "gpt-6.2-sol"), ("terra", "gpt-6.1-terra"), ("luna", "gpt-6-luna"),
                             ("Sol", "gpt-6.2-sol"), ("LUNA", "gpt-6-luna")):
            with self.subTest(family=family):
                self.assertEqual(resolve_codex_model(family), slug)

    def test_full_slug_or_other_model_id_passes_through_without_reading_the_cache(self):
        (self.home / "models_cache.json").unlink()
        for slug in ("gpt-5.6-terra", "gpt-reserve", "gpt-9-sol", "llama", "nova"):
            with self.subTest(slug=slug):
                self.assertEqual(resolve_codex_model(slug), slug)

    def test_missing_unreadable_or_unmatched_cache_is_a_hard_error(self):
        cache = self.home / "models_cache.json"
        cache.write_text(json.dumps({"models": [
            {"slug": "gpt-5.6-terra", "visibility": "list", "upgrade": {"model": "gpt-6.1-terra"}},
            {"slug": "gpt-6.1-terra", "visibility": "hide", "upgrade": None},
            {"slug": "terra", "visibility": "list", "upgrade": None},
        ]}), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "no listed, non-retiring gpt-<version>-terra"):
            resolve_codex_model("terra")
        for content in (None, "not json", json.dumps({"other": []})):
            with self.subTest(content=content):
                if content is None:
                    cache.unlink(missing_ok=True)
                else:
                    cache.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "unreadable models cache"):
                    resolve_codex_model("sol")

    def test_default_cache_is_under_the_home_codex_directory(self):
        with patch.dict(os.environ, {"CODEX_HOME": ""}), patch("dispatch.Path.home", return_value=self.home):
            self.assertEqual(codex_models_cache(), self.home / ".codex" / "models_cache.json")

    def test_dry_run_records_family_and_resolved_slug(self):
        for model, expected in (("sol", {"model": "gpt-6.2-sol", "model_family": "sol"}),
                                ("Sol", {"model": "gpt-6.2-sol", "model_family": "Sol"}),
                                ("gpt-6.1-sol", {"model": "gpt-6.1-sol"})):
            with self.subTest(model=model), patch("sys.stdout", new_callable=StringIO) as stdout:
                launch(self.launch_args(model))
                payload = json.loads(stdout.getvalue())
                self.assertEqual({key: payload.get(key) for key in expected}, expected)
                self.assertEqual("model_family" in payload, "model_family" in expected)
                argv = payload["argv"]
                self.assertEqual(argv[argv.index("-m") + 1], expected["model"])

    def test_receipt_records_family_and_resolved_slug(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.launch_args("luna", dry_run=False)
            args.cwd = directory
            owner = {"address": "t6", "state": "live", "cwd": str(Path.cwd().parent),
                     "foreground": {"cwd": str(Path.cwd())}}
            child = SimpleNamespace(stdout=json.dumps(DispatchReceiptTests.TERMINAL))
            with (
                patch("dispatch.hc_json", side_effect=[{"terminals": [owner]}, owner, {"terminals": []},
                                                               DispatchReceiptTests.TERMINAL]),
                patch("dispatch.subprocess.run", return_value=child) as run,
                patch("dispatch.tempfile.mkdtemp", return_value=directory),
                patch("dispatch.send"),
                patch("builtins.print") as output,
            ):
                launch(args)
            argv = run.call_args_list[-1].args[0]
            self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")
            payload = json.loads(output.call_args.args[0])
            receipt = json.loads(Path(payload["run"]).read_text(encoding="utf-8"))
            for record in (payload, receipt):
                self.assertEqual((record["model"], record["model_family"]), ("gpt-6-luna", "luna"))

    def test_fable_and_astra_are_refused_before_any_launch_step(self):
        for cli, model in (("codex", "astra"), ("codex", "gpt-6.2-astra"), ("codex", "GPT-7-Astra"),
                           ("claude", "fable"), ("claude", "claude-fable-5-2"), ("codex", "fable")):
            with (
                self.subTest(cli=cli, model=model),
                patch("dispatch.hc_json") as hc,
                patch("dispatch.subprocess.run") as run,
                patch("dispatch.codex_models_cache") as cache,
            ):
                with self.assertRaisesRegex(SystemExit, "never launches fable or astra"):
                    launch(self.launch_args(model, cli=cli, dry_run=False))
                hc.assert_not_called()
                run.assert_not_called()
                cache.assert_not_called()


class SharedGuardMigrationTests(unittest.TestCase):
    def test_send_holds_when_dev_has_moved_its_hooks_but_guard_is_missing(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_HOME": directory}):
            cache = Path(directory) / "plugins/cache/kadragon"
            manifest = cache / "dev/5.0.1" / pinned_wave.MANIFEST
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"hooks": "./hooks.json"}', encoding="utf-8")
            verify_delivery_turn(None, {})
            manifest.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "install guard@kadragon"):
                verify_delivery_turn(None, {})
            (cache / "guard/1.0.0").mkdir(parents=True)
            with self.assertRaisesRegex(SystemExit, "restart the idle Codex child"):
                verify_delivery_turn({"plugin_versions": {"dev": "5.0.1"}}, {})
            verify_delivery_turn({"plugin_versions": {"dev": "5.0.1", "guard": "1.0.0"}}, {})


class SharedCodexPreparationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.home = self.root / "codex"
        self.cache = self.home / "plugins/cache/kadragon/guard"
        self.binary = str(self.root / "bin" / "codex.cmd")
        self.enterContext(patch("dispatch.shutil.which", return_value=self.binary))
        self.enterContext(patch.dict(os.environ, {"CODEX_HOME": str(self.home)}))
        self.args = SimpleNamespace(repo=self.root, cwd=self.root, parent="t6")
        self.terminal = {"address": "t7", "parent": "t6", "state": "live",
                         "name": "dispatch-warmup-00112233", "created_ms": 2000}
        self.events = []
        self.screen = "  Hooks need review"
        self.screen_updates = []
        self.native_refresh = False
        self.guard_enabled = True
        self.fail_close_get = False
        self.enterContext(patch("dispatch.WARMUP_SETTLE_SECONDS", 0))
        self.enterContext(patch("dispatch.secrets.token_hex", return_value="00112233"))
        self.enterContext(patch("dispatch.time.time_ns", return_value=2_000_000_000))

    def install(self, version, content):
        root = self.cache / version
        (root / "hooks").mkdir(parents=True)
        (root / ".codex-plugin").mkdir()
        (root / ".codex-plugin/plugin.json").write_text('{"hooks":"hooks.json"}', encoding="utf-8")
        (root / "hooks.json").write_text("{}", encoding="utf-8")
        (root / "hooks/guard.py").write_text(content + "\n", encoding="utf-8")

    def codex(self, argv, **kwargs):
        if argv[0] == self.binary:
            self.events.append(argv)
            self.assertEqual(kwargs["cwd"], self.root)
            self.install("1.1.0", "new guard")
            shutil.rmtree(self.cache / "1.0.0")
            return ""
        git = argv[3:]
        if git == ["fetch", "origin"]:
            self.events.append("git fetch")
            return ""
        commit = "a" * 40
        if git == ["ls-remote", "--exit-code", "origin", "HEAD"]:
            return f"{commit}\tHEAD\n"
        if git == ["show", f"{commit}:{pinned_wave.CATALOG}"]:
            plugins = [{"name": name, "source": {"source": "local", "path": f"./{name}"}} for name in pinned_wave.PLUGINS]
            return json.dumps({"name": "kadragon", "plugins": plugins})
        self.assertEqual(git, ["show", f"{commit}:guard/{pinned_wave.MANIFEST}"])
        return json.dumps({"version": self.expected})

    def hooks(self, binary, home, method, params, **kwargs):
        self.assertEqual((binary, home, method, params), (self.binary, self.home, "hooks/list", {"cwds": [str(self.root)]}))
        self.assertTrue(kwargs["experimental"])
        version = next(self.cache.iterdir()).name
        self.events.append(f"hooks {version}")
        if self.native_refresh and version == "1.0.0":
            self.install("1.1.0", "new guard")
            shutil.rmtree(self.cache / version)
            raise ValueError("native inventory raced the old cache")
        hook = {"pluginId": "guard@kadragon", "source": "plugin", "key": "hook-key", "enabled": self.guard_enabled,
                "eventName": "preToolUse", "matcher": "Bash", "command": "python guard.py",
                "sourcePath": str(self.cache / version / "hooks.json"),
                "trustStatus": "trusted" if version == "1.0.0" else "modified"}
        return {"data": [{"cwd": str(self.root), "errors": [], "warnings": [], "hooks": [
            hook, {**hook, "pluginId": None, "key": "disabled", "enabled": False, "trustStatus": "untrusted"},
        ]}]}

    def hc(self, command, *args, **kwargs):
        if command == "ls":
            self.assertEqual(args, ("--label", shared_codex.cache_label(self.home)))
            return {"terminals": []}
        if command == "run":
            self.events.append("hc run")
            self.assertEqual(args[-3:], (self.binary, "--no-daemon", "--no-alt-screen"))
            self.assertIn("--no-notify", args)
            return {"address": "t7"}
        self.assertEqual(args[-1], "t7")
        if command == "get":
            if self.fail_close_get and kwargs.get("timeout") == 10:
                self.fail_close_get = False
                raise subprocess.TimeoutExpired(["hc", "get"], 10)
            return self.terminal
        if command == "read":
            text = self.screen_updates.pop(0) if self.screen_updates else self.screen
            return {"text": text, "how": "screen", "complete": True}
        self.events.append(f"hc {command}")
        if command == "kill":
            self.terminal["state"] = "finished"
        return {}

    def prepare(self, expected):
        self.expected = expected
        with (patch("dispatch.hc_json", side_effect=self.hc),
              patch("shared_codex.command", side_effect=self.codex),
              patch("shared_codex.request", side_effect=self.hooks), redirect_stdout(StringIO()) as output):
            prepare_codex(self.args)
        return json.loads(output.getvalue())

    def test_upgrade_reports_exact_pending_hooks_and_retains_trusted_baseline(self):
        self.install("1.0.0", "trusted guard")
        report = self.prepare("1.1.0")
        self.assertEqual(self.events, ["git fetch", "hooks 1.0.0",
                                       [self.binary, "plugin", "marketplace", "upgrade", "kadragon"],
                                       "hc run", "hc kill", "hc rm", "hooks 1.1.0"])
        self.assertTrue(report["upgraded"])
        self.assertEqual(report["installed"], {"guard": "1.1.0"})
        self.assertEqual([(hook["key"], hook["trustStatus"]) for hook in report["pending_hooks"]],
                         [("hook-key", "modified")])
        diff = report["hook_content_diffs"]["guard"]
        self.assertEqual(diff["trusted_version"], "1.0.0")
        self.assertIn("-trusted guard\n+new guard", diff["diff"])

        self.events.clear()
        self.terminal["state"] = "live"
        report = self.prepare("1.1.0")
        self.assertFalse(report["upgraded"])
        self.assertEqual(report["hook_content_diffs"]["guard"], diff)

    def test_equal_versions_without_a_trusted_baseline_still_report_pending_hooks(self):
        self.install("1.1.0", "new guard")
        report = self.prepare("1.1.0")
        self.assertFalse(report["upgraded"])
        self.assertEqual(self.events, ["git fetch", "hooks 1.1.0", "hc run", "hc kill", "hc rm", "hooks 1.1.0"])
        self.assertEqual(report["hook_content_diffs"]["guard"],
                         {"reason": "no locally recorded trusted hook contents"})

    def test_native_refresh_reports_changed_versions_and_the_baseline_gap(self):
        self.install("1.0.0", "trusted guard")
        self.native_refresh = True
        report = self.prepare("1.1.0")
        self.assertTrue(report["upgraded"])
        self.assertEqual(report["before"], {"guard": "1.0.0"})
        self.assertEqual(report["hook_content_diffs"]["guard"],
                         {"reason": "no locally recorded trusted hook contents"})
        self.assertEqual(self.events, ["git fetch", "hooks 1.0.0", "hc run", "hc kill", "hc rm", "hooks 1.1.0"])

    def test_preparation_refuses_a_disabled_guard(self):
        self.install("1.1.0", "new guard")
        self.guard_enabled = False
        with self.assertRaisesRegex(SystemExit, "guard@kadragon hook is disabled"):
            self.prepare("1.1.0")
        self.assertIn("hc rm", self.events)
        self.assertFalse((self.home / "dispatch-prepared-cache.json").exists())

    def test_preparation_refuses_a_failed_startup_hook_and_closes_the_child(self):
        self.install("1.1.0", "new guard")
        self.screen_updates = ["  Hooks need review", "• Hook failed\n  └ SessionStart command exited 1"]
        self.fail_close_get = True
        with (patch("dispatch.WARMUP_SETTLE_SECONDS", 2), patch("dispatch.time.sleep"),
              self.assertRaisesRegex(SystemExit, "warm-up startup hook failed")):
            self.prepare("1.1.0")
        self.assertEqual(self.events[-2:], ["hc kill", "hc rm"])
        self.assertFalse(self.fail_close_get)
        self.assertFalse((self.home / "dispatch-prepared-cache.json").exists())

    def test_preparation_leaves_live_wave_untouched_even_from_its_home(self):
        terminals = {"terminals": [{"address": "t7", "state": "live", "parent": "t6"}]}
        with (patch("dispatch.hc_json", return_value=terminals) as hc,
              patch("shared_codex.command") as cmd, patch("shared_codex.request") as hooks):
            with self.assertRaisesRegex(SystemExit, "live wave uses this cache"):
                prepare_codex(self.args)
        hc.assert_called_once_with("ls", "--label", shared_codex.cache_label(self.home), timeout=ANY)
        cmd.assert_not_called()
        hooks.assert_not_called()


class PinnedWaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def make_wave(self, suffix, version, *, legacy=False):
        root = self.tmp / ("dispatch-wave-" + suffix)
        root.mkdir()
        path = root / "wave.json"
        binary = self.tmp / "codex"
        binary.write_text("fixture executable", encoding="utf-8")
        home = root / "home"
        home.mkdir()
        (home / "config.toml").write_text("", encoding="utf-8")
        source = root / "source"
        source.mkdir()
        versions = {"dev": version, "prod": "1.0.0"}
        if not legacy:
            versions["guard"] = "1.0.0"
        hook_owner = "dev" if legacy else "guard"
        wave = {"schema": 1, "market": root.name, "versions": versions,
                "binary": str(binary), "binary_hash": pinned_wave.file_hash(binary),
                "settings": {}, "cache_hash": {}, "hooks": {}, "children": []}
        for name, plugin_version in versions.items():
            plugin = source / name
            (plugin / ".codex-plugin").mkdir(parents=True)
            manifest = {"version": plugin_version}
            if name == hook_owner:
                manifest["hooks"] = "./hooks.json"
                (plugin / "hooks.json").write_text('{"hooks":{}}', encoding="utf-8")
                (plugin / "hooks").mkdir()
                (plugin / "hooks/guard.py").write_text(f"# {plugin_version}", encoding="utf-8")
            (plugin / pinned_wave.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
            if name != "guard":
                (plugin / "SKILL.md").write_text(f"Skill {plugin_version}", encoding="utf-8")
            cache = pinned_wave.cache_path(root, wave, name)
            shutil.copytree(plugin, cache)
            wave["cache_hash"][name] = pinned_wave.tree_hash(plugin)
        wave["source_hash"] = pinned_wave.tree_hash(source)
        wave["hooks"] = {"first": [pinned_wave.cache_path(root, wave, hook_owner).relative_to(root).as_posix()
                                   + "/hooks.json", "sha256:first", 'python "$env:PLUGIN_ROOT/hooks/guard.py"']}
        path.write_text(json.dumps(wave), encoding="utf-8")
        return path, wave

    def verification_stubs(self, path, wave, *, trusted=True):
        root = path.parent
        plugins = {"installed": [
            {"pluginId": f"{name}@{wave['market']}", "enabled": True, "version": wave["versions"][name],
             "source": {"source": "local", "path": str(root / "source" / name)}}
            for name in wave["versions"]
        ]}
        hook_path, hook_hash, command = wave["hooks"]["first"]
        hook_owner = "guard" if "guard" in wave["versions"] else "dev"
        hook = {"pluginId": f"{hook_owner}@{wave['market']}", "source": "plugin", "key": "first",
                "sourcePath": str(root / hook_path), "currentHash": hook_hash, "command": command,
                "enabled": True, "isManaged": False, "trustStatus": "trusted" if trusted else "untrusted"}
        groups = {"data": [{"cwd": str(self.tmp), "warnings": [], "errors": [], "hooks": [hook]}]}
        return plugins, groups

    def test_overlapping_versions_are_independent_of_a_shared_marketplace_refresh(self):
        shared_cache = self.tmp / "shared/plugins/cache/kadragon/dev"
        old, old_wave = self.make_wave("a", "1.0.0")
        (shared_cache / "1.0.0").mkdir(parents=True)
        (shared_cache / "1.0.0" / "SKILL.md").write_text("original", encoding="utf-8")
        new, new_wave = self.make_wave("b", "1.1.0")
        shutil.rmtree(shared_cache / "1.0.0")
        (shared_cache / "1.1.0").mkdir()
        with patch.dict(os.environ, {"CODEX_HOME": str(self.tmp / "shared")}):
            for path, wave in ((old, old_wave), (new, new_wave)):
                plugins, groups = self.verification_stubs(path, wave)
                with patch("pinned_wave.codex_command", return_value=json.dumps(plugins)), \
                     patch("pinned_wave.inspect_hooks", return_value=groups):
                    self.assertTrue(pinned_wave.verify(path, wave, self.tmp))
                cached = pinned_wave.cache_path(path.parent, wave, "dev")
                self.assertEqual((cached / "SKILL.md").read_text(encoding="utf-8"),
                                 f"Skill {wave['versions']['dev']}")
        self.assertNotEqual(old_wave["cache_hash"]["dev"], new_wave["cache_hash"]["dev"])
        self.assertEqual(old_wave["cache_hash"]["guard"], new_wave["cache_hash"]["guard"])

    def test_export_uses_the_catalog_at_the_selected_commit(self):
        repo = self.tmp / "repo"
        repo.mkdir()

        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

        git("init", "-q")
        catalog_path = repo / pinned_wave.CATALOG
        catalog_path.parent.mkdir(parents=True)
        for names in (pinned_wave.LEGACY_PLUGINS, pinned_wave.PLUGINS):
            entries = [{"name": name, "source": {"source": "local", "path": f"./{name}"}} for name in names]
            catalog_path.write_text(json.dumps({"name": "kadragon", "plugins": entries}), encoding="utf-8")
            for name in names:
                manifest = repo / name / pinned_wave.MANIFEST
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text('{"version": "1.0.0"}', encoding="utf-8")
            git("add", ".")
            git("-c", "core.hooksPath=NUL" if os.name == "nt" else "core.hooksPath=/dev/null",
                "-c", "commit.gpgsign=false", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-qm", "marketplace fixture")
            if names == pinned_wave.LEGACY_PLUGINS:
                legacy_commit = git("rev-parse", "HEAD")

        for names, commit in ((pinned_wave.LEGACY_PLUGINS, legacy_commit),
                              (pinned_wave.PLUGINS, git("rev-parse", "HEAD"))):
            with self.subTest(names=names):
                target = self.tmp / str(len(names))
                _, exported = pinned_wave.export_snapshot(repo, commit, target)
                self.assertEqual(exported, names)
                self.assertEqual({path.name for path in target.iterdir() if not path.name.startswith(".")},
                                 set(names))

    def test_existing_wave_receipt_keeps_its_dev_hooks(self):
        path, wave = self.make_wave("legacy", "1.0.0", legacy=True)
        self.assertEqual(pinned_wave.read_wave(path), wave)
        plugins, groups = self.verification_stubs(path, wave)
        with patch("pinned_wave.codex_command", return_value=json.dumps(plugins)), \
                patch("pinned_wave.inspect_hooks", return_value=groups):
            self.assertTrue(pinned_wave.verify(path, wave, self.tmp))

    def test_modified_missing_or_untrusted_hooks_fail_the_delivery_gate(self):
        path, wave = self.make_wave("a", "1.0.0")
        run = {"address": "t7", "wave": str(path), "wave_trusted_at_start": True, "cwd": str(self.tmp)}
        terminal = {"labels": {pinned_wave.WAVE_LABEL: wave["market"]},
                    "foreground": {"argv": [wave["binary"], "--no-daemon"]}, "status": {"app": "codex"}}
        plugins, groups = self.verification_stubs(path, wave, trusted=False)
        with patch("pinned_wave.tempfile.gettempdir", return_value=str(self.tmp)), \
             patch("pinned_wave.codex_command", return_value=json.dumps(plugins)), \
             patch("pinned_wave.inspect_hooks", return_value=groups):
            with self.assertRaisesRegex(SystemExit, "lack native trust"):
                verify_pinned_delivery(run, terminal)
            with self.assertRaisesRegex(SystemExit, "close and relaunch"):
                verify_pinned_delivery({**run, "wave_trusted_at_start": False}, terminal)
            with self.assertRaisesRegex(SystemExit, "supply its launch receipt"):
                verify_pinned_delivery(None, terminal)
            groups["data"][0]["hooks"][0]["command"] = "python C:/external/guard.py"
            with self.assertRaisesRegex(SystemExit, "no verifiable plugin entrypoint"):
                verify_pinned_delivery(run, terminal)
            groups["data"][0]["hooks"] = []
            with self.assertRaisesRegex(SystemExit, "definitions differ"):
                verify_pinned_delivery(run, terminal)
            (pinned_wave.cache_path(path.parent, wave, "guard") / "hooks/guard.py").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "cache changed"):
                verify_pinned_delivery(run, terminal)

    def test_missing_herdr_environment_support_refuses_isolation(self):
        schema = {"methods": [{"name": "terminal.run", "params": [{"name": "argv"}]}]}
        with patch("pinned_wave.command", return_value=json.dumps(schema)), \
             self.assertRaisesRegex(pinned_wave.PinError, "per-terminal environment support"):
            pinned_wave.verify_herdr()

    def test_native_ui_setup_marker_does_not_change_verified_settings(self):
        path, wave = self.make_wave("a", "1.0.0")
        config = path.parent / "home" / "config.toml"
        config.write_text("[tui]\nscreen_reader_detection_done = true\n", encoding="utf-8")
        pinned_wave.verify_files(path, wave)
        config.write_text("sandbox_mode = 'danger-full-access'\n"
                          "[tui]\nscreen_reader_detection_done = true\n", encoding="utf-8")
        with self.assertRaisesRegex(pinned_wave.PinError, "isolated Codex settings changed"):
            pinned_wave.verify_files(path, wave)

    def test_detected_user_hook_settings_require_shared_cache(self):
        home = self.tmp / "shared"
        home.mkdir()
        (home / "config.toml").write_text('[hooks.state."fixture"]\ntrusted_hash = "fixture"\n',
                                           encoding="utf-8")
        pinned_wave.ensure_shared_guards_are_preserved(home)
        (home / "hooks.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(pinned_wave.PinError, "omit shared guards.*hooks.json"):
            pinned_wave.ensure_shared_guards_are_preserved(home)

    @contextmanager
    def mocked_launch(self, path, child_dir, reply):
        args = SimpleNamespace(wave=str(path), cli="codex", model="gpt-6.2-sol", effort="medium", cwd=self.tmp,
                               name=None, title=None, task=None, message=None, keep_connectors=False,
                               parent=None, work_kind="standalone", request="work",
                               unit="unit", git_limits="none", dry_run=False)
        terminal = {"address": "t7", "parent": None, "created_ms": 42}
        child_dir.mkdir()
        with (
            patch.dict(os.environ, {"HC_TERMINAL_ID": "", "CODEX_HOME": str(self.tmp / "shared")}),
            patch("pinned_wave.tempfile.gettempdir", return_value=str(self.tmp)),
            patch("pinned_wave.verify_herdr"),
            patch("pinned_wave.verify", return_value=False),
            patch("dispatch.read_quota_snapshot", return_value=QUOTA_OK),
            patch("dispatch.warn_linked_worktree"),
            patch("dispatch.tempfile.mkdtemp", return_value=str(child_dir)),
            patch("dispatch.hc_json", side_effect=[{"terminals": []}, terminal]),
            patch("dispatch.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(
                {"jsonrpc": "2.0", "id": 1, **reply}))) as process,
            redirect_stdout(StringIO()) as output,
        ):
            yield args, process, output

    def test_launch_starts_native_codex_through_herdr_with_only_private_home(self):
        path, wave = self.make_wave("a", "1.0.0")
        with self.mocked_launch(path, self.tmp / "child", {"result": {"address": "t7"}}) as (args, process, output):
            launch(args)
        cmd = process.call_args
        self.assertEqual(cmd.args[0], ["hc", "connect"])
        frame = cmd.kwargs["input"]
        self.assertTrue(frame.endswith("\n"))
        data = json.loads(frame)
        self.assertEqual(data["method"], "terminal.run")
        self.assertEqual(data["params"]["env"]["CODEX_HOME"], str(path.parent / "home"))
        self.assertEqual(data["params"]["argv"][:2], [wave["binary"], "--no-daemon"])
        self.assertNotIn("--dangerously-bypass-hook-trust", data["params"]["argv"])
        receipt = json.loads(output.getvalue())
        self.assertFalse(receipt["wave_trusted_at_start"])
        self.assertEqual(pinned_wave.read_json(path)["children"], [receipt["run"]])

    def test_known_rejection_clears_pending_wave_reservation(self):
        path, _ = self.make_wave("a", "1.0.0")
        child_dir = self.tmp / "child"
        reply = {"error": {"code": -32000, "data": {"kind": "name_taken"}, "message": "name already taken"}}
        with self.mocked_launch(path, child_dir, reply) as (args, _, _):
            with self.assertRaisesRegex(SystemExit, "rejected.*name_taken"):
                launch(args)
        self.assertEqual(pinned_wave.read_json(path)["children"], [])
        self.assertFalse(child_dir.exists())

    def test_uncertain_spawn_keeps_the_wave_registered(self):
        path, _ = self.make_wave("a", "1.0.0")
        child_dir = self.tmp / "child"
        with self.mocked_launch(path, child_dir, {}) as (args, process, _):
            process.side_effect = subprocess.TimeoutExpired("hc connect", 30)
            with self.assertRaisesRegex(SystemExit, "child may be running"):
                launch(args)
            with self.assertRaisesRegex(SystemExit, "cannot read dispatch receipt"):
                release(SimpleNamespace(wave=str(path)))
        self.assertEqual(pinned_wave.read_json(path)["children"], [str(child_dir / "run.json")])

    def test_receipt_write_error_after_spawn_tells_operator_to_inspect_live_child(self):
        path, _ = self.make_wave("a", "1.0.0")
        child_dir = self.tmp / "child"

        def reject_receipt(target, data):
            if target.name == "run.json":
                raise OSError("disk full")
            write_json(target, data)

        with self.mocked_launch(path, child_dir, {"result": {"address": "t7"}}) as (args, _, _):
            with patch("dispatch.write_json", side_effect=reject_receipt), \
                 self.assertRaisesRegex(SystemExit, "t7: the child may be running"):
                launch(args)
        self.assertEqual(pinned_wave.read_json(path)["children"], [str(child_dir / "run.json")])

    def test_pinned_launch_cannot_opt_in_to_hook_bypass(self):
        args = SimpleNamespace(wave="unused", cli="codex", trust_hooks=True, task=None)
        with self.assertRaisesRegex(SystemExit, "forbids --trust-hooks"):
            launch(args)

    def test_release_waits_for_every_child_and_leaves_other_wave_intact(self):
        path, wave = self.make_wave("a", "1.0.0")
        other, _ = self.make_wave("b", "2.0.0")
        child = self.tmp / "run.json"
        wave["children"] = [str(child)]
        path.write_text(json.dumps(wave), encoding="utf-8")
        child.write_text(json.dumps({"address": "t7", "wave": str(path)}), encoding="utf-8")
        args = SimpleNamespace(wave=str(path))
        with patch("pinned_wave.tempfile.gettempdir", return_value=str(self.tmp)), redirect_stdout(StringIO()):
            with self.assertRaisesRegex(SystemExit, "must be closed first"):
                release(args)
            self.assertTrue(path.is_file())
            child.write_text(json.dumps({"address": "t7", "wave": str(path), "closed_reason": "finished"}),
                             encoding="utf-8")
            release(args)
        self.assertFalse(path.parent.exists())
        self.assertTrue(other.is_file())


class DispatchWatchTests(unittest.TestCase):
    def test_timing_bounds_history_and_reports_missing_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            write_json(receipt, {"address": "t7"})
            output = StringIO()
            with redirect_stdout(output):
                timing(SimpleNamespace(run=receipt, event=None))
            report = json.loads(output.getvalue())
            self.assertIsNone(report["final_head"])
            self.assertIsNone(report["merge"])
            self.assertIsNone(report["launches"][0]["startup_ms"])
            self.assertFalse(receipt.with_name("timing.json").exists())

            head = "a" * 40
            data = phase_timing.empty_history()
            for at in range(phase_timing.MAX_LAUNCHES + 1):
                phase_timing.new_launch(data, at)
            attempts = [phase_timing.start(data, "review", head, False, at)
                        for at in range(phase_timing.MAX_ATTEMPTS + 1)]
            with self.assertRaisesRegex(ValueError, "unknown review attempt"):
                phase_timing.finish(data, "review", attempts[0], "complete", 30)
            phase_timing.finish(data, "review", attempts[1], "complete", 0)
            phase_timing.merged(data, None, 40)
            report = phase_timing.report(data, {"head": head})
            self.assertEqual(report["dropped_launches"], 1)
            self.assertEqual(report["merge"], {"head": None, "confirmed_ms": 40, "elapsed_ms": 40})
            self.assertEqual(report["final_head"], head)
            launch = report["launches"][-1]
            self.assertEqual(launch["dropped_review"], 1)
            self.assertEqual(len(launch["review"]), phase_timing.MAX_ATTEMPTS)
            self.assertEqual(launch["review"][0]["attempt"], attempts[1])
            self.assertIsNone(launch["review"][0]["elapsed_ms"])
            with self.assertRaisesRegex(ValueError, "full Git object SHA"):
                phase_timing.start(data, "ci", "a prompt or a credential", False, 1)

    def test_timing_uses_claude_acknowledgment_and_ignores_stale_results(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            report_path = receipt.with_name("result.json")
            timing_file = receipt.with_name("timing.json")
            args = SimpleNamespace(run=receipt, event=None)

            def measure():
                with redirect_stdout(StringIO()) as output:
                    timing(args)
                return json.loads(output.getvalue())

            write_json(timing_file, phase_timing.new_launch(phase_timing.empty_history(), 1000))
            with patch("dispatch.phase_timing.now_ms", return_value=1500):
                timing(SimpleNamespace(run=receipt, event="delivered"))
            self.assertFalse(receipt.exists())
            write_json(receipt, {"address": "t7", "cli": "claude", "sent": True})
            head = "a" * 40
            write_json(report_path, {"status": "working", "phase": "review", "summary": "review", "head": head})
            self.assertEqual(measure()["launches"][0]["startup_ms"], 500)
            with patch("dispatch.phase_timing.now_ms", return_value=2500):
                timing(SimpleNamespace(run=receipt, event="delivered"))
            self.assertEqual(measure()["launches"][0]["startup_ms"], 500)
            late_ack = phase_timing.new_launch(phase_timing.empty_history(), 1000)
            phase_timing.start(late_ack, "review", head, False, 2000)
            write_json(timing_file, late_ack)
            with patch("dispatch.phase_timing.now_ms", return_value=2500):
                timing(SimpleNamespace(run=receipt, event="delivered"))
            self.assertIsNone(measure()["launches"][0]["startup_ms"])
            write_json(receipt, {"address": "t7", "cli": "codex", "previous_result": report_path.stat().st_mtime_ns})
            self.assertIsNone(measure()["final_head"])

    def test_wait_ignores_legacy_done_while_working_and_emits_only_changes(self):
        report = {"address": "t7", "status": "working", "state": "live", "stop_reason": None,
                  "result": {"status": "done", "phase": "implement", "summary": "작업 중\nsecond line",
                             "pr": "#10"}}
        same = {**report, "result": {**report["result"], "review_retries": 2}}
        ready = {**report, "status": "done", "result": {"status": "ready", "phase": "review",
                                                       "summary": "검증 완료", "pr": "#10"}}
        args = SimpleNamespace(first=False, runs=["run.json"], until={"ready", "blocked", "merged", "idle", "stop"},
                               timeout=30, stall_minutes=30)
        with patch("dispatch.collect_result", side_effect=[report, same, ready]) as probe, \
             patch("dispatch.hc_rpc", return_value={"result": {}}) as hc, patch("dispatch.time.sleep"), redirect_stdout(StringIO()) as output:
            wait(args)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(hc.call_count, 2)
        for invocation in hc.call_args_list:
            self.assertEqual(invocation.args[:2], ("terminal.wait", {"terminal": "t7", "timeout": 1, "caller": None}))
        self.assertEqual(output.getvalue().splitlines(), [
            "t7 · working · implement · 작업 중 · #10 · -",
            "t7 · ready · review · 검증 완료 · #10 · -",
        ])

    def test_wait_first_returns_on_the_first_selected_outcome(self):
        idle = {"address": "t7", "status": "idle", "state": "live", "stop_reason": None, "result": None}
        ready = {**idle, "address": "t8", "status": "done", "result": {"status": "ready", "pr": "#10"}}
        reports = [idle, ready, {**ready, "address": "t9"}, {**ready, "address": "t7"}]
        with TextIOWrapper(BytesIO(), encoding="utf-8") as output, redirect_stdout(output), \
             TextIOWrapper(BytesIO(), encoding="utf-8") as progress, redirect_stderr(progress), \
             patch("dispatch.collect_result", side_effect=reports) as probe, \
             patch("dispatch.hc_rpc") as hc, patch("dispatch.time.sleep") as sleep:
            main(["wait", "--first", "--until", "ready", "a.json", "b.json", "c.json"])
            output.seek(0)
            printed = output.read()
            progress.seek(0)
            statuses = progress.read()
        self.assertEqual([invocation.args[0].name for invocation in probe.call_args_list], ["a.json", "b.json"])
        hc.assert_not_called()
        sleep.assert_not_called()
        self.assertEqual(printed, f"{Path('b.json').resolve()} · t8 · ready · - · - · #10 · -\n")
        self.assertEqual(statuses, "t7 · idle · - · - · - · -\n")

    def test_wait_requires_all_receipts_and_a_stopped_terminal_for_done(self):
        working = {"address": "t7", "status": "working", "state": "live", "stop_reason": None,
                   "result": {"status": "done", "phase": "implement", "summary": "phase complete"}}
        stopped = {**working, "status": "done"}
        second = {**working, "address": "t8", "result": None, "stop_reason": "hooks_broken"}
        args = SimpleNamespace(first=False, runs=["a.json", "b.json"], until={"done", "stop"}, timeout=30, stall_minutes=30)
        with patch("dispatch.collect_result", side_effect=[working, second, stopped]) as probe, \
             patch("dispatch.hc_rpc", return_value={"result": {}}), patch("dispatch.time.sleep"), redirect_stdout(StringIO()) as output:
            wait(args)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(len(output.getvalue().splitlines()), 3)

    def test_wait_can_collect_a_closed_child_without_herdr(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps({"address": "t7", "closed_reason": "finished"}), encoding="utf-8")
            args = SimpleNamespace(first=False, runs=[receipt], until={"stop"}, timeout=30, stall_minutes=30)
            with patch("dispatch.hc_json") as hc, redirect_stdout(StringIO()) as output:
                wait(args)
        hc.assert_not_called()
        self.assertIn("t7 · finished", output.getvalue())

    def test_wait_stops_and_surfaces_drift_even_while_old_hook_directory_exists(self):
        report = {"address": "t7", "status": "working", "state": "live", "stop_reason": None,
                  "result": None, "plugin_drift": ["dev old -> new"]}
        args = SimpleNamespace(first=False, runs=["run.json"], until={"stop"}, timeout=30, stall_minutes=30)
        with patch("dispatch.collect_result", return_value=report), patch("dispatch.hc_rpc") as hc, \
             redirect_stdout(StringIO()) as output:
            wait(args)
        hc.assert_not_called()
        self.assertIn("plugin_drift", output.getvalue())

    def test_wait_treats_the_documented_missing_terminal_error_as_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps({"address": "t7", "created_ms": 1}), encoding="utf-8")
            args = SimpleNamespace(first=False, runs=[receipt], until={"stop"}, timeout=30, stall_minutes=30)
            gone = subprocess.CalledProcessError(3, "hc", stderr='{"error":{"kind":"not_found"}}')
            with patch("dispatch.hc_json", side_effect=gone), redirect_stdout(StringIO()) as output:
                wait(args)
        self.assertIn("Herdr terminal no longer exists", output.getvalue())

    def test_hung_herdr_read_obeys_wait_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            receipt.write_text(json.dumps({"address": "t7", "created_ms": 1}), encoding="utf-8")
            args = SimpleNamespace(first=False, runs=[receipt], until={"stop"}, timeout=1, stall_minutes=30)
            with patch("dispatch.hc_json", side_effect=subprocess.TimeoutExpired("hc", 1)) as hc, \
                 self.assertRaisesRegex(SystemExit, "timed out"):
                wait(args)
        self.assertGreater(hc.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(hc.call_args.kwargs["timeout"], 1)

    def test_wait_times_out_when_no_selected_outcome_occurs(self):
        report = {"address": "t7", "status": "idle", "state": "live", "stop_reason": None, "result": None}
        args = SimpleNamespace(first=False, runs=["run.json"], until={"ready"}, timeout=1, stall_minutes=30)
        with patch("dispatch.collect_result", return_value=report), \
             patch("dispatch.time.monotonic", side_effect=[0, 2]), redirect_stdout(StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "timed out"):
                wait(args)
        self.assertEqual(output.getvalue(), "t7 · idle · - · - · - · -\n")

    def test_piped_brief_is_utf8_even_under_a_legacy_console_encoding(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import dispatch; "
            "dispatch.collect_result = lambda *a, **kw: "
            "{'address':'t7','status':'working','state':'live','stop_reason':None,"
            "'result':{'status':'working','phase':'test','summary':'\\uac80\\uc99d \\U0001f9ea'}}; "
            "dispatch.main(['collect','run.json','--brief'])"
        )
        proc = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], check=True, capture_output=True,
                              env={**os.environ, "PYTHONIOENCODING": "cp949:strict"})
        self.assertEqual(proc.stdout.decode("utf-8").strip(), "t7 · working · test · 검증 🧪 · - · -")


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
        self.assertIn("For standalone work that needs no Git writes and has no user-provided limits, "
                      "pass `--git-limits='not specified'`.", launch_step)
        launch_examples = re.findall(r"```sh (.*?dispatch\.py.*?) ```", launch_step)
        self.assertEqual(len(launch_examples), 2)
        for example in launch_examples:
            self.assertNotIn("--git-grant-recorded", example)
        self.assertIn("After confirming task delivery to every new child", watch_step)
        self.assertIn("Once a parallel PR branch has been pushed, fetch and merge its PR base", watch_step)

    def test_docs_name_codex_models_by_family_only(self):
        docs = [SCRIPTS.parent / "SKILL.md", *sorted((SCRIPTS.parent / "references").glob("*.md"))]
        for doc in docs:
            with self.subTest(doc=doc.name):
                self.assertIsNone(re.search(r"gpt-\d", doc.read_text(encoding="utf-8"), re.IGNORECASE))


class PeekTests(unittest.TestCase):
    def test_codex_capture_keeps_work_and_followup(self):
        screen = """
  >_ OpenAI Codex (v0.172.0)
     ~/Dev/agent-toolkit

  Tip: Use /hooks to view and manage lifecycle hooks.

› <hc from="t2t">$task-next --tree #512
  Dispatch mode: parallel-worktree

  Handoff metadata (JSON):
  <dispatch-handoff>
  {"Assigned unit": "issue #512"}
  </dispatch-handoff>

  Write progress at phase boundaries.

• Ran git status --short --branch
  └ ## main...origin/main [behind 60]

› Continue to review

• Checking evidence.

› Ask Codex to do anything

  GPT-6.2-Sol medium · ~/Dev/agent-toolkit · main · Context 10% used · weekly 45% left
  ← for agents · ? for shortcuts
"""
        self.assertEqual(filtered_transcript(screen, "codex"), [
            "• Ran git status --short --branch", "  └ ## main...origin/main [behind 60]",
            "", "› Continue to review", "", "• Checking evidence.",
        ])

    def test_claude_capture_keeps_response(self):
        screen = """
 ▐▛███▛█   Claude Code v2.1.332
▝▜██████▀  Opus 5.5 · Claude Team
 ▝▝   ▝▝   /tmp/claude-fixture

⚠ Code Mode (experimental) is on · this session can be resumed only with Code Mode on

❯ Reply with the exact sentence: Fixture response.

  Handoff metadata (JSON):
  <dispatch-handoff>
  {"Assigned unit": "fixture"}
  </dispatch-handoff>

● Fixture response.

✻ Sautéed for 1s · done 오전 9:26

                                                    [-]
[Opus 5.5 ◔ medium] │ claude-fixture
Context 3% │ 5h: 21% (1h 43m) │ 7d: 59% (4d 4h) │ cache 59m
                                    ◐ medium · /effort
───────────────────────────────────────────────────────
❯
───────────────────────────────────────────────────────

  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents
"""
        self.assertEqual(filtered_transcript(screen, "claude"), [
            "⚠ Code Mode (experimental) is on · this session can be resumed only with Code Mode on",
            "", "● Fixture response.", "", "✻ Sautéed for 1s · done 오전 9:26",
        ])

    def test_hidden_codex_composer_preserves_indented_work(self):
        screen = "› a task\n\n  • Completed\n\n  GPT-6.2-Sol medium · main\n  ← for agents · ? for shortcuts"
        self.assertEqual(filtered_transcript(screen, "codex"), ["› a task", "", "  • Completed"])

    def test_cropped_dispatch_echo_is_removed(self):
        screen = '    "Assigned unit": "issue #512"\n  }\n  </dispatch-handoff>\n'
        screen += "\n  Write progress at phase boundaries.\n\n• Checking evidence."
        self.assertEqual(filtered_transcript(screen, "codex"), ["• Checking evidence."])

    def test_handoff_filter_preserves_indented_claude_error(self):
        screen = ("❯ /dev:task-next\n\n  Handoff metadata (JSON):\n  <dispatch-handoff>\n"
                  "  {}\n  </dispatch-handoff>\n  ⎿  API Error: Usage Policy")
        self.assertEqual(filtered_transcript(screen, "claude"), ["  ⎿  API Error: Usage Policy"])

    def test_handoff_filter_preserves_indented_codex_hook_notice(self):
        screen = ("› $task-next #512\n\n  Handoff metadata (JSON):\n  <dispatch-handoff>\n"
                  "  {}\n  </dispatch-handoff>\n  Hooks need review")
        self.assertEqual(filtered_transcript(screen, "codex"), ["  Hooks need review"])

    def test_alternative_claude_status_and_codex_working_timer(self):
        rule = "─" * 30
        claude = f"● Fixture response.\n\n~/repo · main · 12%\n{rule}\n❯\n{rule}"
        codex = "• Checking evidence.\n\nWorking (1m 59s • esc to interrupt)\n\n› Ask Codex to do anything"
        self.assertEqual(filtered_transcript(claude, "claude"), ["● Fixture response."])
        self.assertEqual(filtered_transcript(codex, "codex"), ["• Checking evidence."])

    def test_progress_timers_do_not_move_the_cursor(self):
        for seconds in (41, 42):
            claude = f"● Checking evidence.\n\n✻ Thinking… ({seconds}s · ↑ 50 tokens)\n  ⎿  ☐ Run tests"
            codex = f"• Checking evidence.\n\n◦ Exploring repository ({seconds}s • esc to interrupt)"
            self.assertEqual(filtered_transcript(claude, "claude"), ["● Checking evidence.", "", "  ⎿  ☐ Run tests"])
            self.assertEqual(filtered_transcript(codex, "codex"), ["• Checking evidence."])

    def test_peek_cursor_survives_history_rollover_and_keeps_receipt_fields(self):
        terminal = {"address": "t7", "parent": "t1", "created_ms": 42}
        receipt = {**terminal, "cli": "codex", "sent": True}
        screens = iter(("• Old\n• Retained", "• Retained\n• New", "• Retained\n• New"))

        def hc(command, *_args, **_kwargs):
            return terminal if command == "get" else {"text": next(screens), "how": "history", "complete": False}

        with tempfile.TemporaryDirectory() as directory, patch("dispatch.hc_json", side_effect=hc):
            path = Path(directory) / "run.json"
            write_json(path, receipt)
            for since_last, expected in ((False, "• Old\n• Retained\n"), (True, "• New\n"), (True, "")):
                with redirect_stdout(StringIO()) as output:
                    peek(SimpleNamespace(run=str(path), since_last=since_last))
                self.assertEqual(output.getvalue(), expected)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual({key: saved[key] for key in receipt}, receipt)
            self.assertEqual(len(saved["peek_cursor"]), 2)
            self.assertNotIn("• New", json.dumps(saved, ensure_ascii=False))

    def test_peek_rejects_recycled_terminal_without_updating_cursor(self):
        receipt = {"address": "t7", "parent": "t1", "created_ms": 42, "cli": "codex"}
        responses = [receipt, {"text": "unrelated"}, {**receipt, "created_ms": 43}]
        with tempfile.TemporaryDirectory() as directory, patch("dispatch.hc_json", side_effect=responses):
            path = Path(directory) / "run.json"
            write_json(path, receipt)
            with self.assertRaisesRegex(SystemExit, "terminal identity changed"), redirect_stdout(StringIO()) as output:
                peek(SimpleNamespace(run=str(path), since_last=True))
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), receipt)

    def test_peek_leaves_receipt_unlocked_during_read(self):
        receipt = {"address": "t7", "parent": "t1", "created_ms": 42, "cli": "codex", "sent": False}

        def hc(command, *_args, **_kwargs):
            if command == "get":
                return receipt
            with lock_run(path):
                write_json(path, {**receipt, "sent": True})
            return {"text": "• Started"}

        with tempfile.TemporaryDirectory() as directory, patch("dispatch.hc_json", side_effect=hc):
            path = Path(directory) / "run.json"
            write_json(path, receipt)
            with redirect_stdout(StringIO()) as output:
                peek(SimpleNamespace(run=str(path), since_last=True))
            self.assertEqual(output.getvalue(), "• Started\n")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["sent"])

    def test_streamed_line_redraw_and_no_overlap(self):
        self.assertEqual(transcript_offset(["ready", "stream"], ["ready", "streamed", "next"]), 1)
        self.assertEqual(transcript_offset(["old", "ready", "stream"], ["ready", "streamed", "next"]), 1)
        self.assertEqual(transcript_offset(["irrelevant"], ["new"]), 0)


class CodexSendTests(DispatchTestCase):
    READY = "› Ask Codex to do anything\n\n  GPT-6.2-Sol default · ~/repo"
    PASTE = "› [Pasted Content 1576 chars]\n\n  GPT-6.2-Sol default · ~/repo"
    FOOTER_0171 = (
        "  GPT-6.2-Sol high · main · weekly 54% left · Context 0% used · my-app\n"
        "  ← for agents · ? for shortcuts"
    )
    ARGS = SimpleNamespace(address="t7", message="a task")
    IDLE = {"turn": 0, "status": {"state": "idle"}}
    WORKING = {"turn": 0, "status": {"state": "working"}}
    SINGLE_WARNING = f"{READY}\n  ⚠ 1 warning · f2 to view"
    TWO_WARNINGS = f"{READY}\n  ⚠ 2 warnings · f2 to view"
    WARNING_CONTROLS = "  k keep & next · esc dismiss & close · ctrl+shift+c copy · ←/→ warning"
    BYPASS_NOTICE = (
        "  Warnings · 1 of 1 · Startup\n\n"
        "  `--dangerously-bypass-hook-trust` is enabled. Enabled hooks may run\n"
        "  without review for this invocation.\n\n"
        f"{WARNING_CONTROLS}"
    )
    UNSTABLE_FEATURES_NOTICE = (
        "  Warnings · 2 of 2 · Startup\n\n"
        "  Under-development features enabled: code_mode, example_feature.\n"
        "  Under-development features are incomplete and may behave unpredictably.\n"
        "  To suppress this warning, set `suppress_unstable_features_warning = true` in\n"
        "  /tmp/Codex Config/config.toml.\n\n"
        f"{WARNING_CONTROLS}"
    )
    HOOK_REVIEW = (
        "  Hooks need review\n  2 hooks are new or changed.\n\n"
        "› 1. Review hooks\n  2. Trust all and continue\n  3. Continue without trusting (hooks won't run)\n\n"
        "  enter confirm · esc skip"
    )

    def setUp(self):
        super().setUp()
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

        def hc(command, *args, timeout=None):
            if command == "ls":
                return {"terminals": [] if args else [owner]}
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

    def test_relaunch_keeps_working_when_only_timing_history_is_invalid(self):
        with tempfile.TemporaryDirectory() as previous, tempfile.TemporaryDirectory() as replacement:
            receipt = Path(previous) / "run.json"
            write_json(receipt, {"address": "t7", "closed_reason": "finished"})
            timing_file = receipt.with_name("timing.json")
            head = "a" * 40
            old = phase_timing.new_launch(phase_timing.empty_history(), 1000)
            saved_attempt = phase_timing.start(old, "review", head, False, 2000)
            write_json(timing_file, {"launches": None})
            with redirect_stderr(StringIO()) as warnings:
                self.launch_codex(replacement, lambda *_: DispatchReceiptTests.TERMINAL,
                                  relaunch_from=receipt, task=None)
            self.assertIn("cannot carry dispatch timing", warnings.getvalue())
            self.assertEqual(json.loads(timing_file.read_text(encoding="utf-8")), {"launches": None})
            self.assertEqual(json.loads((Path(replacement) / "run.json").read_text(encoding="utf-8"))["address"], "t7")
            started = phase_timing.read(Path(replacement) / "timing.json")
            self.assertEqual(len(started["launches"]), 1)
            self.assertIsNotNone(started["first_launched_ms"])
            current_attempt = phase_timing.start(started, "review", head, False, 3000)
            with self.assertRaisesRegex(ValueError, "unknown review attempt"):
                phase_timing.finish(started, "review", saved_attempt, "complete", 4000)
            self.assertNotEqual(saved_attempt, current_attempt)
            self.assertIsNone(started["launches"][0]["review"][0]["finished_ms"])

    def test_phase_timing_survives_retry_relaunch_and_repeated_collection(self):
        terminal = DispatchReceiptTests.TERMINAL
        sent = False

        def respond(command, *args):
            nonlocal sent
            if command == "get":
                return {**terminal, **(self.WORKING if sent else self.IDLE)}
            if command == "read":
                return self.screen(self.READY)
            self.assertEqual(command, "send")
            sent = True
            return {"started": True}

        def event(receipt, at, verb, **options):
            with patch("dispatch.phase_timing.now_ms", return_value=at), redirect_stdout(StringIO()) as output:
                timing(SimpleNamespace(run=receipt, event=verb, **({"tree": False} | options)))
            return output.getvalue().strip()

        first_head, final_head = "a" * 40, "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "run.json"
            with patch("dispatch.phase_timing.now_ms", side_effect=[1000, 1100]):
                self.launch_codex(directory, respond, task="$task-next #520 private prompt")
            review = event(first, 5000, "start", phase="review", sha=first_head)
            event(first, 5200, "finish", phase="review", attempt=review, outcome="complete")
            event(first, 5300, "finish", phase="review", attempt=review, outcome="complete")
            pending_review = event(first, 5350, "start", phase="review", sha=first_head)
            attempt = event(first, 5400, "start", phase="ci", sha=first_head)
            event(first, 5500, "finish", phase="ci", attempt=attempt, outcome="incomplete")
            attempt = event(first, 5600, "start", phase="ci", sha=first_head)
            event(first, 5800, "finish", phase="ci", attempt=attempt, outcome="failed")
            finished = {**terminal, "state": "finished"}
            with (
                patch("dispatch.phase_timing.now_ms", return_value=6000),
                patch("dispatch.hc_json", side_effect=[finished, {}]),
                redirect_stdout(StringIO()),
            ):
                collect(SimpleNamespace(run=first, close=True))

            replacement = Path(directory) / "replacement"
            replacement.mkdir()
            second = replacement / "run.json"
            sent = False
            with patch("dispatch.phase_timing.now_ms", side_effect=[6500, 6700]):
                self.launch_codex(replacement, respond, relaunch_from=first)
            tree = "c" * 40
            review = event(second, 8000, "start", phase="review", sha=tree, tree=True)
            event(second, 8050, "finish", phase="review", attempt=pending_review, outcome="complete")
            attempt = event(second, 8100, "start", phase="ci", sha=final_head)
            event(second, 8200, "finish", phase="review", attempt=review, outcome="complete")
            with patch("dispatch.subprocess.check_output", side_effect=["d" * 40, tree]) as git:
                with self.assertRaisesRegex(SystemExit, "does not match"):
                    event(second, 8300, "bind-review", attempt=review, head=final_head)
                event(second, 8300, "bind-review", attempt=review, head=final_head)
            self.assertEqual(git.call_args.args[0], ["git", "rev-parse", "--verify", f"{final_head}^{{tree}}"])
            event(second, 8350, "finish", phase="ci", attempt=attempt, outcome="passed")
            event(second, 8500, "merged", head=None)
            event(second, 8550, "merged", head=final_head)
            event(second, 8600, "merged", head=first_head)
            saved = second.with_name("timing.json")
            original = saved.read_bytes()
            self.assertNotIn(b"private prompt", original)
            with (
                patch("dispatch.phase_timing.now_ms", side_effect=AssertionError("poll is read-only")),
                patch("dispatch.hc_json", return_value=finished),
                redirect_stdout(StringIO()) as output,
            ):
                for _ in range(2):
                    collect(SimpleNamespace(run=second, close=False))
                collect(SimpleNamespace(run=second, close=False, brief=True))
            earlier, later, brief = output.getvalue().splitlines()
            self.assertEqual(earlier, later)
            self.assertEqual(saved.read_bytes(), original)
            self.assertIn("startup=200ms implementation=1300ms review=200ms ci=250ms restart=500ms", brief)
            report = json.loads(earlier)["timing"]
            self.assertEqual(report["final_head"], final_head)
            self.assertEqual(report["merge"], {"head": final_head, "confirmed_ms": 8500, "elapsed_ms": 7500})
            original_launch, restart = report["launches"]
            self.assertEqual((original_launch["startup_ms"], original_launch["implementation_ms"]), (100, 3900))
            self.assertEqual(original_launch["review"][0]["finished_ms"], 5200)
            self.assertEqual(original_launch["review"][1]["finished_ms"], 8050)
            self.assertEqual([a["head"] for a in original_launch["ci"]], [first_head, first_head])
            self.assertEqual([a["outcome"] for a in original_launch["ci"]], ["incomplete", "failed"])
            self.assertEqual(restart["review"][0]["head"], final_head)

    def test_launch_withholds_task_on_visible_hook_review_or_failure(self):
        for trust, dialog in ((False, self.HOOK_REVIEW), (True, self.HOOK_REVIEW),
                              (True, f"• Hook failed\n  └ SessionStart hook exited with code 1\n\n{self.READY}")):
            with self.subTest(trust=trust, dialog=dialog), tempfile.TemporaryDirectory() as directory:
                def respond(command, *args):
                    if command == "get":
                        return {**DispatchReceiptTests.TERMINAL, **self.IDLE}
                    if command == "read":
                        return self.screen(dialog)
                    self.fail(f"Task was withheld, but launch called hc {command} {args}")

                with self.assertRaisesRegex(SystemExit, "task withheld.*?/hooks"):
                    self.launch_codex(directory, respond, trust_hooks=trust)

    def test_authorized_launch_sends_after_closing_exact_startup_notice(self):
        for mode in ("immediate", "deferred", "already open"):
            deferred = mode != "immediate"
            already_open = mode == "already open"
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                operations = []
                banner = "  >_ OpenAI Codex (v0.172.0)\n\n"
                checked_after_escape = False
                warning_frames = iter([
                    self.screen(banner + self.SINGLE_WARNING),
                    {**self.screen(banner + self.BYPASS_NOTICE), "complete": False},
                    self.screen(banner + self.BYPASS_NOTICE),
                ])
                open_frames = iter([self.screen(banner + self.BYPASS_NOTICE)])

                def respond(command, *args):
                    nonlocal checked_after_escape
                    if command == "get":
                        viewer_open = operations == ["f2"] or (already_open and not operations)
                        state = self.WORKING if viewer_open or operations[-1:] == ["send"] else self.IDLE
                        if operations[-1:] == ["esc"] and not checked_after_escape:
                            checked_after_escape = True
                            state = self.WORKING
                        return {**DispatchReceiptTests.TERMINAL, **state, "turn": int(deferred)}
                    if command == "read":
                        if not operations:
                            return next(open_frames) if already_open else self.screen(banner + self.SINGLE_WARNING)
                        if operations == ["f2"]:
                            return next(warning_frames)
                        return self.screen(banner + self.READY)
                    if command == "keys":
                        operations.append(args[-1])
                        return {}
                    self.assertEqual(command, "send")
                    self.assertEqual(args[:4], ("--if", "idle", "--", "t7"))
                    self.assertTrue(checked_after_escape)
                    operations.append("send")
                    return {}

                self.launch_codex(directory, respond, trust_hooks=True, task=None if deferred else "$task-next")
                receipt = Path(directory) / "run.json"
                self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["trust_hooks"], True)
                if deferred:
                    self.assertEqual(operations, [])
                    with patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"), \
                            redirect_stdout(StringIO()):
                        send(SimpleNamespace(address="t7", message="$task-next", run=receipt))
                self.assertEqual(operations, ["esc", "send"] if already_open else ["f2", "esc", "send"])
                self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["sent"], True)

    def test_send_dismisses_two_recognized_startup_pages(self):
        first = self.BYPASS_NOTICE.replace("1 of 1", "1 of 2")
        wrapped = self.UNSTABLE_FEATURES_NOTICE.replace("Config/config.toml.", "Config/\n  config.toml.")
        for pages in ((first, self.UNSTABLE_FEATURES_NOTICE),
                      (wrapped.replace("2 of 2", "1 of 2"), first.replace("1 of 2", "2 of 2"))):
            with self.subTest(first=pages[0]), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "run.json"
                receipt.write_text(json.dumps({**DispatchReceiptTests.RECEIPT, "trust_hooks": True}),
                                   encoding="utf-8")
                terminal = {**DispatchReceiptTests.TERMINAL, **self.IDLE}
                frames = iter([self.TWO_WARNINGS, pages[0], pages[0], pages[1]])
                operations = []

                def respond(command, *args):
                    if command == "get":
                        return {**terminal, **self.WORKING} if operations[-1:] == ["send"] else terminal
                    if command == "read":
                        return self.screen(next(frames) if "esc" not in operations else self.READY)
                    if command == "keys":
                        operations.append(args[-1])
                    else:
                        self.assertEqual(command, "send")
                        operations.append("send")
                    return {}

                with patch("dispatch.hc_json", side_effect=respond), patch("dispatch.time.sleep"), \
                        redirect_stdout(StringIO()):
                    try:
                        send(SimpleNamespace(address="t7", message="a task", run=receipt))
                    except SystemExit as error:
                        self.fail(str(error))
                self.assertEqual(operations, ["f2", "right", "esc", "send"])
                self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["sent"], True)

    def test_startup_notice_requires_opt_in_and_recognized_pages(self):
        terminal = {**DispatchReceiptTests.TERMINAL, **self.IDLE}
        failure = "• Hook failed\n  └ SessionStart hook exited with code 1"
        first = self.screen(self.BYPASS_NOTICE.replace("1 of 1", "1 of 2"))
        unknown = self.screen(self.UNSTABLE_FEATURES_NOTICE.replace(
            "Under-development features are incomplete and may behave unpredictably.", "Review hooks first."))
        for label, opt_in, shown, responses, keys, reason in (
            ("no opt-in", False, self.SINGLE_WARNING, [], [], "F2"),
            ("open without opt-in", False, self.BYPASS_NOTICE, [], [], "F2"),
            ("open after startup", True, self.BYPASS_NOTICE, [{**terminal, "turn": 2}], [], "F2"),
            ("unrelated open page", True, self.BYPASS_NOTICE.replace("Startup", "Runtime"), [], [], "F2"),
            ("invalid footer count", True, self.SINGLE_WARNING.replace("1 warning", "0 warnings"), [], [], "F2"),
            ("wrong owner", True, self.SINGLE_WARNING,
             [{**terminal, "created_ms": 51}], [], "terminal identity changed"),
            ("busy", True, self.SINGLE_WARNING, [{**terminal, **self.WORKING}], [], "F2"),
            ("visible failure", True, f"{failure}\n\n{self.SINGLE_WARNING}", [], [], "/hooks"),
            ("unrelated body", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE.replace("is enabled", "is disabled"))], ["f2"], "F2"),
            ("extra body", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE.replace("\n\n  k", "\n  Extra warning\n\n  k"))],
             ["f2"], "F2"),
            ("page count mismatch", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE.replace("1 of 1", "1 of 2"))], ["f2"], "F2"),
            ("missing bypass notice", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.UNSTABLE_FEATURES_NOTICE.replace("2 of 2", "1 of 1")),
              terminal, {}, self.screen(self.SINGLE_WARNING)], ["f2"], "F2"),
            ("unknown second page", True, self.TWO_WARNINGS,
             [terminal, {}, first, terminal, {}, unknown, terminal, {}, self.screen(self.SINGLE_WARNING)],
             ["f2", "right"], "F2"),
            ("wrong source", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE.replace("Startup", "Runtime"))], ["f2"], "F2"),
            ("incomplete page", True, self.SINGLE_WARNING,
             [terminal, {}, {**self.screen(self.BYPASS_NOTICE), "complete": False}], ["f2"], "F2"),
            ("changed owner before Esc", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE), {**terminal, "created_ms": 51}],
             ["f2"], "terminal identity changed"),
            ("changed turn before Esc", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE), {**terminal, "turn": 1}], ["f2"], "F2"),
            ("warning after Esc", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE), terminal, {}, self.screen(self.SINGLE_WARNING)],
             ["f2", "esc"], "F2"),
            ("failure after Esc", True, self.SINGLE_WARNING,
             [terminal, {}, self.screen(self.BYPASS_NOTICE), terminal, {}, self.screen(failure)],
             ["f2", "esc"], "/hooks"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "run.json"
                data = DispatchReceiptTests.RECEIPT
                if opt_in:
                    data = {**data, "trust_hooks": True}
                receipt.write_text(json.dumps(data), encoding="utf-8")
                clock = [0, 0, 31] if label == "incomplete page" else None
                with patch("dispatch.hc_json", side_effect=[self.screen(shown), *responses]) as hc, \
                        patch("dispatch.time.sleep"), patch("dispatch.time.monotonic", side_effect=clock,
                                                            wraps=time.monotonic), \
                        self.assertRaisesRegex(SystemExit, reason):
                    send(SimpleNamespace(address="t7", message="a task", run=receipt))
                mutations = [action for action in hc.call_args_list if action.args[0] not in {"get", "read"}]
                self.assertEqual(mutations, [call("keys", "t7", key) for key in keys])
                self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))["sent"], False)

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

    def test_wrapped_hook_words_are_text_but_a_visible_hook_failure_is_a_blocker(self):
        shown = "› Review instructions\n\n  A note about what to do when a\n  hook failed again."
        self.assertEqual(codex_screen(f"{shown}\n\n{self.READY}"), "ready")
        failure = "• Hook failed\n  └ plugin contents changed; hook approval required"
        self.assertEqual(codex_screen(f"{shown}\n\n{failure}\n\n{self.READY}"), "hooks")
        for notice in ("  └ hook approval required", "  Hooks need review"):
            with self.subTest(notice=notice):
                self.assertEqual(codex_screen(f"{shown}\n\n{notice}\n\n{self.READY}"), "hooks")

    def test_screen_with_indented_tool_output_and_no_composer_is_waiting(self):
        screen = f"› a task\n\n  • Completed\n\n{self.FOOTER_0171}"
        self.assertEqual(codex_screen(screen, sent_message="a task"), "waiting")

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
            grant = DispatchReceiptTests.REVIEW_APPROVAL
            handoff = {**DispatchReceiptTests.HANDOFF, "extra_lines": extra_lines,
                       "review_transfer_approval": grant}
            run = {**DispatchReceiptTests.RECEIPT, "handoff": handoff, "require_review_sources": True}
            receipt.write_text(json.dumps(run), encoding="utf-8")
            args = SimpleNamespace(address="t7", message="a task", run=receipt)
            fields = {**DispatchReceiptTests.FIELDS, "Review transfer approval (verbatim)": grant}
            block = DispatchReceiptTests.BLOCK.replace(
                json.dumps(DispatchReceiptTests.FIELDS, ensure_ascii=False, indent=2),
                json.dumps(fields, ensure_ascii=False, indent=2),
            )
            expected = ("a task" + block + "\n\n" + extra_lines[0] + "\n"
                        + "\n".join(f"> {line}" for line in extra_lines[1:]) + "\n\n"
                        + report_instruction(receipt.resolve().with_name("result.json"), require_review_sources=True))
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
            self.assertIn("dispatch.py report-review", prompt)
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

    def test_recovered_delivery_uses_the_original_first_send_acknowledgment(self):
        working = {**DispatchReceiptTests.TERMINAL, **self.WORKING}
        for first_send in (False, True, None):
            with self.subTest(continuation=first_send), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "run.json"
                run = {**DispatchReceiptTests.RECEIPT, "sent": "unconfirmed", "send_acknowledged_ms": 1100}
                if first_send is not None:
                    run["sent_continuation"] = first_send
                write_json(receipt, run)
                with (
                    patch("dispatch.hc_json", side_effect=[working, self.screen(self.READY)]),
                    patch("dispatch.phase_timing.now_ms", side_effect=AssertionError("read the recorded time")),
                ):
                    with self.assertRaisesRegex(SystemExit, "use --continue"):
                        send(SimpleNamespace(address="t7", message="task", run=receipt))
                timing_data = phase_timing.read(receipt.with_name("timing.json"))
                self.assertEqual(timing_data["launches"][0]["delivered_ms"], 1100 if first_send is False else None)

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

    def test_pinned_lost_submission_checks_hooks_again_before_retry(self):
        terminal = {**DispatchReceiptTests.TERMINAL, **self.IDLE}
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "run.json"
            run = {**DispatchReceiptTests.RECEIPT, "wave": "fixture", "handoff": DispatchReceiptTests.HANDOFF}
            receipt.write_text(json.dumps(run), encoding="utf-8")

            def respond(command, *_args):
                if command == "read":
                    return self.screen(self.READY)
                return terminal if command == "get" else {}

            with (
                patch("dispatch.hc_json", side_effect=respond) as hc,
                patch("dispatch.time.sleep"),
                patch("dispatch.time.monotonic", side_effect=range(1000)),
                patch("dispatch.verify_pinned_delivery", side_effect=[None, SystemExit("pinned hooks changed")]),
                redirect_stderr(StringIO()),
                self.assertRaisesRegex(SystemExit, "pinned hooks changed"),
            ):
                send(SimpleNamespace(address="t7", message="$task-next", run=receipt))
        self.assertEqual(sum(c.args[0] == "send" for c in hc.call_args_list), 1)

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


class LaunchQuotaTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.claude, self.codex = self.root / "claude", self.root / "codex"
        self.claude.mkdir()
        self.now = dt.datetime.now(dt.timezone.utc)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.claude), "CODEX_HOME": str(self.codex),
                    "QUOTA_CLAUDE_CACHE": str(self.claude / "quota.json")}

    def write_usage(self, claude, codex, *, claude_five_hour=None):
        reset = (self.now + dt.timedelta(days=1)).timestamp()
        snapshot = {"used": claude, "reset": reset, "observed": self.now.timestamp()}
        if claude_five_hour is not None:
            snapshot["five_hour"] = {"used": claude_five_hour, "reset": self.now.timestamp() + 3600}
        (self.claude / "quota.json").write_text(json.dumps(snapshot), encoding="utf-8")
        session = self.codex / "sessions" / self.now.strftime("%Y/%m/%d") / "session.jsonl"
        session.parent.mkdir(parents=True, exist_ok=True)
        session.write_text(json.dumps({
            "type": "event_msg", "timestamp": self.now.isoformat(), "payload": {
                "type": "token_count", "rate_limits": {
                    "secondary": {"window_minutes": 10080, "used_percent": codex, "resets_at": reset},
                },
            },
        }), encoding="utf-8")

    def preview(self, cli, model, *options, effort="medium"):
        first_message = ["Example"] if cli == "claude" else ["--task", "Example"]
        return subprocess.run([
            sys.executable, "-I", str(SCRIPTS / "dispatch.py"), "launch", "--dry-run",
            "--cli", cli, "--model", model, "--effort", effort, "--cwd", str(self.root),
            "--work-kind", "standalone", "--request", "Example", "--unit", "Example",
            "--git-limits", "not specified", *options, *first_message,
        ], env=self.env, cwd=self.root, capture_output=True, text=True, encoding="utf-8")

    def test_codex_bias_requires_a_named_exception_for_opus_and_refuses_lower_tiers(self):
        self.write_usage(80, 10)
        for model in ("haiku", "claude-sonnet-4-6", "default"):
            with self.subTest(model=model):
                denied = self.preview("claude", model, "--bias-exception", "security")
                self.assertEqual(denied.returncode, 1)
                self.assertIn("quota bias codex refuses", denied.stderr)
        for options in ((), ("--bias-exception", "  "), ("--bias-exception", "mentions security")):
            with self.subTest(options=options):
                denied = self.preview("claude", "opus", *options)
                self.assertEqual(denied.returncode, 1)
                self.assertIn("requires --bias-exception", denied.stderr)
        accepted = self.preview("claude", "claude-opus-4-6", "--bias-exception", "Auth: SSO")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout)["bias_exception"], "Auth: SSO")

    def test_claude_bias_moves_codex_rows_and_keeps_top_tier(self):
        self.write_usage(10, 80)
        for model, effort in (("gpt-6-luna", "medium"), ("gpt-6.1-terra", "high"),
                              ("gpt-6.2-sol", "medium"), ("gpt-6.2-sol", "high")):
            with self.subTest(model=model, effort=effort):
                denied = self.preview("codex", model, effort=effort)
                self.assertEqual(denied.returncode, 1)
                self.assertIn("quota bias claude refuses", denied.stderr)
        accepted = self.preview("codex", "gpt-6.2-sol", effort="xhigh")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_expiring_passes_tighten_top_tier_exceptions_in_either_direction(self):
        self.write_usage(10, 10)
        for cli, model, home, preferred in (
            ("claude", "opus", self.codex, "codex"),
            ("codex", "gpt-6.2-sol", self.claude, "claude"),
        ):
            with self.subTest(cli=cli):
                path = home / "reset-passes.json"
                path.write_text(json.dumps([(self.now + dt.timedelta(hours=1)).isoformat()]), encoding="utf-8")
                denied = self.preview(cli, model, "--bias-exception", "data migration", effort="xhigh")
                self.assertEqual(denied.returncode, 1)
                self.assertIn("requires --bias-exception with one of: production DB, deploy", denied.stderr)
                accepted = self.preview(cli, model, "--bias-exception", "production DB", effort="xhigh")
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                audit = json.loads(accepted.stdout)
                self.assertEqual(audit["bias"], preferred)
                self.assertTrue(audit["quota_snapshot"]["prefer_expiring_passes"])
                path.unlink()

    def test_critical_approval_is_independent_of_pin_and_passes(self):
        for cli, model, home, usage in (
            ("claude", "sonnet", self.claude, (90, 10)),
            ("codex", "gpt-6-luna", self.codex, (10, 90)),
        ):
            with self.subTest(cli=cli):
                self.write_usage(*usage)
                (home / "reset-passes.json").write_text(
                    json.dumps([(self.now + dt.timedelta(hours=1)).isoformat()]), encoding="utf-8")
                denied = self.preview(cli, model, "--user-pinned")
                self.assertEqual(denied.returncode, 1)
                self.assertIn("requires explicit user approval", denied.stderr)
                still_biased = self.preview(cli, model, "--approve-critical")
                self.assertEqual(still_biased.returncode, 1)
                self.assertIn("quota bias", still_biased.stderr)
                accepted = self.preview(cli, model, "--user-pinned", "--approve-critical")
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                audit = json.loads(accepted.stdout)
                self.assertEqual(audit["quota_snapshot"][cli]["raw_state"], "critical")
                self.assertTrue(audit["critical_approved"])
                self.assertIn("user_pin_reason", audit)

    def test_both_hot_uses_the_longer_runway_or_the_base_table_on_a_tie(self):
        self.write_usage(80, 75)
        denied = self.preview("claude", "sonnet")
        self.assertEqual(denied.returncode, 1)
        self.assertIn("quota bias codex", denied.stderr)
        self.write_usage(75, 75)
        accepted = self.preview("claude", "sonnet")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        audit = json.loads(accepted.stdout)
        self.assertEqual(audit["bias"], "both-hot")
        self.assertEqual(audit["quota_snapshot"]["effective_bias"], "none")

    def test_both_hot_prefers_the_cli_that_can_launch_without_critical_approval(self):
        self.write_usage(10, 80, claude_five_hour=90)
        accepted = self.preview("codex", "gpt-6-luna")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        audit = json.loads(accepted.stdout)
        self.assertEqual(audit["bias"], "both-hot")
        self.assertEqual(audit["quota_snapshot"]["effective_bias"], "codex")

    def test_both_critical_allows_the_cli_with_explicit_approval(self):
        self.write_usage(90, 95)
        accepted = self.preview("codex", "gpt-6-luna", "--approve-critical")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        audit = json.loads(accepted.stdout)
        self.assertEqual(audit["bias"], "both-hot")
        self.assertEqual(audit["quota_snapshot"]["effective_bias"], "none")

    def test_unreadable_codex_log_does_not_disable_claude_critical_gate(self):
        self.write_usage(90, 10)
        original_stat = Path.stat

        def stat(path, *args, **kwargs):
            if path.name == "session.jsonl":
                raise FileNotFoundError(path)
            return original_stat(path, *args, **kwargs)

        snapshot_path = self.claude / "quota.json"
        with (patch.dict(os.environ, self.env), patch("quota.claude_snapshot", return_value=claude_snapshot(snapshot_path)),
              patch("quota.Path.stat", stat), redirect_stdout(StringIO()) as output):
            quota_main()
        snapshot = json.loads(output.getvalue())
        self.assertEqual(snapshot["codex"]["state"], "unknown")
        self.assertEqual(snapshot["claude"]["state"], "critical")
        args = SimpleNamespace(cwd=str(self.root), name=None, parent=None, cli="claude", model="sonnet",
                               effort="medium", task=None, message="Example", keep_connectors=False,
                               dry_run=True, **(DispatchReceiptTests.HANDOFF | {"work_kind": "standalone"}))
        with patch("dispatch.read_quota_snapshot", return_value=snapshot):
            with self.assertRaisesRegex(SystemExit, "requires explicit user approval"):
                launch(args)

    def test_unknown_snapshots_warn_and_leave_the_base_route_available(self):
        accepted = self.preview("claude", "sonnet")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        for cli in ("claude", "codex"):
            self.assertIn(f"{cli} quota snapshot is unavailable", accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout)["bias"], "none")

    def test_unknown_preferred_cli_does_not_block_an_available_hot_cli(self):
        self.write_usage(80, 10)
        (self.codex / "sessions" / self.now.strftime("%Y/%m/%d") / "session.jsonl").unlink()
        accepted = self.preview("claude", "sonnet")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("codex quota snapshot is unavailable", accepted.stderr)
        audit = json.loads(accepted.stdout)
        self.assertEqual(audit["bias"], "codex")
        self.assertEqual(audit["quota_snapshot"]["effective_bias"], "none")

    def test_known_expiring_pass_does_not_block_a_cli_with_an_unknown_snapshot(self):
        self.write_usage(10, 10)
        (self.claude / "quota.json").unlink()
        (self.codex / "reset-passes.json").write_text(
            json.dumps([(self.now + dt.timedelta(hours=1)).isoformat()]), encoding="utf-8")
        accepted = self.preview("claude", "sonnet")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("claude quota snapshot is unavailable", accepted.stderr)
        audit = json.loads(accepted.stdout)
        self.assertEqual(audit["quota_snapshot"]["effective_bias"], "codex")
        self.assertTrue(audit["quota_snapshot"]["prefer_expiring_passes"])

    def test_quota_process_failure_or_invalid_output_warns_and_allows_launch(self):
        args = SimpleNamespace(cwd=str(self.root), name=None, parent=None, cli="claude", model="sonnet",
                               effort="medium", task=None, message="Example", keep_connectors=False,
                               dry_run=True, **(DispatchReceiptTests.HANDOFF | {"work_kind": "standalone"}))
        for response in (subprocess.TimeoutExpired(["quota.py"], 10), SimpleNamespace(stdout="bad JSON"),
                         SimpleNamespace(stdout='{"bias":"none"}')):
            with self.subTest(response=response), patch("dispatch.subprocess.run", side_effect=[response]) as run, \
                    patch("dispatch.warn_linked_worktree"), redirect_stdout(StringIO()) as output, \
                    redirect_stderr(StringIO()) as errors:
                launch(args)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0], [sys.executable, "-I", "-X", "utf8", str(SCRIPTS / "quota.py")])
                self.assertIsNone(json.loads(output.getvalue())["quota_snapshot"])
                self.assertIn("warning: quota check unavailable", errors.getvalue())


@unittest.skipIf(os.name == "nt", "fixture uses a POSIX executable script")
class ResetPassRefreshTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cache = self.home / "reset-passes.json"
        self.marker = self.home / "reset-passes.refreshed"
        self.requests = self.home / "requests"
        self.response = self.home / "response.json"
        self.expiry = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(days=30)
        self.old_cache = json.dumps([(self.expiry + dt.timedelta(days=days)).isoformat() for days in (1, 2)]) + "\n"
        self.cache.write_text(self.old_cache, encoding="utf-8")
        codex = self.home / "codex"
        codex.write_text(f"#!{sys.executable}\n" + """\
import json
import os
import sys
import time
from pathlib import Path

assert sys.argv[1:] == ["app-server"], sys.argv
home = Path(os.environ["CODEX_HOME"])
initialize = json.loads(input())
assert initialize["method"] == "initialize", initialize
print(json.dumps({"id": initialize["id"], "result": {"codexHome": str(home)}}), flush=True)
assert json.loads(input()) == {"method": "initialized"}
request = json.loads(input())
with (home / "requests").open("a", encoding="utf-8") as log:
    log.write(request["method"] + "\\n")
assert request["method"] == "account/rateLimits/read", request
assert request["params"] == {"excludeResetCreditDetails": False}, request
response = json.loads((home / "response.json").read_text(encoding="utf-8"))
time.sleep(response.pop("delay", 0))
print(json.dumps({"id": request["id"], **response}), flush=True)
assert not sys.stdin.readline(), "unexpected extra request"
""", encoding="utf-8")
        codex.chmod(0o700)
        self.env = {**os.environ, "CODEX_HOME": str(self.home), "PATH": f"{self.home}{os.pathsep}{os.environ['PATH']}"}
        self.env["CLAUDE_CONFIG_DIR"] = str(self.home / "claude")
        self.env["QUOTA_CLAUDE_CACHE"] = str(self.home / "claude-quota.json")
        self.credit = {"id": "credit-1", "status": "available", "resetType": "codexRateLimits",
                       "expiresAt": int(self.expiry.timestamp())}
        self.set_response({"availableCount": 1, "credits": [self.credit]})

    def set_response(self, summary):
        self.response.write_text(json.dumps({"result": {"rateLimitResetCredits": summary}}), encoding="utf-8")

    def command(self, *args):
        return [sys.executable, "-I", str(SCRIPTS / "quota.py"), *args]

    def quota_command(self, *args):
        return subprocess.run(self.command(*args), env=self.env, text=True, capture_output=True, timeout=35)

    def test_wave_planning_refreshes_legacy_cache_before_assessing_and_reuses_success(self):
        skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
        planning_args = re.search(r'For wave planning, run `python3 -I "<dispatch>/scripts/quota.py"([^\n`]*)`', skill)
        self.assertIsNotNone(planning_args)
        args = planning_args[1].split()
        result = self.quota_command(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.cache.read_bytes()), [self.expiry.isoformat().replace("+00:00", "Z")])
        self.assertEqual(json.loads(result.stdout)["codex"]["reset_passes"], 1)
        self.assertEqual(self.requests.read_text(encoding="utf-8").splitlines(), ["account/rateLimits/read"])
        self.set_response({"availableCount": 0})
        self.assertEqual(json.loads(self.quota_command(*args).stdout)["codex"]["reset_passes"], 1)
        self.assertEqual(self.requests.read_text(encoding="utf-8").splitlines(), ["account/rateLimits/read"])
        prior_day = time.time() - 24 * 3600
        os.utime(self.marker, (prior_day, prior_day))
        self.assertEqual(json.loads(self.quota_command(*args).stdout)["codex"]["reset_passes"], 0)
        self.assertEqual(json.loads(self.cache.read_bytes()), [])

    def test_manual_forces_explicit_zero_and_ordinary_reads_use_only_cache(self):
        self.assertEqual(self.quota_command("--refresh-if-stale").returncode, 0)
        self.set_response({"availableCount": 0, "credits": None})
        self.assertEqual(json.loads(self.quota_command().stdout)["codex"]["reset_passes"], 1)
        self.assertEqual(self.requests.read_text(encoding="utf-8").splitlines(), ["account/rateLimits/read"])
        result = self.quota_command("--refresh-codex-reset-passes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.cache.read_bytes()), [])
        self.assertEqual(self.requests.read_text(encoding="utf-8").splitlines(), ["account/rateLimits/read"] * 2)

    def test_bad_responses_keep_last_successful_cache_and_report_age(self):
        result = self.quota_command("--refresh-if-stale")
        self.assertEqual(result.returncode, 0, result.stderr)
        cached = self.cache.read_bytes()
        prior = time.time() - 25 * 3600
        os.utime(self.marker, (prior, prior))
        for response in (
            {"result": {}},
            {"result": {"rateLimitResetCredits": {"availableCount": 2, "credits": [self.credit]}}},
            {"result": {"rateLimitResetCredits": {"availableCount": 1, "credits": [{**self.credit, "expiresAt": None}]}}},
            {"result": {"rateLimitResetCredits": {"availableCount": False}}},
            {"error": {"code": -32601, "message": "unsupported"}},
        ):
            with self.subTest(response=response):
                self.response.write_text(json.dumps(response), encoding="utf-8")
                result = self.quota_command("--refresh-if-stale")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["codex"]["reset_passes"], 1)
                self.assertIn("last successful refresh 25.0h ago", result.stderr)
                self.assertEqual(self.cache.read_bytes(), cached)
        failure = self.quota_command("--refresh-codex-reset-passes")
        self.assertEqual(failure.returncode, 1, failure.stderr)

    def test_parallel_planners_share_one_refresh(self):
        self.response.write_text(json.dumps({
            "result": {"rateLimitResetCredits": {"availableCount": 0}}, "delay": 0.25,
        }), encoding="utf-8")
        with subprocess.Popen(self.command("--refresh-if-stale"), env=self.env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as first:
            second = self.quota_command("--refresh-if-stale")
            stdout, stderr = first.communicate(timeout=5)
        self.assertEqual(first.returncode, 0, stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual([json.loads(output)["codex"]["reset_passes"] for output in (stdout, second.stdout)], [0, 0])
        self.assertEqual(self.requests.read_text(encoding="utf-8").splitlines(), ["account/rateLimits/read"])

    def test_lookup_timeout_keeps_legacy_cache_and_reports_file_age(self):
        self.response.write_text(json.dumps({"delay": 60}), encoding="utf-8")
        with (patch.dict(os.environ, self.env), patch("quota.RESET_PASS_LOOKUP_TIMEOUT", 0.5),
              redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err):
            quota_main(["--refresh-if-stale"])
        self.assertIn("timed out", err.getvalue())
        self.assertIn("cache file age", err.getvalue())
        self.assertEqual(self.cache.read_text(encoding="utf-8"), self.old_cache)
        self.assertEqual(json.loads(out.getvalue())["codex"]["reset_passes"], 2)
        self.assertFalse(self.marker.exists())

    def test_run_codex_from_resolved_executable_path(self):
        executable = (self.home / "codex").rename(self.home / "codex.cmd")
        with (patch.dict(os.environ, {**self.env, "PATH": str(self.home)}),
              patch("shutil.which", return_value=str(executable)) as which,
              redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err):
            quota_main(["--refresh-if-stale"])
        self.assertEqual(json.loads(out.getvalue())["codex"]["reset_passes"], 1, err.getvalue())
        which.assert_called_once_with("codex")

    def test_missing_codex_preserves_legacy_cache_and_skips_unconfigured_home(self):
        (self.home / "codex").unlink()
        self.env["PATH"] = str(self.home)
        legacy = self.quota_command("--refresh-if-stale")
        self.assertEqual(json.loads(legacy.stdout)["codex"]["reset_passes"], 2)
        self.assertIn("cache file age", legacy.stderr)
        self.assertFalse((self.home / "reset-passes.lock").exists())
        new_home = self.home / "unconfigured"
        self.env["CODEX_HOME"] = str(new_home)
        result = self.quota_command("--refresh-if-stale")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertFalse(new_home.exists())
        manual = self.quota_command("--refresh-codex-reset-passes")
        self.assertEqual(manual.returncode, 1)
        self.assertIn("Codex CLI executable not found", manual.stderr)
        self.assertFalse(new_home.exists())


class QuotaTests(unittest.TestCase):
    def test_claude_pass_defaults_to_claude_home_and_filters_by_weekly_reset(self):
        now = dt.datetime(2026, 12, 10, tzinfo=dt.timezone.utc).timestamp()
        snapshot = {"used": 75, "reset": now + 2 * 86400, "observed": now}
        expiry = "2026-12-11T07:00:00+09:00"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".claude" / "reset-passes.json"
            path.parent.mkdir()
            path.write_text(json.dumps([expiry]), encoding="utf-8")
            with (patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}),
                  patch("quota.Path.home", return_value=home), patch("quota.time.time", return_value=now),
                  patch("quota.claude_snapshot", return_value=snapshot), redirect_stdout(StringIO()) as output):
                quota_main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["claude"]["state"], "ok")
            self.assertEqual(result["claude"]["raw_state"], "hot")
            self.assertEqual(result["claude"]["reset_passes"], 1)
            self.assertEqual(result["claude"]["reset_passes_before_weekly_reset"], [expiry])
            self.assertEqual(result["bias"], "claude")
            self.assertTrue(result["prefer_expiring_passes"])

    def test_codex_reset_passes_change_routing_and_flag_expiries(self):
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        reset = now + dt.timedelta(days=1)
        soon = (now + dt.timedelta(hours=1)).astimezone(dt.timezone(dt.timedelta(hours=9)))
        later = now + dt.timedelta(hours=2)
        expiries = [
            (reset + dt.timedelta(days=1)).isoformat(), later.isoformat(), reset.isoformat(),
            (now - dt.timedelta(hours=1)).isoformat(), soon.isoformat(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, "CODEX_HOME": str(root), "QUOTA_CLAUDE_CACHE": str(root / "missing")}
            command = [sys.executable, "-I", str(SCRIPTS / "quota.py")]
            passes = root / "reset-passes.json"
            passes.write_text(json.dumps(expiries), encoding="utf-8")
            unknown = json.loads(subprocess.check_output(command, cwd=root, env=env))["codex"]
            self.assertEqual(unknown, {
                "state": "unknown", "reset_passes": 4, "reset_passes_before_weekly_reset": [],
            })

            session = root / "sessions" / now.strftime("%Y/%m/%d") / "session.jsonl"
            session.parent.mkdir(parents=True)
            for used, expected_state, expected_bias in (
                (90, "hot", "claude"), (75, "ok", "codex"), (10, "ok", "codex"),
            ):
                with self.subTest(used=used):
                    session.write_text(json.dumps({
                        "type": "event_msg", "timestamp": now.isoformat(), "payload": {
                            "type": "token_count", "rate_limits": {
                                "primary": {"window_minutes": 10080, "used_percent": used,
                                            "resets_at": reset.timestamp()},
                            },
                        },
                    }), encoding="utf-8")
                    result = json.loads(subprocess.check_output(command, cwd=root, env=env))
                    self.assertEqual(result["codex"]["used"], used)
                    self.assertEqual(result["codex"]["state"], expected_state)
                    self.assertEqual(result["codex"]["reset_passes"], 4)
                    self.assertEqual(result["codex"]["reset_passes_before_weekly_reset"],
                                     [soon.isoformat(), later.isoformat()])
                    self.assertEqual(result["bias"], expected_bias)
                    self.assertEqual(result["prefer_expiring_passes"], expected_bias == "codex")

    def test_codex_reset_passes_missing_malformed_or_expired(self):
        now = dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc)
        snapshot = {"used": 90, "reset": now.timestamp() + WEEK, "observed": now.timestamp()}
        with tempfile.TemporaryDirectory() as directory:
            passes = Path(directory) / ".codex" / "reset-passes.json"
            passes.parent.mkdir()
            for data, count in (
                (None, 0), (b"\xff", 0), (b"[", 0), (b"{}", 0), (b"[null]", 0),
                (b'["2026-11-27T00:00:00Z", "invalid"]', 0),
                (b'["2026-12-04"]', 0),
                (b'["2026-11-25T00:00:00Z", "2026-11-26T00:00:00Z"]', 0),
                (b'["2026-12-04T00:00:00Z", "2026-12-05T00:00:00"]', 2),
            ):
                with self.subTest(data=data):
                    if data is not None:
                        passes.write_bytes(data)
                    with patch("quota.codex_snapshot", return_value=snapshot), \
                            patch("quota.claude_snapshot", return_value=None), \
                            patch("quota.time.time", return_value=now.timestamp()), \
                            patch.dict(os.environ, {"CODEX_HOME": ""}), \
                            patch("quota.Path.home", return_value=Path(directory)), \
                            redirect_stdout(StringIO()) as output:
                        quota_main()
                    codex = json.loads(output.getvalue())["codex"]
                    self.assertEqual(codex["state"], "hot" if count else "critical")
                    self.assertEqual(codex["reset_passes"], count)
                    self.assertEqual(codex["reset_passes_before_weekly_reset"], [])

    def test_weekly_pace_is_at_most_hot_and_preserves_runway(self):
        now = 1_800_000_000
        result = assess({"used": 83, "reset": now + WEEK * 0.554, "observed": now}, now)
        self.assertEqual(result["state"], "hot")
        self.assertEqual(result["elapsed"], 44.6)
        self.assertEqual(result["runway_h"], 15.3)
        self.assertEqual(result["reset_in_h"], 93.1)

    def test_small_early_weekly_pace_does_not_raise_state(self):
        now = 1_800_000_000
        result = assess({"used": 11, "reset": now + WEEK * 0.892, "observed": now}, now)
        self.assertEqual(result["elapsed"], 10.8)
        self.assertEqual(result["state"], "ok")
        self.assertLess(result["runway_h"], result["reset_in_h"])

    def test_weekly_state_thresholds_use_unrounded_values(self):
        now = 1_800_000_000
        for used, elapsed_h, state in (
            (89.99, 1, "hot"),
            (90, 1, "critical"),
            (74.99, 1, "ok"),
            (75, 1, "hot"),
            (18, 24 - 1 / 3600, "ok"),
            (18, 24, "hot"),
            (59.99, 84, "ok"),
            (60, 84, "ok"),
            (60.01, 84, "hot"),
            (70, 92.4, "hot"),
        ):
            with self.subTest(used=used, elapsed_h=elapsed_h):
                reset = now + WEEK - elapsed_h * 3600
                result = assess({"used": used, "reset": reset, "observed": now}, now)
                self.assertEqual(result["state"], state)

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
            (89.99, now + 3600, "hot"),
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
            unknown = {"state": "unknown", "reset_passes": 0, "reset_passes_before_weekly_reset": []}
            self.assertEqual(missing["claude"], unknown)
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

    def test_reader_treats_incomplete_claude_snapshot_as_unknown(self):
        now = time.time()
        valid = {"used": 42, "reset": now + 86400, "observed": now}
        broken = [
            [], {}, {"used": 42}, {"used": 42, "reset": now + 86400},
            {**valid, "used": "42"}, {**valid, "used": 101}, {**valid, "reset": None},
            {**valid, "observed": True}, {**valid, "reset": 10 ** 400},
        {**valid, "observed": 10 ** 400},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "status-line.json"
            env = {**os.environ, "QUOTA_CLAUDE_CACHE": str(snapshot), "CODEX_HOME": str(root)}
            command = [sys.executable, "-I", str(SCRIPTS / "quota.py")]
            for data in broken:
                with self.subTest(data=data):
                    snapshot.write_text(json.dumps(data), encoding="utf-8")
                    out = json.loads(subprocess.check_output(command, cwd=root, env=env))
                    self.assertEqual(out["claude"]["state"], "unknown")
                    self.assertIn("state", out["codex"])
            snapshot.write_text("[" * 100000, encoding="utf-8")
            out = json.loads(subprocess.check_output(command, cwd=root, env=env))
            self.assertEqual(out["claude"]["state"], "unknown")
            snapshot.write_text(json.dumps({**valid, "five_hour": {"used": 91}}), encoding="utf-8")
            out = json.loads(subprocess.check_output(command, cwd=root, env=env))
            self.assertEqual(out["claude"]["used"], 42)
            self.assertNotIn("five_hour_used", out["claude"])


if __name__ == "__main__":
    unittest.main()
