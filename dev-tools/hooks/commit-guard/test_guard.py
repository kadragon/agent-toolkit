#!/usr/bin/env python3
"""Tests for commit-guard hook. Run: python3 test_guard.py --test"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("guard", os.path.join(HERE, "guard.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f" — {name}")
    if not cond:
        fails.append(name)


def run_hook(command, branch="feature/x", marker=False, cwd=None, tool_name="Bash"):
    """Call guard.main() with injected branch/marker. Returns exit code (0 or 2)."""
    payload = json.dumps({
        "tool_name": tool_name,
        "tool_input": {"command": command},
        "cwd": cwd or "/tmp",
    })
    old_stdin, sys.stdin = sys.stdin, io.StringIO(payload)
    old_stderr, sys.stderr = sys.stderr, io.StringIO()
    try:
        guard.main(branch_override=branch, marker_override=marker)
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdin = old_stdin
        sys.stderr = old_stderr


# --- internal helpers ---------------------------------------------------------
check("_is_git_commit: git commit", guard._is_git_commit("git commit"))
check("_is_git_commit: git -C /p commit", guard._is_git_commit("git -C /p commit"))
check("_is_git_commit: git status → False", not guard._is_git_commit("git status"))
check("_is_git_commit: echo hi → False", not guard._is_git_commit("echo hi"))
check("_find_commit_segment: direct", guard._find_commit_segment("git commit -m '[FEAT] x'") is not None)
check("_find_commit_segment: chained", guard._find_commit_segment("echo hi && git commit -m 'wip'") is not None)
check("_find_commit_segment: no commit → None", guard._find_commit_segment("echo hi") is None)
check("_git_cwd: uses -C", guard._git_cwd("git -C /mypath commit", "/cwd") == "/mypath")
check("_git_cwd: no -C → env_cwd", guard._git_cwd("git commit", "/cwd") == "/cwd")

# --- _parse_commit_args -------------------------------------------------------
def _parse(cmd):
    return guard._parse_commit_args(cmd)

check("parse: -m message", _parse("git commit -m '[FEAT] x'")["message"] == "[FEAT] x")
check("parse: --message=", _parse("git commit --message='[FEAT] x'")["message"] == "[FEAT] x")
check("parse: --message space", _parse("git commit --message '[FIX] y'")["message"] == "[FIX] y")
check("parse: -m<msg> attached", _parse("git commit -m[FEAT]")["message"] == "[FEAT]")
check("parse: --amend", _parse("git commit --amend")["has_amend"] is True)
check("parse: --squash", _parse("git commit --squash")["has_merge_squash"] is True)
check("parse: editor_mode (no -m)", _parse("git commit")["editor_mode"] is True)
check("parse: -m overrides editor_mode", _parse("git commit -m 'x'")["editor_mode"] is False)

# -F file read
with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as _fh:
    _fh.write("[FEAT] from file\nsecond line\n")
    _fpath = _fh.name
_parsed_f = _parse(f"git commit -F {_fpath}")
check("-F: reads first line", _parsed_f["message"] == "[FEAT] from file")
check("-F: editor_mode False", _parsed_f["editor_mode"] is False)
os.unlink(_fpath)

_parsed_missing = _parse("git commit -F /nonexistent/x.txt")
check("-F missing: message None (fail-open)", _parsed_missing["message"] is None)
check("-F missing: editor_mode False (msg_file was set)", _parsed_missing["editor_mode"] is False)

# --- non-commit pass-through --------------------------------------------------
check("echo hi pass-through", run_hook("echo hi") == 0)
check("git status pass-through", run_hook("git status") == 0)
check("git add pass-through", run_hook("git add .") == 0)
check("git push pass-through", run_hook("git push origin main") == 0)
check("non-Bash tool ignored", run_hook("git commit -m '[FEAT] x'", tool_name="Read") == 0)

# --- type guard: valid messages -----------------------------------------------
check("[FEAT] x passes", run_hook("git commit -m '[FEAT] x'", branch="feature/x") == 0)
check("[FIX] y passes", run_hook("git commit -m '[FIX] y'", branch="dev") == 0)
check("[REFACTOR] passes", run_hook("git commit -m '[REFACTOR] clean up'", branch="dev") == 0)
check("[DOCS] passes", run_hook("git commit -m '[DOCS] readme'", branch="dev") == 0)
check("[TEST] passes", run_hook("git commit -m '[TEST] add coverage'", branch="dev") == 0)
check("[CONSTRAINT] passes", run_hook("git commit -m '[CONSTRAINT] add lint rule'", branch="dev") == 0)
check("[HARNESS] passes", run_hook("git commit -m '[HARNESS] add ci'", branch="dev") == 0)
check("[PLAN] passes", run_hook("git commit -m '[PLAN] update backlog'", branch="dev") == 0)

# --- type guard: invalid messages blocked ------------------------------------
check("wip blocked", run_hook("git commit -m 'wip'", branch="feature/x") == 2)
check("feat: format blocked", run_hook("git commit -m 'feat: add x'", branch="feature/x") == 2)
check("add thing blocked", run_hook("git commit -m 'add thing'", branch="feature/x") == 2)
check("missing trailing space blocked", run_hook("git commit -m '[FEAT]x'", branch="feature/x") == 2)
check("wrong type blocked", run_hook("git commit -m '[WIP] thing'", branch="feature/x") == 2)

# --- branch guard: main/master blocked ----------------------------------------
check("main branch blocked", run_hook("git commit -m '[FEAT] x'", branch="main", marker=False) == 2)
check("master branch blocked", run_hook("git commit -m '[FEAT] x'", branch="master", marker=False) == 2)

# --- branch guard: allow-main marker present ----------------------------------
check("main + allow-main marker passes", run_hook("git commit -m '[FEAT] x'", branch="main", marker=True) == 0)
check("master + allow-main marker passes", run_hook("git commit -m '[FEAT] x'", branch="master", marker=True) == 0)

# --- --amend: type guard skipped, branch guard still applies -----------------
check("--amend skips type guard", run_hook("git commit --amend", branch="feature/x") == 0)
check("--amend + bad msg: type guard skipped", run_hook("git commit --amend -m 'wip'", branch="feature/x") == 0)
check("--amend on main: branch guard fires", run_hook("git commit --amend", branch="main", marker=False) == 2)
check("--amend on main + marker: passes", run_hook("git commit --amend", branch="main", marker=True) == 0)

# --- editor mode (no -m, no -F) -----------------------------------------------
check("editor mode: feature branch passes", run_hook("git commit", branch="feature/x") == 0)
check("editor mode: main blocked", run_hook("git commit", branch="main", marker=False) == 2)
check("editor mode: main + marker passes", run_hook("git commit", branch="main", marker=True) == 0)

# --- git -C path handling ----------------------------------------------------
check("git -C /x commit valid passes", run_hook("git -C /x commit -m '[FIX] y'", branch="feature/x") == 0)
check("git -C /x commit invalid blocked", run_hook("git -C /x commit -m 'wip'", branch="feature/x") == 2)
check("git -C /x commit main blocked", run_hook("git -C /x commit -m '[FIX] y'", branch="main", marker=False) == 2)

# --- chained commands ---------------------------------------------------------
check("chained &&: bad msg blocked", run_hook("echo hi && git commit -m 'wip'", branch="feature/x") == 2)
check("chained ;: valid msg passes", run_hook("git status; git commit -m '[FEAT] ok'", branch="feature/x") == 0)
check("chained &&: valid msg passes", run_hook("git add . && git commit -m '[FIX] z'", branch="dev") == 0)

# --- -F file source -----------------------------------------------------------
with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as _fh:
    _fh.write("[FEAT] from file\n")
    _fpath = _fh.name
check("-F valid msg passes", run_hook(f"git commit -F {_fpath}", branch="feature/x") == 0)
os.unlink(_fpath)

with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as _fh:
    _fh.write("bad msg\n")
    _fpath = _fh.name
check("-F invalid msg blocked", run_hook(f"git commit -F {_fpath}", branch="feature/x") == 2)
os.unlink(_fpath)

check("-F nonexistent: fail-open", run_hook("git commit -F /nonexistent/msg.txt", branch="feature/x") == 0)

# --- end-to-end subprocess: malformed stdin → exit 0 -------------------------
_r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py")],
                    input="not json", text=True, capture_output=True)
check("e2e malformed stdin exit 0", _r.returncode == 0)

# --- end-to-end subprocess: non-commit → exit 0 ------------------------------
_r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py")],
                    input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo hi"}, "cwd": "/tmp"}),
                    text=True, capture_output=True)
check("e2e non-commit exit 0", _r.returncode == 0)

# --- allow-main marker read from real AGENTS.md/CLAUDE.md -------------------
with tempfile.TemporaryDirectory() as _d:
    subprocess.run(["git", "init", "-q", _d], check=True)
    # make an initial commit so rev-parse --abbrev-ref HEAD works (empty repos exit 128)
    subprocess.run(["git", "-C", _d, "config", "user.email", "test@test.com"], check=True)
    subprocess.run(["git", "-C", _d, "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", _d, "commit", "--allow-empty", "-m", "init"], check=True)
    # confirm we're on main/master
    _branch = subprocess.run(["git", "-C", _d, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    payload_main = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m '[FEAT] x'"},
        "cwd": _d,
    })
    if _branch in ("main", "master"):
        # no marker → BLOCK
        _r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py")],
                            input=payload_main, text=True, capture_output=True)
        check("e2e main branch no marker blocked (exit 2)", _r.returncode == 2)

        # write marker to AGENTS.md → ALLOW
        with open(os.path.join(_d, "AGENTS.md"), "w") as _fh:
            _fh.write("# Agents\n<!-- commit-guard: allow-main -->\n")
        _r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py")],
                            input=payload_main, text=True, capture_output=True)
        check("e2e main branch AGENTS.md marker passes (exit 0)", _r.returncode == 0)
    else:
        print(f"SKIP — e2e marker tests (default branch is '{_branch}', not main/master)")

# --- e2e type guard via subprocess -------------------------------------------
with tempfile.TemporaryDirectory() as _d:
    subprocess.run(["git", "init", "-q", _d], check=True)
    subprocess.run(["git", "-C", _d, "config", "user.email", "test@test.com"], check=True)
    subprocess.run(["git", "-C", _d, "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", _d, "commit", "--allow-empty", "-m", "init"], check=True)
    subprocess.run(["git", "-C", _d, "checkout", "-b", "feature/test"], capture_output=True)
    payload_bad = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m 'wip'"},
        "cwd": _d,
    })
    _r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py")],
                        input=payload_bad, text=True, capture_output=True)
    check("e2e bad type message blocked (exit 2)", _r.returncode == 2)

    payload_good = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m '[FEAT] x'"},
        "cwd": _d,
    })
    _r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py")],
                        input=payload_good, text=True, capture_output=True)
    check("e2e valid type message passes (exit 0)", _r.returncode == 0)

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("all passed")
