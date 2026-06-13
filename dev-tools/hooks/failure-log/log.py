#!/usr/bin/env python3
"""failure-log — PostToolUse(Bash) recorder for genuinely-failed commands.

Appends one JSONL line per non-zero Bash command to the *per-repo* log
`<git-root>/.claude/logs/failed-commands.jsonl`, so each project accumulates its
own record of what went wrong. The harness-curator skill later reads these logs
to propose harness fixes (a recurring failure → a guard/doc/skill).

Noise filter (these non-zero exits are normal control flow, not mistakes):
  - signals / cancel        exit 129,130,137,143  (SIGINT/SIGTERM/SIGKILL, Ctrl-C)
  - grep/rg "no match"       grep|egrep|fgrep|rg|ag with exit 1
  - test/lint/typecheck red  go test, pytest, jest, golangci-lint, eslint, ruff,
                             mypy, tsc, pyright, cargo test, vitest, ... (expected
                             red during TDD / iteration — not a command mistake)
  - conditionals / diff      test, [, [[, diff, cmp returning 1 (difference found)

Design contract: this runs after EVERY Bash call. It must be fast and must NEVER
raise or block — always exit 0. A logging failure must never disrupt the session.
"""

import json
import os
import re
import subprocess
import sys
import time

LOG_REL = os.path.join(".claude", "logs", "failed-commands.jsonl")
MAX_LINES = 1000          # bound the per-repo log; keep the newest N
CMD_CAP = 600             # truncate stored command
STDERR_CAP = 1000         # truncate stored stderr tail

SIGNAL_CODES = {129, 130, 137, 141, 143}

# first "real" token of a command after stripping env-assignments / sudo / leading
# subshell punctuation — used for command-class noise rules
_LEAD_NOISE = re.compile(r"^\s*[\(\{!]*\s*")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")

# command classes whose non-zero exit is expected control flow
NOMATCH_TOOLS = {"grep", "egrep", "fgrep", "rg", "ag"}
COND_TOOLS = {"test", "[", "[[", "diff", "cmp"}
# test/lint/typecheck runners: match anywhere in the command (they are often
# invoked as `npm run test`, `poetry run pytest`, `go test ./...`)
EXPECTED_RED = re.compile(
    r"(?:^|[\s;&|])(?:"
    r"go\s+test|gotestsum|pytest|py\.test|unittest|"
    r"jest|vitest|mocha|ava|"
    r"golangci-lint|eslint|ruff|flake8|mypy|pyright|tsc|"
    r"cargo\s+test|rspec|phpunit|"
    r"npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test"
    r")(?:$|[\s;&|])"
)


def first_token(command):
    """Leading command word after stripping env-assignments / sudo / punctuation."""
    s = _LEAD_NOISE.sub("", command)
    for part in s.split():
        if _ENV_ASSIGN.match(part):
            continue
        if part == "sudo":
            continue
        return part
    return ""


def second_token(command):
    """Second command word after the same env/sudo/punctuation stripping."""
    s = _LEAD_NOISE.sub("", command)
    real = [p for p in s.split() if not _ENV_ASSIGN.match(p) and p != "sudo"]
    return real[1] if len(real) > 1 else ""


def should_log(command, return_code):
    """True only for failures worth recording (mistakes, not normal control flow)."""
    if return_code == 0:
        return False
    if return_code in SIGNAL_CODES:
        return False
    if not command or not command.strip():
        return False
    head = os.path.basename(first_token(command))
    # a pipeline's exit code is its last stage (no pipefail), so `cat x | grep y`
    # exiting 1 is grep's no-match — judge the no-match rule on the tail too
    tail = os.path.basename(first_token(command.rsplit("|", 1)[-1]))
    if return_code == 1 and (head in NOMATCH_TOOLS or tail in NOMATCH_TOOLS):
        return False
    # `git grep` exits 1 on no-match, just like bare grep
    if return_code == 1 and (head == "git" and second_token(command) == "grep"):
        return False
    if return_code == 1 and head in COND_TOOLS:
        return False
    # test/lint/typecheck red == expected only at exit 1; exit 2 (compile/config
    # error, bad usage) is a real failure worth logging
    if return_code == 1 and EXPECTED_RED.search(command):
        return False
    return True


def git_root(cwd):
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            root = out.stdout.strip()
            if root:
                return root
    except Exception:
        pass
    return None


def log_path(cwd):
    """Per-repo log path; fall back to CLAUDE_PROJECT_DIR; else None (skip)."""
    root = git_root(cwd) or os.environ.get("CLAUDE_PROJECT_DIR")
    if not root or not os.path.isdir(root):
        return None
    return os.path.join(root, LOG_REL)


def build_record(data, now_ms):
    ti = data.get("tool_input", {}) or {}
    tr = data.get("tool_response", {}) or {}
    code = tr.get("returnCode", tr.get("exitCode"))
    stderr = (tr.get("stderr") or "")[-STDERR_CAP:]
    return {
        "ts": now_ms,
        "exitCode": code,
        "command": (ti.get("command") or "")[:CMD_CAP],
        "cwd": data.get("cwd", ""),
        "stderr": stderr,
        "session": data.get("session_id", ""),
    }


def append_capped(path, line):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    # never let captured stderr snippets get committed, whatever the repo ignores
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        try:
            with open(gi, "w", encoding="utf-8") as f:
                f.write("*\n")
        except Exception:
            pass
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []
    lines.append(line + "\n")
    if len(lines) > MAX_LINES:
        lines = lines[-MAX_LINES:]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    tr = data.get("tool_response", {}) or {}
    code = tr.get("returnCode", tr.get("exitCode"))
    ti = data.get("tool_input", {}) or {}
    if not isinstance(code, int):
        return
    if not should_log(ti.get("command", ""), code):
        return
    path = log_path(data.get("cwd", os.getcwd()))
    if not path:
        return
    rec = build_record(data, int(time.time() * 1000))
    append_capped(path, json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
