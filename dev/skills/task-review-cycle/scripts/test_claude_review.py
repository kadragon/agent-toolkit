#!/usr/bin/env python3
"""Regression tests for claude-review.sh's prompt assembly and output contract.

This script is the Claude review slot for every runtime, called in the foreground under a Bash
timeout. It replaced an in-process Agent spawn that had no timeout of its own, so a hung inner
run — or one whose completion notification was lost (upstream claude-code #49150, #58637,
#68117) — stalled the review cycle with no bound.

The case that earns this file is the Sprint Contract argument. The prompt is built in an
UNQUOTED heredoc, which expands `$` and backticks; a contract legitimately carries both (a
lint/test command, a shell snippet inside an acceptance criterion), so appending it there would
execute the contract's `$(...)` in this shell. The contract must be concatenated by parameter
expansion instead. `case_contract_is_not_executed` is the red-capable proof of that: move the
append back inside the heredoc and it fails.

`case_script_parses` guards a second trap found the same way. The prompt used to be read as
`PROMPT=$(cat <<EOF ...)`, and inside a command substitution bash 3.2 scans the heredoc body for
quotes instead of taking it literally — the apostrophes in it (run's, branch's) opened a quote
that swallowed the rest of the file, so the script exited 127 running its own comments as
commands. That was already true before this slot became the primary review path; it never showed
because bash 5 on the CI runner parses it correctly. The body is now read with `read -r -d ''`.

Also covered: the contract section is absent when no contract is passed, effort reaches the
prompt, a clean array passes through, an array wrapped in prose is recovered, unparseable output
becomes the `code_review_slot` sentinel rather than a silent `[]`, and a missing `claude` CLI
exits non-zero.

The `claude` CLI is stubbed on PATH by a POSIX shebang script, so these cases are skipped on
Windows; CI runs them on ubuntu.

Run: python3 dev/skills/task-review-cycle/scripts/test_claude_review.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "claude-review.sh"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []

STUB = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["CLAUDE_STUB_CAPTURE"], "w") as fh:
    fh.write(sys.argv[-1])
if os.environ.get("CLAUDE_STUB_ARGV"):
    with open(os.environ["CLAUDE_STUB_ARGV"], "w") as fh:
        fh.write(json.dumps(sys.argv[1:]))
sys.stdout.write(os.environ.get("CLAUDE_STUB_STDOUT", ""))
sys.exit(int(os.environ.get("CLAUDE_STUB_EXIT", "0")))
"""


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def envelope(result_text):
    """The `--output-format json` wrapper the script reads `.result` out of."""
    return json.dumps({"result": result_text})


def run(tmp, args, stdout="", exit_code=0, with_cli=True, progress_log=None):
    """Run claude-review.sh with a stubbed `claude`. Returns (completed_process, prompt_seen).

    The argv the stub saw is left in tmp/argv.json. `progress_log` sets REVIEW_PROGRESS_LOG.
    """
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    capture = tmp / "prompt.txt"
    capture.unlink(missing_ok=True)

    if with_cli:
        stub = bin_dir / "claude"
        stub.write_text(STUB)
        stub.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CLAUDE_STUB_CAPTURE": str(capture),
        "CLAUDE_STUB_STDOUT": stdout,
        "CLAUDE_STUB_EXIT": str(exit_code),
        "CLAUDE_STUB_ARGV": str(tmp / "argv.json"),
    }
    env.pop("REVIEW_PROGRESS_LOG", None)
    if progress_log is not None:
        env["REVIEW_PROGRESS_LOG"] = str(progress_log)
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=tmp,
        env=env,
        timeout=60,
    )
    prompt = capture.read_text() if capture.exists() else ""
    return proc, prompt


CONTRACT = """**Tag:** [FIX]
**Acceptance criteria:**
- [ ] `pytest -q` exits 0
**Lint/test command:** make test"""


def case_script_parses(_tmp):
    """The contract append sits after a heredoc whose body contains backticks.

    bash 3.2 mis-tracks quoting from there on, so an apostrophe or a backtick in the appended
    block rejects the WHOLE file — on macOS only, while bash 5 on the CI runner stays green.
    This case caught exactly that during development; on a bash 5 runner it degrades to a plain
    syntax check, which is still worth having.
    """
    print("\ncase: the script parses (bash 3.2 quoting-state trap)")
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    check("bash -n exits 0", proc.returncode == 0, proc.stderr)


def case_no_contract_omits_grading(tmp):
    print("\ncase: two args -> no contract section in the prompt")
    _, prompt = run(tmp, ["main", ""], stdout=envelope("[]"))
    check("prompt was captured", bool(prompt))
    check("no Sprint Contract heading", "Sprint Contract:" not in prompt)
    check('no contract source rule', '"source":"contract"' not in prompt)


def case_contract_reaches_prompt(tmp):
    print("\ncase: third arg -> contract graded, verbatim, read-only")
    _, prompt = run(tmp, ["main", "", CONTRACT], stdout=envelope("[]"))
    check("contract text appears verbatim", CONTRACT in prompt, prompt[-400:])
    check('contract findings tagged', '"source":"contract"' in prompt)
    check("P0 severity stated", "severity P0" in prompt)
    # The prompt is hard-wrapped, so match against a whitespace-collapsed copy.
    flat = " ".join(prompt.split())
    check(
        "lint/test command explicitly not run here",
        "Do NOT run the lint/test command named in the contract" in flat,
        prompt[-400:],
    )
    check("read-only reason given", "this session is read-only" in flat, prompt[-400:])
    # A read-only reviewer can never gather evidence for "pytest exits 0". Grading its absence as
    # P0 would make every contract with an execution-based criterion unmergeable, since Step 4
    # refuses to merge on an open contract finding.
    check(
        "execution-based criteria are graded against supplied evidence",
        "Lint/test evidence" in flat,
        prompt[-500:],
    )
    check(
        "absence of a run is never itself a finding",
        "Never report a criterion as unmet merely because this session could not run it" in flat,
        prompt[-500:],
    )


def case_contract_is_not_executed(tmp):
    """The heredoc is unquoted; a contract must never be interpolated into it."""
    print("\ncase: contract containing $(...) and backticks is inert")
    marker_a = tmp / "pwned-dollar"
    marker_b = tmp / "pwned-backtick"
    hostile = (
        "**Lint/test command:** $(touch " + str(marker_a) + ")\n"
        "- [ ] backtick form `touch " + str(marker_b) + "` stays literal\n"
        "- [ ] a bare $VAR and $HOME survive unexpanded"
    )
    _, prompt = run(tmp, ["main", "", hostile], stdout=envelope("[]"))
    check("$(...) did not execute", not marker_a.exists())
    check("backticks did not execute", not marker_b.exists())
    check("$(...) reached the prompt literally", "$(touch " + str(marker_a) + ")" in prompt)
    check("backtick text reached the prompt literally", "`touch " + str(marker_b) + "`" in prompt)
    check("$HOME was not expanded", "$HOME" in prompt)


def case_blocking_scope_and_failure_field(tmp):
    """Opus 5.5 review guidance: list only merge-blocking problems, each with how it fails.

    consolidation-guide.md keys off both: P2/P3 never gate a merge, and a code-review finding
    with an empty failure field is folded into the low-confidence note.
    """
    print("\ncase: prompt scopes to merge-blocking findings and requires a failure field")
    _, prompt = run(tmp, ["main", ""], stdout=envelope("[]"))
    flat = " ".join(prompt.split())
    check("scoped to merge-blocking problems", "only problems you would block the merge for" in flat, prompt[:800])
    check("schema severity is P0/P1 only", '"severity":"P0"|"P1",' in flat and '"P2"' not in flat and "P3" not in flat, prompt[:800])
    check("schema carries a failure field", '"failure":"' in flat, prompt[:800])
    check("failure is defined as a concrete demonstration", "how to show it fails" in flat, prompt[:800])
    # Blocking-only and the passthrough rule must agree, or the headless run gets two opposite orders.
    check("passthrough never drops a blocking finding", "never re-rank, re-judge, merge, summarize or drop a blocking finding" in flat, prompt[:1600])


def case_effort_reaches_prompt(tmp):
    print("\ncase: effort arg lands in the skill args, not the skill name")
    _, prompt = run(tmp, ["main", "high"], stdout=envelope("[]"))
    check('effort passed as args', 'with args "high"' in prompt, prompt[:400])
    check("skill name unchanged", 'Skill "code-review"' in prompt)


def case_array_passthrough(tmp):
    print("\ncase: a clean array is emitted as-is")
    findings = '[{"file":"a.py","line":1,"severity":"P2","confidence":80,' \
               '"problem":"x","fix":"y","source":"code-review"}]'
    proc, _ = run(tmp, ["main", ""], stdout=envelope(findings))
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("stdout is the array", json.loads(proc.stdout) == json.loads(findings), proc.stdout)


def case_empty_array_passthrough(tmp):
    print("\ncase: [] survives as a real 'reviewed, found nothing'")
    proc, _ = run(tmp, ["main", ""], stdout=envelope("[]"))
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("stdout is []", json.loads(proc.stdout) == [], proc.stdout)


def case_prose_wrapped_array_recovered(tmp):
    print("\ncase: an array wrapped in prose is recovered")
    wrapped = 'Here is what I found:\n[{"file":"a.py","line":2,"severity":"P1",' \
              '"confidence":90,"problem":"p","fix":"f","source":"code-review"}]\nDone.'
    proc, _ = run(tmp, ["main", ""], stdout=envelope(wrapped))
    check("exit 0", proc.returncode == 0, proc.stderr)
    parsed = json.loads(proc.stdout)
    check("array recovered", isinstance(parsed, list) and parsed[0]["file"] == "a.py", proc.stdout)


def case_unparseable_emits_sentinel(tmp):
    print("\ncase: unparseable output becomes the sentinel, never a silent []")
    proc, _ = run(tmp, ["main", ""], stdout=envelope("I could not read the diff."))
    parsed = json.loads(proc.stdout)
    check(
        "sentinel on stdout",
        parsed.get("code_review_slot") == "inner-run-unavailable",
        proc.stdout,
    )
    check("not an empty array", parsed != [], proc.stdout)


def case_missing_cli_exits_nonzero(tmp):
    print("\ncase: no claude CLI -> non-zero, so the caller records a skipped slot")
    # PATH holds bash and jq but no `claude` — emptying it entirely would fail to
    # find the interpreter instead, which is a different error than the one under test.
    bin_dir = tmp / "nocladebin"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("bash", "jq"):
        found = shutil.which(tool)
        link = bin_dir / tool
        if found and not link.exists():
            link.symlink_to(found)
    proc = subprocess.run(
        [str(bin_dir / "bash"), str(SCRIPT), "main", ""],
        capture_output=True,
        text=True,
        cwd=tmp,
        env={**os.environ, "PATH": str(bin_dir)},
        timeout=60,
    )
    check("non-zero exit", proc.returncode != 0)
    check("names the missing CLI", "claude CLI not found" in proc.stderr, proc.stderr)


def case_cli_failure_propagates(tmp):
    print("\ncase: a non-zero claude run propagates instead of emitting findings")
    proc, _ = run(tmp, ["main", ""], stdout="boom", exit_code=3)
    check("exit code propagates", proc.returncode == 3, str(proc.returncode))
    check("nothing on stdout", proc.stdout.strip() == "", proc.stdout)


def stream(*events, tail=""):
    """A `--output-format stream-json` transcript: one JSON event per line."""
    return "".join(json.dumps(e) + "\n" for e in events) + tail


def assistant(*content):
    return {"type": "assistant", "message": {"content": list(content)}}


def stream_result(text):
    return {"type": "result", "subtype": "success", "is_error": False, "result": text}


def argv_seen(tmp):
    return json.loads((tmp / "argv.json").read_text())


def case_no_log_keeps_json_path(tmp):
    """Without a pane there is no progress log, and the run must be byte-for-byte the old one."""
    print("\ncase: REVIEW_PROGRESS_LOG unset -> unchanged --output-format json run")
    proc, _ = run(tmp, ["main", ""], stdout=envelope("[]"))
    argv = argv_seen(tmp)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("json output format", argv[argv.index("--output-format") + 1] == "json", str(argv[:6]))
    check("no --verbose", "--verbose" not in argv, str(argv[:6]))
    check("read-only plan mode kept", argv[argv.index("--permission-mode") + 1] == "plan", str(argv[:6]))


def case_stream_writes_progress_and_parses_result(tmp):
    print("\ncase: REVIEW_PROGRESS_LOG set -> stream-json, progress lines, result parsed")
    log = tmp / "progress.log"
    log.unlink(missing_ok=True)
    findings = '[{"file":"a.py","line":3,"severity":"P1","confidence":90,' \
               '"problem":"p","failure":"f","fix":"x","source":"code-review"}]'
    out = stream(
        {"type": "system", "subtype": "init"},
        assistant({"type": "tool_use", "name": "Bash", "input": {"command": "git diff main...HEAD --name-only"}}),
        assistant({"type": "text", "text": "Reading the changed script\nnow"}),
        stream_result(findings),
    )
    proc, _ = run(tmp, ["main", ""], stdout=out, progress_log=log)
    argv = argv_seen(tmp)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("stream-json output format", argv[argv.index("--output-format") + 1] == "stream-json", str(argv[:7]))
    check("--verbose passed (stream-json requires it)", "--verbose" in argv, str(argv[:7]))
    check("read-only plan mode kept", argv[argv.index("--permission-mode") + 1] == "plan", str(argv[:7]))
    try:
        parsed = json.loads(proc.stdout)
    except ValueError:
        parsed = None
    check("stdout is the result array", parsed == json.loads(findings), proc.stdout)
    text = log.read_text() if log.exists() else ""
    check("tool call logged", "Bash" in text and "git diff main...HEAD --name-only" in text, text)
    check("assistant text logged on one line", "Reading the changed script now" in text, text)
    check("raw JSON events stay out of the log", '"type"' not in text, text)


def case_stream_without_result_is_sentinel(tmp):
    """An intermediate `[]` must never be recovered as a clean review."""
    print("\ncase: stream with no result event -> sentinel, never []")
    log = tmp / "progress.log"
    out = stream(
        assistant({"type": "text", "text": "[]"}),
        assistant({"type": "tool_use", "name": "Read", "input": {"file_path": "/x/[].py"}}),
    )
    proc, _ = run(tmp, ["main", ""], stdout=out, progress_log=log)
    try:
        parsed = json.loads(proc.stdout)
    except ValueError:
        parsed = None
    check("exit 0", proc.returncode == 0, proc.stderr)
    check(
        "sentinel on stdout",
        isinstance(parsed, dict) and parsed.get("code_review_slot") == "inner-run-unavailable",
        proc.stdout,
    )


def case_stream_error_result_is_sentinel(tmp):
    """A result event without .result must not fall back to bracket recovery on the envelope."""
    print("\ncase: error result event (no .result) -> sentinel, never a recovered []")
    log = tmp / "progress.log"
    out = stream({"type": "result", "subtype": "error_during_execution", "is_error": True,
                  "permission_denials": []})
    proc, _ = run(tmp, ["main", ""], stdout=out, progress_log=log)
    try:
        parsed = json.loads(proc.stdout)
    except ValueError:
        parsed = None
    check(
        "sentinel on stdout",
        isinstance(parsed, dict) and parsed.get("code_review_slot") == "inner-run-unavailable",
        proc.stdout,
    )


def case_stream_logs_subagents_and_findings(tmp):
    """The pane is a results board: subagent lifecycle while running, every finding at the end."""
    print("\ncase: subagent start/finish and each finding land in the log")
    log = tmp / "progress.log"
    log.unlink(missing_ok=True)
    findings = [
        {"file": "a.sh", "line": 7, "severity": "P0", "confidence": 90, "problem": "unquoted var",
         "failure": "a path with a space breaks", "fix": "quote", "source": "code-review"},
        {"file": "b.md", "line": 2, "severity": "P0", "confidence": 100, "problem": "criterion 3 unmet",
         "failure": "", "fix": "add test", "source": "contract"},
    ]
    out = stream(
        {"type": "system", "subtype": "task_started", "description": "/code-review", "task_type": "local_agent"},
        {"type": "system", "subtype": "task_notification", "status": "completed", "summary": "/code-review"},
        stream_result(json.dumps(findings)),
    )
    proc, _ = run(tmp, ["main", ""], stdout=out, progress_log=log)
    text = log.read_text() if log.exists() else ""
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("stdout unchanged (the array)", json.loads(proc.stdout) == findings, proc.stdout)
    check("subagent start logged", "/code-review" in text and "started" in text, text)
    check("subagent finish logged", "completed" in text, text)
    check("finding count stated", "2 finding" in text, text)
    check("first finding: severity, location, problem", "P0" in text and "a.sh:7" in text and "unquoted var" in text, text)
    check("first finding: how it fails", "a path with a space breaks" in text, text)
    check("contract finding marked", "b.md:2" in text and "contract" in text, text)


def case_stream_logs_empty_and_sentinel(tmp):
    print("\ncase: [] and the sentinel are both stated in the log, never left silent")
    log = tmp / "progress.log"
    log.unlink(missing_ok=True)
    run(tmp, ["main", ""], stdout=stream(stream_result("[]")), progress_log=log)
    text = log.read_text() if log.exists() else ""
    check("empty review stated", "no blocking findings" in text, text)
    log.unlink(missing_ok=True)
    run(tmp, ["main", ""], stdout=stream(stream_result("I could not read the diff.")), progress_log=log)
    text = log.read_text() if log.exists() else ""
    check("unparseable result stated", "no parseable findings" in text, text)


def case_stream_unwritable_log_still_reviews(tmp):
    print("\ncase: an unwritable progress log never fails the review")
    log = tmp / "missing-dir" / "progress.log"
    out = stream(assistant({"type": "text", "text": "hi"}), stream_result("[]"))
    proc, _ = run(tmp, ["main", ""], stdout=out, progress_log=log)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("stdout is []", proc.stdout.strip() == "[]", proc.stdout)


def case_stream_truncated_last_line(tmp):
    print("\ncase: a truncated trailing event does not hide the result")
    log = tmp / "progress.log"
    out = stream(stream_result("[]"), tail='{"type":"assistant","mess')
    proc, _ = run(tmp, ["main", ""], stdout=out, progress_log=log)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("stdout is []", proc.stdout.strip() == "[]", proc.stdout)


def case_stream_cli_failure_propagates(tmp):
    print("\ncase: stream path -> a non-zero claude run propagates, even after a result")
    log = tmp / "progress.log"
    proc, _ = run(tmp, ["main", ""], stdout=stream(stream_result("[]")), exit_code=4, progress_log=log)
    check("exit code propagates", proc.returncode == 4, str(proc.returncode))
    check("nothing on stdout", proc.stdout.strip() == "", proc.stdout)


def main():
    if os.name == "nt":
        print("POSIX-only (the claude stub uses a shebang) — skipped on Windows")
        return 0
    if not shutil.which("jq"):
        print("jq is required for these tests", file=sys.stderr)
        return 1
    if not SCRIPT.exists():
        print(f"missing script under test: {SCRIPT}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for case in (
            case_script_parses,
            case_no_contract_omits_grading,
            case_contract_reaches_prompt,
            case_contract_is_not_executed,
            case_effort_reaches_prompt,
            case_blocking_scope_and_failure_field,
            case_array_passthrough,
            case_empty_array_passthrough,
            case_prose_wrapped_array_recovered,
            case_unparseable_emits_sentinel,
            case_missing_cli_exits_nonzero,
            case_cli_failure_propagates,
            case_no_log_keeps_json_path,
            case_stream_writes_progress_and_parses_result,
            case_stream_without_result_is_sentinel,
            case_stream_error_result_is_sentinel,
            case_stream_logs_subagents_and_findings,
            case_stream_logs_empty_and_sentinel,
            case_stream_unwritable_log_still_reviews,
            case_stream_truncated_last_line,
            case_stream_cli_failure_propagates,
        ):
            case(tmp)
    failed = _results.count(False)
    print(f"\n{len(_results) - failed}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
