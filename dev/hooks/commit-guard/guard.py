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
     main is not mis-attributed to an un-run checkout. A bare switch — `git
     checkout <ref>` / `git switch <ref>` with a single ref, no `--` pathspec
     and no `--detach` — re-attributes the chain to that ref when either the
     target is protected (so `checkout -b X && checkout main && commit` blocks)
     or attribution is already tracked in-chain (so `checkout main && checkout
     feature/x && commit` follows to feature/x rather than sticking at main). A
     bare switch to a feature branch from live detection (no in-chain attribution
     yet) stays untrusted (ambiguous pathspec) and does not unblock; a detached
     checkout (`--detach`) never re-attributes (the commit lands on a detached
     HEAD, not the branch ref).
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
        # shlex's punctuation_chars mode only auto-extends wordchars with
        # '~-./*?=' — without '@{}' a reflog ref like '@{-1}' gets split into
        # separate one-char tokens ('@', '{', '-1', '}'), which then get
        # rejoined with spaces and corrupt the segment text.
        lex.wordchars += "@{}"
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

# checkout/switch options that ALWAYS consume a following separate-token value
# (conservative: only options whose value is never optional, so skipping the
# next token can never accidentally swallow the real branch positional).
_CHECKOUT_SWITCH_VALUE_OPTS = {"--conflict"}

# previous-branch-ref spellings ('-' and '@{-N}') whose actual destination is
# statically unknown at hook time — see _UNKNOWN_SWITCH_TARGET below.
_PREV_BRANCH_REF_RE = re.compile(r"^@\{-\d+\}$")


def _is_prev_branch_ref(tok):
    return tok == "-" or bool(_PREV_BRANCH_REF_RE.match(tok))


# carrier returned by _bare_switch_target for a switch to a previous-branch ref
# ('-', '@{-N}') — distinct from None (not a bare switch at all) and from a
# plain str (a known branch name), so the caller can attempt real resolution
# (virtual chain-stack + reflog) instead of unconditionally treating it as
# unresolvable. See _resolve_prev_ref.
class _PrevRef:
    __slots__ = ("n",)

    def __init__(self, n):
        self.n = n


def _prev_ref_n(tok):
    """'-' -> 1; '@{-N}' -> N."""
    return 1 if tok == "-" else int(tok[3:-1])


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
    unambiguous branch ref, return that branch name; a _PrevRef(n) if it
    switches to a previous-branch ref ('-', '@{-N}'); else None.

    Recognizes `git checkout <ref>` and `git switch <ref>` with exactly one
    positional argument and no `--` separator. Returns None for:
      - create forms (-b/-c/--orphan/...) — handled by _new_branch_created
      - a `--` pathspec separator (`checkout <ref> -- <path>` restores files,
        it does NOT switch branch)
      - a `--detach`/`-d` flag (`checkout --detach main` lands on a detached
        HEAD; a commit there does NOT update the protected branch ref)
      - zero or multiple positionals (`checkout <ref> <path>` is a pathspec
        restore from <ref>, current branch unchanged)

    Returns _PrevRef(n) for `-`/`@{-n}` (previous-branch refs): the caller
    resolves the actual destination via _resolve_prev_ref (in-chain virtual
    stack + real reflog), falling back to unknown (None) attribution — and
    thus live branch detection — only when that resolution cannot be proven
    correct (fail-toward-block).

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
        if tok in ("--detach", "-d"):
            return None  # detached HEAD — commit does not update the branch ref
        if _is_prev_branch_ref(tok):
            positionals.append(_PrevRef(_prev_ref_n(tok)))
            i += 1
            continue
        if tok in _CHECKOUT_SWITCH_VALUE_OPTS:
            i += 2  # skip the option AND its separate-token value
            continue
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


def _prev_branch(cwd, n, _override=None):
    """Return the real reflog '@{-n}' branch name, or '' on failure.

    _override may be a string (returned as-is) or a callable (cwd, n) -> str
    (used by tests that need per-cwd/per-n reflog injection).
    """
    if _override is not None:
        if callable(_override):
            return _override(cwd, n)
        return _override
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", f"@{{-{n}}}"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _resolve_prev_ref(n, chain_stack, cwd, stack_reliable, branch_override, reflog_override):
    """Resolve a previous-branch ref ('-'=@{-1}, '@{-n}') to its real target
    branch, or None if it cannot be proven (caller must fail-toward-block).

    Combines the in-chain simulated switch history (chain_stack, most-recent
    last) with the real pre-chain state:
      - n <= depth-1  → chain_stack[depth-1-n]      (statically known)
      - n == depth    → pre-chain current branch    (_current_branch shell-out)
      - n > depth     → real reflog '@{-(n-depth)}'  (_prev_branch shell-out)

    stack_reliable must be True — once any bare switch to a known (statically
    ambiguous) target has occurred, chain_stack's depth can no longer be
    trusted to match git's real reflog depth, and resolving further would risk
    a bypass (a commit landing on main getting allowed). Returns None in that
    case, and also when the resolved target is "HEAD" (detached — a commit
    there does not update the protected branch, so there is no branch name to
    trust).
    """
    if not stack_reliable:
        return None
    depth = len(chain_stack)
    if n <= depth - 1:
        resolved = chain_stack[depth - 1 - n]
    elif n == depth:
        resolved = _current_branch(cwd, _override=branch_override)
    else:
        resolved = _prev_branch(cwd, n - depth, _override=reflog_override)
    if not resolved or resolved == "HEAD":
        return None
    return resolved


# git subcommands statically known to never change which branch HEAD points
# at (so a segment invoking one of these cannot silently move the chain off
# the depth _resolve_prev_ref assumes). Deliberately conservative and NOT an
# exhaustive list of "safe" commands — anything absent from it (including an
# unrecognized token, which may be a configured alias like `co = checkout`
# that literal "checkout"/"switch" matching can never see) is treated as
# potentially HEAD-moving and poisons chain-stack reliability instead.
_HEAD_NEUTRAL_SUBCOMMANDS = {"commit"}


def _is_unmodeled_git_segment(segment):
    """True if this segment is a `git` invocation whose effect on HEAD is not
    provably modeled by `_new_branch_created`/`_bare_switch_target` (called
    before this in the attribution loop) or known to be HEAD-neutral.

    Covers: `checkout`/`switch` forms not caught by the two functions above
    (detach, pathspec restore, multi-positional — already left untrusted for
    `running_branch`, but chain_stack's DEPTH must also stop being trusted
    past them); and — critically — any OTHER subcommand, since a git alias
    (`git -c alias.co=checkout co X`, or a persisted `co = checkout` in
    .gitconfig) invokes checkout/switch under a name this file's literal
    token matching cannot recognize. Poisoning on every unrecognized
    subcommand closes that gap without needing to resolve aliases: a later
    '@{-N}' just falls back to live branch detection instead of trusting a
    chain_stack depth that may not reflect what actually ran.
    """
    toks = _tokens(segment)
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    if i >= len(toks) or os.path.basename(toks[i]) != "git":
        return False
    i += 1
    while i < len(toks):
        tok = toks[i]
        if tok in GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(toks):
        return False  # bare 'git', no subcommand — nothing to poison over
    return toks[i] not in _HEAD_NEUTRAL_SUBCOMMANDS


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


def main(branch_override=None, marker_override=None, reflog_override=None):
    """Main hook logic. branch_override / marker_override / reflog_override for
    test injection.

    branch_override may be:
      - None       → real git subprocess call
      - str        → returned for ALL cwds (legacy test interface)
      - callable   → called as branch_override(cwd) → str (per-cwd injection)

    reflog_override (used to resolve real '@{-n}' refs beyond the in-chain
    simulated depth) may be:
      - None       → real git subprocess call
      - str        → returned for ALL (cwd, n) (legacy test interface)
      - callable   → called as reflog_override(cwd, n) → str
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
    # chain_stack / stack_reliable back '@{-N}'/'-' resolution only — they are
    # independent of running_branch's own trust rules (see _resolve_prev_ref).
    chain_stack = []       # ordered in-chain "current branch" history, most-recent last
    stack_reliable = True  # False once chain_stack's depth can no longer be proven exact
    any_switch_seen = False  # True once any HEAD-moving switch has appeared in the chain
    for idx, seg in enumerate(segments):
        # Branch attribution may only carry across '&&' (predecessor guaranteed to
        # have succeeded). After '||', ';', '|', '&' or a newline the earlier
        # checkout may not have run — drop the attribution so the commit falls
        # back to live branch detection.
        if operators[idx] is not None and operators[idx] != "&&":
            running_branch = None
            chain_stack = []
            if any_switch_seen:
                # an earlier switch (trusted or not) may have run at runtime and
                # mutated the real reflog — a later '@{-N}' resolved against the
                # hook-time (pre-chain) reflog would be stale, so stop resolving.
                stack_reliable = False
        stripped = seg.strip()
        toks = _tokens(stripped)
        if len(toks) >= 2 and toks[0] == "cd":
            # cd <path>: update running effective cwd (resolve relative paths).
            # A cwd change voids branch attribution — the new directory may be a
            # different repo where the earlier checkout never applied.
            running_cwd = os.path.abspath(os.path.join(running_cwd, toks[1]))
            running_branch = None
            chain_stack = []
            if any_switch_seen:
                stack_reliable = False
        created = _new_branch_created(stripped)
        if created is not None:
            running_branch = created
            chain_stack.append(created)
            any_switch_seen = True
        else:
            # A bare switch re-attributes the chain to its target when EITHER:
            #   (a) the target is a protected branch — `checkout -b X && checkout
            #       main && commit` lands on main → block (fail-toward-block); OR
            #   (b) attribution is already being tracked in-chain (running_branch
            #       non-None) — a later bare switch then updates to the real
            #       landing branch, so `checkout main && checkout feature/x &&
            #       commit` is correctly attributed to feature/x (not stuck at
            #       main), and `checkout -b X && checkout Y && commit` follows to Y.
            # When running_branch is still None (no in-chain attribution yet), a
            # bare switch to a NON-protected target is left untrusted (ambiguous
            # pathspec), preserving the conservative "bare checkout from live main
            # does not unblock" rule.
            switched = _bare_switch_target(stripped)
            if isinstance(switched, _PrevRef):
                any_switch_seen = True
                # Resolve against THIS segment's own effective cwd (honors a
                # `-C <path>` on the switch itself), not the shell-cd-tracked
                # running_cwd — otherwise a `-C`-scoped switch/commit chain
                # resolves against the wrong repository's reflog.
                switch_cwd = _git_cwd(stripped, running_cwd)
                resolved = _resolve_prev_ref(
                    switched.n, chain_stack, switch_cwd, stack_reliable,
                    branch_override, reflog_override,
                )
                if resolved is None:
                    # unresolvable (or resolution proven unreliable) — drop the
                    # in-chain attribution and stop trusting chain_stack depth,
                    # so the commit falls back to live branch detection
                    # (fail-toward-block).
                    running_branch = None
                    chain_stack = []
                    stack_reliable = False
                else:
                    running_branch = resolved
                    chain_stack.append(resolved)
            elif switched is not None:
                # bare switch to a statically-known (but branch-vs-pathspec
                # ambiguous) target — chain_stack's depth can no longer be
                # proven exact past this point, so poison future '@{-N}'
                # resolution even though running_branch's own trust rule
                # (below) is unaffected.
                any_switch_seen = True
                stack_reliable = False
                if switched in ("main", "master") or running_branch is not None:
                    running_branch = switched
            elif _is_unmodeled_git_segment(stripped):
                # detach / pathspec restore / multi-positional checkout-or-switch
                # form, an unrecognized subcommand (possibly a git alias for
                # checkout/switch), or any other unmodeled git invocation —
                # chain_stack depth is unprovable past this segment.
                any_switch_seen = True
                stack_reliable = False
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

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL") + f" — {name}")
        if not cond:
            fails.append(name)

    def run(command, branch="feature/x", marker=False, cwd=None, tool_name="Bash", reflog=None):
        """Simulate a hook invocation. Returns exit code (0=allow, 2=block)."""
        payload = json.dumps({
            "tool_name": tool_name,
            "tool_input": {"command": command},
            "cwd": cwd or "/tmp",
        })
        old_stdin, sys.stdin = sys.stdin, io.StringIO(payload)
        old_stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            main(branch_override=branch, marker_override=marker, reflog_override=reflog)
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

    # bare switch THROUGH main to a feature branch must follow to the landing
    # branch, not stay stuck at main: `checkout main && checkout feature/x &&
    # commit` lands on feature/x → allowed even though it transited main.
    # (live override here stands in for a non-main pre-chain branch; the in-chain
    # attribution overrides live detection regardless.)
    check("checkout main then checkout feature/x then commit → passes (follows to feature/x)",
          run("git checkout main && git checkout feature/x && git commit -m '[FEAT] y'", branch="main", marker=False) == 0)
    # once attribution is tracked in-chain, a bare switch to a non-protected branch
    # follows: `checkout -b X && checkout Y && commit` lands on Y → allowed.
    check("checkout -b X then bare checkout Y then commit → passes (follows to Y)",
          run("git checkout -b feature/x && git checkout feature/y && git commit -m '[FEAT] z'", branch="main", marker=False) == 0)
    # detached HEAD: `checkout --detach main` / `switch --detach master` lands on a
    # detached HEAD — a commit there does NOT update the protected branch, so the
    # switch must NOT re-attribute to main (no false block). Live detection (a
    # non-main feature branch here, standing in for the real 'HEAD' detached ref)
    # governs instead.
    check("checkout --detach main then commit → passes (detached, no re-attribution)",
          run("git checkout --detach main && git commit -m '[FEAT] y'", branch="feature/x", marker=False) == 0)
    check("switch --detach master then commit → passes (detached, no re-attribution)",
          run("git switch --detach master && git commit -m '[FEAT] y'", branch="feature/x", marker=False) == 0)

    # option-value desync: `--conflict <style>` takes a separate-token value that
    # must NOT be miscounted as the switch's positional branch arg — otherwise the
    # real target ('main') is pushed out of the len==1 positional check and the
    # switch-back to main is silently missed (bypass).
    check("checkout -b X then checkout --conflict merge main then commit → blocked",
          run("git checkout -b feature/x && git checkout --conflict merge main && "
              "git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout --conflict=merge main (attached form) then commit on main → blocked",
          run("git checkout --conflict=merge main && git commit -m '[FEAT] y'", branch="feature/x", marker=False) == 2)

    # previous-branch-ref switch-back targets ('-' / '@{-N}') are resolved via
    # the virtual chain-stack + real reflog (_resolve_prev_ref). At depth 1,
    # '-'/'@{-1}' resolve through _current_branch (the pre-chain live branch)
    # — the same value the old always-unknown fallback reached, so these
    # existing cases keep their original expected outcome unchanged.
    check("checkout -b X then checkout - then commit (live=main) → blocked",
          run("git checkout -b feature/x && git checkout - && git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout -b X then checkout @{-1} then commit (live=main) → blocked",
          run("git checkout -b feature/x && git checkout @{-1} && git commit -m '[FEAT] y'", branch="main", marker=False) == 2)
    check("checkout -b X then checkout - then commit (live=feature/y) → passes (no false block)",
          run("git checkout -b feature/x && git checkout - && git commit -m '[FEAT] y'", branch="feature/y", marker=False) == 0)
    # N == depth uses the pre-chain live branch (_current_branch), NOT the real
    # reflog — a decoy reflog value must not override it.
    check("checkout -b X then checkout @{-1} then commit (reflog decoy ignored) → blocked",
          run("git checkout -b feature/x && git checkout @{-1} && git commit -m '[FEAT] y'",
              branch="main", marker=False, reflog="feature/decoy") == 2)

    # N > depth resolves via the REAL reflog ('@{-(N-depth)}'): the task's
    # motivating false-block — `checkout -b tmp && checkout @{-2}` — where
    # @{-2} actually lands on a feature branch must now be allowed instead of
    # falling back to live (main) detection.
    check("checkout -b tmp then checkout @{-2} (reflog=feature) → passes (real target, no false block)",
          run("git checkout -b tmp && git checkout @{-2} && git commit -m '[FEAT] y'",
              branch="main", marker=False, reflog="feature/z") == 0)
    check("checkout -b tmp then checkout @{-2} (reflog=main) → still blocked",
          run("git checkout -b tmp && git checkout @{-2} && git commit -m '[FEAT] y'",
              branch="main", marker=False, reflog="main") == 2)
    check("checkout -b tmp then checkout @{-5} (reflog resolution fails) → blocked (fail-toward-block)",
          run("git checkout -b tmp && git checkout @{-5} && git commit -m '[FEAT] y'",
              branch="main", marker=False, reflog="") == 2)
    check("checkout -b tmp then checkout @{-2}/@{-3} (reflog varies by n) → resolves per-n",
          run("git checkout -b tmp && git checkout @{-2} && git commit -m '[FEAT] y'",
              branch="main", marker=False,
              reflog=lambda _cwd, n: "feature/z" if n == 1 else "main") == 0)
    check("checkout -b tmp then checkout @{-3} (reflog varies by n, n=2→main) → blocked",
          run("git checkout -b tmp && git checkout @{-3} && git commit -m '[FEAT] y'",
              branch="main", marker=False,
              reflog=lambda _cwd, n: "feature/z" if n == 1 else "main") == 2)

    # N <= depth-1 resolves statically from chain_stack — no shell-out at all.
    # (depth=3 chain; decoy branch/reflog prove the shell-outs are never consulted.)
    check("checkout -b X, main, Y then checkout @{-2} (chain_stack[0]=X) → passes",
          run("git checkout -b X && git checkout -b main && git checkout -b Y && "
              "git checkout @{-2} && git commit -m '[FEAT] z'",
              branch="feature/decoy-live", marker=False, reflog="feature/decoy-reflog") == 0)
    check("checkout -b X, main, Y then checkout @{-1} (chain_stack[1]=main) → blocked",
          run("git checkout -b X && git checkout -b main && git checkout -b Y && "
              "git checkout @{-1} && git commit -m '[FEAT] z'",
              branch="feature/decoy-live", marker=False, reflog="feature/decoy-reflog") == 2)

    # Bypass guards: a bare switch to a KNOWN target, or an unmodeled
    # checkout/switch (detach/pathspec/multi-positional), poisons chain_stack
    # depth — a later '@{-N}' must NOT trust it (would risk allowing a commit
    # that actually lands on main).
    check("checkout -b A then bare checkout main then checkout @{-1} then commit → blocked (poisoned)",
          run("git checkout -b A && git checkout main && git checkout @{-1} && git commit -m '[FEAT] y'",
              branch="main", marker=False) == 2)
    check("checkout -b A ; checkout @{-1} then commit (reflog decoy) → blocked (reset+switch poisons)",
          run("git checkout -b A ; git checkout @{-1} && git commit -m '[FEAT] y'",
              branch="main", marker=False, reflog="feature/decoy") == 2)

    # No prior switch in the chain: real reflog is still pristine at hook time,
    # so '@{-1}' resolves reliably straight from it.
    check("bare checkout @{-1} then commit (no prior switch, reflog=feature) → passes",
          run("git checkout @{-1} && git commit -m '[FEAT] y'", branch="feature/x", reflog="feature/w") == 0)
    check("bare checkout @{-1} then commit (no prior switch, reflog=main) → blocked",
          run("git checkout @{-1} && git commit -m '[FEAT] y'", branch="feature/x", reflog="main") == 2)

    # A `-C <path>` on the switch/commit segments must be honored when resolving
    # prev-refs — using the hook's own (unrelated) cwd instead of the segment's
    # real `-C` target would query the wrong repository's branch/reflog and
    # could allow a commit that actually lands on main in the REAL target repo.
    native_repo_a = os.path.abspath(os.path.join("/hostcwd", "/repoA"))
    check("checkout -b tmp then checkout @{-1} via -C /repoA (real target repo honored) → blocked",
          run("git -C /repoA checkout -b tmp && git -C /repoA checkout @{-1} && "
              "git -C /repoA commit -m '[FEAT] y'",
              cwd="/hostcwd",
              branch=lambda cwd: "main" if cwd == native_repo_a else "decoy-live",
              reflog=lambda cwd, n: "main" if cwd == native_repo_a else "decoy-reflog") == 2)
    check("checkout -b tmp then checkout @{-1} via -C /repoA (real target repo honored) → passes when non-main",
          run("git -C /repoA checkout -b tmp && git -C /repoA checkout @{-1} && "
              "git -C /repoA commit -m '[FEAT] y'",
              cwd="/hostcwd",
              branch=lambda cwd: "feature/real" if cwd == native_repo_a else "decoy-live",
              reflog=lambda cwd, n: "decoy-reflog") == 0)

    # A git ALIAS for checkout/switch (inline `-c alias.X=checkout` or a
    # persisted `.gitconfig` alias) is invisible to literal "checkout"/"switch"
    # token matching — it must poison chain-stack reliability just like an
    # unmodeled checkout form, so a later '@{-N}' falls back to live detection
    # instead of resolving against a chain_stack depth the alias may have
    # silently shifted.
    check("git alias for checkout (-c alias.co=checkout) poisons stack → blocked",
          run("git -c alias.co=checkout co feature/foo && git checkout @{-1} && git commit -m '[FEAT] x'",
              branch="main", reflog="feature/bar") == 2)

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
    check("-F valid msg passes", run(f"git commit -F {shlex.quote(fpath)}", branch="feature/x") == 0)
    os.unlink(fpath)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
        fh.write("bad msg\n")
        fpath = fh.name
    check("-F invalid msg blocked", run(f"git commit -F {shlex.quote(fpath)}", branch="feature/x") == 2)
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
