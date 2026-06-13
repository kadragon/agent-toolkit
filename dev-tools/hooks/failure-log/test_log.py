#!/usr/bin/env python3
"""Tests for failure-log hook. Run: python3 test_log.py"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("log", os.path.join(HERE, "log.py"))
log = importlib.util.module_from_spec(spec)
spec.loader.exec_module(log)

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f" — {name}")
    if not cond:
        fails.append(name)


# --- should_log: skip success / signals / noise ----------------------------
check("success skipped", log.should_log("go build ./...", 0) is False)
check("SIGINT skipped", log.should_log("sleep 100", 130) is False)
check("SIGTERM skipped", log.should_log("server", 143) is False)
check("empty cmd skipped", log.should_log("   ", 1) is False)

check("grep no-match skipped", log.should_log("grep -q foo file.txt", 1) is False)
check("rg no-match skipped", log.should_log("rg pattern src/", 1) is False)
check("piped grep no-match skipped", log.should_log("cat x | grep foo", 1) is False)
check("grep real error logged (code 2)", log.should_log("grep -X bad", 2) is True)

check("test conditional skipped", log.should_log("[ -f missing ]", 1) is False)
check("diff difference skipped", log.should_log("diff a b", 1) is False)

check("git grep no-match skipped", log.should_log("git grep -q foo", 1) is False)
check("git -C grep no-match skipped", log.should_log("git -C /p grep foo", 1) is False)
check("git --no-pager grep skipped", log.should_log("git --no-pager grep foo", 1) is False)
check("git commit failure logged", log.should_log("git commit -m x", 1) is True)
check("SIGPIPE skipped", log.should_log("sort big | head", 141) is False)
check("go test compile err (exit 2) logged", log.should_log("go test ./...", 2) is True)
check("eslint config err (exit 2) logged", log.should_log("eslint .", 2) is True)
check("go test red skipped", log.should_log("go test ./...", 1) is False)
check("npm run test:unit red skipped", log.should_log("npm run test:unit", 1) is False)
check("./gradlew test red skipped", log.should_log("./gradlew test", 1) is False)
check("dotnet test red skipped", log.should_log("dotnet test", 1) is False)
check("local jest red skipped", log.should_log("./node_modules/.bin/jest", 1) is False)
check("pip install pytest failure logged", log.should_log("pip install pytest", 1) is True)
check("npm install jest failure logged", log.should_log("npm install jest", 1) is True)
check("env-with-spaces real fail logged", log.should_log('VAR="a b" gti status', 1) is True)
check("git_subcommand resolves through -C", log.git_subcommand("git -C /p grep x") == "grep")
check("first_token env w/ spaces", log.first_token('VAR="a b" gti') == "gti")
check("pytest red skipped", log.should_log("pytest -q", 1) is False)
check("npm run test red skipped", log.should_log("npm run test", 1) is False)
check("golangci-lint red skipped", log.should_log("golangci-lint run", 1) is False)
check("poetry pytest red skipped", log.should_log("poetry run pytest", 1) is False)

# --- should_log: REAL failures get logged ----------------------------------
check("typo command logged", log.should_log("gti status", 127) is True)
check("build failure logged", log.should_log("go build ./...", 2) is True)
check("missing file logged", log.should_log("cat nope.txt", 1) is True)
check("env-prefixed cmd logged", log.should_log("FOO=1 ./run.sh", 1) is True)
check("sudo cmd logged", log.should_log("sudo systemctl restart x", 1) is True)

# --- first_token ------------------------------------------------------------
check("first_token strips env", log.first_token("A=1 B=2 grep x") == "grep")
check("first_token strips sudo", log.first_token("sudo grep x") == "grep")
check("first_token subshell", log.first_token("( grep x )") == "grep")

# --- build_record -----------------------------------------------------------
rec = log.build_record({
    "tool_input": {"command": "x" * 5000},
    "tool_response": {"returnCode": 2, "stderr": "y" * 5000},
    "cwd": "/repo", "session_id": "s1",
}, 1234)
check("record truncates command", len(rec["command"]) == log.CMD_CAP)
check("record truncates stderr", len(rec["stderr"]) == log.STDERR_CAP)
check("record exitCode", rec["exitCode"] == 2)
check("record ts", rec["ts"] == 1234)
check("exit_code via exitCode key", log.exit_code({"exitCode": 3}) == 3)
check("exit_code via snake_case key", log.exit_code({"exit_code": 4}) == 4)
rec2 = log.build_record({"tool_response": {"exitCode": 5}}, 1)
check("record exitCode fallback", rec2["exitCode"] == 5)

# --- append_capped trims ----------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "sub", "log.jsonl")
    for i in range(log.MAX_LINES + 50):
        log.append_capped(p, json.dumps({"i": i}))
    with open(p) as f:
        lines = f.readlines()
    check("log capped at MAX_LINES", len(lines) == log.MAX_LINES)
    check("log keeps newest", json.loads(lines[-1])["i"] == log.MAX_LINES + 49)

# --- end-to-end: real failure writes to git-root/.claude/logs --------------
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init", "-q", d], check=True)
    payload = {
        "tool_name": "Bash", "cwd": d, "session_id": "s9",
        "tool_input": {"command": "gti status"},
        "tool_response": {"returnCode": 127, "stderr": "command not found: gti"},
    }
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True)
    logged = os.path.join(d, "logs.placeholder")  # noqa: keep var grouping
    target = os.path.join(d, ".claude", "logs", "failed-commands.jsonl")
    check("e2e exit 0", r.returncode == 0)
    check("e2e log written", os.path.exists(target))
    with open(target) as f:
        row = json.loads(f.readline())
    check("e2e command recorded", row["command"] == "gti status")
    check("e2e exitCode recorded", row["exitCode"] == 127)
    gi = os.path.join(d, ".claude", "logs", ".gitignore")
    check("e2e gitignore created", os.path.exists(gi) and open(gi).read().strip() == "*")

# --- end-to-end: noise (go test red) writes nothing ------------------------
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init", "-q", d], check=True)
    payload = {
        "tool_name": "Bash", "cwd": d, "session_id": "s9",
        "tool_input": {"command": "go test ./..."},
        "tool_response": {"returnCode": 1, "stderr": "FAIL"},
    }
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True)
    target = os.path.join(d, ".claude", "logs", "failed-commands.jsonl")
    check("e2e noise not written", not os.path.exists(target))

# --- end-to-end: exitCode-only payload (no returnCode key) -----------------
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init", "-q", d], check=True)
    payload = {
        "tool_name": "Bash", "cwd": d, "session_id": "s",
        "tool_input": {"command": "gti push"},
        "tool_response": {"exitCode": 127, "stderr": "not found"},
    }
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True)
    target = os.path.join(d, ".claude", "logs", "failed-commands.jsonl")
    check("e2e exitCode-only written", os.path.exists(target))
    with open(target) as f:
        row = json.loads(f.readline())
    check("e2e exitCode-only recorded", row["exitCode"] == 127)

# --- end-to-end: non-git cwd falls back to CLAUDE_PROJECT_DIR ---------------
with tempfile.TemporaryDirectory() as nogit, tempfile.TemporaryDirectory() as proj:
    subprocess.run(["git", "init", "-q", proj], check=True)
    payload = {
        "tool_name": "Bash", "cwd": nogit, "session_id": "s",
        "tool_input": {"command": "gti status"},
        "tool_response": {"returnCode": 127, "stderr": "x"},
    }
    env = dict(os.environ, CLAUDE_PROJECT_DIR=proj)
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True, env=env)
    # nogit is itself non-git; git_root(nogit) returns None → fall back to proj
    target = os.path.join(proj, ".claude", "logs", "failed-commands.jsonl")
    check("e2e CLAUDE_PROJECT_DIR fallback", os.path.exists(target))

# --- end-to-end: non-Bash tool ignored -------------------------------------
r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                   input=json.dumps({"tool_name": "Read"}), text=True, capture_output=True)
check("e2e non-Bash exit 0", r.returncode == 0)

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("all passed")
