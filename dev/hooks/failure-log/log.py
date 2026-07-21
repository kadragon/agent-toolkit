#!/usr/bin/env python3
"""failure-log — PostToolUse(Bash) recorder for genuinely-failed commands.

Appends one JSONL line per non-zero Bash command to the *per-repo* log
`<git-root>/.claude/logs/failed-commands.jsonl`, so each project accumulates its
own record of what went wrong. The harness-curate skill later reads these logs
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

import json
import os
import re
import shlex
import subprocess
import sys
import time

_IS_WIN = sys.platform == "win32"
# O_NOFOLLOW: raises ELOOP on Unix if path is a symlink; undefined on Windows (use 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# whole-file lock region for msvcrt.locking (locks from offset 0 past EOF; Windows allows this)
_LOCK_BYTES = 0x7FFFFFFF

try:
    import fcntl as _fcntl
    _LOCK_EX = _fcntl.LOCK_EX  # eager: AttributeError here → next branch below
    _LOCK_UN = _fcntl.LOCK_UN

    def _lock(f):
        _fcntl.flock(f.fileno(), _LOCK_EX)  # type: ignore[attr-defined]

    def _unlock(f):
        _fcntl.flock(f.fileno(), _LOCK_UN)  # type: ignore[attr-defined]

except (ImportError, AttributeError):
    try:
        import msvcrt as _msvcrt

        # Windows mandatory byte-range lock guarding append_capped's read-modify-write.
        # LK_NBLCK (non-blocking): if a concurrent PostToolUse hook holds the region,
        # raise immediately so the outer except drops this one entry rather than stalling
        # ~10s (LK_LOCK retries 10×/1s) — the hook contract is "fast, never block";
        # best-effort logging prefers dropping over stalling. Lock and unlock anchor at
        # offset 0 via os.lseek (raw fd — avoids TextIOWrapper buffer-state exceptions)
        # so the [0, _LOCK_BYTES) region is identical. The unlock seek is load-bearing:
        # writelines advances the position, and LK_UNLCK must release the locked region.
        def _lock(f):  # type: ignore[misc]
            os.lseek(f.fileno(), 0, os.SEEK_SET)
            _msvcrt.locking(f.fileno(), _msvcrt.LK_NBLCK, _LOCK_BYTES)  # type: ignore[attr-defined]

        def _unlock(f):  # type: ignore[misc]
            os.lseek(f.fileno(), 0, os.SEEK_SET)
            _msvcrt.locking(f.fileno(), _msvcrt.LK_UNLCK, _LOCK_BYTES)  # type: ignore[attr-defined]

    except (ImportError, AttributeError):
        # neither fcntl nor msvcrt: locking skipped (safe for serial use)
        def _lock(_f):  # type: ignore[misc]
            pass

        def _unlock(_f):  # type: ignore[misc]
            pass

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
    """Append one line, trimming to MAX_LINES, under an exclusive lock (Unix).

    On Unix: flock guards read-modify-write; O_NOFOLLOW rejects pre-planted symlinks
    (raises ELOOP → OSError, caught silently). On Windows: O_NOFOLLOW is unavailable,
    so both the log and .gitignore opens are guarded by an os.path.islink() pre-check
    (TOCTOU best-effort), and msvcrt.locking provides a non-blocking mandatory
    byte-range lock (locking is skipped only when neither fcntl nor msvcrt is
    importable). Self-contained: swallows OSError/UnicodeDecodeError so a logging
    failure never disrupts the session."""
    d = os.path.dirname(path)
    try:
        os.makedirs(d, exist_ok=True)
        gi = os.path.join(d, ".gitignore")
        try:
            if _O_NOFOLLOW == 0 and os.path.islink(gi):
                raise OSError("symlink at gitignore path")
            gi_fd = os.open(gi, os.O_CREAT | os.O_RDWR | _O_NOFOLLOW, 0o644)
            try:
                gf = os.fdopen(gi_fd, "r+", encoding="utf-8")
            except OSError:
                os.close(gi_fd)
                raise
            with gf:
                content = gf.read()
                if not any(ln.strip() in {"*", "failed-commands.jsonl"}
                           for ln in content.splitlines()):
                    gf.seek(0, 2)
                    prefix = "\n" if content and not content.endswith("\n") else ""
                    gf.write(prefix + "*\n")
        except (OSError, UnicodeDecodeError):
            # gitignore update failed (symlink, perms, or non-UTF-8 content); caught HERE
            # — not at the outer except — so the log write below is still attempted.
            # .gitignore maintenance is best-effort; logging is the primary behavior.
            pass
        if _O_NOFOLLOW == 0 and os.path.islink(path):
            raise OSError("symlink at log path")
        log_fd = os.open(path, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600)
        try:
            f = os.fdopen(log_fd, "r+", encoding="utf-8")
        except OSError:
            os.close(log_fd)
            raise
        with f:
            _lock(f)
            try:
                f.seek(0)
                lines = f.readlines()
                lines.append(line + "\n")
                if len(lines) > MAX_LINES:
                    lines = lines[-MAX_LINES:]
                f.seek(0)
                f.truncate()
                f.writelines(lines)
                f.flush()  # push buffered writes to the OS before releasing the lock,
                           # so a parallel reader cannot grab the lock and see stale data
            finally:
                _unlock(f)
    except (OSError, UnicodeDecodeError):
        # OSError: any FS failure (symlink/ELOOP, perms, msvcrt lock contention).
        # UnicodeDecodeError: a non-UTF-8 *log* file read (ValueError subclass, not an
        # OSError); the .gitignore decode case is handled at the inner except so it does
        # not abort the log write. Swallow both so a logging failure never disrupts the
        # session.
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


def _test():
    import tempfile
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL") + f" — {name}")
        if not cond:
            fails.append(name)

    # symlink planted at log path → append_capped must skip silently, target untouched
    # O_NOFOLLOW not available on Windows; symlink guard is Unix-only by design
    if _IS_WIN:
        print("SKIP — symlink protection test (O_NOFOLLOW unavailable on Windows)")
    else:
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "target.txt")
            with open(target, "w") as fh:
                fh.write("original\n")
            link = os.path.join(td, "link.jsonl")
            os.symlink(target, link)
            append_capped(link, '{"test":1}')
            with open(target) as fh:
                content = fh.read()
            check("symlink write skipped — target unmodified", content == "original\n")
            check("symlink still a symlink", os.path.islink(link))

    # .gitignore without trailing newline → write must start a new line, not corrupt last pattern
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "test.jsonl")
        gi_path = os.path.join(td, ".gitignore")
        with open(gi_path, "w", encoding="utf-8") as gh:
            gh.write("keep")  # no trailing newline
        append_capped(log_path, '{"test":1}')
        with open(gi_path, encoding="utf-8") as gh:
            gi_content = gh.read()
        check(".gitignore line boundary preserved", gi_content == "keep\n*\n")

    # invalid-UTF-8 .gitignore → append must not raise AND must still record the log entry
    # (.gitignore maintenance is best-effort; a corrupt one must not drop the log write)
    with tempfile.TemporaryDirectory() as td:
        log_p = os.path.join(td, "test.jsonl")
        gi_path = os.path.join(td, ".gitignore")
        with open(gi_path, "wb") as gh:
            gh.write(b"\xff\xfe not valid utf-8\n")
        raised = False
        try:
            append_capped(log_p, '{"test":1}')
        except UnicodeDecodeError:
            raised = True
        check("invalid-utf8 .gitignore does not raise", not raised)
        wrote = os.path.exists(log_p) and \
            '{"test":1}' in open(log_p, encoding="utf-8").read()
        check("log entry written despite undecodable .gitignore", wrote)

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        try:
            main()
        except BaseException:
            pass
        sys.exit(0)
