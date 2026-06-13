#!/usr/bin/env python3
"""failure-log — PostToolUse(Bash) recorder for genuinely-failed commands.

Appends one JSONL line per non-zero Bash command to the *per-repo* log
`<git-root>/.claude/logs/failed-commands.jsonl`, so each project accumulates its
own record of what went wrong. The harness-curator skill later reads these logs
to propose harness fixes (a recurring failure → a guard/doc/skill).

Noise filter (these non-zero exits are normal control flow, not mistakes):
  - signals / cancel        exit 129,130,137,141,143 (SIGINT/SIGTERM/SIGKILL/SIGPIPE)
  - grep/rg/git-grep         no-match exit 1
  - test/lint/typecheck red  go test, pytest, jest, golangci-lint, mvn/gradle/
                             dotnet test, ... at exit 1 (expected red during TDD;
                             exit 2 = compile/config error is still logged). An
                             install of a test runner (`pip install pytest`) is a
                             real failure, not a red test run.
  - conditionals / diff      test, [, [[, diff, cmp returning 1 (difference found)

Design contract: this runs after EVERY Bash call. It must be fast and must NEVER
raise or block — always exit 0. A logging failure must never disrupt the session.
"""

import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time

LOG_REL = os.path.join(".claude", "logs", "failed-commands.jsonl")
MAX_LINES = 1000          # bound the per-repo log; keep the newest N
CMD_CAP = 600             # truncate stored command
STDERR_CAP = 1000         # truncate stored stderr tail

SIGNAL_CODES = {129, 130, 137, 141, 143}

# leading subshell punctuation to strip before tokenizing
_LEAD_NOISE = re.compile(r"^\s*[\(\{!]*\s*")
# an env-assignment token starts `NAME=` (value, with or without spaces, follows)
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# command classes whose non-zero exit is expected control flow
NOMATCH_TOOLS = {"grep", "egrep", "fgrep", "rg", "ag"}
COND_TOOLS = {"test", "[", "[[", "diff", "cmp"}
# git options that consume the following token as their value
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}

# test/lint/typecheck runners: match anywhere in the command. Boundaries allow a
# leading `/` (./node_modules/.bin/jest) and a trailing `:` (npm run test:unit).
EXPECTED_RED = re.compile(
    r"(?:^|[\s;&|/])(?:"
    r"go\s+test|gotestsum|pytest|py\.test|unittest|"
    r"jest|vitest|mocha|ava|"
    r"golangci-lint|eslint|ruff|flake8|mypy|pyright|tsc|"
    r"cargo\s+test|rspec|phpunit|"
    r"mvn\s+test|gradle\s+test|gradlew\s+test|dotnet\s+test|ctest|"
    r"npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test"
    r")(?:$|[\s;&|:])"
)
# an install/add of a package (incl. a test runner) — its exit 1 is a real failure,
# so it must NOT be swallowed by EXPECTED_RED matching the runner's name as an arg
INSTALLERS = re.compile(
    r"(?:^|[\s;&|])(?:pip|pip3|npm|pnpm|yarn|poetry|cargo|brew|apt|apt-get|uv|pipx|go)"
    r"\s+(?:install|add|get)\b"
)


def tokens(command):
    """Command words, env-assignments and sudo stripped, quotes respected."""
    s = _LEAD_NOISE.sub("", command or "")
    try:
        parts = shlex.split(s)
    except ValueError:
        parts = s.split()
    return [p for p in parts if not _ENV_ASSIGN.match(p) and p != "sudo"]


def first_token(command):
    t = tokens(command)
    return t[0] if t else ""


def git_subcommand(command):
    """The git subcommand (e.g. `grep` in `git -C path grep`), or ''."""
    t = tokens(command)
    if not t or os.path.basename(t[0]) != "git":
        return ""
    i = 1
    while i < len(t):
        tok = t[i]
        if tok in GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok
    return ""


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
    # `git grep` (with any leading git options) exits 1 on no-match, like bare grep
    if return_code == 1 and git_subcommand(command) == "grep":
        return False
    if return_code == 1 and head in COND_TOOLS:
        return False
    # test/lint/typecheck red == expected only at exit 1; exit 2 (compile/config
    # error, bad usage) is a real failure. An install of a runner is also real.
    if return_code == 1 and EXPECTED_RED.search(command) and not INSTALLERS.search(command):
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


def exit_code(tr):
    """Read the exit code across known field spellings."""
    return tr.get("returnCode", tr.get("exitCode", tr.get("exit_code")))


def build_record(data, now_ms):
    ti = data.get("tool_input", {}) or {}
    tr = data.get("tool_response", {}) or {}
    stderr = (tr.get("stderr") or "")[-STDERR_CAP:]
    return {
        "ts": now_ms,
        "exitCode": exit_code(tr),
        "command": (ti.get("command") or "")[:CMD_CAP],
        "cwd": data.get("cwd", ""),
        "stderr": stderr,
        "session": data.get("session_id", ""),
    }


def append_capped(path, line):
    """Append one line, trimming to MAX_LINES, atomically under an exclusive lock.

    Read-modify-write is guarded by flock so parallel agent fan-outs against the
    same repo can't clobber each other's entries. Self-contained: swallows OSError
    (disk full, permissions) so a logging failure never propagates."""
    d = os.path.dirname(path)
    try:
        os.makedirs(d, exist_ok=True)
        # never let captured stderr snippets get committed, whatever the repo ignores
        gi = os.path.join(d, ".gitignore")
        if not os.path.exists(gi):
            with open(gi, "w", encoding="utf-8") as f:
                f.write("*\n")
        with open(path, "a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                lines = f.readlines()
                lines.append(line + "\n")
                if len(lines) > MAX_LINES:
                    lines = lines[-MAX_LINES:]
                f.seek(0)
                f.truncate()
                f.writelines(lines)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    tr = data.get("tool_response", {}) or {}
    code = exit_code(tr)
    ti = data.get("tool_input", {}) or {}
    if not isinstance(code, int) or isinstance(code, bool):
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
    except BaseException:
        pass
    sys.exit(0)
