#!/usr/bin/env python3
"""commit-guard — branch and message guards for `git commit`.

Two entry points, one policy:

  * `main()` — the PreToolUse(Bash) hook. Reads a hook payload on stdin and
    statically analyses the Bash command string.
  * `precommit_check()` — a direct CLI check, `--precommit-check --message
    <text> [--cwd <path>]`, for callers that run `git commit` inside a script
    where the hook cannot see it. `scripts/commit-and-push.sh` in the
    `task-review` skill is the bundled caller; without this the hook never fired
    on that path at all, because the Bash tool only ever saw `bash <script>`.

Both apply the same two guards below and share `_current_branch`,
`_marker_present`, and `TYPE_PATTERN`, so policy lives in exactly one place.

The hook path applies two guards:
  1. Branch guard: blocks commits to main/master unless the repo's AGENTS.md
     or CLAUDE.md contains the literal marker <!-- commit-guard: allow-main -->.
     A branch created earlier in the same chain — `git checkout -b/-B/--orphan
     <name>` or `git switch -c/-C/--create/--orphan <name>` — is honored: the
     commit's branch is the newly created one, not the pre-checkout branch the
     live `rev-parse` still reports. This attribution carries across `&&`
     (where the creation is guaranteed to have run), and across `;`/newline
     only when the creation is proven to succeed: it is a literal `git
     checkout -b <name>` / `git switch -c <name>` that runs unconditionally,
     follows nothing but inert segments, commits and earlier proven creations,
     sits in no heredoc, and the branch is creatable in the repo right now
     (`_branch_creatable`) beside those earlier names. Any later segment
     that is neither inert nor a commit ends that proof, and a commit aimed at
     another repo (`-C`, `GIT_DIR=`) is not covered by it. It is dropped across `||`/`|`/`&`,
     an unproven `;`/newline, or a `cd`, so a commit that may actually land on
     main is not mis-attributed to an un-run checkout. A bare switch — `git
     checkout <ref>` / `git switch <ref>` with a single ref, no `--` pathspec
     and no `--detach` — re-attributes the chain to that ref when either the
     target is protected (so `checkout -b X && checkout main && commit` blocks)
     or attribution is already tracked in-chain (so `checkout main && checkout
     feature/x && commit` follows to feature/x rather than sticking at main). A
     bare switch to a feature branch from live detection (no in-chain attribution
     yet) stays untrusted (ambiguous pathspec) and does not unblock; a detached
     checkout (`--detach`) never re-attributes (the commit lands on a detached
     HEAD, not the branch ref). A command substitution, quoted or not, is read
     as a command of its own; a switch or `cd` behind an expansion that may be
     empty, in a case arm or in a function body may or may not run, so it can
     only add a cwd to check or move the chain toward a protected branch.
  2. Type guard: commit message must match ^\\[(TYPE)\\] (with trailing space).
     Skipped for editor-mode commits (no -m/-F), --amend, and --squash flags,
     and for messages carrying shell-expandable command substitution (unquoted
     or double-quoted '$(...)' / backticks) whose real text is statically
     undecidable (fail-open). Single-quoted substitution is literal — git
     receives it verbatim — so it stays type-checked.

Design contract (HOOK PATH ONLY): never-raise, always exit 0 (allow) unless a
guard fires (exit 2). A guard failure prints the reason to stderr and exits 2.
All other exits are 0 (fail-open: parse errors, missing git, non-commit commands
all pass through). The `--precommit-check` entry point is deliberately exempt
from never-raise — see the `__main__` block: a caller that asked for a verdict
must not receive a silent allow when this file itself is broken. Its wrapper
treats any non-zero as "do not commit", so a crash blocks rather than passes.

`precommit_check()` keeps the exit-code contract (0 allow / 2 block) but is
deliberately STRICTER than the hook on the type guard: its message arrives as a
real argv value that the shell has already expanded, so there is no statically
undecidable text and none of the `_has_expandable_subst` / raw-token machinery
applies. Do not "restore" that fail-open branch here — a literal `$(...)` in an
argv message is exactly the message git will receive. The branch guard is
likewise simpler: the caller commits at the moment it invokes this, so live
`rev-parse` is authoritative and no in-chain attribution is needed.
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

# Words that stand before a command without being one: the reserved words a
# compound command puts there (`then git commit`, `do git commit`) and the
# grouping and negation marks.
_SHELL_KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "time", "!", "{", "("}
# A redirect: an optional fd, the operator, then its target when attached.
_REDIRECT = re.compile(r"^\d*(?:<<<|<<-?|<>|<&|>>|>&|>\||&>>|&>|<|>)(.*)$")


# Expansions that may expand to nothing, at the front of a word: `$x`, `$1`,
# `$!`, `$@`, `$*`, `${ … }`, `$( … )` and a backtick substitution. `$$`, `$?`,
# `$#`, `$0`, `${# … }` and `$(( … ))` always expand to something, so they are
# not here.
_EMPTY_PARAM = re.compile(r"^\$(?:[A-Za-z_][A-Za-z0-9_]*|[1-9!@*])")


# A quoted expansion that may expand to no word at all: `"$@"`, `"${a[@]}"`.
_ALL_WORDS = re.compile(r"^(?:\$@|\$\{@[^}]*\}|\$\{[A-Za-z_][A-Za-z0-9_]*\[@\][^}]*\})$")


def _strip_expansions(tok):
    """tok (a word's source text, quotes intact) without the expansions that
    lead it and may be empty: `$!git` is `git` when no job ran, and so is
    `"$x"git`. Returns tok unchanged when none leads it, and when an expansion
    never closes. A quoted empty expansion standing alone is still a word, the
    empty string: then '""' is what remains, except for `"$@"` and
    `"${a[@]}"`, which expand to no word at all."""
    rest, quoted = tok, False
    while rest:
        m = _EMPTY_PARAM.match(rest)
        if m:
            rest = rest[m.end():]
            continue
        if rest.startswith(("$((", "${#")):
            break
        try:
            if rest[0] == '"':
                end = _double_quoted(rest, 1)[1]
                raw = rest[1:end - 1]  # read before unescaping: `"\$x"` is text
                if _strip_expansions(raw):
                    break  # text that is not only expansions: never empty
                quoted = quoted or not _ALL_WORDS.match(raw)
            else:
                end = _expansion_end(rest, 0)
        except (ValueError, RecursionError):
            return tok
        if end is None:
            break
        rest = rest[end:]
    return '""' if quoted and not rest else rest


def _command_start(parts, bare=None, expansions=False, raws=None):
    """Index of the command word in a token list: past the shell keywords,
    env-assigns (`x=$(true)` too) and redirects (`>log git commit`) that may
    lead it, and a function head (`f()`, `function f`). A case pattern never
    reaches here: _split_segments ends a segment at its `)`.

    With expansions and raws (each token's source text, quotes intact), also
    past an unquoted expansion that may be empty (`$()git`, `$x git`), cut
    from the word and its raw in place. Only commit detection asks for it:
    such a word may as well run something else (`x=echo; $x git checkout -b
    f`), so it proves no branch switch.

    bare[k] says token k had no quoting: a quoted `(` or `)` is text. Without
    it every token counts as bare.
    """
    n = len(parts)

    def is_bare(k, word):
        return k < n and parts[k] == word and (bare is None or bare[k])

    i = 0
    while i < n:
        tok = parts[i]
        m = _REDIRECT.match(tok)
        if m:
            i += 1 if m.group(1) else 2  # a bare operator takes the next token
            continue
        if _ENV_ASSIGN.match(tok) and tok.endswith("$") and is_bare(i + 1, "("):
            # `x=$(( … ))` padded by _split_segments: one assignment word
            # (a command substitution reaches here as `$()`, unpadded)
            depth, j = 0, i + 1
            while j < n:
                if is_bare(j, "("):
                    depth += 1
                elif is_bare(j, ")"):
                    depth -= 1
                    if not depth:
                        break
                j += 1
            if j < n:
                i = j + 1
                continue
            break
        if tok in _SHELL_KEYWORDS or _ENV_ASSIGN.match(tok):
            i += 1
            continue
        if is_bare(i, "function") and i + 1 < n:
            i += 4 if is_bare(i + 2, "(") and is_bare(i + 3, ")") else 2
            continue
        if tok != "$" and is_bare(i + 1, "(") and is_bare(i + 2, ")"):
            i += 3  # `f()`
            continue
        if not expansions or raws is None:
            break
        rest = _strip_expansions(raws[i])
        if rest == raws[i]:
            break
        if not rest:
            i += 1
            continue
        try:
            words = _words(rest)[0]
        except (ValueError, RecursionError):
            break
        if len(words) != 1:
            break
        parts[i], raws[i] = words[0], rest  # read again: a redirect (`${x}<<EOF`) or the command
    return i


def _function_nesting(segment):
    """(head, depth, bare_head) for a segment: head says it opens a function
    definition (`f() {`, `function f`), whose body runs when f is called, not
    where it is written; depth is how many braces and parens it opens less
    how many it closes, so a body running over later segments (`f() { a;`
    … `}`) can be followed to its end; bare_head says it is the head alone,
    its body on a later segment."""
    try:
        words, bare, _ = _words(segment)
    except (ValueError, RecursionError):
        return False, 0, False
    n = len(words)

    def is_bare(k, word):
        return k < n and words[k] == word and bare[k]

    depth = -1 if is_bare(0, "}") else 0
    j = 0
    while j < n and bare[j] and words[j] in _SHELL_KEYWORDS:
        depth += words[j] == "{"  # a '(' is counted below with the rest
        j += 1
    k = 0
    if is_bare(j, "function") and j + 1 < n:
        k = 4 if is_bare(j + 2, "(") and is_bare(j + 3, ")") else 2
    elif (is_bare(j + 1, "(") and is_bare(j + 2, ")")
          and re.match(r"^[A-Za-z_][A-Za-z0-9_.:-]*$", words[j]) is not None):
        k = 3
    after = j + k
    while k and after < n and is_bare(after, "{"):
        depth += 1
        after += 1
    rest = [w for w, b in zip(words[:j] + words[j + k:], bare[:j] + bare[j + k:]) if b]
    depth += rest.count("(") - rest.count(")")
    return k > 0, depth, k > 0 and j + k == n


# Words that open or close a compound command around the one inside it.
_COMPOUND_SYNTAX = _SHELL_KEYWORDS | {"}", ")", "esac", "fi", "done"}


def _compound_inert(segment):
    """True if the segment, inside a function definition or a case, runs
    nothing but an _is_inert command once the compound's own syntax is set
    aside: a function head, a brace or paren, a reserved word. Whatever else
    it runs may move HEAD or the directory, now or when the function is
    called."""
    try:
        words, bare, _ = _words(segment)
    except (ValueError, RecursionError):
        return False
    n = len(words)

    def is_bare(k, word):
        return k < n and bare[k] and words[k] == word

    i = 0
    while i < n:
        if bare[i] and words[i] in _COMPOUND_SYNTAX:
            i += 1
        elif is_bare(i + 1, "(") and is_bare(i + 2, ")"):
            i += 3  # `f ( )`
        elif is_bare(i, "function") and i + 1 < n:
            i += 4 if is_bare(i + 2, "(") and is_bare(i + 3, ")") else 2
        else:
            break
    j = n
    while j > i and bare[j - 1] and words[j - 1] in _COMPOUND_SYNTAX:
        j -= 1
    return _is_inert(shlex.join(words[i:j]))


def _ansi_c(s, i):
    """Decode the $'…' string whose body starts at i. Returns (text, index past
    the closing quote); ValueError when it never closes."""
    simple = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f",
              "v": "\v", "e": "\x1b", "E": "\x1b", "\\": "\\", "'": "'", '"': '"', "?": "?"}
    out = []
    while i < len(s):
        ch = s[i]
        if ch == "'":
            return "".join(out), i + 1
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append(simple.get(nxt, "\\" + nxt))  # \x, \u, octal: kept as written
            i += 2
            continue
        out.append(ch)
        i += 1
    raise ValueError("unclosed $'")


def _skip_group(s, i, opener, closer):
    """Index just past the `closer` matching an `opener` that ends before i,
    over nested quotes, escapes and backticks. ValueError when it never closes."""
    depth = 1
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if s.startswith("$$", i):
            i += 2
            continue
        if s.startswith("$'", i):
            i = _ansi_c(s, i + 2)[1]
            continue
        if ch == "'":
            j = s.find("'", i + 1)
            if j == -1:
                raise ValueError("unclosed '")
            i = j + 1
            continue
        if ch == '"':
            i = _double_quoted(s, i + 1)[1]
            continue
        if ch == "`":
            i = _skip_backtick(s, i + 1)
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if not depth:
                return i + 1
        i += 1
    raise ValueError("unclosed " + opener)


def _skip_backtick(s, i):
    """Index just past the backtick closing one that ends before i."""
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "`":
            return i + 1
        i += 1
    raise ValueError("unclosed `")


def _expansion_end(s, i):
    """Index past a `$(`/`${`/backtick expansion starting at i, else None."""
    if s[i] == "`":
        return _skip_backtick(s, i + 1)
    if s[i] == "$" and s[i + 1:i + 2] in ("(", "{"):
        opener = s[i + 1]
        return _skip_group(s, i + 2, opener, ")" if opener == "(" else "}")
    return None


def _double_quoted(s, i):
    """Read a "…" body starting at i. Returns (text, index past the closing
    quote); an expansion inside is kept as written, its own quotes included."""
    out = []
    while i < len(s):
        ch = s[i]
        if ch == '"':
            return "".join(out), i + 1
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in '$`"\\':
                out.append(nxt)
            elif nxt != "\n":
                out.append(ch + nxt)
            i += 2
            continue
        end = _expansion_end(s, i)
        if end is not None:
            out.append(s[i:end])
            i = end
            continue
        out.append(ch)
        i += 1
    raise ValueError('unclosed "')


def _words(s):
    """Split a shell fragment into words as bash reads them, before expansion:
    quotes removed, $'…' decoded, a `$( … )`, `${ … }` or backtick kept whole
    with what is quoted inside it. Returns (words, bare), bare[k] saying word k
    had no quote or escape, and raws, each word's source text. ValueError on
    an unclosed quote or expansion.

    shlex cannot do this: it fails on `$'a\\'b'` and on a quote nested in
    "$( … )", and a failed split hid the commit in that segment.
    """
    words, bare, raws = [], [], []
    cur, cur_bare, begin = None, True, 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch in " \t\n":
            if cur is not None:
                words.append(cur)
                bare.append(cur_bare)
                raws.append(s[begin:i])
                cur, cur_bare = None, True
            i += 1
            continue
        if cur is None:
            cur, begin = "", i
        if ch == "\\":
            if i + 1 >= n:
                raise ValueError("no escaped character")
            if s[i + 1] != "\n":
                cur += s[i + 1]
            cur_bare = False
            i += 2
        elif ch == "'":
            j = s.find("'", i + 1)
            if j == -1:
                raise ValueError("unclosed '")
            cur += s[i + 1:j]
            cur_bare = False
            i = j + 1
        elif ch == '"':
            text, i = _double_quoted(s, i + 1)
            cur += text
            cur_bare = False
        elif s.startswith("$$", i):
            cur += "$$"  # the shell's pid: no $'…' string after it
            i += 2
        elif s.startswith("$'", i):
            text, i = _ansi_c(s, i + 2)
            cur += text
            cur_bare = False
        else:
            end = _expansion_end(s, i)
            if end is None:
                end = i + 1
            cur += s[i:end]
            i = end
    if cur is not None:
        words.append(cur)
        bare.append(cur_bare)
        raws.append(s[begin:])
    return words, bare, raws


def _tokens(s, expansions=False):
    """Tokenize a shell fragment from its command word on (_command_start;
    expansions as there).

    The stripping applies only to the prefix before the command name: once
    we've seen the command, remaining tokens (e.g. -m 'foo=bar', `echo then`)
    are left intact.

    _words cannot read a heredoc inside "$( … )" (an apostrophe in the body
    of the usual `-m "$(cat <<'EOF' … )"` message), and shlex can: when _words
    fails, shlex reads it. When both fail → return [] so the segment is treated
    as non-commit (fail-open), preserving the documented never-block-on-parse-
    error contract.
    """
    s = _LEAD_NOISE.sub("", s or "")
    try:
        parts, bare, raws = _words(s)
    except (ValueError, RecursionError):
        try:
            parts = shlex.split(s)
        except ValueError:
            return []  # unparseable segment → fail-open (not a commit)
        bare, raws = None, _shlex_raws(s, len(parts))
    return parts[_command_start(parts, bare, expansions, raws):]


def _shlex_raws(s, count):
    """Each shlex word's source text, split where _scan finds an unquoted
    blank, when that agrees with shlex on the word count; else None. A
    posix=False split cannot be used: it reads the apostrophe of a heredoc
    body inside "$( … )" as a quote and miscounts."""
    cls, balanced = _scan(s)
    if not balanced:
        return None
    raws, begin = [], None
    for k, ch in enumerate(s):
        if ch in " \t\n" and cls[k] == _CODE:
            if begin is not None:
                raws.append(s[begin:k])
                begin = None
        elif begin is None:
            begin = k
    if begin is not None:
        raws.append(s[begin:])
    return raws if len(raws) == count else None


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
    # posix=False keeps the quotes, so each token is its own source text and
    # the expansions _tokens cuts are cut here too: the two lists stay aligned
    raws = list(parts)
    return raws[_command_start(parts, expansions=True, raws=raws):]


# Characters after which a '#' opens a word, and so a comment: whitespace and
# the shell metacharacters. Anywhere else ('a#b', '$#', '${#v}') it is text.
_COMMENT_PRECEDERS = " \t\n;&|()<>"

# What _scan says each character of a command is.
_CODE = "c"      # unquoted command text, separators included
_ESC = "e"       # a backslash and the character it escapes
_SQ = "s"        # single-quoted, the quotes included
_DQ = "d"        # double-quoted: the quotes, and a "$( … )" inside them, included
_COMMENT = "#"   # a comment, up to but not including its newline
_HEREDOC = "h"   # a heredoc body and its delimiter line
_PATTERN = "p"   # a case pattern's '(', '|' or ')'
_GLOB = "g"      # an extglob group's '(', '|' or ')' inside a case pattern: text

# A reserved word ending the text before a word: the word is in command position
# when this one is.
_RESERVED_BEFORE = re.compile(r"(?:^|(?<=[\s;&|(]))(if|elif|while|until|then|do|else|time|!|\{)$")
_JOIN = "j"      # a line continuation: the backslash and its newline


# What may follow an `esac` that closes its case.
_ESAC_AFTER = ("", " ", "\t", "\n", ";", "&", "|", ")")


def _tick_text(raw, quoted):
    """A backtick body as bash runs it: a backslash before '$', '`' or '\\'
    (and, inside double quotes, '"') is dropped, so a nested `\\`…\\`` is a
    substitution again."""
    return re.sub(r'\\([$`\\"])' if quoted else r'\\([$`\\])', r"\1", raw)


def _scan(command):
    """(classes, balanced) of _scan_full."""
    cls, balanced, _, _ = _scan_full(command)
    return cls, balanced


def _scan_full(command):
    """Say what each character of a shell command is. Returns (classes,
    balanced, subs, arm): one of the constants above per character; False
    when a quote or a "$( … )" never closes; each outermost command
    substitution as (body_start, body_end, quoted, anchor, text), its body
    being command[body_start:body_end], or text when that is not None (a
    backtick body, unescaped); anchor is the index of the '<<' whose heredoc
    body holds it, else None; and per character, where it sits in a
    case: "arm" in an arm, "case" elsewhere between `case` and `esac`, else
    False.

    The one place that tracks quoting; _strip_comments, _split_segments,
    _outside_quotes and _has_expandable_subst all read its answer, so they
    cannot disagree on an escape or on where a quote ends.

    A `$(` or a backtick inside double quotes opens a command of its own,
    with its own quotes, comments and heredocs; all of it stays part of the
    string. So does one in a heredoc body under an unquoted delimiter, which
    stays part of the body. An unquoted `$(` is left as command text. A `<<` is a heredoc only when its
    delimiter line follows: `$((1<<2))` has none, and swallowing the lines
    after it would hide them.
    """
    n = len(command)
    cls = [_CODE] * n
    balanced = True
    subs = []
    arm: list = [False] * n

    def heredoc_word(i):
        """The (delimiter, strip_tabs, quoted) a '<<' ending at i announces,
        or None. quoted: any part of the delimiter is quoted, which leaves the
        body literal text."""
        strip = command[i:i + 1] == "-"
        if strip:
            i += 1
        while i < n and command[i] in " \t":
            i += 1
        word = []
        quote = None
        quoted = False
        while i < n:
            ch = command[i]
            if quote:
                if ch == quote:
                    quote = None
                else:
                    word.append(ch)
            elif ch in "'\"":
                quote = ch
                quoted = True
            elif ch == "\\" and i + 1 < n:
                i += 1
                word.append(command[i])
                quoted = True
            elif ch in " \t\n;&|<>()":
                break
            else:
                word.append(ch)
            i += 1
        if quote or not word:
            return None
        return "".join(word), strip, quoted

    def tick_end(i, end):
        """The index of the backtick closing one opened just before i, or
        None when none does before end."""
        while i < end and command[i] != "`":
            i += 2 if command[i] == "\\" else 1
        return i if i < end else None

    def body_substs(i, end, anchor):
        """Note each substitution in a heredoc body, command[i:end], as an
        outermost one: under an unquoted delimiter bash runs them. One that
        does not close inside the body is no command, and ends the reading."""
        nonlocal balanced
        while i < end:
            ch = command[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                close_at = tick_end(i + 1, end)
                if close_at is None:
                    return
                subs.append((i + 1, close_at, True, anchor,
                             _tick_text(command[i + 1:close_at], False)))
                i = close_at + 1
                continue
            if ch == "$" and command[i + 1:i + 2] == "(":
                # code() reads the substitution's own quotes and parens; what
                # it marks and whether it closes stay the body's business
                kept, was = cls[i:], balanced
                after = code(i + 2, True)
                cls[i:], balanced = kept, was
                if after > end:
                    return
                subs.append((i + 2, after - 1, True, anchor, None))
                i = after
                continue
            i += 1

    def bodies(i, pending, record=False):
        """Mark the heredoc bodies starting at i; returns the index after them.
        record: note the substitutions in an unquoted-delimiter body."""
        for delim, strip, quoted, anchor in pending:
            j = i
            while True:
                if j >= n:
                    return i  # no delimiter line: not a heredoc after all
                end = command.find("\n", j)
                if end == -1:
                    end = n
                line = command[j:end]
                if (line.lstrip("\t") if strip else line) == delim:
                    break
                j = end + 1
            if record and not quoted:
                body_substs(i, j, anchor)
            j = min(end + 1, n)
            cls[i:j] = [_HEREDOC] * (j - i)
            i = j
        return i

    def double(i, record=False):
        """From just past an opening '"' to just past the one that closes it.
        record: note each "$( … )" in it as an outermost substitution."""
        nonlocal balanced
        while i < n:
            ch = command[i]
            if ch == "\\" and i + 1 < n:
                cls[i] = cls[i + 1] = _ESC
                i += 2
                continue
            cls[i] = _DQ
            if ch == '"':
                return i + 1
            if ch == "`":
                close_at = tick_end(i + 1, n)
                if close_at is None:
                    break
                cls[i:close_at + 1] = [_DQ] * (close_at + 1 - i)
                if record and balanced:
                    subs.append((i + 1, close_at, True, None,
                                 _tick_text(command[i + 1:close_at], True)))
                i = close_at + 1
                continue
            if ch == "$" and command[i + 1:i + 2] == "(":
                cls[i + 1] = _DQ
                body = i + 2
                i = code(body, True)
                if record and balanced:
                    subs.append((body, i - 1, True, None, None))
                continue
            i += 1
        balanced = False
        return i

    def code(i, nested):
        """Command text from i: to the end, or (nested, inside a double-quoted
        `$(`) to just past the ')' that closes it."""
        nonlocal balanced
        start = i
        # What is open at this level, innermost last: 'cmd' (a subshell),
        # 'subst' (`$(`, `<(`, `>(`), 'tick', 'arith' (`((`), 'array' (`=(`),
        # 'param' (`${`), 'extglob' (`@(` in a pattern), and from `case` to
        # `esac`: 'case_subj' / 'case_word' (the subject, then `in`),
        # 'case_start' (a pattern list's start), 'case_pat' (in a pattern)
        # and 'case_body' (the arm after its ')'). `$((` opens 'subst' then
        # 'arith'.
        opened = []
        pending = []  # (delimiter, strip_tabs, quoted, len(opened) where announced, '<<' index)
        word_start = True  # the next character would open a word
        # the outermost unquoted command substitution open at the top level:
        # (body_start, len(opened) once it opened)
        rec = None

        def open_subst(kind, body):
            nonlocal rec
            opened.append(kind)
            if not nested and rec is None:
                rec = (body, len(opened))

        def close():
            """Close the innermost construct and return what it was. A
            substitution takes the heredocs announced inside it along: bash
            reads those from its own text, so none of them reaches the lines
            after it."""
            nonlocal pending, rec
            kind = opened.pop()
            if kind in ("subst", "tick"):
                pending = [p for p in pending if p[3] <= len(opened)]
            if rec is not None and len(opened) < rec[1]:
                subs.append((rec[0], i, False, None,
                             _tick_text(command[rec[0]:i], False) if kind == "tick" else None))
                rec = None
            return kind

        def inner():
            """What is open since the innermost substitution: one starts a
            fresh command, so an enclosing (( … )) or ${ … } does not reach in."""
            k = len(opened)
            while k and opened[k - 1] not in ("subst", "tick"):
                k -= 1
            return opened[k:]

        def lone_dollar(i):
            """Whether the '$' run just before i leaves one '$' for i: '$$' is
            the shell's pid, so only an odd run does."""
            k = i
            while k > 0 and command[k - 1] == "$" and cls[k - 1] == _CODE:
                k -= 1
            return (i - k) % 2 == 1

        pattern_ends = set()  # the ')' of each case pattern: an arm starts there

        def at_command(i):
            """Whether the word at i is in command position: first at this
            level, or after a separator, an open paren, a case pattern or a
            reserved word that is itself in command position (`echo do case`
            is three words of one command)."""
            while True:
                k = i - 1
                while k >= start and command[k] in " \t":
                    k -= 1
                if k < start or k in pattern_ends:
                    return True
                if (command[k] in ";&|(\n" and cls[k] == _CODE
                        and not (command[k] == "|" and command[k - 1:k] == ">")):
                    return True  # an unescaped separator, not the `|` of `>|`
                m = _RESERVED_BEFORE.search(command, start, k + 1)
                if m is None:
                    return False
                i = m.start(1)  # a loop, not recursion: `if if if …` has no depth limit

        def arith_closes(j):
            """Whether the '((' ending just before j closes as '))'. bash reads
            one that does not, such as `((a) )`, as two subshells."""
            depth = 0
            while j < n:
                c = command[j]
                if c == "\\":
                    j += 1  # an escaped paren counts for neither reading
                elif c in "'\"":
                    # bash skips quoted text when it matches the parens
                    j = command.find(c, j + 1)
                    if j == -1:
                        return False
                elif c == "(":
                    depth += 1
                elif c == ")":
                    if depth == 0:
                        return command[j + 1:j + 2] == ")"
                    depth -= 1
                j += 1
            return False

        while i < n:
            ch = command[i]
            if not nested:
                arm[i] = ("arm" if "case_body" in opened
                          else "case" if any(k.startswith("case") for k in opened) else False)
            top = opened[-1] if opened else None
            if (top in ("case_subj", "case_start") and ch not in " \t\n"
                    and not (ch == "#" and word_start)):
                # bash reads `esac` as reserved only at a pattern list's start:
                # not as the subject, nor after a pattern's '(' or '|'
                if (top == "case_start" and word_start and command.startswith("esac", i)
                        and command[i + 4:i + 5] in _ESAC_AFTER):
                    opened.pop()
                    i += 4
                    word_start = False
                    continue
                opened[-1] = "case_word" if top == "case_subj" else "case_pat"
            elif (top == "case_word" and word_start and command.startswith("in", i)
                    and command[i + 2:i + 3] in ("", " ", "\t", "\n")):
                opened[-1] = "case_start"
                i += 2
                word_start = False
                continue
            # in arithmetic and in ${ … }, '#' and '<<' are operators
            here = inner()
            plain = "arith" not in here and "param" not in here
            if ch == "\\" and i + 1 < n:
                if command[i + 1] == "\n":
                    # joins two lines and leaves the word boundary where it was
                    cls[i] = cls[i + 1] = _JOIN
                else:
                    cls[i] = cls[i + 1] = _ESC  # `a\ #b` is one word
                    word_start = False
                i += 2
                continue
            if ch == "#" and word_start and plain:
                # bash finds the closing backtick before it reads a comment
                while i < n and command[i] != "\n" and not (
                        command[i] == "`" and "tick" in opened):
                    cls[i] = _COMMENT
                    i += 1
                continue
            if ch == "'":
                # in $'…' a backslash escapes; in '…' nothing does
                ansi = lone_dollar(i)
                j = i + 1
                while j < n and command[j] != "'":
                    j += 2 if ansi and command[j] == "\\" else 1
                if j >= n:
                    balanced = False
                j = min(j + 1, n)
                cls[i:j] = [_SQ] * (j - i)
                i = j
                word_start = False
                continue
            if ch == '"':
                cls[i] = _DQ
                i = double(i + 1, not nested and rec is None)
                word_start = False
                continue
            if ch == "\n":
                i += 1
                if pending:
                    i = bodies(i, [p[:3] + p[4:] for p in pending], not nested and rec is None)
                    pending = []
                word_start = True
                continue
            if ch == "`":
                # a closing backtick ends no word: `` `true`# `` is one word
                word_start = not (opened and opened[-1] == "tick")
                if word_start:
                    open_subst("tick", i + 1)
                else:
                    close()
                i += 1
                continue
            if ch == "{" and lone_dollar(i):
                opened.append("param")
                i += 1
                word_start = False  # `${#v}` is a length, not a comment
                continue
            if ch == "}" and opened and opened[-1] == "param":
                opened.pop()
                i += 1
                word_start = False
                continue
            top = opened[-1] if opened else None
            if (top in ("case_pat", "extglob") and ch == "(" and i
                    and command[i - 1] in "?*+@!" and cls[i - 1] == _CODE):
                # an extglob group, `@(a|b)`: its '|' and ')' end no pattern
                opened.append("extglob")
                cls[i] = _GLOB
                i += 1
                word_start = False
                continue
            if top == "extglob" and ch in "|)":
                if ch == ")":
                    opened.pop()
                cls[i] = _GLOB
                i += 1
                word_start = False
                continue
            case = opened[-1] if opened and opened[-1].startswith("case") else None
            if case == "case_pat" and (ch in "|)" or ch == "(" and command[i - 1:i] not in "$<>"):
                # a pattern's own punctuation: no subshell, pipe or close
                cls[i] = _PATTERN
                if ch == ")":
                    opened[-1] = "case_body"
                    pattern_ends.add(i)
                i += 1
                word_start = True
                continue
            if case == "case_body" and ch == ";" and command[i + 1:i + 2] in (";", "&"):
                # `;;`, `;&` or `;;&`: the next pattern list follows
                opened[-1] = "case_start"
                i += 3 if command[i + 1:i + 3] == ";&" else 2
                word_start = True
                continue
            if ch == "(" and not (opened and opened[-1] == "param"
                                  and command[i - 1:i] != "$"):
                # in ${ … } only `$(` opens anything: `${v//(/}` is a pattern
                before = command[i - 1:i]
                if command[i + 1:i + 2] == "(" and arith_closes(i + 2):
                    opened += ["subst" if before == "$" else "arith", "arith"]
                    i += 2
                else:
                    if before in ("$", "<", ">"):
                        open_subst("subst", i + 1)
                    else:
                        opened.append("array" if before == "=" else "cmd")
                    i += 1
                word_start = True
                continue
            if ch == ")":
                if opened and opened[-1] not in ("param", "tick"):
                    # past a subshell or a (( … )) a '#' opens a comment; past
                    # a substitution or an array it is still in the word
                    word_start = close() in ("cmd", "arith")
                    i += 1
                    continue
                if nested and not opened:
                    cls[start:i + 1] = [_DQ] * (i + 1 - start)
                    return i + 1
                i += 1
                word_start = True
                continue
            if (command[i:i + 2] == "<<" and command[i + 2:i + 3] != "<"
                    and command[i - 1:i] != "<" and plain and "array" not in here):
                announced = heredoc_word(i + 2)
                i += 2
                word_start = True
                if announced:
                    pending.append(announced + (len(opened), i - 2))
                    # the delimiter is a word even when it opens with '#'
                    if command[i:i + 1] == "-":
                        i += 1
                    while i < n and command[i] in " \t":
                        i += 1
                    word_start = False
                continue
            if word_start and plain and command[i:i + 4] in ("case", "esac"):
                after = command[i + 4:i + 5]
                if command[i] == "c" and after in (" ", "\t") and at_command(i):
                    opened.append("case_subj")  # the subject, then `in`
                    i += 4
                    word_start = False
                    continue
                if command[i] == "e" and after in _ESAC_AFTER and case == "case_body" and at_command(i):
                    opened.pop()
            word_start = ch in _COMMENT_PRECEDERS
            i += 1
        if nested:
            balanced = False
            cls[start:] = [_DQ] * (n - start)
        return i

    code(0, False)
    return cls, balanced, subs, arm


def _strip_comments(command):
    """The command with every shell comment removed: an unquoted, unescaped '#'
    that opens a word, through the end of its own line. The newline stays, so
    the next line is still a separate command. Quote characters inside a
    comment are dropped with it and cannot open a span over later lines.
    """
    cls, _ = _scan(command)
    return "".join(ch for ch, kind in zip(command, cls) if kind != _COMMENT)


def _outside_quotes(command):
    """The unquoted, unescaped command text alone: no quoted span, comment or
    heredoc body."""
    cls, _ = _scan(command)
    return "".join(ch for ch, kind in zip(command, cls) if kind == _CODE)


def _has_expandable_subst(raw_arg):
    """True if raw_arg (a message token with its original quotes intact) contains
    a shell-EXPANDABLE command substitution — a '$(' or backtick that is neither
    inside single quotes nor escaped. Those two are literal (git receives them
    verbatim), so the message is decidable and must be type-checked → False.
    """
    cls, _ = _scan(raw_arg)
    for i, ch in enumerate(raw_arg):
        if cls[i] in (_SQ, _ESC):
            continue
        if ch == "`" or (ch == "$" and raw_arg[i + 1:i + 2] == "("):
            return True
    return False


def _operator_at(command, cls, i):
    """The separator that starts at unquoted index i and its width, else
    (None, 0). An '&' or '|' that belongs to a redirect ('2>&1', '&>log',
    '>|f') is text."""
    ch = command[i]
    if ch in "\n;":
        return ";", 1  # a newline separates commands like ';'
    nxt = command[i + 1] if i + 1 < len(command) and cls[i + 1] == _CODE else ""
    prev = command[i - 1] if i > 0 and cls[i - 1] == _CODE else ""
    if ch == "&":
        if nxt == "&":
            return "&&", 2
        if prev in ("<", ">") or nxt == ">":
            return None, 0
        return "&", 1
    if ch == "|":
        if nxt == "|":
            return "||", 2
        if prev == ">":
            return None, 0
        return "|", 1
    return None, 0


def _split_segments(command):
    """(segments, operators) of _split_full."""
    segments, operators, _, _, _ = _split_full(command)
    return segments, operators


def _split_full(command):
    """Quote-aware split on shell segment separators: ; && || | & and newline.

    _scan says which characters are command text; only those can separate.
    Comments, heredoc bodies and line continuations are left out of the
    segments, quoted spans are kept verbatim (downstream _tokens() unquotes
    them), and an unquoted paren is set apart so it never fuses with a word.
    An unquoted command substitution is a command of its own: its body is cut
    from the segment, leaving `$()` or two backticks in its place, so nothing
    inside it can split the segment.

    Returns (segments, operators, arms, bodies, cases): a list of stripped segment
    strings (individual segments may be empty); a parallel list of the
    separator operator that PRECEDES each segment (operators[0] is None; the
    rest are one of '&&' '||' '|' ';' '&', or ')' after a case pattern); per
    segment, whether it sits in a case arm; per segment, the bodies of
    the command substitutions in it, quoted or not, which run before it;
    and per segment, (in_case, open_after): whether any of it is inside a
    case, and whether a case is still open where it ends.
    Callers use the operator to decide whether state from an earlier segment
    (e.g. an in-chain branch creation) may carry into a later one — only '&&'
    guarantees the predecessor ran successfully; main() proves it separately
    for a creation followed by ';'.
    """
    cls, balanced, subs, arm = _scan_full(command)
    if not balanced:
        # an unclosed quote: split on every separator, attribute nothing
        segs = re.split(r"&&|\|\||[;|\n&]", _strip_comments(command))
        return (segs, [None] * len(segs), [False] * len(segs), [[] for _ in segs],
                [(False, False)] * len(segs))

    starts = {}
    anchored = {}  # '<<' index → the heredoc body substitutions it announced
    for body, end, quoted, anchor, text in subs:
        if anchor is None:
            starts[body] = (end, quoted, text)
        else:
            # run as the command holding the '<<' runs, not after the body
            anchored.setdefault(anchor, []).append(command[body:end] if text is None else text)
    # the parens of an unquoted `$( … )` stay joined to the word around them
    joined = {k for body, (end, quoted, _) in starts.items() if not quoted for k in (body - 1, end)}
    segments = []
    operators: list = [None]  # operator preceding each segment; first has none
    arms, bodies, cases = [], [], []
    current, in_arm, found = [], False, []
    in_case, case_now = False, False

    def end_segment():
        nonlocal current, in_arm, found, in_case
        segments.append("".join(current).strip())
        arms.append(in_arm)
        bodies.append(found)
        cases.append((in_case, bool(case_now)))
        current, in_arm, found, in_case = [], False, [], False

    i = 0
    while i < len(command):
        if i in anchored:
            found += anchored.pop(i)
        if i in starts:
            end, quoted, text = starts[i]
            found.append(command[i:end] if text is None else text)
            if not quoted and end > i:
                i = end  # the body is read on its own
                continue
        ch, kind = command[i], cls[i]
        if kind in (_COMMENT, _HEREDOC, _JOIN):
            i += 1
            continue
        in_arm = in_arm or arm[i] == "arm"
        case_now = arm[i]
        in_case = in_case or bool(case_now)
        if kind == _PATTERN:
            if ch == ")":
                # the arm after a case pattern runs only when it matches
                end_segment()
                operators.append(")")
            i += 1
            continue
        op, width = _operator_at(command, cls, i) if kind == _CODE else (None, 0)
        if op is None:
            pad = kind == _CODE and ch in "()" and i not in joined
            current.append(f" {ch} " if pad else ch)
            i += 1
            continue
        i += width
        if op == ";" and not "".join(current).strip() and len(operators) > 1:
            # Nothing since the last operator: this ';' is the newline after
            # a line-end operator (`a &&` + newline, with or without a space
            # or comment between) or an empty line, and separates nothing.
            continue
        end_segment()
        operators.append(op)
    end_segment()
    return segments, operators, arms, bodies, cases


def _is_git_commit(segment):
    """True if this shell segment is a git commit invocation.

    Handles wrapper words like 'command' (POSIX shell built-in that just
    executes the named command) preceding 'git'.
    """
    toks = _tokens(segment, expansions=True)
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
    toks = _tokens(segment, expansions=True)
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


def _new_branch_created(segment, expansions=False, flag=False):
    """If this segment creates+switches to a new branch, return its name, else None.

    Recognizes `git checkout -b/-B <name>` and `git switch -c/-C <name>`.
    A bare `git checkout <name>` (switch to existing) is intentionally NOT
    matched: whether <name> is a branch, path, or commit is statically
    ambiguous, so we do not let it override the live branch detection.
    expansions: read past a leading expansion that may be empty (_tokens).
    flag: return (name, the create flag) instead.
    """
    toks = _tokens(segment, expansions)
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
            return (toks[i + 1], toks[i]) if flag else toks[i + 1]
        i += 1
    return None


# git subcommands that cannot create, delete or rename a branch ref nor move
# HEAD to another branch. Deliberately short: anything absent is treated as
# able to do either.
_REF_NEUTRAL_SUBCOMMANDS = {"add", "commit", "diff", "log", "mv", "rm", "show", "status"}

# Commands that cannot touch a repository or the working directory. Anything
# else running before an in-chain creation (a script, `bash -c`, `make`,
# `pushd`, a bare `cd`) may have taken the branch name or moved to another
# repo, so the hook-time creatable check no longer describes what will run.
# The same default covers a creation that may never run: the `if`, `{` or
# `f() {` that opens a compound command around it is not inert either.
_INERT_COMMANDS = {":", "[", "echo", "ls", "printf", "pwd", "set", "test", "true"}

# The only creation spelling whose success the creatable check can vouch for:
# a literal name, no wrapper, env assignment, git-level option (`-C <path>`,
# `GIT_DIR=`: another repo), start point, quoting or expansion (`"$BRANCH"`:
# another name at runtime), and neither `--orphan` nor a force flag, which
# fail or succeed on conditions that check does not read.
_PROVABLE_CREATION_RE = re.compile(
    r"^git\s+(?:checkout\s+-b|switch\s+(?:-c|--create))\s+([A-Za-z0-9][A-Za-z0-9._/-]*)$"
)


def _runs_unconditionally(idx, segments, operators):
    """True if segment idx runs whatever came before it: it opens the command or
    follows ';'/newline. An operator left at the end of a line (`make lint ||`
    + newline) stays the next line's operator (_split_segments drops the
    newline's ';'); the walk back covers an empty segment that still holds one.
    """
    j = idx
    while True:
        if operators[j] not in (None, ";"):
            return False
        if j == 0 or segments[j - 1].strip():
            return True
        j -= 1


def _git_subcommand_at(toks, i):
    """Index of the git subcommand, given the index just past the 'git' token."""
    while i < len(toks):
        tok = toks[i]
        if tok in GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    return i


def _is_inert(segment):
    """True only if the segment provably leaves branch refs, HEAD and the
    working directory alone: empty, plain variable assignments, a command in
    _INERT_COMMANDS, or `git` with a subcommand in _REF_NEUTRAL_SUBCOMMANDS.
    A command or process substitution, a subshell, a `GIT_*` assignment or an
    unparseable segment (a trailing line continuation among them) never is.
    """
    raw = segment.strip()
    if not raw:
        return True
    if "`" in raw or "(" in raw:
        return False
    try:
        parts = shlex.split(raw)
    except ValueError:
        return False
    i = 0
    while i < len(parts) and _ENV_ASSIGN.match(parts[i]):
        if parts[i].startswith("GIT_"):
            return False
        i += 1
    rest = parts[i:]
    if not rest:
        return True
    if rest[0] in _INERT_COMMANDS:
        return True
    if rest[0] != "git":
        return False
    sub = _git_subcommand_at(rest, 1)
    return sub < len(rest) and rest[sub] in _REF_NEUTRAL_SUBCOMMANDS


def _redirects_git(segment):
    """True if the segment aims its git call at another repository: a `GIT_*`
    assignment in front of it, or any git-level option (`-C <path>`,
    `--git-dir`, `--work-tree`) before the subcommand. An unparseable segment
    counts as redirecting.
    """
    text = _LEAD_NOISE.sub("", segment)
    try:
        parts, bare, raws = _words(text)
    except (ValueError, RecursionError):
        try:
            parts, bare, raws = shlex.split(text), None, None
        except ValueError:
            return True
    # the same prefix _is_git_commit reads past, or a commit it sees behind
    # `{`, `>log` or `$x` would go unexamined here
    i = _command_start(parts, bare, expansions=True, raws=raws)
    if any(_ENV_ASSIGN.match(tok) and tok.startswith("GIT_") for tok in parts[:i]):
        return True
    while i < len(parts) and parts[i] in _GIT_WRAPPERS:
        i += 1
    if i >= len(parts) or os.path.basename(parts[i]) != "git":
        return False
    return _git_subcommand_at(parts, i + 1) != i + 1


def _is_provable_creation(segment, name):
    """True if the segment is exactly `git checkout -b <name>` or `git switch
    -c|--create <name>` — see _PROVABLE_CREATION_RE."""
    m = _PROVABLE_CREATION_RE.match(segment.strip())
    return bool(m) and m.group(1) == name


# Files and directories a git dir holds while a merge, cherry-pick, revert,
# rebase or am is under way; `git switch -c` refuses to run during any of them.
_IN_PROGRESS_MARKERS = (
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply",
)


def _names_collide(a, b):
    """True if branches a and b cannot both exist: equal, or one sits above the
    other (`feature` and `feature/x`). Compared case-insensitively, as loose
    refs are on a case-folding filesystem."""
    a = a.casefold()
    b = b.casefold()
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _branch_creatable(cwd, name, _override=None):
    """True only when creating and switching to branch <name> in cwd is proven
    able to succeed: the name is a valid branch name, no existing branch equals
    it, sits above it or sits below it (`feature` blocks `feature/x` and the
    reverse, see _names_collide), no merge/rebase/cherry-pick/revert is in
    progress, and the index holds no unmerged entry. Any git failure (not a
    repo, timeout, missing git) answers False.

    _override may be a bool, or a callable(cwd, name) → bool, for tests.
    """
    if _override is not None:
        return _override(cwd, name) if callable(_override) else _override

    def git(*args):
        out = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=3,
        )
        return out.stdout if out.returncode == 0 else None

    try:
        # a name git rewrites ('@{-1}' → the previous branch) is not a literal
        fmt = git("check-ref-format", "--branch", name)
        # the full name: a short one comes back as 'heads/<name>' beside a same-named tag
        refs = git("for-each-ref", "--format=%(refname)", "refs/heads/")
        git_dir = git("rev-parse", "--absolute-git-dir")
        unmerged = git("ls-files", "--unmerged")
    except Exception:
        return False
    if fmt is None or fmt.strip() != name or refs is None or not git_dir or unmerged is None:
        return False
    if unmerged.strip():
        return False
    if any(os.path.exists(os.path.join(git_dir.strip(), m)) for m in _IN_PROGRESS_MARKERS):
        return False
    return not any(
        _names_collide(name, ref.strip()[len("refs/heads/"):]) for ref in refs.splitlines()
    )


def _bare_switch_target(segment, expansions=False):
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

    expansions: read past a leading expansion that may be empty (_tokens).
    """
    toks = _tokens(segment, expansions)
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


def _is_unmodeled_git_segment(segment, expansions=False):
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

    expansions: read past a leading expansion that may be empty (_tokens).
    """
    toks = _tokens(segment, expansions)
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
    toks = _tokens(segment, expansions=True)
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


# A brace expansion, `{a,b}` or `{a..b}`: bash rewrites the word before git
# reads it (`{main,}` is `main`).
_BRACE_EXPANSION = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")

# git subcommands that cannot move HEAD: one run inside a substitution leaves
# the chain's branch where it was.
_HEAD_STILL_SUBCOMMANDS = {
    "add", "blame", "cat-file", "commit", "config", "describe", "diff", "for-each-ref",
    "grep", "log", "ls-files", "merge-base", "mv", "name-rev", "remote", "rev-list",
    "rev-parse", "rm", "show", "show-ref", "status",
}


def _has_expansion(word):
    """True if word (unquoted text) holds an expansion: its value is known
    only at runtime, or is not the text written."""
    return "$" in word or "`" in word or _BRACE_EXPANSION.search(word) is not None


# Commands that run shell code in this shell or a child of it: what that code
# does to HEAD is not read, so it may move it. A script or build tool
# (`./run.sh`, `bash run.sh`, `make`) is not one of them: a user decision
# (2026-10-15) left those trusted, accepting the residual.
_EVAL_COMMANDS = {"eval", "source", "."}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}


def _runs_code(toks):
    """True if toks, past any _GIT_WRAPPERS, run shell code: an _EVAL_COMMANDS
    word, or a shell given `-c` (alone or in a flag cluster such as `-lc`)."""
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    if i >= len(toks):
        return False
    if toks[i] in _EVAL_COMMANDS:
        return True
    if os.path.basename(toks[i]) not in _SHELLS:
        return False
    for tok in toks[i + 1:]:
        if not tok.startswith("-") or tok.startswith("--"):
            break
        if "c" in tok[1:]:
            return True
    return False


def _may_move_head(segment):
    """True if the segment, read past a leading expansion, runs a git
    subcommand that may move HEAD, or runs shell code (_runs_code)."""
    toks = _tokens(segment, expansions=True)
    if _runs_code(toks):
        return True
    i = 0
    while i < len(toks) and toks[i] in _GIT_WRAPPERS:
        i += 1
    if i >= len(toks) or os.path.basename(toks[i]) != "git":
        return False
    i = _git_subcommand_at(toks, i + 1)
    return i < len(toks) and toks[i] not in _HEAD_STILL_SUBCOMMANDS


# How deep command substitutions are read inside one another. Each level
# reads its whole body again, so a pathological nesting is cut off here
# rather than left to run for seconds.
_MAX_SUBST_DEPTH = 32


def _commit_segments(command, cwds, running_branch, chain_stack, stack_reliable,
                     any_switch_seen, overrides, level=0):
    """The git commits in command, as (segment, cwds, branch) each: the cwds
    the commit may run in and the branch an earlier creation in the chain put
    it on (None: read the live branch). The other arguments are the state the
    command starts in, as main() tracks it below; overrides are main()'s
    (branch, reflog, creatable) test hooks.

    A command substitution is a command of its own, run before the segment
    holding it, in that segment's cwd and branch; whatever it changes stays
    in its subshell, except HEAD, which the repo shares: a body that may move
    HEAD drops the chain's branch. Its commits are read the same way,
    recursively, to _MAX_SUBST_DEPTH: past it RecursionError, as when the
    stack runs out.

    Returns (commits, moved): moved says some git call in command may move
    HEAD.
    """
    if level > _MAX_SUBST_DEPTH:
        raise RecursionError("command substitutions nest too deep")
    branch_override, reflog_override, creatable_override = overrides
    segments, operators, arms, bodies, cases = _split_full(command)
    effective_cwd_at = {}  # segment_index → the cwds it may run in
    effective_branch_at = {}  # segment_index → branch created earlier in-chain, or None
    running_cwds = list(cwds)
    # running_branch: None = no in-chain branch creation seen → use live detection
    chain_stack = list(chain_stack)  # in-chain "current branch" history, most-recent last
    # chain_stack / stack_reliable back '@{-N}'/'-' resolution only — they are
    # independent of running_branch's own trust rules (see _resolve_prev_ref).
    # stack_reliable: False once chain_stack's depth can no longer be proven exact
    # any_switch_seen: True once any HEAD-moving switch has appeared in the chain
    # A heredoc body outside quotes is split into segments like real commands,
    # so a creation "seen" there may be text. A quoted `"$(cat <<'EOF' ...)"`
    # commit message stays one token and is no obstacle.
    has_heredoc = "<<" in _outside_quotes(command)
    ref_touched = False      # True once an earlier segment was anything but inert
    carries_semicolon = False  # the attribution comes from a creation proven to succeed
    proven_created = []      # names created under that proof, absent from the live refs
    fn_depth = 0             # braces and parens open in a function body being defined
    fn_pending = False       # a function head seen alone: its body follows
    nested_commits = []      # commits found in substitution bodies
    moved = False            # some git call here may move HEAD
    # A function definition or a case, `case` to `esac`, is one compound: the
    # chain state on entering it, restored past its end unless something in
    # it is not provably inert (dirty).
    compound = None
    dirty = False

    def maybe_cwds(path):
        return list(dict.fromkeys(os.path.abspath(os.path.join(c, path)) for c in running_cwds))

    for idx, seg in enumerate(segments):
        # Branch attribution carries across '&&' (predecessor guaranteed to have
        # succeeded), and across ';' or a newline only from a creation proven to
        # succeed (carries_semicolon, set below). After '||', '|', '&', or an
        # unproven ';', the earlier checkout may not have run — drop the
        # attribution so the commit falls back to live branch detection.
        op = operators[idx]
        if op is not None and op != "&&" and not (op == ";" and carries_semicolon):
            running_branch = None
            chain_stack = []
            carries_semicolon = False
            if any_switch_seen:
                # an earlier switch (trusted or not) may have run at runtime and
                # mutated the real reflog — a later '@{-N}' resolved against the
                # hook-time (pre-chain) reflog would be stale, so stop resolving.
                stack_reliable = False
        stripped = seg.strip()
        # A case arm may not run and a function body runs later, if at all:
        # they add commit detection, and a cwd they may move to, never a
        # branch. A function body is followed to the brace or paren closing it.
        head, depth, bare_head = _function_nesting(stripped)
        in_body = fn_depth > 0 or (fn_pending and stripped)
        if in_body or head:
            fn_pending = bare_head
            fn_depth = max(fn_depth + depth, 0)
        guarded = op == ")" or arms[idx] or head or bool(in_body)
        if compound is None and (head or in_body or cases[idx][0]):
            compound = (running_branch, list(chain_stack), stack_reliable, any_switch_seen)
            dirty = False
        for body in bodies[idx]:
            if guarded:
                found, body_moved = _commit_segments(
                    body, running_cwds, None, [], False, True, overrides, level + 1)
            else:
                found, body_moved = _commit_segments(
                    body, running_cwds, running_branch, chain_stack, stack_reliable, True,
                    overrides, level + 1)
            nested_commits += found
            if body_moved:
                # the substitution ran in a subshell, but on the same repo
                dirty = True
                moved = True
                running_branch = None
                chain_stack = []
                carries_semicolon = False
                stack_reliable = False
                any_switch_seen = True
        moved = moved or _may_move_head(stripped)
        if _runs_code(_tokens(stripped, expansions=True)):
            # shell code that is not read may have switched: drop the chain's branch
            running_branch = None
            chain_stack = []
            carries_semicolon = False
            stack_reliable = False
            any_switch_seen = True
        toks = _tokens(stripped)
        exp_toks = _tokens(stripped, expansions=True)
        # an expansion that may be empty leads the command: what follows it
        # may run, or may not
        hidden = exp_toks != toks
        pattern = idx + 1 < len(operators) and operators[idx + 1] == ")"
        if compound is not None and not pattern and not _compound_inert(stripped):
            # what may move HEAD or the directory is open-ended (`eval`,
            # `sh -c`, `pushd`, a function), so only a provably inert command
            # leaves the compound clean
            dirty = True
        if len(exp_toks) >= 2 and exp_toks[0] == "cd":
            # cd <path>: update running effective cwd (resolve relative paths).
            # A cwd change voids branch attribution — the new directory may be a
            # different repo where the earlier checkout never applied. A cd that
            # may not run leaves both cwds.
            cd_cwds = maybe_cwds(exp_toks[1])
            running_cwds = (list(dict.fromkeys(running_cwds + cd_cwds)) if guarded or hidden
                            else cd_cwds)
            running_branch = None
            chain_stack = []
            carries_semicolon = False
            if any_switch_seen:
                stack_reliable = False
        if guarded:
            running_branch = None
            chain_stack = []
            carries_semicolon = False
            stack_reliable = False
            any_switch_seen = True
        created, create_flag = (None if guarded else _new_branch_created(stripped, flag=True)) or (None, None)
        if created is not None and create_flag in ("-B", "-C") and _has_expansion(created):
            # a forced creation resets a branch that exists: a name known only
            # at runtime may be a protected one (`-B "$b"`)
            created = None
            running_branch = None
            chain_stack = []
            stack_reliable = False
            any_switch_seen = True
        if created is not None:
            running_branch = created
            chain_stack.append(created)
            any_switch_seen = True
            # The creation is proven to succeed when it runs unconditionally,
            # nothing before it could have taken the name, moved to another repo
            # or opened a compound command around it, it is spelled as a literal `checkout -b`/`switch -c`,
            # and the branch can be created in the repo as it stands now. Only
            # then does a following ';' say as much as '&&' would.
            # A proof still standing (carries_semicolon) means everything before
            # was inert, a commit or a proven creation: the repo differs from
            # the live one only by the names in proven_created.
            carries_semicolon = (
                not has_heredoc
                and len(running_cwds) == 1
                and (not ref_touched or carries_semicolon)
                and _runs_unconditionally(idx, segments, operators)
                and _is_provable_creation(stripped, created)
                and not any(_names_collide(created, earlier) for earlier in proven_created)
                and _branch_creatable(
                    _git_cwd(stripped, running_cwds[0]), created, _override=creatable_override,
                )
            )
            if carries_semicolon:
                proven_created.append(created)
        elif hidden and not guarded:
            # A switch behind an expansion may run or may not. It can only move
            # the chain toward a protected branch, never off one, and leaves
            # chain_stack's depth unprovable.
            switched = _bare_switch_target(stripped, expansions=True)
            forced = _new_branch_created(stripped, expansions=True, flag=True)
            if forced is not None and forced[1] in ("-B", "-C"):
                switched = forced[0]  # a forced creation resets and switches to an existing branch
            if isinstance(switched, _PrevRef):
                resolved = _resolve_prev_ref(
                    switched.n, chain_stack, _git_cwd(stripped, running_cwds[0]),
                    stack_reliable and len(running_cwds) == 1,
                    branch_override, reflog_override,
                )
                if resolved is None:
                    running_branch = None
                    chain_stack = []
                elif resolved in ("main", "master"):
                    running_branch = resolved
            elif switched is not None and _has_expansion(switched):
                running_branch = None
                chain_stack = []
            elif switched in ("main", "master"):
                running_branch = switched
            if (switched is not None or _is_unmodeled_git_segment(stripped, expansions=True)
                    or forced is not None):
                any_switch_seen = True
                stack_reliable = False
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
            switched = None if guarded else _bare_switch_target(stripped)
            if isinstance(switched, _PrevRef):
                any_switch_seen = True
                # Resolve against THIS segment's own effective cwd (honors a
                # `-C <path>` on the switch itself), not the shell-cd-tracked
                # running_cwd — otherwise a `-C`-scoped switch/commit chain
                # resolves against the wrong repository's reflog.
                switch_cwd = _git_cwd(stripped, running_cwds[0])
                resolved = _resolve_prev_ref(
                    switched.n, chain_stack, switch_cwd,
                    stack_reliable and len(running_cwds) == 1,
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
                if _has_expansion(switched):
                    # a target known only at runtime may be a protected one
                    running_branch = None
                    chain_stack = []
                elif switched in ("main", "master") or running_branch is not None:
                    running_branch = switched
            elif _is_unmodeled_git_segment(stripped):
                # detach / pathspec restore / multi-positional checkout-or-switch
                # form, an unrecognized subcommand (possibly a git alias for
                # checkout/switch), or any other unmodeled git invocation —
                # chain_stack depth is unprovable past this segment.
                any_switch_seen = True
                stack_reliable = False
        if carries_semicolon and created is None:
            # The proof covers the creation and the repo it ran in, nothing after.
            if _redirects_git(stripped):
                # this very git call runs somewhere the creation did not
                running_branch = None
                chain_stack = []
                carries_semicolon = False
            elif not _is_inert(stripped) and not _is_git_commit(stripped):
                # a later switch may fail and leave HEAD where it was, and any
                # other command (`pushd`, a script, a line that does not parse)
                # may move HEAD or the directory: trusted across '&&' only
                carries_semicolon = False
        if not _is_inert(stripped):
            ref_touched = True
        effective_cwd_at[idx] = list(running_cwds)
        effective_branch_at[idx] = running_branch
        if compound is not None and fn_depth == 0 and not fn_pending and not cases[idx][1]:
            # the compound ends here: its own separators, and its arms that
            # may not run, say nothing of the chain around it
            if not dirty:
                running_branch, chain_stack, stack_reliable, any_switch_seen = compound
                chain_stack = list(chain_stack)
            compound = None

    # Collect all commit segments with their effective cwds and in-chain branch
    commit_segs = []
    for idx, seg in enumerate(segments):
        stripped = seg.strip()
        if _is_git_commit(stripped):
            # -C flag overrides the cd-tracked cwd for this specific git call
            git_cwds = list(dict.fromkeys(_git_cwd(stripped, c) for c in effective_cwd_at[idx]))
            commit_segs.append((stripped, git_cwds, effective_branch_at[idx]))
    return commit_segs + nested_commits, moved


def main(branch_override=None, marker_override=None, reflog_override=None,
         creatable_override=None):
    """Main hook logic. branch_override / marker_override / reflog_override /
    creatable_override (see _branch_creatable) for test injection.

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
    overrides = (branch_override, reflog_override, creatable_override)
    try:
        commit_segs, _ = _commit_segments(command, [env_cwd], None, [], True, False, overrides)
    except RecursionError:
        # nesting past what the analysis can read: passing it would let a
        # commit hidden in it through (fail-open), and its spelling cannot be
        # trusted (`com\mit`), so nothing past it is read
        _block("commit-guard: blocked — the command nests too deep to check for a commit.")

    if not commit_segs:
        return  # not a git commit invocation → pass through

    # Check ALL commit segments — any failure blocks the entire command
    for seg, effective_cwds, created_branch in commit_segs:
        # --- Branch guard ---------------------------------------------------------
        # A branch created earlier in the same chain (checkout -b/switch -c) is
        # where the commit actually lands — it takes precedence over the live
        # branch, which still reports the pre-checkout branch at PreToolUse time.
        # A cd that may or may not have run leaves more than one cwd: each is
        # checked.
        for effective_cwd in effective_cwds:
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


def precommit_check(message, cwd=None, branch_override=None, marker_override=None):
    """Direct (non-hook) guard check for a caller about to run `git commit`.

    Applies the same branch and type guards as the hook, against the LIVE repo
    state — the caller commits immediately after this returns, so there is no
    command chain to attribute and `rev-parse` is authoritative.

    Returns None on allow; raises SystemExit(2) via `_block` on a violation.
    `branch_override` / `marker_override` are for test injection, matching
    `main()`'s interface.
    """
    cwd = cwd or os.getcwd()

    branch = _current_branch(cwd, _override=branch_override)
    if branch in ("main", "master"):
        if not _marker_present(cwd, _override=marker_override):
            _block(
                f"commit-guard: blocked — branch '{branch}' is protected. "
                "Add <!-- commit-guard: allow-main --> to AGENTS.md or CLAUDE.md to opt in."
            )

    # No expandable-substitution escape here — see the module docstring. The
    # message is a real argv value, so what we match is exactly what git gets.
    if not TYPE_PATTERN.match(message or ""):
        _block(
            f"commit-guard: blocked — message does not match required format "
            r"^\[(FEAT|REFACTOR|FIX|TEST|CONSTRAINT|DOCS|HARNESS|PLAN)\] . "
            f"Got: {message!r}"
        )


def _cli_precommit(argv):
    """Parse `--precommit-check --message <text> [--cwd <path>]` and run the check.

    Returns an exit code. A malformed invocation is a caller bug, not a commit
    to judge — it exits 1 (distinct from the guard's own 2) so a wrapper can
    tell "you called me wrong" from "your commit is rejected".
    """
    message = None
    cwd = None
    i = 0
    while i < len(argv):
        if argv[i] == "--message" and i + 1 < len(argv):
            message = argv[i + 1]
            i += 2
            continue
        if argv[i] == "--cwd" and i + 1 < len(argv):
            cwd = argv[i + 1]
            i += 2
            continue
        i += 1
    if message is None:
        print("commit-guard: --precommit-check requires --message <text>", file=sys.stderr)
        return 1
    try:
        precommit_check(message, cwd=cwd)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    return 0


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

    def run(command, branch="feature/x", marker=False, cwd=None, tool_name="Bash", reflog=None,
            creatable=False):
        """Simulate a hook invocation. Returns exit code (0=allow, 2=block).

        creatable answers _branch_creatable; False by default so no case shells
        out to git or depends on the directory the suite runs in."""
        payload = json.dumps({
            "tool_name": tool_name,
            "tool_input": {"command": command},
            "cwd": cwd or "/tmp",
        })
        old_stdin, sys.stdin = sys.stdin, io.StringIO(payload)
        old_stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            main(branch_override=branch, marker_override=marker, reflog_override=reflog,
                 creatable_override=creatable)
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

    # ...and across ';' / newline only from a creation proven to succeed
    # (PR #111 false-block: `git checkout -b X` on one line, `git commit` on a later one)
    def on_main(command, creatable=True):
        return run(command, branch="main", marker=False, creatable=creatable)

    check("newline: checkout -b then commit on a later line passes",
          on_main("git checkout -b feature/x\ngit commit -m '[FEAT] y'") == 0)
    check("newline: switch -c, add, then commit passes",
          on_main("git switch -c feature/x\ngit add -A\ngit commit -m '[FEAT] y'") == 0)
    check("semicolon: checkout -b ; commit passes when creatable",
          on_main("git checkout -b feature/x ; git commit -m '[FEAT] y'") == 0)
    check("semicolon: add before the creation keeps it proven",
          on_main("git add -A; git checkout -b feature/x; git commit -m '[FEAT] y'") == 0)
    check("semicolon: creation, then '&&' chain to the commit passes",
          on_main("git checkout -b feature/x; git add -A && git commit -m '[FEAT] y'") == 0)
    check("semicolon: a bad type is still type-blocked",
          on_main("git checkout -b feature/x\ngit commit -m 'wip'") == 2)
    # fail-toward-block: every way the creation may not have run, or not landed
    check("semicolon: branch not creatable → blocked",
          on_main("git checkout -b feature/x\ngit commit -m '[FEAT] y'", creatable=False) == 2)
    check("semicolon: creation named main → blocked",
          on_main("git checkout -b main\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation after '&&' is conditional → blocked",
          on_main("make lint && git checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation after '||' is conditional → blocked",
          on_main("make lint || git checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation in a pipeline → blocked",
          on_main("echo x | git checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation after '&' → blocked",
          on_main("sleep 1 & git checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: commit after '||' runs only if the creation failed → blocked",
          on_main("git checkout -b feature/x || git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then commit behind a later '||' → blocked",
          on_main("git checkout -b feature/x; false || git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation with a start point → blocked",
          on_main("git checkout -b feature/x origin/main\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation with another option → blocked",
          on_main("git checkout --track -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation aimed at another repo with -C → blocked",
          on_main("git -C /other checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: earlier `git branch` may have taken the name → blocked",
          on_main("git branch feature/x\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: second creation of the same name fails at runtime → blocked",
          on_main("git checkout -b feature/x\ngit checkout main\n"
                  "git checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then bare switch back to main → blocked",
          on_main("git checkout -b feature/x\ngit checkout main\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then checkout - back to main → blocked",
          on_main("git checkout -b feature/x\ngit checkout -\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then cd elsewhere → blocked",
          on_main("git checkout -b feature/x\ncd /other/repo\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation inside an untaken if → blocked",
          on_main("if false; then\ngit checkout -b feature/x\nfi\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation inside a loop body → blocked",
          on_main("for f in $LIST; do\ngit checkout -b feature/x\ndone\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation inside an uncalled function → blocked",
          on_main("mk() {\ngit checkout -b feature/x\n}\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation inside a subshell group → blocked",
          on_main("(git checkout -b feature/x)\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation as a heredoc body line → blocked",
          on_main("cat <<EOF\ngit checkout -b feature/x\nEOF\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation as a body line of a `: <<'EOF'` comment block → blocked",
          on_main(": <<'EOF'\ngit checkout -b feature/x\nEOF\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation that is really a continued echo argument → blocked",
          on_main("echo hi \\\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: a backtick substitution before the creation → blocked",
          on_main("echo `git branch feature/x`; git checkout -b feature/x; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: braces inside a quoted message are not grouping",
          on_main("git checkout -b feature/x\ngit commit -m '[FEAT] use { braces }'") == 0)
    check("semicolon: a quoted heredoc commit message is no obstacle",
          on_main("git checkout -b feature/x\ngit add -A\n"
                  "git commit -m \"$(cat <<'EOF'\n[FEAT] y\n\nbody\nEOF\n)\"") == 0)
    check("semicolon: '<<' inside a quoted message is not a heredoc",
          on_main("git checkout -b feature/x\ngit commit -m '[FIX] handle << operator'") == 0)
    check("semicolon: an assignment line before the creation keeps it proven",
          on_main("SCOPE='a b'\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 0)
    check("semicolon: `set -e` and an echo before the creation keep it proven",
          on_main("set -euo pipefail\necho start\ngit switch --create feature/x\n"
                  "git commit -m '[FEAT] y'") == 0)
    # an operator left at the end of a line still governs the next line
    check("semicolon: creation after a trailing '||' and newline → blocked",
          on_main("make lint || \ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation after a trailing '&&' and newline → blocked",
          on_main("[ -n \"$CI\" ] && \ngit switch -c feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation after a trailing '|' and newline → blocked",
          on_main("echo x | \ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation after a line continuation → blocked",
          on_main("make lint && \\\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    # the proof covers the creation alone, never a later switch
    check("semicolon: creation, main, then a switch that may fail → blocked",
          on_main("git checkout -b feature/x; git checkout main; git checkout typo; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a bare switch that may fail → blocked",
          on_main("git checkout -b feature/x; git checkout typo; git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a git alias that may switch → blocked",
          on_main("git checkout -b feature/x; git co main; git commit -m '[FEAT] y'") == 2)
    # a second creation is proven on top of a first one that still stands
    check("semicolon: two creations in a row, commit lands on the second → passes",
          on_main("git checkout -b a; git checkout -b b; git commit -m '[FEAT] y'") == 0)
    check("newline: creation, commit, second creation, commit → passes",
          on_main("git checkout -b a\ngit commit -m '[FEAT] y'\n"
                  "git switch -c b\ngit commit -m '[FEAT] z'") == 0)
    check("semicolon: second creation of the first one's name → blocked",
          on_main("git checkout -b a; git checkout -b a; git commit -m '[FEAT] y'") == 2)
    check("semicolon: second creation under the first one's name → blocked",
          on_main("git checkout -b a; git checkout -b a/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: second creation above the first one's name → blocked",
          on_main("git checkout -b a/x; git checkout -b A; git commit -m '[FEAT] y'") == 2)
    check("semicolon: second creation not creatable in the repo → blocked",
          run("git checkout -b a; git checkout -b b; git commit -m '[FEAT] y'", branch="main",
              creatable=lambda cwd, name: name == "a") == 2)
    check("semicolon: second creation after an unproven first → blocked",
          run("git checkout -b a; git checkout -b b; git commit -m '[FEAT] y'", branch="main",
              creatable=lambda cwd, name: name == "b") == 2)
    check("semicolon: second creation behind '&&' is conditional → blocked",
          on_main("git checkout -b a; test -f x && git checkout -b b; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: a script between the two creations → blocked",
          on_main("git checkout -b a; ./prepare.sh; git checkout -b b; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: a switch between the two creations → blocked",
          on_main("git checkout -b a; git checkout main; git checkout -b b; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: second creation named main → blocked",
          on_main("git checkout -b a; git checkout -b main; git commit -m '[FEAT] y'") == 2)

    # a comment ends at its own line, never at the end of the command
    check("comment line above a commit on main → blocked",
          on_main("# note\ngit commit -m '[FEAT] y'") == 2)
    check("comment line above a badly typed commit → type-blocked",
          run("# note\ngit commit -m 'wip'") == 2)
    check("trailing comment on an earlier line does not hide the commit → blocked",
          on_main("git status # look first\ngit commit -m '[FEAT] y'") == 2)
    check("comment after ';' does not hide the next line → blocked",
          on_main("git add -A;# stage\ngit commit -m '[FEAT] y'") == 2)
    check("'#' inside a word is text, not a comment → blocked",
          on_main("echo a#b; git commit -m '[FEAT] y'") == 2)
    check("'$#' is text, not a comment → blocked",
          on_main("echo $#; git commit -m '[FEAT] y'") == 2)
    check("an apostrophe in a comment opens no quote over later lines → blocked",
          on_main("# don't skip\ngit status; git commit -m '[FEAT] y'") == 2)
    check("an escaped '#' is text, not a comment → blocked",
          on_main("echo \\# x; git commit -m '[FEAT] y'") == 2)
    check("a commented-out commit is no commit → passes",
          on_main("# git commit -m 'wip'\ngit status") == 0)
    check("a commit after '#' on its own line stays commented out → passes",
          on_main("git status # git commit -m 'wip'") == 0)
    check("'#' in a quoted message is kept and type-checked → passes",
          run("git commit -m '[FIX] close #316'") == 0)
    check("'#' opening a quoted message is kept → type-blocked",
          run("git commit -m '#316 fix'") == 2)
    check("'#' in a double-quoted message survives a comment on the line above",
          run("# note\ngit commit -m \"[FIX] see #316\"") == 0)
    check("comment between a proven creation and the commit keeps the carry → passes",
          on_main("git checkout -b feature/x\n# now commit\ngit commit -m '[FEAT] y'") == 0)
    check("'<<' inside a comment is not a heredoc → passes",
          on_main("# a << b\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 0)
    check("a creation that is only a comment proves nothing → blocked",
          on_main("# git checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    # an operator at the end of a line still separates the next line
    check("';' then newline does not hide the commit → blocked",
          on_main("git add -A;\ngit commit -m '[FEAT] y'") == 2)
    check("'&&' then newline does not hide the commit → blocked",
          on_main("git add -A &&\ngit commit -m '[FEAT] y'") == 2)
    check("'&&' then newline: the commit is still type-checked",
          run("git add -A &&\ngit commit -m 'wip'") == 2)
    check("'||' then newline does not hide the commit → blocked",
          on_main("make lint ||\ngit commit -m '[FEAT] y'") == 2)
    check("'|' then newline does not hide the commit → blocked",
          on_main("echo x |\ngit commit -m '[FEAT] y'") == 2)
    check("'&' then newline does not hide the commit → blocked",
          on_main("sleep 1 &\ngit commit -m '[FEAT] y'") == 2)
    check("'&&' then newline carries a creation like '&&' on one line → passes",
          on_main("git checkout -b feature/x &&\ngit commit -m '[FEAT] y'",
                  creatable=False) == 0)
    check("'||' then newline after a proven creation → blocked",
          on_main("git checkout -b feature/x ||\ngit commit -m '[FEAT] y'") == 2)
    check("creation after '||' then newline is conditional → blocked",
          on_main("make lint ||\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    check("a redirect operator is still text, not a separator",
          _split_segments("make 2>&1 | tee log")[1] == [None, "|"])
    check("'&&', a space, then newline carries a creation like '&&' → passes",
          on_main("git checkout -b feature/x origin/main && \ngit commit -m '[FEAT] y'") == 0)
    check("'&&', a comment, then newline carries a creation like '&&' → passes",
          on_main("git checkout -b feature/x origin/main && # go\n"
                  "git commit -m '[FEAT] y'") == 0)
    check("'||', a comment, then newline still drops the creation → blocked",
          on_main("git checkout -b feature/x || # or\ngit commit -m '[FEAT] y'") == 2)
    check("'&&', a comment, then newline does not hide a commit on main → blocked",
          on_main("git add -A && # stage\ngit commit -m '[FEAT] y'") == 2)
    check("an empty line between a proven creation and the commit keeps the carry",
          on_main("git checkout -b feature/x\n\ngit commit -m '[FEAT] y'") == 0)
    check("_split_segments: '&&', space, newline is one '&&'",
          _split_segments("a && \nb") == (["a", "b"], [None, "&&"]))
    check("an escaped space before '#' keeps it text → blocked",
          on_main("echo a\\ #b; git commit -m '[FEAT] y'") == 2)
    check("a line continuation before '#' keeps it text → blocked",
          on_main("echo a\\\n#b; git commit -m '[FEAT] y'") == 2)
    check("_strip_comments: '#' after a continuation following a space is a comment",
          _strip_comments("a \\\n# b\nc") == "a \\\n\nc")
    check("_strip_comments: '#' right after a closing quote is text",
          _strip_comments("echo 'a'#b") == "echo 'a'#b")
    check("_split_segments: '&&' then newline is one '&&'",
          _split_segments("a &&\nb") == (["a", "b"], [None, "&&"]))
    check("_split_segments: ';' then newline is one ';'",
          _split_segments("a;\nb") == (["a", "b"], [None, ";"]))

    check("_strip_comments keeps the newline that ends the comment",
          _strip_comments("a # b\nc") == "a \nc")
    check("_split_segments: text after a comment line is its own segment",
          _split_segments("# note\ngit commit -m 'wip'")[0] == ["", "git commit -m 'wip'"])

    check("no creation: bare switches joined by ';' still fall back to live main → blocked",
          on_main("git checkout main && git checkout typo; git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a switch split by a line continuation → blocked",
          on_main("git checkout -b feature/x\ngit checkout \\\n  main\n"
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then pushd elsewhere → blocked",
          on_main("git checkout -b feature/x; pushd /other; git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a script that may switch → blocked",
          on_main("git checkout -b feature/x; bash switch.sh; git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a commit aimed at another repo with -C → blocked",
          on_main("git checkout -b feature/x\ngit -C /other commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a commit aimed at another repo with GIT_DIR= → blocked",
          on_main("git checkout -b feature/x\nGIT_DIR=/other/.git git commit -m '[FEAT] y'") == 2)
    check("semicolon: two commits after the creation, the first with a heredoc message, both pass",
          on_main("git checkout -b feature/x\ngit commit -m \"$(cat <<'EOF'\n[FEAT] y\nEOF\n)\"\n"
                  "git add -A\ngit commit -m '[FEAT] z'") == 0)
    # a name the shell rewrites is not the name that was checked
    check("semicolon: creation of a quoted \"$BRANCH\" → blocked",
          on_main("git checkout -b \"$BRANCH\"\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation of an unquoted $BRANCH → blocked",
          on_main("git checkout -b $BRANCH\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation of a \"feature/$(whoami)\" name → blocked",
          on_main("git checkout -b \"feature/$(whoami)\"\ngit commit -m '[FEAT] y'") == 2)
    check("semicolon: creation of a literal quoted name → blocked (only the bare spelling is proven)",
          on_main("git checkout -b 'feature/x'\ngit commit -m '[FEAT] y'") == 2)
    # anything but an inert command before the creation may have taken the name
    check("semicolon: `bash -c` before the creation → blocked",
          on_main("bash -c 'git branch feature/x'; git checkout -b feature/x; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: a script before the creation → blocked",
          on_main("bash create-branch.sh; git checkout -b feature/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: pushd before the creation → blocked",
          on_main("pushd /other; git checkout -b feature/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: a bare cd before the creation → blocked",
          on_main("cd; git checkout -b feature/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: a command substitution before the creation → blocked",
          on_main("echo $(git branch feature/x); git checkout -b feature/x; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: GIT_DIR= on the creation aims at another repo → blocked",
          on_main("GIT_DIR=/other/.git git checkout -b feature/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: an earlier `export GIT_DIR` → blocked",
          on_main("export GIT_DIR=/other/.git; git checkout -b feature/x; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: an earlier GIT_DIR assignment line → blocked",
          on_main("GIT_DIR=/other/.git\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)
    # spellings that fail or succeed on conditions the creatable check does not read
    check("semicolon: switch --orphan → blocked",
          on_main("git switch --orphan feature/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: checkout --orphan → blocked",
          on_main("git checkout --orphan feature/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: checkout -B → blocked",
          on_main("git checkout -B feature/x; git commit -m '[FEAT] y'") == 2)
    check("semicolon: `command git checkout -b` → blocked",
          on_main("command git checkout -b feature/x; git commit -m '[FEAT] y'") == 2)

    # _branch_creatable against a real repository
    def git_in(repo, *args):
        return subprocess.run(
            ["git", "-C", repo, "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
             "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
            capture_output=True, text=True,
        )

    repo = tempfile.mkdtemp()
    git_in(repo, "init", "-q")
    git_in(repo, "commit", "--allow-empty", "--no-verify", "-q", "-m", "init")
    git_in(repo, "branch", "taken")
    git_in(repo, "branch", "topic/deep/leaf")
    git_in(repo, "checkout", "-q", "-b", "elsewhere")  # so '@{-1}' resolves to a real branch
    git_in(repo, "branch", "release")
    git_in(repo, "tag", "release")  # a same-named tag makes the short ref name 'heads/release'
    check("creatable: an existing branch that shares its name with a tag is not",
          _branch_creatable(repo, "release") is False)
    check("creatable: a new name in a real repo", _branch_creatable(repo, "feature/new") is True)
    check("creatable: an existing branch is not", _branch_creatable(repo, "taken") is False)
    check("creatable: an existing branch differing only in case is not",
          _branch_creatable(repo, "Taken") is False)
    check("creatable: a name under an existing branch is not",
          _branch_creatable(repo, "taken/sub") is False)
    check("creatable: a name above an existing branch is not",
          _branch_creatable(repo, "topic/deep") is False)
    check("creatable: a sibling of an existing branch is",
          _branch_creatable(repo, "topic/deep/other") is True)
    check("creatable: an invalid branch name is not", _branch_creatable(repo, "bad..name") is False)
    check("creatable: a previous-branch ref is not a literal name",
          _branch_creatable(repo, "@{-1}") is False)
    check("creatable: a directory that is no repository answers False",
          _branch_creatable(tempfile.mkdtemp(), "feature/new") is False)
    # states in which the creation itself refuses to run
    busy = tempfile.mkdtemp()
    git_in(busy, "init", "-q")
    git_in(busy, "commit", "--allow-empty", "--no-verify", "-q", "-m", "init")
    check("creatable: a quiet repo is", _branch_creatable(busy, "feature/new") is True)
    busy_git_dir = git_in(busy, "rev-parse", "--absolute-git-dir").stdout.strip()
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        marker_path = os.path.join(busy_git_dir, marker)
        with open(marker_path, "w", encoding="utf-8") as fh:
            fh.write("0" * 40 + "\n")
        check(f"creatable: not while {marker} is present",
              _branch_creatable(busy, "feature/new") is False)
        os.remove(marker_path)
    for marker in ("rebase-merge", "rebase-apply"):
        marker_path = os.path.join(busy_git_dir, marker)
        os.mkdir(marker_path)
        check(f"creatable: not while {marker}/ is present",
              _branch_creatable(busy, "feature/new") is False)
        os.rmdir(marker_path)
    # a real conflict: an unmerged index entry with no marker file left (stash pop)
    with open(os.path.join(busy, "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("base\n")
    git_in(busy, "add", "f.txt")
    git_in(busy, "commit", "--no-verify", "-q", "-m", "base")
    with open(os.path.join(busy, "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("stashed\n")
    git_in(busy, "stash", "-q")
    with open(os.path.join(busy, "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("committed\n")
    git_in(busy, "commit", "--no-verify", "-q", "-am", "diverge")
    git_in(busy, "stash", "pop")
    check("creatable: fixture left an unmerged entry",
          bool(git_in(busy, "ls-files", "--unmerged").stdout.strip()))
    check("creatable: not with an unmerged index entry",
          _branch_creatable(busy, "feature/new") is False)

    check("real repo: checkout -b of a new name then commit on a later line passes",
          run("git checkout -b feature/new\ngit commit -m '[FEAT] y'", branch="main",
              cwd=repo, creatable=None) == 0)
    check("real repo: checkout -b of an existing name then commit → blocked",
          run("git checkout -b taken\ngit commit -m '[FEAT] y'", branch="main",
              cwd=repo, creatable=None) == 2)

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

    # --- precommit_check(): the direct CLI entry point used by commit-and-push.sh ---
    # Without this path the hook never fired on the task-review commit path at all,
    # because the Bash tool only saw `bash <script>` (see module docstring).
    def run_pre(message, branch="feature/x", marker=False, cwd="/tmp"):
        """Simulate a --precommit-check invocation. Returns exit code (0/2)."""
        old_stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            precommit_check(message, cwd=cwd, branch_override=branch, marker_override=marker)
            return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
        finally:
            sys.stderr = old_stderr

    check("precommit: valid type on feature branch passes", run_pre("[FEAT] x") == 0)
    check("precommit: every valid type accepted",
          all(run_pre(f"[{t}] x") == 0 for t in
              ("FEAT", "REFACTOR", "FIX", "TEST", "CONSTRAINT", "DOCS", "HARNESS", "PLAN")))
    check("precommit: bad message blocked", run_pre("wip") == 2)
    check("precommit: conventional-commit style blocked", run_pre("feat: add x") == 2)
    check("precommit: missing trailing space blocked", run_pre("[FEAT]x") == 2)
    check("precommit: unknown type blocked", run_pre("[CHORE] x") == 2)
    check("precommit: empty message blocked", run_pre("") == 2)
    check("precommit: None message blocked", run_pre(None) == 2)
    check("precommit: multi-line message checks first line only",
          run_pre("[FIX] subject\n\nbody text") == 0)

    check("precommit: main blocked without marker", run_pre("[FEAT] x", branch="main") == 2)
    check("precommit: master blocked without marker", run_pre("[FEAT] x", branch="master") == 2)
    check("precommit: main allowed with marker",
          run_pre("[FEAT] x", branch="main", marker=True) == 0)
    check("precommit: marker does not excuse a bad message",
          run_pre("wip", branch="main", marker=True) == 2)
    check("precommit: branch guard fires before type guard on main",
          run_pre("wip", branch="main", marker=False) == 2)

    # Unlike the hook path, an argv message is already shell-expanded — a literal
    # '$(...)' is exactly what git receives, so it stays type-checked (no fail-open).
    check("precommit: literal $(...) is NOT excused (stricter than hook)",
          run_pre("$(cat msg.txt)") == 2)
    check("precommit: backtick text is NOT excused", run_pre("`cat msg.txt`") == 2)
    check("precommit: valid type with $(...) in the body passes",
          run_pre("[FEAT] handle $(x) safely") == 0)

    # a commit behind a shell keyword or a leading redirect is still a commit
    check("commit in an if body → blocked",
          on_main("if true; then git commit -m 'wip'; fi") == 2)
    check("commit in a for body → blocked",
          on_main("for f in a; do git commit -m 'wip'; done") == 2)
    check("commit behind a leading redirect → blocked",
          on_main(">log git commit -m 'wip'") == 2)
    check("commit in an if body is type-checked",
          run("if true; then git commit -m 'wip'; fi") == 2)
    check("commit in an if body with a valid type → passes",
          run("if true; then git commit -m '[FEAT] y'; fi") == 0)
    check("commit in an else body → blocked",
          on_main("if false; then :; else git commit -m '[FEAT] y'; fi") == 2)
    check("commit in a while body → blocked",
          on_main("while read -r f; do git commit -m '[FEAT] y'; done") == 2)
    check("commit as an if condition → blocked",
          on_main("if ! git commit -m '[FEAT] y'; then echo no; fi") == 2)
    check("commit in a group after `then` → blocked",
          on_main("if true; then { git commit -m '[FEAT] y'; }; fi") == 2)
    check("commit behind `time` → blocked",
          on_main("time git commit -m '[FEAT] y'") == 2)
    check("commit behind a detached leading redirect → blocked",
          on_main("> log git commit -m '[FEAT] y'") == 2)
    check("commit behind a leading fd redirect → blocked",
          on_main("2>&1 git commit -m '[FEAT] y'") == 2)
    check("commit behind a redirect and an assignment → blocked",
          on_main(">log GIT_EDITOR=true git commit -m '[FEAT] y'") == 2)
    check("commit behind a leading redirect is type-checked",
          run(">log git commit -m 'wip'") == 2)
    check("a keyword as an argument opens no command → passes",
          run("echo then git commit -m 'wip'") == 0)
    check("creation and commit joined by '&&' in an if body → passes",
          on_main("if true; then git checkout -b feature/x && git commit -m '[FEAT] y'; fi") == 0)
    check("creation as an if condition proves nothing for the body → blocked",
          on_main("if git checkout -b feature/x; then git commit -m '[FEAT] y'; fi") == 2)

    check("semicolon: creation, then a grouped commit aimed at another repo → blocked",
          on_main("git checkout -b feature/x; { git -C /other commit -m '[FEAT] y'; }") == 2)
    check("semicolon: creation, then a redirected commit aimed at another repo → blocked",
          on_main("git checkout -b feature/x; >log git -C /other commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a negated GIT_DIR= commit → blocked",
          on_main("git checkout -b feature/x; ! GIT_DIR=/o/.git git commit -m '[FEAT] y'") == 2)
    check("semicolon: creation, then a redirected commit in the same repo → passes",
          on_main("git checkout -b feature/x\n>log git commit -m '[FEAT] y'") == 0)

    # a heredoc body is text, not commands
    check("an apostrophe in a heredoc body does not hide the commit after it → blocked",
          on_main("cat <<EOF > note.txt\nDon't panic\nEOF\ngit commit -m '[FEAT] y'") == 2)
    check("the commit after such a heredoc is type-checked",
          run("cat <<EOF\nDon't panic\nEOF\ngit commit -m 'wip'") == 2)
    check("a heredoc body line reading `git commit` is text → passes",
          run("cat <<EOF\ngit commit -m \"wip\"\nEOF") == 0)
    check("the same line after a '#' body line is text → passes",
          run("cat <<EOF\n# title\ngit commit -m \"wip\"\nEOF") == 0)
    check("a quoted delimiter ends the body all the same → passes",
          run("cat <<'EOF'\ngit commit -m \"wip\"\nEOF\ngit status") == 0)
    check("'<<-' ends at a tab-indented delimiter → blocked",
          run("cat <<-EOF\n\tgit commit -m ok\n\tEOF\ngit commit -m 'wip'") == 2)
    check("'<<-' body is text → passes",
          run("cat <<-EOF\n\tgit commit -m wip\n\tEOF") == 0)
    check("two heredocs on one line, both bodies are text → blocked after them",
          run("cat <<A <<B\ngit commit -m one\nA\ngit commit -m two\nB\ngit commit -m 'wip'") == 2)
    check("two heredocs on one line, both bodies are text → passes",
          run("cat <<A <<B\ngit commit -m one\nA\ngit commit -m two\nB") == 0)
    check("an operator on the heredoc line still governs the line after the body",
          _split_segments("cat <<EOF &&\nbody\nEOF\nb") == (["cat <<EOF", "b"], [None, "&&"]))
    check("a heredoc with no delimiter line hides nothing → blocked",
          on_main("cat <<EOF\nbody\ngit commit -m '[FEAT] y'") == 2)
    check("'<<' in arithmetic is no heredoc → blocked",
          on_main("echo $((1<<2))\ngit commit -m '[FEAT] y'") == 2)
    check("a here-string is no heredoc → blocked",
          on_main("cat <<<EOF\ngit commit -m '[FEAT] y'\nEOF") == 2)
    check("an apostrophe in a heredoc commit message → passes",
          run("git commit -m \"$(cat <<'EOF'\n[FEAT] y\n\nDon't panic\nEOF\n)\"") == 0)
    check("a commit after a heredoc message holding both quote kinds is still seen",
          run("git commit -m \"$(cat <<'EOF'\n[FEAT] y\n\nDon't \"quote\"\nEOF\n)\"\n"
              "git commit -m 'wip'") == 2)

    # one scanner: escapes, and a quote nested in "$( … )"
    check("a quote nested in \"$( … )\" does not hide the commit after it → blocked",
          on_main("echo \"$(echo \"x #\")\"; git commit -m 'wip'") == 2)
    check("the commit after it is type-checked",
          run("echo \"$(echo \"x #\")\"; git commit -m 'wip'") == 2)
    check("a ';' inside a nested quote separates nothing → passes",
          run("echo \"$(echo \"a; git commit -m wip; b\")\"") == 0)
    check("_split_segments keeps a nested \"$( … )\" in one segment",
          _split_segments("echo \"$(echo \"a; b\")\"; c") ==
          (["echo \"$(echo \"a; b\")\"", "c"], [None, ";"]))
    check("a commit split by a line continuation → blocked",
          on_main("git commit \\\n  -m '[FEAT] y'") == 2)
    check("a commit split by a line continuation is type-checked",
          run("git commit \\\n  -m 'wip'") == 2)
    check("an escaped quote opens no span over later lines → blocked",
          on_main("echo it\\'s\ngit commit -m '[FEAT] y'") == 2)
    check("an escaped quote in a $'…' string does not end it → blocked",
          on_main("echo $'it\\'s # x'; git commit -m '[FEAT] y'") == 2)
    check("_outside_quotes drops a nested \"$( … )\" whole",
          _outside_quotes("a \"$(b \"c << d\")\" e") == "a  e")
    check("_has_expandable_subst: \"$(x)\" expands",
          _has_expandable_subst("\"$(x)\""))
    check("_has_expandable_subst: an escaped '$(' in double quotes is literal",
          not _has_expandable_subst("\"\\$(x)\""))
    check("_has_expandable_subst: an escaped backtick is literal",
          not _has_expandable_subst("\"\\`x\\`\""))
    check("_has_expandable_subst: '\\'' does not reopen a single quote",
          _has_expandable_subst("'it'\\''s'$(x)") and
          not _has_expandable_subst("'it'\\''s $(x)'"))
    check("a message with an escaped '$(' is type-checked",
          run("git commit -m \"\\$(date) wip\"") == 2)

    # where bash sees no quote or no heredoc, the scanner must see none either
    check("'$$' before a quote opens no $'…' string → blocked",
          on_main("echo $$'\\'; git commit -m 'wip'; echo \"'\" #\"") == 2)
    check("'$$$' before a quote still opens a $'…' string → blocked",
          on_main("echo $$$'a\\'b # '; git commit -m '[FEAT] y'") == 2)
    check("'<<' in $(( … )) with a matching later line is no heredoc → blocked",
          on_main("echo $((1<<EOF))\ngit commit -m 'wip'\nEOF") == 2)
    check("'<<' in (( … )) is no heredoc → blocked",
          on_main("(( x = 1 << EOF ))\ngit commit -m 'wip'\nEOF") == 2)
    check("'<<' in an array literal is no heredoc → blocked",
          on_main("x=( a <<EOF )\ngit commit -m 'wip'\nEOF") == 2)
    check("'<<' in ${ … } is no heredoc → blocked",
          on_main("echo ${x:-<<EOF }\ngit commit -m 'wip'\nEOF") == 2)
    check("a heredoc announced in $( … ) does not reach past its ')' → blocked",
          on_main("echo $(cat <<EOF)\ngit commit -m 'wip'\nEOF") == 2)
    check("a heredoc announced in backticks does not reach past them → blocked",
          on_main("echo `cat <<EOF`\ngit commit -m 'wip'\nEOF") == 2)
    check("a heredoc inside an unquoted $( … ) is still text → passes",
          run("x=$(cat <<EOF\ngit commit -m \"wip\"\nEOF\n)\ngit status") == 0)
    check("a heredoc in a subshell is still text → passes",
          run("(cat <<EOF)\ngit commit -m \"wip\"\nEOF\ngit status") == 0)
    check("a heredoc after a closed $(( … )) is still text → passes",
          run("echo $((1+2)); cat <<EOF\ngit commit -m \"wip\"\nEOF") == 0)
    check("a '#' opening a heredoc delimiter is no comment → blocked",
          on_main("cat <<#X; git commit -m '[FEAT] y'\n#X") == 2)

    # a '#' joined to a closing construct is still in the word
    check("a '#' after a closing backtick is no comment → blocked",
          on_main("echo `true`#; git commit -m wip") == 2)
    check("a comment just inside backticks ends at the closing one → blocked",
          on_main("echo `#x`; git commit -m wip") == 2)
    check("a '#' after a closing $( … ) is no comment → blocked",
          on_main("echo $(true)#; git commit -m wip") == 2)
    check("a '#' after a closing $(( … )) is no comment → blocked",
          on_main("echo $((1))#; git commit -m wip") == 2)
    check("a '#' after a closing array is no comment → blocked",
          on_main("x=(a)#; git commit -m wip") == 2)
    check("a '#' after a closing subshell opens a comment → passes",
          run("(true)#; git commit -m wip") == 0)
    check("'((' that closes as ') )' is two subshells, '#' a comment → blocked",
          on_main("((echo a) # it's\n) && git commit -m wip # '") == 2)
    check("a heredoc announced in <( … ) does not reach past its ')' → blocked",
          on_main("cat <(cat <<EOF)\ngit commit -m wip\nEOF") == 2)
    check("'$${' opens no ${ … }, so a later heredoc is still text → passes",
          run("echo $${\ncat <<EOF\ngit commit -m wip\nEOF\ngit status") == 0)
    check("'$${' in a quoted $( … ) leaves it balanced → blocked",
          on_main("echo \"$(echo $${)\"; git commit -m wip") == 2)
    check("a heredoc in $( … ) inside an array is still text → passes",
          run("x=( $(cat <<EOF\ngit commit -m wip\nEOF\n) )\ngit status") == 0)
    check("a '#' in $( … ) inside $(( … )) opens a comment → blocked",
          on_main("echo $(( $(echo 1 # \"\n) + 1 ))\ngit commit -m wip\n# \"") == 2)
    check("a '(' in a ${ … } pattern opens nothing, so '}' closes it → blocked",
          on_main("echo ${v//(/} # don't\ngit commit -m wip # '") == 2)
    check("a '(' in a ${ … } pattern leaves a later heredoc as text → passes",
          run("echo ${v//(/x}\ncat <<'EOF'\ngit commit -m \"wip\"\nEOF") == 0)
    check("a quoted '))' does not close '((' as arithmetic → blocked",
          on_main("((echo \"))\") # it's\n) && git commit -m wip # '") == 2)
    check("a single-quoted '))' does not close '((' either → blocked",
          on_main("((echo '))') # it's\n) && git commit -m wip # '") == 2)

    # a word shlex cannot read is still read: $'…' escapes, quotes nested in "$( … )"
    check("a $'…' argument with an escaped quote → blocked",
          on_main("git commit -m wip $'a\\'b'") == 2)
    check("a $'…' message is decoded before the type check → passes",
          run("git commit -m $'[FEAT] it\\'s'") == 0)
    check("a $'…' message without a type is type-checked",
          run("git commit -m $'it\\'s wip'") == 2)
    check("a quote nested in \"$( … )\" inside a commit → blocked",
          on_main("git commit -m \"$(echo 'it\"s')\" -m wip") == 2)
    check("_tokens reads $'…' and keeps \"$( … )\" one word",
          _tokens("git commit -m $'a\\'b' \"$(echo 'x\"y')\"") ==
          ["git", "commit", "-m", "a'b", "$(echo 'x\"y')"])
    check("_tokens: '$$' before a quote opens no $'…' string",
          _tokens("echo $$'a\\'") == ["echo", "$$a\\"])

    # a command word built by an expansion that may be empty
    check("'$()' before git → blocked", on_main("$()git commit -m wip") == 2)
    check("'$(true)' before git → blocked", on_main("$(true)git commit -m wip") == 2)
    check("'$!' before git → blocked", on_main("$!git commit -m wip") == 2)
    check("'${x}' before git → blocked", on_main("${x}git commit -m wip") == 2)
    check("a backtick substitution before git → blocked",
          on_main("`true`git commit -m wip") == 2)
    check("'${x#a}' and a heredoc before git → blocked",
          on_main("${x#a}<<EOF git commit -m wip\nbody\nEOF") == 2)
    check("an expansion word before git → blocked", on_main("$x git commit -m wip") == 2)
    check("an assignment from a substitution before git → blocked",
          on_main("x=$(true) git commit -m wip") == 2)
    check("a commit behind an expansion is type-checked",
          run("$x git commit -m wip") == 2)
    check("an expansion as an argument opens no command → passes",
          run("echo $(date) git commit") == 0)

    # a commit in a case arm or a function body
    check("commit in a case arm → blocked",
          on_main("case x in x) git commit -m 'wip';; esac") == 2)
    check("commit in a later case arm → blocked",
          on_main("case x in a) true;; x) git commit -m 'wip';; esac") == 2)
    check("commit in an 'a|b)' case arm → blocked",
          on_main("case x in a|x) git commit -m 'wip';; esac") == 2)
    check("commit in a '(x)' case arm → blocked",
          on_main("case x in (x) git commit -m 'wip';; esac") == 2)
    check("commit in a case arm on its own line → blocked",
          on_main("case x in\n  x) git commit -m 'wip' ;;\nesac") == 2)
    check("commit in a case arm is type-checked",
          run("case x in x) git commit -m 'wip';; esac") == 2)
    check("commit in a function body → blocked",
          on_main("f() { git commit -m 'wip'; }; f") == 2)
    check("commit in a 'function f' body → blocked",
          on_main("function f { git commit -m 'wip'; }; f") == 2)
    check("commit in a 'function f ()' body → blocked",
          on_main("function f () { git commit -m 'wip'; }; f") == 2)
    check("commit in a subshell function body → blocked",
          on_main("f() ( git commit -m 'wip' ); f") == 2)
    check("a quoted ')' in a message is no case pattern → blocked",
          on_main("git commit -m ')' -m '[FEAT] y'") == 2)
    check("a quoted ')' message is still type-checked",
          run("git commit -m ')' x") == 2)
    check("a subshell closing before a redirect keeps its commit → blocked",
          on_main("(true; git commit -m '[FEAT] y') >log") == 2)
    check("an escaped ')' as an argument opens no command → passes",
          run("echo case x in x\\) git commit") == 0)
    check("a case arm with no commit → passes",
          run("case x in x) git status;; esac") == 0)

    # a case pattern ')' inside $( … ) does not close the substitution
    check("a heredoc in a case arm in $( … ) does not reach past its ')' → blocked",
          on_main("x=$(case a in a) cat <<EOF;; esac)\ngit commit -m wip\nEOF") == 2)
    check("a heredoc in a case arm in $( … ) is still text inside it → passes",
          run("x=$(case a in a) cat <<EOF\ngit commit -m wip\nEOF\n;; esac)\ngit status") == 0)
    check("a nested case's esac does not end the outer one → blocked",
          on_main("echo \"$(case a in a) case b in b) echo;; esac;; c) cat <<EOF;; esac)\"\n"
                  "git commit -m wip\nEOF") == 2)
    check("_split_segments ends a segment at a case pattern's ')'",
          _split_segments("case x in a|b) git commit;; esac") ==
          (["case x in ab", "git commit", "esac"], [None, ")", ";"]))

    # review of the above: never weaker than shlex, no pattern without a case
    check("the usual heredoc message with an apostrophe, on main → blocked",
          on_main("git commit -m \"$(cat <<'EOF'\n[FEAT] y\n\nit's done\nEOF\n)\"") == 2)
    check("the usual heredoc message with an apostrophe is type-checked",
          run("git commit -m \"$(cat <<'EOF'\nwip it's done\nEOF\n)\"") == 0
          and _is_git_commit("git commit -m \"$(cat <<'EOF'\nwip it's\nEOF\n)\""))
    check("a $'…' with an escaped quote inside \"$( … )\" → blocked",
          on_main("git commit -m '[FIX] x' \"$(printf '%s' $'it\\'s')\"") == 2)
    check("the ')' closing a split $( … ) is no case pattern → blocked",
          on_main("echo $(git add -A; git commit -m wip) done") == 2)
    check("a creation after a split $( … ) is not credited → blocked",
          on_main("echo $(true; echo x) git checkout -b feat && git commit -m '[FEAT] y'") == 2)
    check("a quoted ')' does not hide a -C redirect",
          _redirects_git("git -C /other commit -m ')' -m '[FEAT] y'"))
    check("a creation behind an expansion proves no switch → blocked",
          on_main("x=echo; $x git checkout -b feature/x && git commit -m '[FIX] x'") == 2)
    check("a quoted '}' in a leading ${ … } does not end it → blocked",
          on_main("${x:+'}'}git commit -m wip") == 2)
    # second review: no case after an argument, no new false block
    check("'do' as an argument opens no case, so '|' still pipes → blocked",
          on_main("echo do case | git commit -m wip") == 2)
    check("'if' as an argument opens no case, so '||' still separates → blocked",
          on_main("false if case || git commit -m wip") == 2)
    check("an 'esac' argument does not end the case → blocked",
          on_main("case x in x) echo esac;; y) git commit -m wip;; esac") == 2)
    check("an escaped '$x' is no expansion → passes", run("\\$x git commit -m wip") == 0)
    check("a quoted '$x' is no expansion → passes", run("'$x' git commit -m wip") == 0)
    check("'$0' is never empty → passes", run("$0git commit -m wip") == 0)
    check("'$(( … ))' is never empty → passes", run("$((0))git commit -m wip") == 0)
    check("'${#x}' is never empty → passes", run("${#x}git commit -m wip") == 0)
    check("'$x' joined to an empty quote before git → blocked",
          on_main("$x''git commit -m wip") == 2)
    check("a commit behind '$x' is type-checked through a '$(' message",
          run("$x git commit -m 'wip $(x)'") == 2)
    check("a function body takes no branch from where it is defined → blocked",
          on_main("git checkout -b feat; f() { git commit -m '[FIX] x'; }; git checkout main; f",
                  creatable=True) == 2)
    check("a creation in a function head credits nothing → blocked",
          on_main("f() { git checkout -b feat && git commit -m '[FIX] x'; }; f") == 2)

    # third review: a case arm or function definition changes no cwd or branch
    check("a cd in a function never called moves no cwd → blocked",
          run("f() { cd /other; }; git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("a cd in a case arm that may not match moves no cwd → blocked",
          run("case x in y) cd /other;; esac; git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("a creation in a subshell function head credits nothing → blocked",
          on_main("f() ( git checkout -b feat ) && git commit -m '[FIX] x'") == 2)
    check("an empty one-line case closes, so '|' still pipes → blocked",
          on_main("case x in esac; echo x | git commit -m wip") == 2)
    check("a long run of reserved words does not overflow the scanner → blocked",
          on_main("if " * 1200 + "case x in x) true;; esac; git commit -m wip") == 2)
    check("'x=$()' is no function head: the in-chain branch holds → passes",
          on_main("git checkout -b feat && x=$() && git commit -m '[FIX] y'") == 0)
    # fourth review: an escaped separator puts no word in command position
    check("an escaped ';' before 'case' opens no case → blocked",
          on_main("echo \\; case x | git commit -m wip") == 2)
    check("an escaped ';' before 'do case' opens no case → blocked",
          on_main("echo \\; do case x | git commit -m wip") == 2)
    check("the '|' of '>|' before 'case' opens no case → blocked",
          on_main("echo x >| case | git commit -m wip") == 2)
    nest = 450
    check("deeply nested \"$( … )\" does not crash the hook → blocked",
          on_main("git commit -m wip " + "\"$(echo " * nest + "x" + ")\"" * nest) == 2)
    check("a case after `time` opens its arm → blocked",
          on_main("time case x in x) git commit -m wip;; esac") == 2)
    check("an expansion before git on the shlex path → blocked",
          on_main("$x git commit -m \"$(cat <<'EOF'\n[FIX] it's done\nEOF\n)\"") == 2)
    check("an escaped backtick in a leading substitution → blocked",
          on_main("`echo \\``git commit -m wip") == 2)

    # PR #324 follow-ups: a substitution is a command of its own
    check("a commit inside a command-position $( … ) → blocked",
          on_main("$(git commit -m wip)") == 2)
    check("a commit inside an argument's $( … ) → blocked",
          on_main("echo $(git commit -m wip)") == 2)
    check("a commit inside a backtick substitution → blocked",
          on_main("echo `git commit -m wip`") == 2)
    check("a commit inside a double-quoted \"$( … )\" → blocked",
          on_main("echo \"$(git commit -m wip)\"") == 2)
    check("a commit after ';' inside $( … ) → blocked",
          on_main("x=$(true; git commit -m wip)") == 2)
    check("a substitution keeps the branch its chain created → passes",
          on_main("git checkout -b feat && x=$(git commit -m '[FIX] y')") == 0)
    check("a commit inside $( … ) is type-checked",
          run("x=$(git commit -m wip)") == 2)
    check("a ';' inside a leading assignment's $( … ) → blocked",
          on_main("x=$(true; echo) git commit -m wip") == 2)
    check("a '|' inside a leading assignment's $( … ) → blocked",
          on_main("x=$(a | b) git commit -m wip") == 2)
    check("a ';' inside a leading assignment's backticks → blocked",
          on_main("x=`true; echo` git commit -m wip") == 2)
    check("a case ')' inside a leading assignment's $( … ) → blocked",
          on_main("x=$(case a in a) echo;; esac) git commit -m wip") == 2)
    check("_split_segments does not split inside $( … )",
          _split_segments("x=$(true; echo) git commit") == (["x=$() git commit"], [None]))
    check("an empty double-quoted expansion before git → blocked",
          on_main("\"$x\"git commit -m wip") == 2)
    check("a double-quoted expansion standing alone is the command → passes",
          run("\"$x\" git commit -m wip") == 0)
    check("a quoted '$x' before git is text → passes", run("'$x'git commit -m wip") == 0)
    check("a switch to main behind an expansion → blocked",
          run("git checkout -b feat && $x git checkout main && git commit -m '[FIX] x'") == 2)
    check("a switch to a feature branch behind an expansion unblocks nothing → blocked",
          on_main("$x git checkout feature/y && git commit -m '[FIX] x'") == 2)
    check("a forced creation of a runtime name credits nothing → blocked",
          on_main("git checkout -B \"$b\" && git commit -m '[FIX] x'") == 2)
    check("a creation of a runtime name is credited → passes",
          on_main("git checkout -b \"$b\" && git commit -m '[FIX] x'") == 0)
    check("a switch to a runtime name drops the chain's branch → blocked",
          on_main("git checkout -b feat && git checkout \"$b\" && git commit -m '[FIX] x'") == 2)
    check("a feature switch behind an expansion keeps the chain's branch → passes",
          on_main("git checkout -b feat && $x git checkout feature/y && git commit -m '[FIX] x'")
          == 0)
    check("a cd behind an expansion may run: both cwds are checked → blocked",
          run("$x cd /other && git commit -m '[FIX] x'",
              branch=lambda cwd: "main" if cwd == "/other" else "feature/y") == 2)
    check("a cd behind an expansion may not run: both cwds are checked → blocked",
          run("$x cd /other && git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("'$( (true) )' may be empty: the command is git → blocked",
          on_main("$( (true) )git commit -m wip") == 2)
    check("a later cd in a function body moves no cwd → blocked",
          run("f() { true; cd /other; }; git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("a cd in a multi-line function body moves no cwd → blocked",
          run("f() {\n  cd /other\n}\ngit commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("a later cd in a case arm moves no cwd → blocked",
          run("case x in y) true; cd /other;; esac; git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("a case arm that runs its cd is checked in both cwds → blocked",
          run("case x in x) cd /other;; esac; git commit -m '[FIX] x'",
              branch=lambda cwd: "main" if cwd == "/other" else "feature/y") == 2)
    check("a cd after a function body still moves the cwd → passes",
          run("f() { true; }; cd /other; git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 0)
    check("an expansion before git on the shlex path with differing word counts → blocked",
          on_main("$x git commit -m\"$(cat <<'EOF'\nit's\nEOF\n)\"") == 2)
    check("'x=$(true)git' is one assignment; the command is 'commit' → passes",
          on_main("x=$(true)git commit -m wip") == 0)
    check("'esac' after '|' in a pattern does not close the case → blocked",
          on_main("case x in y|esac) git commit -m wip;; esac") == 2)
    check("'esac' after '(' in a pattern does not close the case → blocked",
          on_main("case x in (esac) git commit -m wip;; esac") == 2)
    check("'esac' as the case subject does not close the case → blocked",
          on_main("case esac in (esac) git commit -m wip;; esac") == 2)
    check("'esac' at a pattern list's start still closes an empty case → blocked",
          on_main("case x in\nesac; echo x | git commit -m wip") == 2)
    check("an extglob pattern's inner ')' does not open the arm → blocked",
          on_main("case x in @(a|x)) git commit -m wip;; esac") == 2)
    check("an extglob pattern's '|' is no pipe → passes",
          run("case x in @(a|x)) echo;; esac") == 0)
    check("'\"$@\"' may expand to no word before git → blocked",
          on_main("\"$@\" git commit -m wip") == 2)
    check("'\"${a[@]}\"' may expand to no word before git → blocked",
          on_main("\"${a[@]}\" git commit -m wip") == 2)
    check("an escaped '\\$x' in quotes is text → passes", on_main("\"\\$x\"git commit -m wip") == 0)
    check("a checkout inside $( … ) drops the chain's branch → blocked",
          on_main("git checkout -b feat && x=$(git checkout main) && git commit -m '[FIX] x'") == 2)
    check("a checkout after ';' inside $( … ) drops the chain's branch → blocked",
          on_main("git checkout -b feat && echo $(true; git checkout main) && git commit -m '[FIX] x'")
          == 2)
    check("a read-only git call inside $( … ) keeps the chain's branch → passes",
          on_main("git checkout -b feat && x=$(git rev-parse HEAD) && git commit -m '[FIX] x'") == 0)
    check("a brace-expanded switch target drops the chain's branch → blocked",
          on_main("git checkout -b feat && git checkout {main,} && git commit -m '[FIX] x'") == 2)
    check("a forced creation behind an expansion may land on main → blocked",
          run("$x git checkout -B main && git commit -m '[FIX] x'") == 2)
    check("a forced switch -C behind an expansion may land on main → blocked",
          run("$x git switch -C main && git commit -m '[FIX] x'") == 2)
    check("past the substitution depth cap a respelled commit → blocked",
          on_main("x=" + "$(echo " * 40 + "y" + ")" * 40 + "; git com\\mit -m wip") == 2)
    deep = 1500  # past the recursion limit wherever the suite's stack stands
    try:
        deep_code = on_main("git commit -m \"" + "$(echo \"" * deep + "x" + "\")" * deep + "\"")
    except RecursionError:
        deep_code = "RecursionError"
    check("a deeply nested \"$( … )\" commit does not fail open → blocked", deep_code == 2)
    check("a backtick substitution inside double quotes runs → blocked",
          on_main('echo "`git commit -m wip`"') == 2)
    check("an escaped backtick inside double quotes is text → passes",
          on_main('echo "\\`git commit -m wip\\`"') == 0)
    check("a $( … ) in a heredoc body under an unquoted delimiter runs → blocked",
          on_main("cat <<EOF\n$(git commit -m wip)\nEOF") == 2)
    check("a backtick in a heredoc body under an unquoted delimiter runs → blocked",
          on_main("cat <<EOF\n`git commit -m wip`\nEOF") == 2)
    check("a $( … ) after text in a heredoc body runs → blocked",
          on_main("cat <<-EOF\n\tnote: $(git commit -m wip)\n\tEOF\necho done") == 2)
    check("a heredoc body under a quoted delimiter is text → passes",
          on_main("cat <<'EOF'\n$(git commit -m wip)\nEOF") == 0)
    check("a heredoc body under a backslash-quoted delimiter is text → passes",
          on_main("cat <<\\EOF\n`git commit -m wip`\nEOF") == 0)
    check("an escaped '\\$(' in a heredoc body is text → passes",
          on_main("cat <<EOF\n\\$(git commit -m wip)\nEOF") == 0)
    check("a $( … ) in a heredoc body that never closes is no command → passes",
          on_main("cat <<EOF\n$(git commit -m wip\nEOF\necho ok") == 0)
    check("a function definition with no switch keeps the chain's branch → passes",
          on_main("git checkout -b feat && f() { true; } && git commit -m '[FIX] x'") == 0)
    check("a function body over several lines keeps the chain's branch → passes",
          on_main("git checkout -b feat && f()\n{\n  true\n} && git commit -m '[FIX] x'") == 0)
    check("a case with no switch keeps the chain's branch → passes",
          on_main("git checkout -b feat && case a in a) true;; b) echo;; esac && git commit -m '[FIX] x'")
          == 0)
    check("a nested case with no switch keeps the chain's branch → passes",
          on_main("git checkout -b feat && case a in a) case b in b) true;; esac;; esac"
                  " && git commit -m '[FIX] x'") == 0)
    check("a function body that switches drops the chain's branch → blocked",
          on_main("git checkout -b feat && f() { git checkout main; } && f && git commit -m '[FIX] x'")
          == 2)
    check("a function body that cds drops the chain's branch → blocked",
          on_main("git checkout -b feat && f() { cd /x; } && git commit -m '[FIX] x'") == 2)
    check("a function body running its arguments drops the chain's branch → blocked",
          on_main("git checkout -b feat && f() { \"$@\"; } && f git checkout main"
                  " && git commit -m '[FIX] x'") == 2)
    check("a case arm that switches drops the chain's branch → blocked",
          on_main("git checkout -b feat && case a in a) git checkout main;; esac"
                  " && git commit -m '[FIX] x'") == 2)
    check("a case subject that switches drops the chain's branch → blocked",
          on_main("git checkout -b feat && case $(git checkout main) in *) true;; esac"
                  " && git commit -m '[FIX] x'") == 2)
    check("a commit inside a case arm still reads the live branch → blocked",
          on_main("git checkout -b feat && case a in a) git commit -m '[FIX] x';; esac") == 2)
    check("a commit in a function body still reads the live branch → blocked",
          on_main("git checkout -b feat && f() { git commit -m '[FIX] x'; } && git checkout main && f")
          == 2)
    for arm in ("eval 'git checkout main'", "sh -c 'git checkout main'", "env git checkout main",
                "pushd /x", "g", "x=$(true)"):
        check(f"a case arm running {arm!r} drops the chain's branch → blocked",
              on_main(f"git checkout -b feat && case a in a) {arm};; esac && git commit -m '[FIX] x'")
              == 2)
    check("a function body running 'eval' drops the chain's branch → blocked",
          on_main("git checkout -b feat && f() { eval \"$1\"; } && git commit -m '[FIX] x'") == 2)
    check("an 'if' in a case arm that only echoes keeps the chain's branch → passes",
          on_main("git checkout -b feat && case a in a) if true; then echo y; fi;; esac"
                  " && git commit -m '[FIX] x'") == 0)
    check("a heredoc body's switch runs before a later '&&' commit → blocked",
          on_main("git checkout -b feat && cat <<EOF && git commit -m '[FIX] x'\n"
                  "$(git checkout main)\nEOF") == 2)
    check("a heredoc body's commit runs in the cwd before a later cd → blocked",
          run("cat <<EOF && cd /x\n$(git commit -m '[FIX] y')\nEOF",
              branch=lambda cwd: "feature/y" if cwd == "/x" else "main") == 2)
    check("a nested escaped backtick in a quoted backtick runs → blocked",
          on_main('echo "`echo \\`git commit -m wip\\``"') == 2)
    check("a nested escaped backtick in a heredoc body runs → blocked",
          on_main("cat <<EOF\n`echo \\`git commit -m wip\\``\nEOF") == 2)
    check("a nested escaped backtick in an unquoted backtick runs → blocked",
          on_main("echo `echo \\`git commit -m wip\\``") == 2)
    check("a cd in a substitution body moves no HEAD: the chain's branch holds → passes",
          on_main("git checkout -b feat && x=$(cd /tmp && ls) && git commit -m '[FIX] x'") == 0)
    check("a switch after a cd in a substitution body drops the chain's branch → blocked",
          on_main("git checkout -b feat && x=$(cd /tmp && git checkout main)"
                  " && git commit -m '[FIX] x'") == 2)
    for runner in ("sh -c 'git checkout main'", "bash -c 'git checkout main'",
                   "/bin/zsh -lc 'git checkout main'", "eval 'git checkout main'",
                   "eval \"$cmd\"", "source ./switch.sh", ". ./switch.sh",
                   "command eval 'git checkout main'"):
        check(f"a code runner {runner!r} drops the chain's branch → blocked",
              on_main(f"git checkout -b feat && {runner} && git commit -m '[FIX] x'") == 2)
        check(f"a code runner {runner!r} in a substitution body drops the chain's branch → blocked",
              on_main(f"git checkout -b feat && x=$({runner}) && git commit -m '[FIX] x'") == 2)
    check("a code runner on its own line drops the proven creation's branch → blocked",
          on_main("git checkout -b feat\nsh -c 'git checkout main'\ngit commit -m '[FIX] x'") == 2)
    # Residual, by decision: a script or build tool is not read, so it keeps the branch.
    for cmd in ("npm test", "make lint", "./run-tests.sh", "bash ./run-tests.sh"):
        check(f"{cmd!r} keeps the chain's branch → passes",
              on_main(f"git checkout -b feat && {cmd} && git commit -m '[FIX] x'") == 0)
    check("'||' after a clean case still drops the chain's branch → blocked",
          on_main("git checkout -b feat || case a in a) true;; esac && git commit -m '[FIX] x'") == 2)
    check("'||' between two clean compounds still drops the chain's branch → blocked",
          on_main("git checkout -b feat && case a in a) true;; esac || f() { true; }"
                  " && git commit -m '[FIX] x'") == 2)

    # _cli_precommit(): a malformed invocation is a caller bug (exit 1), which a
    # wrapper must be able to tell apart from a rejected commit (exit 2).
    # _cli_precommit takes no override hooks, so it shells out to real git. Point
    # it at an empty non-repo directory: _current_branch then returns "" and the
    # branch guard is inert, leaving these cases to test argv dispatch alone. Using
    # the live cwd instead would make them pass or fail with the checkout's branch
    # — green locally on a feature branch, red in CI on main.
    cli_cwd = tempfile.mkdtemp()

    def run_cli(argv):
        old_stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            # PREPENDED, not appended: appending would hand a trailing valueless
            # `--message` the `--cwd` flag as its value, silently converting the
            # malformed-invocation case into a valid one.
            return _cli_precommit(["--cwd", cli_cwd] + argv)
        finally:
            sys.stderr = old_stderr

    check("precommit CLI: missing --message exits 1 (not 2)",
          run_cli(["--precommit-check"]) == 1)
    check("precommit CLI: --message with no value exits 1",
          run_cli(["--precommit-check", "--message"]) == 1)
    # Bypass regression: the message value lands in argv, so a __main__ that
    # membership-tests "--test" BEFORE "--precommit-check" would run the test
    # suite and exit 0 for a commit message of exactly `--test` — read as ALLOW
    # by the wrapper. _cli_precommit must judge such a message on its text alone.
    check("precommit CLI: a message of '--test' is judged, not dispatched",
          run_cli(["--precommit-check", "--message", "--test"]) == 2)
    check("precommit CLI: a message of '--precommit-check' is judged too",
          run_cli(["--precommit-check", "--message", "--precommit-check"]) == 2)
    check("precommit CLI: a flag-shaped message with a valid type still passes",
          run_cli(["--precommit-check", "--message", "[FIX] --test harness wiring"]) == 0)

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    # Order matters: --precommit-check is tested FIRST. Its --message value is
    # arbitrary caller text that lands in argv, so a membership test for "--test"
    # would match a commit message of exactly `--test` — running the test suite
    # and exiting 0, which the wrapper reads as ALLOW. That is a guard bypass.
    # Checking the mode flag first makes the message text unable to select a mode.
    if "--precommit-check" in sys.argv:
        # Direct CLI mode: no hook payload on stdin, no never-raise wrapper —
        # a caller invoking this explicitly wants the verdict, and a crash here
        # must not be swallowed into a silent allow.
        sys.exit(_cli_precommit(sys.argv[1:]))
    elif "--test" in sys.argv:
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
