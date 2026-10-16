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
     The branch is the live one, read with `rev-parse` in each cwd the
     commit may run in, before the command runs: a `cd` is followed, and a
     `cd` that may not run (case arm, function body, subshell, behind an
     expansion that may be empty) adds its directory to the ones checked.
     A branch the same command creates or switches to is not seen, so
     `git checkout -b x && git commit` on main blocks: create or switch the
     branch in a separate command first. The reverse is an accepted
     residual: a HEAD move the hook does not read (`git checkout main`, a
     script, `sh -c`, `eval`) passes on a live feature branch. Predicting
     the branch a command will land on from its text was tried and dropped
     (2026-10-16): it grew without bound and still blocked common chains.
     Finding the commit stays thorough: a commit after a heredoc,
     behind a comment, keyword, redirect or expansion, in a case arm,
     function body or command substitution is still found.
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
the same live `rev-parse`: the caller commits at the moment it invokes this.
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
    from the word and its raw in place. Only commit detection asks for it.

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

    The one place that tracks quoting; _strip_comments, _split_segments
    and _has_expandable_subst all read its answer, so they
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
    segments, operators, _, _ = _split_full(command)
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

    Returns (segments, operators, arms, bodies): a list of stripped segment
    strings (individual segments may be empty); a parallel list of the
    separator operator that PRECEDES each segment (operators[0] is None; the
    rest are one of '&&' '||' '|' ';' '&', or ')' after a case pattern); per
    segment, whether it sits in a case arm; and per segment, the bodies of
    the command substitutions in it, quoted or not, which run before it.
    """
    cls, balanced, subs, arm = _scan_full(command)
    if not balanced:
        # an unclosed quote: split on every separator
        segs = re.split(r"&&|\|\||[;|\n&]", _strip_comments(command))
        return segs, [None] * len(segs), [False] * len(segs), [[] for _ in segs]

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
    arms, bodies = [], []
    current, in_arm, found = [], False, []

    def end_segment():
        nonlocal current, in_arm, found
        segments.append("".join(current).strip())
        arms.append(in_arm)
        bodies.append(found)
        current, in_arm, found = [], False, []

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
    return segments, operators, arms, bodies


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


# How deep command substitutions are read inside one another. Each level
# reads its whole body again, so a pathological nesting is cut off here
# rather than left to run for seconds.
_MAX_SUBST_DEPTH = 32


def _commit_segments(command, cwds, level=0):
    """The git commits in command, as (segment, cwds) each: the cwds the
    commit may run in, followed through `cd`. A `cd` that may not run (in a
    case arm, a function body, a subshell, or behind an expansion that may be
    empty) adds its directory to the ones already possible.

    A command substitution is a command of its own, run in the cwd of the
    segment holding it; its commits are read the same way, recursively, to
    _MAX_SUBST_DEPTH: past it RecursionError, as when the stack runs out.
    """
    if level > _MAX_SUBST_DEPTH:
        raise RecursionError("command substitutions nest too deep")
    segments, operators, arms, bodies = _split_full(command)
    running_cwds = list(cwds)
    fn_depth = 0             # braces and parens open in a function body being defined
    fn_pending = False       # a function head seen alone: its body follows
    commits = []
    for idx, seg in enumerate(segments):
        stripped = seg.strip()
        head, depth, bare_head = _function_nesting(stripped)
        in_body = fn_depth > 0 or (fn_pending and stripped)
        if in_body or head:
            fn_pending = bare_head
            fn_depth = max(fn_depth + depth, 0)
        guarded = operators[idx] == ")" or arms[idx] or head or bool(in_body)
        for body in bodies[idx]:
            commits += _commit_segments(body, running_cwds, level + 1)
        exp_toks = _tokens(stripped, expansions=True)
        if len(exp_toks) >= 2 and exp_toks[0] == "cd":
            cd_cwds = list(dict.fromkeys(
                os.path.abspath(os.path.join(c, exp_toks[1])) for c in running_cwds))
            hidden = exp_toks != _tokens(stripped)
            running_cwds = (list(dict.fromkeys(running_cwds + cd_cwds)) if guarded or hidden
                            else cd_cwds)
        if _is_git_commit(stripped):
            # -C overrides the cd-tracked cwd for this git call
            commits.append((stripped, list(dict.fromkeys(_git_cwd(stripped, c) for c in running_cwds))))
    return commits


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
    try:
        commit_segs = _commit_segments(command, [env_cwd])
    except RecursionError:
        # nesting past what the analysis can read: passing it would let a
        # commit hidden in it through (fail-open), and its spelling cannot be
        # trusted (`com\mit`), so nothing past it is read
        _block("commit-guard: blocked — the command nests too deep to check for a commit.")

    if not commit_segs:
        return  # not a git commit invocation → pass through

    # Check ALL commit segments — any failure blocks the entire command
    for seg, effective_cwds in commit_segs:
        # --- Branch guard ---------------------------------------------------------
        # The live branch, read before the command runs: a branch the same
        # command creates or switches to is not seen. A cd that may or may
        # not have run leaves more than one cwd: each is checked.
        for effective_cwd in effective_cwds:
            branch = _current_branch(effective_cwd, _override=branch_override)
            if branch in ("main", "master"):
                if not _marker_present(effective_cwd, _override=marker_override):
                    _block(
                        f"commit-guard: blocked — branch '{branch}' is protected. "
                        "Create or switch to a feature branch in a separate command first "
                        "(the branch is read before this command runs), or add "
                        "<!-- commit-guard: allow-main --> to AGENTS.md or CLAUDE.md to opt in."
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

    # the branch is the live one, read before the command runs: a branch the
    # same command creates or switches to is not seen (user decision 2026-10-16)
    def on_main(command):
        return run(command, branch="main", marker=False)

    def block_reason(command):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"})
        old_stdin, sys.stdin = sys.stdin, io.StringIO(payload)
        old_stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            main(branch_override="main", marker_override=False)
        except SystemExit:
            pass
        finally:
            reason = sys.stderr.getvalue()
            sys.stdin, sys.stderr = old_stdin, old_stderr
        return reason

    check("live main: checkout -b X && commit → blocked",
          on_main("git checkout -b feature/x && git commit -m '[FEAT] y'") == 2)
    check("live main: checkout -qb X && commit → blocked",
          on_main("git checkout -qb feature/x && git commit -m '[FEAT] y'") == 2)
    check("live main: switch -c X && commit → blocked",
          on_main("git switch -c feature/x && git commit -m '[FEAT] y'") == 2)
    check("live feature: checkout -b X && commit → passes",
          run("git checkout -b feature/y && git commit -m '[FEAT] y'", branch="feature/x") == 0)
    check("live feature: a switch to main the hook does not follow → passes (accepted residual)",
          run("git checkout main && git commit -m '[FEAT] y'", branch="feature/x") == 0)
    check("live feature: sh -c that may switch → passes (accepted residual)",
          run("sh -c 'git checkout main' && git commit -m '[FEAT] y'", branch="feature/x") == 0)
    check("the main block names the separate-command fix",
          "separate command" in block_reason("git checkout -b x && git commit -m '[FEAT] y'"))


    check("semicolon: a bad type is still type-blocked",
          on_main("git checkout -b feature/x\ngit commit -m 'wip'") == 2)

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
    check("a redirect operator is still text, not a separator",
          _split_segments("make 2>&1 | tee log")[1] == [None, "|"])
    check("'&&', a comment, then newline does not hide a commit on main → blocked",
          on_main("git add -A && # stage\ngit commit -m '[FEAT] y'") == 2)
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

    check("semicolon: an earlier `export GIT_DIR` → blocked",
          on_main("export GIT_DIR=/other/.git; git checkout -b feature/x; "
                  "git commit -m '[FEAT] y'") == 2)
    check("semicolon: an earlier GIT_DIR assignment line → blocked",
          on_main("GIT_DIR=/other/.git\ngit checkout -b feature/x\ngit commit -m '[FEAT] y'") == 2)


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
          on_main("git checkout -b feat; f() { git commit -m '[FIX] x'; }; git checkout main; f") == 2)

    # third review: a case arm or function definition changes no cwd
    check("a cd in a function never called moves no cwd → blocked",
          run("f() { cd /other; }; git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("a cd in a case arm that may not match moves no cwd → blocked",
          run("case x in y) cd /other;; esac; git commit -m '[FIX] x'",
              branch=lambda cwd: "feature/y" if cwd == "/other" else "main") == 2)
    check("an empty one-line case closes, so '|' still pipes → blocked",
          on_main("case x in esac; echo x | git commit -m wip") == 2)
    check("a long run of reserved words does not overflow the scanner → blocked",
          on_main("if " * 1200 + "case x in x) true;; esac; git commit -m wip") == 2)
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
    check("a heredoc body's commit runs in the cwd before a later cd → blocked",
          run("cat <<EOF && cd /x\n$(git commit -m '[FIX] y')\nEOF",
              branch=lambda cwd: "feature/y" if cwd == "/x" else "main") == 2)
    check("a nested escaped backtick in a quoted backtick runs → blocked",
          on_main('echo "`echo \\`git commit -m wip\\``"') == 2)
    check("a nested escaped backtick in a heredoc body runs → blocked",
          on_main("cat <<EOF\n`echo \\`git commit -m wip\\``\nEOF") == 2)
    check("a nested escaped backtick in an unquoted backtick runs → blocked",
          on_main("echo `echo \\`git commit -m wip\\``") == 2)
    for runner in ("sh -c 'git checkout main'", "bash -c 'git checkout main'",
                   "/bin/zsh -lc 'git checkout main'", "eval 'git checkout main'",
                   "eval \"$cmd\"", "source ./switch.sh", ". ./switch.sh",
                   "command eval 'git checkout main'"):
        check(f"a code runner {runner!r} drops the chain's branch → blocked",
              on_main(f"git checkout -b feat && {runner} && git commit -m '[FIX] x'") == 2)
        check(f"a code runner {runner!r} in a substitution body drops the chain's branch → blocked",
              on_main(f"git checkout -b feat && x=$({runner}) && git commit -m '[FIX] x'") == 2)
    for runner in ("bash -o pipefail -c 'git checkout main'", "bash --login -c 'git checkout main'",
                   "bash -O extglob -c 'git checkout main'", "bash --norc -c 'git checkout main'",
                   "env sh -c 'git checkout main'", "/usr/bin/env FOO=1 bash -c 'git checkout main'",
                   "builtin eval 'git checkout main'", "command -p eval 'git checkout main'",
                   "nohup sh -c 'git checkout main'", "timeout 5 sh -c 'git checkout main'",
                   "timeout -s KILL 5 sh -c 'git checkout main'"):
        check(f"a code runner {runner!r} drops the chain's branch → blocked",
              on_main(f"git checkout -b feat && {runner} && git commit -m '[FIX] x'") == 2)

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
