#!/usr/bin/env python3
"""commit-guard — PreToolUse(Bash) gate for `git commit` invocations.

Intercepts git commit commands before execution and applies two guards:
  1. Branch guard: blocks commits to main/master unless the repo's AGENTS.md
     or CLAUDE.md contains the literal marker <!-- commit-guard: allow-main -->.
  2. Type guard: commit message must match ^\\[(TYPE)\\] (with trailing space).
     Skipped for editor-mode commits (no -m/-F), --amend, and --squash flags.

Design contract: never-raise, always exit 0 (allow) unless a guard fires (exit 2).
A guard failure prints the reason to stderr and exits 2. All other exits are 0
(fail-open: parse errors, missing git, non-commit commands all pass through).
"""

import json
import os
import re
import shlex
import subprocess
import sys

ALLOW_MAIN_MARKER = "<!-- commit-guard: allow-main -->"
TYPE_PATTERN = re.compile(r"^\[(FEAT|REFACTOR|FIX|TEST|CONSTRAINT|DOCS|HARNESS|PLAN)\] ")

# git options that consume the following token as their value (git-level, before subcommand)
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}

# strip leading subshell punctuation; env-assign detector
_LEAD_NOISE = re.compile(r"^\s*[\(\{!]*\s*")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _tokens(s):
    """Tokenize a shell fragment, stripping env-assigns. ValueError → split()."""
    s = _LEAD_NOISE.sub("", s or "")
    try:
        parts = shlex.split(s)
    except ValueError:
        parts = s.split()
    return [p for p in parts if not _ENV_ASSIGN.match(p)]


def _is_git_commit(segment):
    """True if this shell segment is a git commit invocation."""
    toks = _tokens(segment)
    if not toks:
        return False
    if os.path.basename(toks[0]) != "git":
        return False
    # walk past git-level flags (e.g. -C path, -c key=val, --no-pager)
    i = 1
    while i < len(toks):
        tok = toks[i]
        if tok in GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok == "commit"
    return False


def _split_segments(command):
    """Naïve split on ;  &&  ||  |  to get independent shell segments."""
    return re.split(r"&&|\|\||[;|]", command)


def _find_commit_segment(command):
    """Return the first segment that is a git commit invocation, or None."""
    for seg in _split_segments(command):
        if _is_git_commit(seg.strip()):
            return seg.strip()
    return None


def _git_cwd(segment, env_cwd):
    """Effective cwd for the git call: env_cwd unless overridden by -C flag."""
    toks = _tokens(segment)
    i = 1  # skip 'git'
    while i < len(toks):
        tok = toks[i]
        if tok == "-C" and i + 1 < len(toks):
            return toks[i + 1]
        if tok in GIT_VALUE_OPTS - {"-C"}:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    return env_cwd


def _current_branch(cwd, _override=None):
    """Return current branch name, or '' on failure. _override injects for tests."""
    if _override is not None:
        return _override
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _marker_present(git_cwd, _override=None):
    """True if AGENTS.md or CLAUDE.md at git root contains the allow-main marker.
    _override injects True/False for tests (bypasses subprocess + filesystem)."""
    if _override is not None:
        return _override
    try:
        root_out = subprocess.run(
            ["git", "-C", git_cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if root_out.returncode != 0:
            return False
        root = root_out.stdout.strip()
        for fname in ("AGENTS.md", "CLAUDE.md"):
            fp = os.path.join(root, fname)
            try:
                with open(fp, encoding="utf-8") as fh:
                    if ALLOW_MAIN_MARKER in fh.read():
                        return True
            except (OSError, UnicodeDecodeError):
                pass
    except Exception:
        pass
    return False


def _parse_commit_args(segment):
    """Parse git commit flags. Returns dict with keys:
      message: str | None    (extracted message text, or None if not determinable)
      has_amend: bool
      has_merge_squash: bool (--squash flag present)
      editor_mode: bool      (no -m and no -F: message comes from editor)
    Fail-open: -F read error sets message=None (treated as editor_mode by caller).
    """
    toks = _tokens(segment)
    # skip to 'git'
    i = 0
    while i < len(toks) and os.path.basename(toks[i]) != "git":
        i += 1
    i += 1  # skip 'git' itself
    # skip git-level options
    while i < len(toks):
        tok = toks[i]
        if tok in GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    i += 1  # skip 'commit'

    message = None
    has_amend = False
    has_merge_squash = False
    msg_file = None

    while i < len(toks):
        tok = toks[i]
        if tok in ("-m", "--message") and i + 1 < len(toks):
            message = toks[i + 1]
            i += 2
            continue
        if tok.startswith("--message="):
            message = tok[len("--message="):]
            i += 1
            continue
        if tok.startswith("-m") and len(tok) > 2:
            message = tok[2:]
            i += 1
            continue
        if tok in ("-F", "--file") and i + 1 < len(toks):
            msg_file = toks[i + 1]
            i += 2
            continue
        if tok.startswith("--file="):
            msg_file = tok[len("--file="):]
            i += 1
            continue
        if tok == "--amend":
            has_amend = True
        if tok == "--squash":
            has_merge_squash = True
        i += 1

    # -F: read first line of the file (fail-open on error)
    if msg_file is not None and message is None:
        try:
            with open(msg_file, encoding="utf-8") as fh:
                message = fh.readline().rstrip("\n")
        except (OSError, UnicodeDecodeError):
            message = None  # unreadable → fail-open (caller sees message=None, msg_file set)

    # editor_mode: no explicit message AND no -F flag
    editor_mode = (message is None and msg_file is None)
    return {
        "message": message,
        "has_amend": has_amend,
        "has_merge_squash": has_merge_squash,
        "editor_mode": editor_mode,
    }


def _block(reason):
    """Print reason to stderr and raise SystemExit(2) to signal a block."""
    print(reason, file=sys.stderr)
    raise SystemExit(2)


def main(branch_override=None, marker_override=None):
    """Main hook logic. branch_override / marker_override for test injection."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    ti = data.get("tool_input", {}) or {}
    command = ti.get("command") or ""
    if not command.strip():
        return

    seg = _find_commit_segment(command)
    if seg is None:
        return  # not a git commit invocation → pass through

    env_cwd = data.get("cwd") or os.getcwd()
    effective_cwd = _git_cwd(seg, env_cwd)

    # --- Branch guard ---------------------------------------------------------
    branch = _current_branch(effective_cwd, _override=branch_override)
    if branch in ("main", "master"):
        if not _marker_present(effective_cwd, _override=marker_override):
            _block(
                f"commit-guard: blocked — branch '{branch}' is protected. "
                "Add <!-- commit-guard: allow-main --> to AGENTS.md or CLAUDE.md to opt in."
            )

    # --- Type guard -----------------------------------------------------------
    args = _parse_commit_args(seg)
    # skip type check for editor mode, --amend, or --squash (merge/squash workflows)
    skip_type = args["editor_mode"] or args["has_amend"] or args["has_merge_squash"]
    if not skip_type:
        msg = args["message"]
        if msg is not None and not TYPE_PATTERN.match(msg):
            _block(
                f"commit-guard: blocked — message does not match required format "
                r"^\[(FEAT|REFACTOR|FIX|TEST|CONSTRAINT|DOCS|HARNESS|PLAN)\] . "
                f"Got: {msg!r}"
            )
        # msg is None here only when -F read failed → fail-open (allow)


def _test():
    """Embedded test suite. Run: python3 guard.py --test"""
    import io
    import tempfile
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL") + f" — {name}")
        if not cond:
            fails.append(name)

    def run(command, branch="feature/x", marker=False, cwd=None, tool_name="Bash"):
        """Simulate a hook invocation. Returns exit code (0=allow, 2=block)."""
        payload = json.dumps({
            "tool_name": tool_name,
            "tool_input": {"command": command},
            "cwd": cwd or "/tmp",
        })
        old_stdin, sys.stdin = sys.stdin, io.StringIO(payload)
        old_stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            main(branch_override=branch, marker_override=marker)
            return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
        finally:
            sys.stdin = old_stdin
            sys.stderr = old_stderr

    # non-commit pass-through
    check("echo hi pass-through", run("echo hi") == 0)
    check("git status pass-through", run("git status") == 0)
    check("non-Bash tool pass-through", run("git commit -m '[FEAT] x'", tool_name="Read") == 0)

    # type guard: valid messages
    check("[FEAT] x passes", run("git commit -m '[FEAT] x'", branch="feature/x") == 0)
    check("[FIX] passes", run("git commit -m '[FIX] y'", branch="dev") == 0)

    # type guard: invalid messages blocked
    check("wip blocked", run("git commit -m 'wip'", branch="feature/x") == 2)
    check("no-bracket blocked", run("git commit -m 'feat: add x'", branch="feature/x") == 2)

    # branch guard: main/master blocked
    check("main branch blocked", run("git commit -m '[FEAT] x'", branch="main", marker=False) == 2)
    check("master branch blocked", run("git commit -m '[FEAT] x'", branch="master", marker=False) == 2)

    # allow-main marker present
    check("main + allow-main marker passes", run("git commit -m '[FEAT] x'", branch="main", marker=True) == 0)

    # --amend: type guard skipped, branch guard still applies
    check("--amend skips type guard", run("git commit --amend", branch="feature/x") == 0)
    check("--amend + bad msg: type guard skipped", run("git commit --amend -m 'wip'", branch="feature/x") == 0)
    check("--amend on main blocked", run("git commit --amend", branch="main", marker=False) == 2)

    # editor mode (no -m): type guard skipped, branch guard applies
    check("editor mode passes (non-main)", run("git commit", branch="feature/x") == 0)
    check("editor mode blocked (main)", run("git commit", branch="main", marker=False) == 2)

    # -C path handling
    check("git -C /x commit -m '[FIX] y' passes", run("git -C /x commit -m '[FIX] y'", branch="feature/x") == 0)
    check("git -C /x commit -m 'wip' blocked", run("git -C /x commit -m 'wip'", branch="feature/x") == 2)

    # chained commands
    check("chained: git commit in chain detected", run("echo hi && git commit -m 'wip'", branch="feature/x") == 2)
    check("chained: valid git commit in chain passes", run("git status; git commit -m '[FEAT] ok'", branch="feature/x") == 0)

    # -F file source
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
        fh.write("[FEAT] from file\n")
        fpath = fh.name
    check("-F valid msg passes", run(f"git commit -F {fpath}", branch="feature/x") == 0)
    os.unlink(fpath)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
        fh.write("bad msg\n")
        fpath = fh.name
    check("-F invalid msg blocked", run(f"git commit -F {fpath}", branch="feature/x") == 2)
    os.unlink(fpath)

    check("-F nonexistent: fail-open", run("git commit -F /nonexistent/msg.txt", branch="feature/x") == 0)

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        _code = 0
        try:
            main()
        except SystemExit as e:
            _code = e.code if isinstance(e.code, int) else 0
        except BaseException:
            pass
        sys.exit(_code)
