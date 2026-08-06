#!/usr/bin/env python3
"""
Unit tests for scan_transcripts.py — resolve_project_dir() exact-match priority,
and the Codex-side session discovery / parsing added alongside it.

Run: python test_scan_transcripts.py
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "scan_transcripts.py"
spec = importlib.util.spec_from_file_location("scan_transcripts", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def test_resolve_prefers_exact_match_over_higher_file_count_fuzzy_match():
    """Exact encode_project() dir wins even when a fuzzy sibling has more files."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/knue-patis"
        exact_name = mod.encode_project(path)
        exact_dir = os.path.join(proj_root, exact_name)
        os.mkdir(exact_dir)
        open(os.path.join(exact_dir, "session1.jsonl"), "w").close()

        fuzzy_name = exact_name.replace("-", "_", 1)
        fuzzy_dir = os.path.join(proj_root, fuzzy_name)
        os.mkdir(fuzzy_dir)
        for i in range(5):
            open(os.path.join(fuzzy_dir, f"session{i}.jsonl"), "w").close()

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir returns exact dir despite fuzzy dir having more files",
            resolved == exact_dir,
            f"expected {exact_dir!r}, got {resolved!r}",
        )


def test_resolve_falls_back_to_fuzzy_when_exact_absent():
    """No exact dir → fuzzy match by loose key, picking the most populated candidate."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/knue-patis"
        exact_name = mod.encode_project(path)

        fuzzy_name = exact_name.replace("-", "_", 1)
        fuzzy_dir = os.path.join(proj_root, fuzzy_name)
        os.mkdir(fuzzy_dir)
        open(os.path.join(fuzzy_dir, "session0.jsonl"), "w").close()

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir falls back to fuzzy match when exact dir absent",
            resolved == fuzzy_dir,
            f"expected {fuzzy_dir!r}, got {resolved!r}",
        )


def test_resolve_skips_empty_exact_dir_in_favor_of_populated_fuzzy_sibling():
    """Exact dir exists but has 0 jsonl files → resolver falls through to the
    populated fuzzy sibling instead of trusting the empty exact-match slot."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/knue-patis"
        exact_name = mod.encode_project(path)
        exact_dir = os.path.join(proj_root, exact_name)
        os.mkdir(exact_dir)  # exists but empty — e.g. created solely by Step 6's state write

        fuzzy_name = exact_name.replace("-", "_", 1)
        fuzzy_dir = os.path.join(proj_root, fuzzy_name)
        os.mkdir(fuzzy_dir)
        open(os.path.join(fuzzy_dir, "session0.jsonl"), "w").close()

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir returns fuzzy sibling when exact dir has no jsonl files",
            resolved == fuzzy_dir,
            f"expected {fuzzy_dir!r}, got {resolved!r}",
        )


def test_resolve_prefers_empty_exact_dir_over_equally_empty_fuzzy_sibling():
    """Exact dir exists but empty, and a loose-key-matching sibling is ALSO empty →
    the empty exact dir is the floor (best_count seeded from exact_count), not an
    arbitrary equally-empty sibling."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/knue-patis"
        exact_name = mod.encode_project(path)
        exact_dir = os.path.join(proj_root, exact_name)
        os.mkdir(exact_dir)  # exists but empty

        fuzzy_name = exact_name.replace("-", "_", 1)
        fuzzy_dir = os.path.join(proj_root, fuzzy_name)
        os.mkdir(fuzzy_dir)  # also empty — no jsonl files

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir returns empty exact dir over equally-empty fuzzy sibling",
            resolved == exact_dir,
            f"expected {exact_dir!r}, got {resolved!r}",
        )


def test_resolve_falls_back_to_exact_path_when_nothing_matches():
    """No exact dir, no fuzzy sibling → returns the (nonexistent) exact path."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/totally-unrelated"
        exact = os.path.join(proj_root, mod.encode_project(path))

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir returns exact path when nothing matches",
            resolved == exact,
            f"expected {exact!r}, got {resolved!r}",
        )


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_codex_session_meta_cwd_matches_project_and_ignores_others():
    """find_codex_session_files matches only files whose session_meta.cwd equals the
    target project path — Codex sessions are date-partitioned, not project-partitioned,
    so this cwd check is the only way to attribute a rollout file to a project."""
    with tempfile.TemporaryDirectory() as codex_root:
        day_dir = os.path.join(codex_root, "sessions", "2026", "01", "01")
        os.makedirs(day_dir)
        target = "/Users/me/Dev/toolkit"
        match_fp = os.path.join(day_dir, "rollout-match.jsonl")
        other_fp = os.path.join(day_dir, "rollout-other.jsonl")
        _write_jsonl(match_fp, [{"type": "session_meta", "payload": {"cwd": target}}])
        _write_jsonl(other_fp, [{"type": "session_meta", "payload": {"cwd": "/Users/me/Dev/other"}}])

        matches = mod.find_codex_session_files(codex_root, target)
        check(
            "find_codex_session_files returns only the matching-cwd file",
            matches == [match_fp],
            f"expected [{match_fp!r}], got {matches!r}",
        )


def test_codex_session_files_exclude_archived_sessions():
    """archived_sessions/ must never be scanned (retention overflow, not the working
    set — see module docstring); only sessions/ is walked."""
    with tempfile.TemporaryDirectory() as codex_root:
        target = "/Users/me/Dev/toolkit"
        archived_dir = os.path.join(codex_root, "archived_sessions", "2026", "01", "01")
        os.makedirs(archived_dir)
        archived_fp = os.path.join(archived_dir, "rollout-archived.jsonl")
        _write_jsonl(archived_fp, [{"type": "session_meta", "payload": {"cwd": target}}])

        matches = mod.find_codex_session_files(codex_root, target)
        check(
            "find_codex_session_files ignores archived_sessions even on a cwd match",
            matches == [],
            f"expected no matches, got {matches!r}",
        )


def test_codex_message_text_joins_input_text_blocks():
    payload = {"role": "user", "content": [{"type": "input_text", "text": "hello "},
                                            {"type": "input_text", "text": "world"}]}
    text = mod._codex_message_text(payload)
    check(
        "_codex_message_text joins multiple input_text blocks",
        text == "hello  world",
        f"got {text!r}",
    )


def test_codex_turn_signal_detects_skill_load_marker():
    txt = "<skill>\n<name>dev:task-next</name>\n<path>/x/SKILL.md</path>\n---\nname: task-next\n"
    kind, value = mod._codex_turn_signal(txt)
    check(
        "_codex_turn_signal extracts the skill name from a <skill> load marker",
        (kind, value) == ("skill", "dev:task-next"),
        f"got {(kind, value)!r}",
    )


def test_codex_turn_signal_flags_harness_injected_noise():
    for txt in [
        "<environment_context>...</environment_context>",
        "<user_action>\n  <context>User initiated a review task.</context>\n</user_action>",
        "# AGENTS.md instructions for /Users/me/Dev/toolkit\n\n<INSTRUCTIONS>",
        "<hook_prompt hook_run_id=\"stop:1:/x\">some output</hook_prompt>",
    ]:
        kind, _ = mod._codex_turn_signal(txt)
        check(
            f"_codex_turn_signal flags harness-injected noise: {txt[:40]!r}",
            kind == "noise",
            f"got kind={kind!r}",
        )


def test_codex_turn_signal_passes_through_ordinary_user_text():
    kind, value = mod._codex_turn_signal("please fix the failing test in parser.py")
    check(
        "_codex_turn_signal returns (None, None) for ordinary free-text turns",
        (kind, value) == (None, None),
        f"got {(kind, value)!r}",
    )


def test_scan_codex_files_skips_malformed_lines_without_raising():
    """Never raises on a malformed line (module invariant) — a bad line is skipped,
    not fatal, and well-formed records around it still get parsed."""
    with tempfile.TemporaryDirectory() as d:
        fp = os.path.join(d, "rollout-x.jsonl")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "session_meta", "payload": {"cwd": "/x"}}) + "\n")
            f.write("{not valid json\n")
            f.write(json.dumps({
                "type": "response_item", "timestamp": "2026-01-01T00:00:00.000Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "please investigate the failing build"}]},
            }) + "\n")

        try:
            summary = mod.scan_codex_files([fp])
        except Exception as e:
            check("scan_codex_files never raises on a malformed line", False, f"raised {e!r}")
        else:
            check(
                "scan_codex_files never raises on a malformed line",
                True,
            )
            check(
                "scan_codex_files still parses the well-formed record around the bad line",
                summary["sessions"] == 1 and len(summary["prompts"]) == 1,
                f"got {summary!r}",
            )


def _assistant_tool_use(blocks):
    return {"type": "assistant", "timestamp": "2026-01-01T00:00:00.000Z",
            "message": {"content": blocks}}


def _user_tool_result(tool_use_id, content, is_error=False):
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "timestamp": "2026-01-01T00:00:01.000Z",
            "message": {"content": [block]}}


def test_scan_dir_collects_verifier_failures():
    """VERIFIER-FAILURES (Signal 8): a failing CI command, a qa-verifier rejection,
    and a hook denial are each collected with the right kind label."""
    with tempfile.TemporaryDirectory() as tdir:
        _write_jsonl(os.path.join(tdir, "s1.jsonl"), [
            _assistant_tool_use([{"type": "tool_use", "name": "Bash", "id": "t1",
                                  "input": {"command": "bash scripts/ci-wait.sh 123"}}]),
            _user_tool_result("t1", "run 3 concluded: failure", is_error=True),
            _assistant_tool_use([{"type": "tool_use", "name": "Agent", "id": "t2",
                                  "input": {"subagent_type": "qa-verifier",
                                            "prompt": "verify sprint contract"}}]),
            _user_tool_result("t2", [{"type": "text",
                                      "text": "VERDICT: BLOCKING — criterion 2 not met"}]),
            _user_tool_result("t9", "PreToolUse:Bash hook error: commit-guard: blocked —"
                                    " branch 'main' is protected", is_error=True),
        ])
        summary = mod.scan_dir(tdir, "fixture")
        kinds = [k for k, _ in summary["verifier_failures"]]
        check(
            "scan_dir collects ci-fail, qa-reject, hook-deny",
            kinds == ["ci-fail", "qa-reject", "hook-deny"],
            f"got {summary['verifier_failures']!r}",
        )
        check(
            "ci-fail detail carries the failing command",
            "ci-wait.sh" in dict(zip(kinds, [d for _, d in summary["verifier_failures"]]))
            .get("ci-fail", ""),
            f"got {summary['verifier_failures']!r}",
        )


def test_scan_dir_ignores_non_verifier_noise():
    """Negative cases: a non-CI Bash failure, a passing CI command, and a qa-verifier
    result with no rejection phrasing must NOT enter VERIFIER-FAILURES."""
    with tempfile.TemporaryDirectory() as tdir:
        _write_jsonl(os.path.join(tdir, "s1.jsonl"), [
            _assistant_tool_use([{"type": "tool_use", "name": "Bash", "id": "t1",
                                  "input": {"command": "git status --porcelain"}}]),
            _user_tool_result("t1", "fatal: not a git repository", is_error=True),
            _assistant_tool_use([{"type": "tool_use", "name": "Bash", "id": "t2",
                                  "input": {"command": "python3 scripts/x.py --test"}}]),
            _user_tool_result("t2", "Results: 12/12 passed"),
            _assistant_tool_use([{"type": "tool_use", "name": "Agent", "id": "t3",
                                  "input": {"subagent_type": "qa-verifier",
                                            "prompt": "verify"}}]),
            _user_tool_result("t3", [{"type": "text",
                                      "text": "All acceptance criteria met. Approve."}]),
        ])
        summary = mod.scan_dir(tdir, "fixture")
        check(
            "scan_dir keeps noise out of verifier_failures",
            summary["verifier_failures"] == [],
            f"got {summary['verifier_failures']!r}",
        )


def test_scan_dir_collects_async_qa_reject_from_string_record():
    """Async agent verdicts arrive as plain-string user records (teammate-message /
    task-notification), not tool_results — the spawn's tool_result is launch metadata
    and must NOT be classified; the string record with rejection phrasing must be."""
    with tempfile.TemporaryDirectory() as tdir:
        _write_jsonl(os.path.join(tdir, "s1.jsonl"), [
            _assistant_tool_use([{"type": "tool_use", "name": "Agent", "id": "t1",
                                  "input": {"subagent_type": "qa-verifier",
                                            "prompt": "verify"}}]),
            _user_tool_result("t1", "Async agent launched successfully. agentId: abc"),
            {"type": "user", "timestamp": "2026-01-01T00:00:02.000Z",
             "message": {"content": 'Another Claude session sent a message:\n'
                                    '<teammate-message teammate_id="qa-1" color="blue" '
                                    'summary="QA verify sprint — BLOCKING findings">\n'
                                    'Verdict: BLOCKING — criterion 2 not met\n'
                                    '</teammate-message>'}},
        ])
        summary = mod.scan_dir(tdir, "fixture")
        check(
            "async qa-verifier rejection is mined from the string record",
            summary["verifier_failures"] == [("qa-reject",
                                              "QA verify sprint — BLOCKING findings")],
            f"got {summary['verifier_failures']!r}",
        )


def test_scan_dir_ci_fail_on_passed_false_json_without_is_error():
    """ci-wait.sh reports failure as {"passed": false} at exit 0 — no is_error flag.
    The JSON verdict must still count as ci-fail; a timeout verdict must not."""
    with tempfile.TemporaryDirectory() as tdir:
        _write_jsonl(os.path.join(tdir, "s1.jsonl"), [
            _assistant_tool_use([{"type": "tool_use", "name": "Bash", "id": "t1",
                                  "input": {"command": "bash scripts/ci-wait.sh 42"}}]),
            _user_tool_result("t1", '{"passed": false, "reason": "rework-cap"}'),
            _assistant_tool_use([{"type": "tool_use", "name": "Bash", "id": "t2",
                                  "input": {"command": "bash scripts/ci-wait.sh 43"}}]),
            _user_tool_result("t2", '{"passed": false, "reason": "timeout"}'),
        ])
        summary = mod.scan_dir(tdir, "fixture")
        kinds = [k for k, _ in summary["verifier_failures"]]
        check(
            "passed:false JSON verdict counts as ci-fail; timeout does not",
            kinds == ["ci-fail"],
            f"got {summary['verifier_failures']!r}",
        )


def test_emit_caps_verifier_failures_and_prints_dropped():
    """emit() shows at most VERIFIER_CAP samples and prints the dropped count."""
    import contextlib
    import io
    summary = {"label": "fixture", "sessions": 1, "prompts": [], "skill_sessions": {},
               "agent_sessions": {}, "corrections": [], "agent_corrections": [],
               "frictions": [],
               "verifier_failures": [("ci-fail", f"cmd {i}")
                                     for i in range(mod.VERIFIER_CAP + 3)]}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.emit(summary)
    out = buf.getvalue()
    sample_lines = [line for line in out.splitlines() if line.startswith("  [ci-fail]")]
    check(
        "emit prints VERIFIER-FAILURES header with dropped count",
        "VERIFIER-FAILURES" in out and "[dropped 3]" in out,
        f"got: {out[:400]!r}",
    )
    check(
        "emit caps samples at VERIFIER_CAP",
        len(sample_lines) == mod.VERIFIER_CAP,
        f"got {len(sample_lines)} sample lines",
    )


def test_scan_dir_hook_deny_outranks_pending_ci_kind():
    """A hook-blocked CI command is a denial, not a CI failure — hook-deny wins."""
    with tempfile.TemporaryDirectory() as tdir:
        _write_jsonl(os.path.join(tdir, "s1.jsonl"), [
            _assistant_tool_use([{"type": "tool_use", "name": "Bash", "id": "t1",
                                  "input": {"command": "bash scripts/ci-wait.sh 9"}}]),
            _user_tool_result("t1", "PreToolUse:Bash hook error: blocked", is_error=True),
        ])
        summary = mod.scan_dir(tdir, "fixture")
        kinds = [k for k, _ in summary["verifier_failures"]]
        check(
            "hook-deny outranks the pending ci-fail classification",
            kinds == ["hook-deny"],
            f"got {summary['verifier_failures']!r}",
        )


SUITES = [
    (
        "resolve_project_dir: exact match beats higher-file-count fuzzy match",
        test_resolve_prefers_exact_match_over_higher_file_count_fuzzy_match,
    ),
    (
        "resolve_project_dir: falls back to fuzzy match when exact absent",
        test_resolve_falls_back_to_fuzzy_when_exact_absent,
    ),
    (
        "resolve_project_dir: skips empty exact dir for populated fuzzy sibling",
        test_resolve_skips_empty_exact_dir_in_favor_of_populated_fuzzy_sibling,
    ),
    (
        "resolve_project_dir: empty exact dir is floor over equally-empty fuzzy sibling",
        test_resolve_prefers_empty_exact_dir_over_equally_empty_fuzzy_sibling,
    ),
    (
        "resolve_project_dir: falls back to exact path when nothing matches",
        test_resolve_falls_back_to_exact_path_when_nothing_matches,
    ),
    (
        "find_codex_session_files: matches project cwd, ignores others",
        test_codex_session_meta_cwd_matches_project_and_ignores_others,
    ),
    (
        "find_codex_session_files: excludes archived_sessions",
        test_codex_session_files_exclude_archived_sessions,
    ),
    (
        "_codex_message_text: joins input_text blocks",
        test_codex_message_text_joins_input_text_blocks,
    ),
    (
        "_codex_turn_signal: detects <skill> load marker",
        test_codex_turn_signal_detects_skill_load_marker,
    ),
    (
        "_codex_turn_signal: flags harness-injected noise",
        test_codex_turn_signal_flags_harness_injected_noise,
    ),
    (
        "_codex_turn_signal: passes through ordinary user text",
        test_codex_turn_signal_passes_through_ordinary_user_text,
    ),
    (
        "scan_codex_files: never raises on a malformed line",
        test_scan_codex_files_skips_malformed_lines_without_raising,
    ),
    (
        "scan_dir: collects verifier failures (Signal 8)",
        test_scan_dir_collects_verifier_failures,
    ),
    (
        "scan_dir: keeps non-verifier noise out of VERIFIER-FAILURES",
        test_scan_dir_ignores_non_verifier_noise,
    ),
    (
        "scan_dir: hook-deny outranks pending ci-fail",
        test_scan_dir_hook_deny_outranks_pending_ci_kind,
    ),
    (
        "scan_dir: async qa-reject mined from string record",
        test_scan_dir_collects_async_qa_reject_from_string_record,
    ),
    (
        "scan_dir: passed:false JSON is ci-fail, timeout is not",
        test_scan_dir_ci_fail_on_passed_false_json_without_is_error,
    ),
    (
        "emit: VERIFIER-FAILURES capped with dropped count",
        test_emit_caps_verifier_failures_and_prints_dropped,
    ),
]

if __name__ == "__main__":
    for suite_name, fn in SUITES:
        print(f"\n[{suite_name}]")
        try:
            fn()
        except AttributeError as e:
            print(f"  {FAIL}  AttributeError: {e}  (function not yet implemented)")
            _results.append(False)
        except Exception as e:
            print(f"  {FAIL}  Unexpected: {e}")
            _results.append(False)

    total = len(_results)
    passed = sum(_results)
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)
