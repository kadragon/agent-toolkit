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

# strip leading subshell punctuation
_LEAD_NOISE = re.compile(r"^\s*[\(\{!]*\s*")
# env-assign detector — matches only a complete token that is VAR=value
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# wrapper words that may precede 'git' but do not affect semantics
_GIT_WRAPPERS = {"command", "exec"}


def _tokens(s):
    """Tokenize a shell fragment, stripping LEADING env-assigns only.

    Env-assign stripping applies only to the prefix before the command name:
    once we've seen the first non-assign token (the command), remaining tokens
    (e.g. -m 'foo=bar') are left intact.

    On shlex.split ValueError (unbalanced quotes etc.) → return [] so the
    segment is treated as non-commit (fail-open), preserving the documented
    never-block-on-parse-error contract.
    """
    s = _LEAD_NOISE.sub("", s or "")
    try:
        parts = shlex.split(s)
    except ValueError:
        return []  # unparseable segment → fail-open (not a commit)
    # strip only the leading env-assignment prefix (before the command name)
    i = 0
    while i < len(parts) and _ENV_ASSIGN.match(parts[i]):
        i += 1
    return parts[i:]


def _split_segments(command):
    """Quote-aware split on shell segment separators: ; && || | & and newline.

    Uses shlex.shlex with posix=False so quoted tokens are preserved verbatim
    (e.g. '[FEAT] a && b' stays as one token) — downstream _tokens() then
    calls shlex.split() which correctly unquotes them.  Newlines outside quotes
    are pre-normalized to ';' via a simple quote-tracking pass.

    Returns a list of raw segment strings; individual segments may be empty.
    """
    # Replace unquoted newlines with ';' (newline = command separator in shell).
    # A simple state-machine is sufficient since we don't need full posix quoting
    # here — we just need to know if we're inside a single or double-quoted span.
    buf = []
    in_single = False
    in_double = False
    for ch in command:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "\n" and not in_single and not in_double:
            ch = ";"
        buf.append(ch)
    normalized = "".join(buf)

    # Lex with posix=False so quotes are kept as part of the token text.
    # punctuation_chars groups '&&', '||', '|', ';', '&' as operator tokens.
    try:
        lex = shlex.shlex(normalized, posix=False, punctuation_chars="&|;<>")
        lex.whitespace_split = False
        tokens = list(lex)
    except ValueError:
        return re.split(r"&&|\|\||[;|\n&]", command)

    _SEP_OPS = {"&&", "||", "|", ";", "&"}
    segments = []
    current = []
    for tok in tokens:
        if tok in _SEP_OPS:
            segments.append(" ".join(current))
            current = []
        else:
            current.append(tok)
    segments.append(" ".join(current))
    return segments


def _is_git_commit(segment):
    """True if this shell segment is a git commit invocation.

    Handles wrapper words like 'command' (POSIX shell built-in that just
    executes the named command) preceding 'git'.
    """
    toks = _tokens(segment)
    if not toks:
        return False
    # skip optional wrapper words (e.g. 'command git commit')
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    if i >= len(toks) or os.path.basename(toks[i]) != "git":
        return False
    i += 1  # skip 'git'
    # walk past git-level flags (e.g. -C path, -c key=val, --no-pager)
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


def _git_cwd(segment, env_cwd):
    """Effective cwd for the git call: env_cwd unless overridden by -C flag.

    Relative -C values are resolved as absolute paths against env_cwd.
    """
    toks = _tokens(segment)
    # skip wrapper words
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    i += 1  # skip 'git'
    while i < len(toks):
        tok = toks[i]
        if tok == "-C" and i + 1 < len(toks):
            val = toks[i + 1]
            # normalize relative paths against env_cwd
            return os.path.abspath(os.path.join(env_cwd, val))
        if tok in GIT_VALUE_OPTS - {"-C"}:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    return env_cwd


def _current_branch(cwd, _override=None):
    """Return current branch name, or '' on failure.

    _override may be a string (returned as-is for any cwd) or a callable
    (cwd) -> str (used by tests that need per-cwd branch injection).
    """
    if _override is not None:
        if callable(_override):
            return _override(cwd)
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

    Multiple -m flags: git uses the FIRST as the commit subject line.
    The first -m/--message sets `message`; subsequent ones are ignored for
    type-checking (they become the body in git's eyes).

    Bundled short options: -am parses the trailing 'm' as the message flag,
    consuming the next token as the message value.
    """
    toks = _tokens(segment)
    # skip wrapper words then find 'git'
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    # skip to 'git'
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
            if message is None:  # first -m wins (git uses first as subject)
                message = toks[i + 1]
            i += 2
            continue
        if tok.startswith("--message="):
            if message is None:
                message = tok[len("--message="):]
            i += 1
            continue
        if tok.startswith("-m") and len(tok) > 2:
            # -m<msg> attached (e.g. -m[FEAT] or -mwip)
            if message is None:
                message = tok[2:]
            i += 1
            continue
        # bundled short flags: -am, -pam, etc. — if last char is 'm',
        # it consumes the next token as the message value
        if (tok.startswith("-") and not tok.startswith("--")
                and len(tok) > 2 and tok.endswith("m")
                and i + 1 < len(toks)):
            if message is None:
                message = toks[i + 1]
            i += 2
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
    """Main hook logic. branch_override / marker_override for test injection.

    branch_override may be:
      - None       → real git subprocess call
      - str        → returned for ALL cwds (legacy test interface)
      - callable   → called as branch_override(cwd) → str (per-cwd injection)
    """
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

    env_cwd = data.get("cwd") or os.getcwd()

    # Build a map of segment-index → effective cwd by tracking cd commands
    # that appear before commit segments in the same command chain.
    segments = list(_split_segments(command))
    effective_cwd_at = {}  # segment_index → effective cwd
    running_cwd = env_cwd
    for idx, seg in enumerate(segments):
        toks = _tokens(seg.strip())
        if len(toks) >= 2 and toks[0] == "cd":
            # cd <path>: update running effective cwd (resolve relative paths)
            running_cwd = os.path.abspath(os.path.join(running_cwd, toks[1]))
        effective_cwd_at[idx] = running_cwd

    # Collect all commit segments with their effective cwds
    commit_segs = []
    for idx, seg in enumerate(segments):
        stripped = seg.strip()
        if _is_git_commit(stripped):
            # -C flag overrides the cd-tracked cwd for this specific git call
            base_cwd = effective_cwd_at[idx]
            git_effective_cwd = _git_cwd(stripped, base_cwd)
            commit_segs.append((stripped, git_effective_cwd))

    if not commit_segs:
        return  # not a git commit invocation → pass through

    # Check ALL commit segments — any failure blocks the entire command
    for seg, effective_cwd in commit_segs:
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
