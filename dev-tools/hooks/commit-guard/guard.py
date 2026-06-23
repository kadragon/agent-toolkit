#!/usr/bin/env python3
"""commit-guard — PreToolUse(Bash) gate for `git commit` invocations.

Intercepts git commit commands before execution and applies two guards:
  1. Branch guard: blocks commits to main/master unless the repo's AGENTS.md
     or CLAUDE.md contains the literal marker <!-- commit-guard: allow-main -->.
     A branch created earlier in the same chain — `git checkout -b/-B/--orphan
     <name>` or `git switch -c/-C/--create/--orphan <name>` — is honored: the
     commit's branch is the newly created one, not the pre-checkout branch the
     live `rev-parse` still reports. This attribution carries only across `&&`
     (where the creation is guaranteed to have run) and is dropped across
     `||`/`;`/`|`/`&`/newline or a `cd`, so a commit that may actually land on
     main is not mis-attributed to an un-run checkout. A bare switch BACK onto a
     protected branch — `git checkout main` / `git switch master` with a single
     ref and no `--` pathspec — re-attributes the chain to that branch, so
     `checkout -b X && checkout main && commit` is blocked (the commit lands on
     main). Only main/master targets update attribution (fail-toward-block); a
     bare switch to a feature branch stays untrusted (ambiguous pathspec) and
     does not unblock.
  2. Type guard: commit message must match ^\\[(TYPE)\\] (with trailing space).
     Skipped for editor-mode commits (no -m/-F), --amend, and --squash flags,
     and for messages carrying shell-expandable command substitution (unquoted
     or double-quoted '$(...)' / backticks) whose real text is statically
     undecidable (fail-open). Single-quoted substitution is literal — git
     receives it verbatim — so it stays type-checked.

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


def _raw_tokens(s):
    """Like _tokens() but posix=False: quote characters are kept inside each
    token, so the type guard can tell a single-quoted (literal) '$(...)' from a
    shell-expandable one. Returns [] on parse error.

    CAVEAT — does NOT always align 1:1 with _tokens(). posix=False splits on a
    different rule set: a token whose quoting spans a whitespace boundary
    (`-m'a b'`, `--message='a b'`, adjacent quotes `'a''b'`, a quoted leading
    env-assign `FOO='a b'`, or a `$'...'` ANSI-C string) desyncs the two lists.
    Callers MUST verify `len(raw_tokens) == len(tokens)` before trusting an
    index, and fall back to a quote-agnostic decision when they diverge.
    """
    s = _LEAD_NOISE.sub("", s or "")
    try:
        parts = shlex.split(s, posix=False)
    except ValueError:
        return []
    i = 0
    while i < len(parts) and _ENV_ASSIGN.match(parts[i]):
        i += 1
    return parts[i:]


def _has_expandable_subst(raw_arg):
    """True if raw_arg (a message token with its original quotes intact) contains
    a shell-EXPANDABLE command substitution — a '$(' or backtick that is NOT
    inside single quotes. Single-quoted substitution is literal (git receives it
    verbatim), so it is decidable and must be type-checked → returns False.
    """
    in_single = False
    in_double = False
    i = 0
    n = len(raw_arg)
    while i < n:
        ch = raw_arg[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single:
            if ch == "`":
                return True
            if ch == "$" and i + 1 < n and raw_arg[i + 1] == "(":
                return True
        i += 1
    return False


def _split_segments(command):
    """Quote-aware split on shell segment separators: ; && || | & and newline.

    Uses shlex.shlex with posix=False so quoted tokens are preserved verbatim
    (e.g. '[FEAT] a && b' stays as one token) — downstream _tokens() then
    calls shlex.split() which correctly unquotes them.  Newlines outside quotes
    are pre-normalized to ';' via a simple quote-tracking pass.

    Returns (segments, operators): a list of raw segment strings (individual
    segments may be empty) and a parallel list of the separator operator that
    PRECEDES each segment (operators[0] is None; the rest are one of
    '&&' '||' '|' ';' '&'). Callers use the operator to decide whether state
    from an earlier segment (e.g. an in-chain branch creation) may carry into a
    later one — only '&&' guarantees the predecessor ran successfully.
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
        segs = re.split(r"&&|\|\||[;|\n&]", command)
        return segs, [None] * len(segs)

    _SEP_OPS = {"&&", "||", "|", ";", "&"}
    segments = []
    operators: list = [None]  # operator preceding each segment; first has none
    current = []
    for tok in tokens:
        if tok in _SEP_OPS:
            segments.append(" ".join(current))
            operators.append(tok)
            current = []
        else:
            current.append(tok)
    segments.append(" ".join(current))
    return segments, operators


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


# checkout/switch flags that CREATE a new branch (force + long variants included).
# '--orphan' (unborn branch) creates+switches for both subcommands.
_CHECKOUT_NEW_FLAGS = {"-b", "-B", "--orphan"}
_SWITCH_NEW_FLAGS = {"-c", "-C", "--create", "--orphan"}


def _new_branch_created(segment):
    """If this segment creates+switches to a new branch, return its name, else None.

    Recognizes `git checkout -b/-B <name>` and `git switch -c/-C <name>`.
    A bare `git checkout <name>` (switch to existing) is intentionally NOT
    matched: whether <name> is a branch, path, or commit is statically
    ambiguous, so we do not let it override the live branch detection.
    """
    toks = _tokens(segment)
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    if i >= len(toks) or os.path.basename(toks[i]) != "git":
        return None
    i += 1  # skip 'git'
    while i < len(toks):  # skip git-level options
        tok = toks[i]
        if tok in GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(toks):
        return None
    sub = toks[i]
    i += 1
    if sub == "checkout":
        new_flags = _CHECKOUT_NEW_FLAGS
    elif sub == "switch":
        new_flags = _SWITCH_NEW_FLAGS
    else:
        return None
    # the first token after a new-branch flag is the branch name
    while i < len(toks):
        if toks[i] in new_flags and i + 1 < len(toks):
            return toks[i + 1]
        i += 1
    return None


def _bare_switch_target(segment):
    """If this segment is a bare branch switch (no create flag) to a single
    unambiguous branch ref, return that branch name, else None.

    Recognizes `git checkout <ref>` and `git switch <ref>` with exactly one
    positional argument and no `--` separator. Returns None for:
      - create forms (-b/-c/--orphan/...) — handled by _new_branch_created
      - a `--` pathspec separator (`checkout <ref> -- <path>` restores files,
        it does NOT switch branch)
      - zero or multiple positionals (`checkout <ref> <path>` is a pathspec
        restore from <ref>, current branch unchanged)

    The caller only acts on a main/master target (re-attributing the chain to a
    protected branch — the fail-toward-block direction). A non-protected target
    is left for the caller to ignore, so the only false-positive surface is a
    pathspec literally named 'main'/'master' on a non-main branch — contrived and
    strictly safer than mis-attributing a real switch-back to main.
    """
    toks = _tokens(segment)
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    if i >= len(toks) or os.path.basename(toks[i]) != "git":
        return None
    i += 1  # skip 'git'
    while i < len(toks):  # skip git-level options
        tok = toks[i]
        if tok in GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(toks):
        return None
    sub = toks[i]
    i += 1
    if sub == "checkout":
        new_flags = _CHECKOUT_NEW_FLAGS
    elif sub == "switch":
        new_flags = _SWITCH_NEW_FLAGS
    else:
        return None
    positionals = []
    while i < len(toks):
        tok = toks[i]
        if tok == "--":
            return None  # pathspec restore — not a branch switch
        if tok in new_flags:
            return None  # create form — _new_branch_created owns this segment
        if tok.startswith("-"):
            i += 1  # other boolean flag (-f, --track, ...) → skip
            continue
        positionals.append(tok)
        i += 1
    return positionals[0] if len(positionals) == 1 else None


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
      message: str | None     (extracted message text, or None if not determinable)
      message_raw: str | None  (the inline -m value with original quotes intact, or
                                None when the message is not from an inline -m flag —
                                e.g. -F file, editor mode; lets the type guard tell a
                                single-quoted literal '$(...)' from an expandable one)
      raw_aligned: bool        (True iff the raw token list aligns 1:1 with the posix
                                tokens, so message_raw is positionally trustworthy;
                                False → caller must fall back to a quote-agnostic
                                decision, see _raw_tokens caveat)
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
    raw_toks = _raw_tokens(segment)  # quote-preserving; may desync (see _raw_tokens)
    # Only trust raw-token indices when the two tokenizers agree on token count.
    # A length mismatch means some token straddled a posix/non-posix split
    # boundary, so positional lookup would return the wrong fragment.
    raw_aligned = len(raw_toks) == len(toks)

    def _raw_at(idx):
        """Raw (quoted) token at idx, or None if alignment is unprovable/short."""
        if not raw_aligned or idx >= len(raw_toks):
            return None
        return raw_toks[idx]

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
    message_raw = None
    has_amend = False
    has_merge_squash = False
    msg_file = None

    while i < len(toks):
        tok = toks[i]
        if tok in ("-m", "--message") and i + 1 < len(toks):
            if message is None:  # first -m wins (git uses first as subject)
                message = toks[i + 1]
                message_raw = _raw_at(i + 1)
            i += 2
            continue
        if tok.startswith("--message="):
            if message is None:
                message = tok[len("--message="):]
                raw = _raw_at(i)
                message_raw = raw[len("--message="):] if raw else None
            i += 1
            continue
        if tok.startswith("-m") and len(tok) > 2:
            # -m<msg> attached (e.g. -m[FEAT] or -mwip)
            if message is None:
                message = tok[2:]
                raw = _raw_at(i)
                message_raw = raw[2:] if raw else None
            i += 1
            continue
        # bundled short flags: -am, -pam, etc. — if last char is 'm',
        # it consumes the next token as the message value
        if (tok.startswith("-") and not tok.startswith("--")
                and len(tok) > 2 and tok.endswith("m")
                and i + 1 < len(toks)):
            if message is None:
                message = toks[i + 1]
                message_raw = _raw_at(i + 1)
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
        "message_raw": message_raw,
        "raw_aligned": raw_aligned,
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
    segments, operators = _split_segments(command)
    effective_cwd_at = {}  # segment_index → effective cwd
    effective_branch_at = {}  # segment_index → branch created earlier in-chain, or None
    running_cwd = env_cwd
    running_branch = None  # None = no in-chain branch creation seen → use live detection
    for idx, seg in enumerate(segments):
        # Branch attribution may only carry across '&&' (predecessor guaranteed to
        # have succeeded). After '||', ';', '|', '&' or a newline the earlier
        # checkout may not have run — drop the attribution so the commit falls
        # back to live branch detection.
        if operators[idx] is not None and operators[idx] != "&&":
            running_branch = None
        stripped = seg.strip()
        toks = _tokens(stripped)
        if len(toks) >= 2 and toks[0] == "cd":
            # cd <path>: update running effective cwd (resolve relative paths).
            # A cwd change voids branch attribution — the new directory may be a
            # different repo where the earlier checkout never applied.
            running_cwd = os.path.abspath(os.path.join(running_cwd, toks[1]))
            running_branch = None
        created = _new_branch_created(stripped)
        if created is not None:
            running_branch = created
        else:
            # A bare switch BACK onto a protected branch re-attributes the chain:
            # `checkout -b X && checkout main && commit` lands on main. Only
            # protected targets update attribution (fail-toward-block); a bare
            # switch to a feature branch is left untrusted (ambiguous pathspec),
            # preserving the conservative "bare checkout does not unblock" rule.
            switched = _bare_switch_target(stripped)
            if switched in ("main", "master"):
                running_branch = switched
        effective_cwd_at[idx] = running_cwd
        effective_branch_at[idx] = running_branch

    # Collect all commit segments with their effective cwds and in-chain branch
    commit_segs = []
    for idx, seg in enumerate(segments):
        stripped = seg.strip()
        if _is_git_commit(stripped):
            # -C flag overrides the cd-tracked cwd for this specific git call
            base_cwd = effective_cwd_at[idx]
            git_effective_cwd = _git_cwd(stripped, base_cwd)
            commit_segs.append((stripped, git_effective_cwd, effective_branch_at[idx]))

    if not commit_segs:
        return  # not a git commit invocation → pass through

    # Check ALL commit segments — any failure blocks the entire command
    for seg, effective_cwd, created_branch in commit_segs:
        # --- Branch guard ---------------------------------------------------------
        # A branch created earlier in the same chain (checkout -b/switch -c) is
        # where the commit actually lands — it takes precedence over the live
        # branch, which still reports the pre-checkout branch at PreToolUse time.
        if created_branch is not None:
            branch = created_branch
        else:
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
            # A message carrying SHELL-EXPANDABLE command substitution ('$(...)'
            # or backticks, unquoted or double-quoted) is read literally here —
            # the shell would expand it before git sees it, but the hook cannot
            # (running it is unsafe). Its real text is statically undecidable, so
            # per the fail-open contract (cf. -F read failure / editor mode) skip
            # the type check. Single-quoted substitution is NOT expandable — git
            # receives it verbatim — so it stays decidable and IS type-checked;
            # we classify via the raw (quote-preserving) arg, not the unquoted msg.
            if args["raw_aligned"] and args["message_raw"] is not None:
                undecidable = _has_expandable_subst(args["message_raw"])
            else:
                # Raw-token alignment is unprovable (quoted leading env-assign,
                # attached -m'a b', adjacent quotes, $'...', backslash escapes all
                # desync posix vs non-posix splitting) — we cannot recover the
                # message's quote context. Fall back to the conservative, quote-
                # agnostic heuristic: any '$(' or backtick → undecidable → fail-open.
                # Safe direction: never a false block of a legit expandable message;
                # at worst it skips type-checking a literal it could have enforced,
                # which is no weaker than the guard's pre-existing behavior.
                undecidable = msg is not None and ("$(" in msg or "`" in msg)
            if msg is not None and not undecidable and not TYPE_PATTERN.match(msg):
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

    # in-chain branch creation: checkout -b / switch -c move off main before the commit
    check("checkout -b then commit on main passes",
          run("git checkout -b feature/x && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    check("switch -c then commit on main passes",
          run("git switch -c feature/x && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    check("checkout -B then commit on main passes",
          run("git checkout -B feature/x && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    check("checkout -b to literal main still blocked",
          run("git checkout -b main && git commit -m '[FEAT] y'", branch="feature/x", marker=False) == 2)
    check("bare checkout (no -b) does not unblock main",
          run("git checkout feature/x && git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout -b then bad-type commit still type-blocked",
          run("git checkout -b feature/x && git commit -m 'wip'", branch="main", marker=False) == 2)

    # bare switch-back to a protected branch re-attributes: checkout -b moves off
    # main, then a bare `checkout main` / `switch main` moves back, so the commit
    # lands on main → must block even though live detection saw the new branch.
    check("checkout -b X then bare checkout main then commit → blocked",
          run("git checkout -b feature/x && git checkout main && git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout -b X then bare switch main then commit → blocked",
          run("git checkout -b feature/x && git switch main && git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout -b X then bare checkout master then commit → blocked",
          run("git checkout -b feature/x && git checkout master && git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    # bare switch ONTO main from a feature live branch also re-attributes → blocked
    check("bare checkout main from feature then commit → blocked",
          run("git checkout main && git commit -m '[FEAT] y'", branch="feature/x", marker=False) == 2)
    # bare switch to a NON-protected branch must NOT re-attribute (no false block):
    # a `checkout main -- file` restore (has '--') keeps the new-branch attribution.
    check("checkout -b X then checkout main -- file (restore) then commit → passes",
          run("git checkout -b feature/x && git checkout main -- file.py && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    check("checkout -b X then checkout main file (pathspec restore) then commit → passes",
          run("git checkout -b feature/x && git checkout main file.py && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    # bare switch-back attribution only carries across '&&'
    check("checkout -b X || bare checkout main ; commit → live detection (main) blocks anyway",
          run("git checkout -b feature/x ; git checkout main ; git commit -m '[FEAT] y'", branch="main", marker=False) == 2)

    # branch attribution only propagates across '&&' (guaranteed-success predecessor)
    check("checkout -b || commit on main still blocked (|| not guaranteed)",
          run("git checkout -b feature/x || git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout -b ; commit on main still blocked (; not guaranteed)",
          run("git checkout -b feature/x ; git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout -b && echo && commit on main passes (&&-chain preserved)",
          run("git checkout -b feature/x && echo ok && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    check("cd to another repo after checkout -b resets attribution → blocked on main",
          run("git checkout -b feature/x && cd /other/repo && git commit -m '[FEAT] y'", branch="main", marker=False) == 2)

    # long-flag branch creation: switch --create / checkout|switch --orphan
    check("switch --create then commit on main passes",
          run("git switch --create feature/x && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    check("checkout --orphan then commit on main passes",
          run("git checkout --orphan feature/x && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)

    # command-substitution message: only EXPANDABLE subst (double-quoted/unquoted)
    # is statically undecidable → fail-open. Single-quoted subst is LITERAL — the
    # shell does not expand it, git receives the text verbatim → type guard enforces.
    # "expandable" = the OUTER shell would expand it before git sees it (the hook
    # never runs expansion itself); it classifies the raw token's quote context.
    check("double-quoted $(...) is expandable → skips type check",
          run('git commit -m "$(cat msg.txt)"', branch="feature/x") == 0)
    check("double-quoted backtick is expandable → skips type check",
          run('git commit -m "`cat msg.txt`"', branch="feature/x") == 0)
    check("single-quoted $(...) literal still type-checked → blocked",
          run("git commit -m '$(cat msg.txt)'", branch="feature/x") == 2)
    check("single-quoted backtick literal still type-checked → blocked",
          run("git commit -m '`cat msg.txt`'", branch="feature/x") == 2)
    check("single-quoted literal with valid type passes",
          run("git commit -m '[FEAT] $(x) ok'", branch="feature/x") == 0)
    check("plain bad message still blocked (no subst)",
          run("git commit -m 'wip changes'", branch="feature/x") == 2)
    check("$(...) message still branch-guarded on main",
          run("git commit -m '$(cat msg.txt)'", branch="main", marker=False) == 2)

    # raw/posix token misalignment → fail-open (never a false block). A quoted
    # leading env-assign with a space desyncs _raw_tokens from _tokens; the guard
    # must fall back to the quote-agnostic heuristic, not block a legit message.
    check("env-assign + double-quoted $(...) fails open (no false block)",
          run("GIT_AUTHOR_NAME='Jane Doe' git commit -m \"$(cat msg.txt)\"", branch="feature/x") == 0)
    check("env-assign + valid type still passes (misaligned)",
          run("FOO='bar baz' git commit -m '[FEAT] x'", branch="feature/x") == 0)
    check("env-assign + bad literal still blocked (misaligned, no subst)",
          run("FOO='bar baz' git commit -m 'wip'", branch="feature/x") == 2)
    # attached -m'...' with internal space also desyncs → conservative fail-open
    check("attached -m'$(...)' fails open on misalignment",
          run("git commit -m'wip $(date)'", branch="feature/x") == 0)

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
