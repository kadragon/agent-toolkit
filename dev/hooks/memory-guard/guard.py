#!/usr/bin/env python3
"""memory-guard — hygiene gate for auto-memory writes.

Claude Code's auto-memory store (`~/.claude/projects/<slug>/memory/*.md`) is loaded
verbatim into every later session. A secret written there persists across sessions on a
surface nobody re-reads; a bidirectional or zero-width character makes what a reviewer
reads differ from what the model receives; an unbounded body turns a one-fact store into
a context tax. All three are decidable, so they belong in a hook rather than in
`harness-capture` prose that a model has to remember to follow.

Two entry points, one policy:

  * `main()` — the PreToolUse(Write|Edit) hook. Reads a hook payload on stdin and checks
    the pending content before it lands.
  * `--check-file <path>` — a direct CLI check, so `harness-capture` can pre-check a
    memory file (or piped content, via `-`) at its "show the write before applying" step
    and rewrite rather than get denied.

Both share `_scan_secrets`, `_scan_chars`, `_scan_size`, and `_scan_status`, so policy lives
in one place.

Four checks:
  1. Secret patterns — AWS access-key ids, GitHub tokens/PATs, Slack tokens, npm tokens,
     Anthropic and generic `sk-` provider keys, and PEM private-key headers. Each family
     carries a length floor so ordinary prose ("the sk- prefix") cannot trip it.
  2. Control and bidirectional formatting characters — C0/C1/DEL, zero-width, bidi marks,
     embeddings, isolates, and the invisible line separators. The table is carried
     deliberately from `scripts/ci/check_asset_hygiene.py` `_forbidden_chars()`, including
     its two carve-outs: CR is NOT checked (the repo's line-ending job owns CRLF) and
     U+FE0F is allowed (legitimate emoji presentation modifier). It is duplicated rather
     than imported because that file is repo CI tooling and is never installed onto the
     machine where this hook runs.
  3. Body size — `BODY_CHAR_CAP` characters, measured after stripping a leading `---`
     frontmatter block. `MEMORY.md` is exempt from this check alone: it is the index, and
     it grows one line per surviving memory by design.
  4. Lifecycle status — a `status:` key in the frontmatter must carry one of `STATUS_VALUES`,
     nested under `metadata:` where every consumer reads it. That field is what makes
     supersession decidable for `harness-capture`'s Memory hygiene pass and
     `harness-curate`'s prune lens, and both a typo and a misplaced key are silent rot: a
     filter reading `metadata.status == "superseded"` matches neither `superceded` nor a
     top-level `status:`. **An absent `status` is not a finding** — it reads as `active`, so
     existing memories need no migration and a memory written without `harness-capture` in
     context is never blocked.

Known gap, deliberate: on `Edit` the payload carries `new_string`, a fragment rather than
the resulting file, so checks 1, 2 and 4 run on that fragment and check 3 is skipped.
Reconstructing the post-edit size from a fragment is fragile, and the size cap is the one
rule a `Write` of the same file would catch anyway.

What check 4 reaches on a fragment is narrower than on a file, and the difference matters:
a fragment carrying the whole `status: <value>` line is graded on its value (a prose mention
— backticked, or carrying a list marker or trailing words — is not a match), but an `Edit`
that replaces the scalar alone (`old_string: active`, `new_string: superseded`) carries no
`status:` anchor and is not graded at all, and placement is never graded on a fragment
because there is no frontmatter to locate the key in. The brace refusal skips a fragment
for the same reason — it carries no frontmatter whose structure could be judged — so an
`Edit` introducing `metadata: {status: pending}` is admitted where a `Write` of the same
file is refused. It keys on whether the text OPENS a `---` block (`_structure_region`), not
on whether that block closes, and it looks past a BOM, blank lines or indentation before the
fence: a file missing its closing fence or carrying leading noise is still a file, and each
shape read as a fragment and skipped every structure check. The `Write` path and
`--check-file` see the finished file and are the reliable gate; `harness-capture` runs the
latter at its show-the-write step for exactly that reason.

Design contract (HOOK PATH ONLY): never-raise, always exit 0 (allow) unless a check fires
(exit 2). A firing check prints its reasons to stderr and exits 2. Everything else exits 0
— non-memory paths, other tools, malformed payloads, unreadable input. `--check-file` is
deliberately exempt from never-raise: a caller that asked for a verdict must not receive a
silent pass because this file itself is broken.

Run the regression suite: python3 guard.py --test
"""

import json
import os
import re
import sys

# Body characters, frontmatter excluded. The store's largest entry at the time this cap was
# set was 1579 bytes including frontmatter, so this leaves ~1.6x headroom: enough for one
# fact plus its Why/How-to-apply lines, not enough for a pasted transcript or log dump.
BODY_CHAR_CAP = 2000

# Auto-memory lifecycle. `active` is the default an absent field reads as; `superseded` marks
# an entry a later memory replaced; `rejected` marks one the user vetoed or the session
# disproved, kept so the same lesson is not re-learned. Ordered as written, not alphabetically:
# the tuple doubles as the message the guard prints.
STATUS_VALUES = ("active", "superseded", "rejected")

# A bare `status: <value>` YAML block-mapping key on its own line, capturing its indent so a
# misplaced top-level key can be told from one nested under `metadata:`. Deliberately strict:
# a body line mentioning `status: foo` inside prose, backticks, or a list item carries other
# characters on the line and does not match. A trailing `#` opens a comment only when
# whitespace precedes it — the YAML rule — so `status: active#typo` is read as the value
# `active#typo` and rejected rather than silently accepted as `active`.
#
# Supported syntax is block mapping, one key per line — which is also why this pattern
# cannot see a flow mapping (`metadata: {type: project, status: pending}`): the key and its
# value share a line with everything else in the braces. Parsing YAML properly would mean a
# dependency this hook deliberately does not have, so rather than admit that syntax
# unchecked, `_brace_lines` refuses any unquoted brace in the frontmatter and the author
# writes block mappings, which the store's own writer emits anyway.
STATUS_LINE = re.compile(
    r"^(?P<indent>[ \t]*)status:[ \t]*(?P<v>[^\r\n]*?)(?:[ \t]+#[^\r\n]*)?[ \t]*\r?$",
    re.MULTILINE,
)

# A block scalar header: `key: |`, `key: >`, with any chomping/indent indicator and an
# optional comment. Everything indented under one is literal text, not structure.
BLOCK_SCALAR = re.compile(r"^(?P<indent>[ \t]*)[^:\r\n]*:[ \t]*[|>][0-9+-]*[ \t]*(?:#[^\r\n]*)?$")


def _forbidden_chars() -> dict[int, str]:
    """Codepoint -> short reason. Mirrors scripts/ci/check_asset_hygiene.py."""
    banned: dict[int, str] = {}

    # C0 controls. TAB and LF are structure; CR belongs to the line-ending job.
    for cp in range(0x00, 0x20):
        if cp not in (0x09, 0x0A, 0x0D):
            banned[cp] = "C0 control character"
    banned[0x7F] = "DEL control character"

    # C1 controls — never meaningful in UTF-8 source text.
    for cp in range(0x80, 0xA0):
        banned[cp] = "C1 control character"

    # Bidirectional controls: the trojan-source reordering vector.
    for cp in (0x200E, 0x200F, 0x061C):
        banned[cp] = "bidirectional mark"
    for cp in range(0x202A, 0x202F):
        banned[cp] = "bidirectional embedding/override"
    for cp in range(0x2066, 0x206A):
        banned[cp] = "bidirectional isolate"

    # Zero-width and invisible characters.
    for cp in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF):
        banned[cp] = "zero-width/invisible character"

    # Invisible line breaks. Python's own splitlines() treats them as newlines.
    for cp in (0x2028, 0x2029):
        banned[cp] = "line/paragraph separator"

    return banned


FORBIDDEN_CHARS = _forbidden_chars()

# Each family carries a length floor so prose naming a prefix cannot trip the gate.
SECRET_PATTERNS = (
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("Slack token", re.compile(r"\b(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    # The tail accepts `-` and `_`, not just alphanumerics: today's dominant OpenAI shapes
    # (`sk-proj-…`, `sk-svcacct-…`) carry a second hyphen, and an alphanumeric-only tail
    # breaks at it four characters in — well under the floor, so a real key went unmatched.
    ("provider API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("PEM private key header", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


def _is_memory_file(path: str) -> bool:
    """True for a markdown file inside a `memory/` directory under a `.claude` ancestor.

    Matches `~/.claude/projects/<slug>/memory/foo.md` on both platforms without hardcoding
    the project slug. Split on both separators: a Windows payload carries backslashes, and
    a POSIX `pathlib` would read the whole thing as one filename.
    """
    if not path:
        return False
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if not parts or not parts[-1].lower().endswith(".md"):
        return False
    try:
        mem_idx = len(parts) - 1 - parts[::-1].index("memory")
    except ValueError:
        return False
    return ".claude" in parts[:mem_idx]


def _is_index_file(path: str) -> bool:
    """True for the store's `MEMORY.md` index, which the size cap exempts."""
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    return bool(parts) and parts[-1] == "MEMORY.md"


def _scan_secrets(text: str) -> list[str]:
    """Findings for known credential shapes. The matched value is never echoed back."""
    return [f"{label} detected" for label, pat in SECRET_PATTERNS if pat.search(text)]


def _scan_chars(text: str) -> list[str]:
    """Findings for control, bidi, and invisible characters, one line per distinct kind."""
    seen = set()
    for ch in text:
        reason = FORBIDDEN_CHARS.get(ord(ch))
        if reason:
            seen.add(f"{reason} U+{ord(ch):04X}")
    return sorted(seen)


def _body(text: str) -> str:
    """Content after a leading `---` frontmatter block, or the whole text when there is none."""
    if not text.startswith("---"):
        return text
    rest = text.split("\n", 1)
    if len(rest) < 2:
        return text
    # `\r?` is load-bearing: the CLI opens files with `newline=""`, so a CRLF memory file
    # keeps its `\r` and a `[ \t]*$` terminator would never match — leaving the whole
    # frontmatter counted against the body cap, and the two entry points disagreeing about
    # the same memory on line endings alone.
    closing = re.search(r"^---[ \t]*\r?$", rest[1], re.MULTILINE)
    return rest[1][closing.end():].lstrip("\r\n") if closing else text


def _scan_size(text: str) -> list[str]:
    """Finding when the body exceeds the cap. Frontmatter does not count against it."""
    n = len(_body(text))
    if n > BODY_CHAR_CAP:
        return [f"body is {n} characters, over the {BODY_CHAR_CAP}-character cap"]
    return []


def _frontmatter(text: str) -> str | None:
    r"""The leading `---` block's inner text, or None when there is no closed frontmatter.

    Shares `_body`'s delimiter rules, `\r?` included, so the two never disagree about where
    a CRLF memory file's frontmatter ends. The docstring is raw: an unescaped escape
    sequence in a plain string would embed a real control character in what `help()` shows.
    """
    if not text.startswith("---"):
        return None
    rest = text.split("\n", 1)
    if len(rest) < 2:
        return None
    closing = re.search(r"^---[ \t]*\r?$", rest[1], re.MULTILINE)
    return rest[1][:closing.start()] if closing else None


def _safe_value(value: str) -> str:
    """A rendering of `value` safe to print. Carries `_scan_secrets`'s never-echo policy.

    A rejected status value is whatever the file held, and the hook prints its findings to
    stderr, where they land in logs. Echoing a credential pasted where the value belongs is
    the one thing `_scan_secrets` is careful never to do, so only a short, plainly-not-a-secret
    token is shown back; anything else is named, not quoted.
    """
    return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,24}", value) else "(redacted)"


def _key_column(line: str) -> int:
    """Column where the line's key starts, counting `- ` sequence markers as indentation.

    A block scalar's content is what is indented past its KEY, not past the start of the
    line. For a sequence item (`- description: |`) those differ: the line's leading
    whitespace is 0 while the key sits at column 2, so measuring the line would treat the
    item's own sibling keys as literal text — and a `metadata: {status: pending}` beside
    such a scalar was admitted that way.
    """
    i = 0
    while i < len(line):
        if line[i] in " \t":
            i += 1
        elif line[i] == "-" and i + 1 < len(line) and line[i + 1] in " \t":
            i += 2
        else:
            break
    return i


def _brace_lines(region: str) -> list[int]:
    """1-based line numbers WITHIN `region` holding a `{` that is YAML structure, not text.

    Numbers are region-relative; the caller shifts them past the opening `---` so the
    finding names the line the author sees in the file.

    The rule is inverted on purpose, and the inversion is the point. An earlier version
    asked "does a flow mapping open at a key?", which meant enumerating the spellings that
    can open one — and every round of review found another the enumeration missed: the
    brace on a continuation line, a quoted key, an anchor before the brace, the explicit-key
    form, a mapping nested in a flow sequence, a block-sequence item (`- {status: x}`), a
    space before the colon. Each is ordinary YAML that `yaml.safe_load` parses and
    `STATUS_LINE` cannot see, so each admitted an invalid `status` silently. Chasing them
    one at a time is unbounded; asking instead "is there a brace here at all" is not.

    So a `{` anywhere in the frontmatter is refused unless it is plainly text: inside a
    quoted scalar, or indented under a block scalar (`description: |`). Those two carve-outs
    are what keeps a memory able to *describe* this syntax — including this hook's own
    documentation — while nothing can use it. The cost is that an unquoted prose brace
    (`description: use {name} here`) is refused too; the fix is to quote the value, which
    the finding says.

    Comments are not scanned: a `#` outside quotes ends the line, so a brace in a trailing
    comment is not structure either.
    """
    hits, block_indent = [], None
    for lineno, raw in enumerate(region.splitlines(), start=1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        indent = _key_column(line)
        if block_indent is not None:
            if indent > block_indent:
                continue  # literal text under a block scalar
            block_indent = None
        if BLOCK_SCALAR.match(line):
            block_indent = indent
            continue
        quote = None
        prev = ""
        for ch in line:
            if quote:
                # Inside a scalar. YAML escapes with a backslash only in double quotes; a
                # single-quoted scalar escapes its delimiter by doubling it, which this loop
                # handles naturally — the second quote re-opens a scalar that ends at the
                # next one, and a brace between them stays quoted either way.
                if ch == quote and not (quote == '"' and prev == "\\"):
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#" and prev in (" ", "\t", ""):
                break  # a comment: the rest of the line is not structure
            elif ch == "{":
                hits.append(lineno)
                break
            prev = ch
    return hits


# Whatever can sit before a frontmatter fence without being content: a BOM, blank lines,
# indentation. `_frontmatter`/`_body` test `startswith("---")` at byte 0, so any of these
# made a real file read as an Edit fragment and skipped every structure check.
LEADING_NOISE = "\ufeff \t\r\n"


def _structure_region(text: str) -> str | None:
    """The frontmatter to judge structure in, or None when the text opens none.

    Deliberately more lenient than `_frontmatter()` in one direction and stricter in
    another. More lenient: it tolerates a BOM or blank lines before the fence, and an
    absent closing fence — a `Write` of a file shaped either way is still a file, and
    gating on `_frontmatter()`'s exact `startswith("---")` + closed-block test let both
    through carrying a braced `status:`. Stricter: it returns None for text that opens no
    fence at all, which is how an `Edit` fragment and a `MEMORY.md` index stay exempt.

    `_frontmatter()` itself is left alone on purpose: `_body()` shares its delimiter rules,
    and loosening them would move the body-size cap's measurement as a side effect.
    """
    lead = len(text) - len(text.lstrip(LEADING_NOISE))
    rest = text[lead:]
    if not rest.startswith("---"):
        return None
    after = rest.split("\n", 1)
    if len(after) < 2:
        return ""
    closing = re.search(r"^---[ \t]*\r?$", after[1], re.MULTILINE)
    return after[1][:closing.start()] if closing else after[1]


def _scan_status(text: str) -> list[str]:
    """Findings for a `status:` key that is misplaced, whose value is outside `STATUS_VALUES`,
    or that a YAML flow mapping would hide from both checks.

    Scans the frontmatter of a full memory file; on an Edit fragment (no closed frontmatter)
    it scans the fragment itself — see the module docstring's known-gap note. An absent
    `status` is silent: the field is optional and reads as `active`.

    Placement is graded only on a full file. The schema nests `status` under `metadata:`
    beside `type`, and every consumer reads `metadata.status`, so a top-level key would be
    admitted by a value-only check and then be invisible to the prune lens — the judgment it
    carried silently lost. A fragment has no frontmatter to locate the key in, so it is
    graded on its value alone.
    """
    region = _frontmatter(text)
    is_full_file = region is not None
    if region is None:
        region = text
    allowed = ", ".join(STATUS_VALUES)
    findings = []
    structure_region = _structure_region(text)
    if structure_region is not None:
        # Before grading any value: braces can carry `status:` where STATUS_LINE cannot see
        # it, so that syntax would be admitted silently. The refusal is what keeps the value
        # check total, so it runs whenever the text opens frontmatter — a file whose closing
        # `---` is missing included. Only an Edit fragment, which opens none, is exempt:
        # there is no frontmatter in it whose structure could be judged.
        for lineno in _brace_lines(structure_region):
            # +1 for the opening `---`, which `_frontmatter` strips: the number in the
            # finding has to be the one the author counts to in the file.
            findings.append(
                f"frontmatter line {lineno + 1} carries an unquoted `{{` — memory frontmatter is "
                "block mappings, one key per line, because a `status:` inside braces is never "
                "checked. If the brace is prose, quote the value or use a `|` block scalar"
            )
    for m in STATUS_LINE.finditer(region):
        if is_full_file and not m.group("indent"):
            findings.append(
                "status key sits at the top level of the frontmatter — nest it under "
                "`metadata:`, where every consumer reads it"
            )
        # Strip twice around the quotes: `"  active  "` is padding inside a quoted scalar,
        # not a different value, and rejecting it would block a legitimate memory.
        value = m.group("v").strip().strip("\"'").strip()
        if value in STATUS_VALUES:
            continue
        if value:
            findings.append(f"status value '{_safe_value(value)}' is not one of {allowed}")
        else:
            findings.append(f"status key is empty — expected one of {allowed}")
    return list(dict.fromkeys(findings))


def check(text: str, *, size: bool = True) -> list[str]:
    """All findings for `text`. `size=False` for an Edit fragment — see the module docstring."""
    findings = _scan_secrets(text) + _scan_chars(text) + _scan_status(text)
    if size:
        findings += _scan_size(text)
    return findings


def main() -> int:
    """PreToolUse hook path. Returns the exit code; never raises past the __main__ wrapper."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name")
    if tool not in ("Write", "Edit"):
        return 0
    ti = data.get("tool_input", {}) or {}
    path = ti.get("file_path") or ""
    if not _is_memory_file(path):
        return 0

    if tool == "Write":
        text = ti.get("content") or ""
        size = not _is_index_file(path)
    else:
        text = ti.get("new_string") or ""
        size = False
    if not text:
        return 0

    findings = check(text, size=size)
    if not findings:
        return 0
    print(f"memory-guard: blocked {tool} to {os.path.basename(path)}", file=sys.stderr)
    for f in findings:
        print(f"  - {f}", file=sys.stderr)
    print(
        "  Rewrite the memory so it passes — redact the credential, strip the invisible "
        "characters, cut the body, or correct the status value. There is no bypass marker.",
        file=sys.stderr,
    )
    return 2


def _cli_check_file(argv: list[str]) -> int:
    """`--check-file <path|->`. Exit 1 on any finding, 2 on a usage or read error."""
    try:
        target = argv[argv.index("--check-file") + 1]
    except (ValueError, IndexError):
        print("usage: guard.py --check-file <path|->", file=sys.stderr)
        return 2
    try:
        if target == "-":
            text = sys.stdin.read()
        else:
            with open(target, encoding="utf-8", newline="") as fh:
                text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"guard.py: cannot read {target}: {e}", file=sys.stderr)
        return 2

    findings = check(text, size=not _is_index_file(target))
    if not findings:
        print(f"memory-guard: clean ({len(_body(text))} body characters)")
        return 0
    print(f"memory-guard: {len(findings)} finding(s) in {target}", file=sys.stderr)
    for f in findings:
        print(f"  - {f}", file=sys.stderr)
    return 1


def _test() -> None:
    import io

    fails = []

    def ok(name, cond):
        print(f"{'PASS' if cond else 'FAIL'}: {name}")
        if not cond:
            fails.append(name)

    def hook(payload):
        old, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
        try:
            return main()
        finally:
            sys.stdin = old

    mem = "/home/me/.claude/projects/slug/memory/note.md"
    win = "C:\\Users\\me\\.claude\\projects\\slug\\memory\\note.md"

    # --- path predicate ---
    ok("posix memory path matches", _is_memory_file(mem))
    ok("windows memory path matches", _is_memory_file(win))
    ok("index file matches too", _is_memory_file("/home/me/.claude/x/memory/MEMORY.md"))
    ok("memory dir without .claude ancestor does not match",
       not _is_memory_file("/repo/memory/note.md"))
    ok(".claude without memory dir does not match",
       not _is_memory_file("/home/me/.claude/settings.md"))
    ok("non-markdown in memory dir does not match",
       not _is_memory_file("/home/me/.claude/x/memory/note.json"))
    ok("a file literally named memory.md is not the directory",
       not _is_memory_file("/home/me/.claude/memory.md"))
    ok("empty path does not match", not _is_memory_file(""))
    ok("MEMORY.md recognised as index", _is_index_file(mem.replace("note.md", "MEMORY.md")))
    ok("ordinary memory not treated as index", not _is_index_file(mem))

    # --- secret families. Fixtures are assembled at runtime so no complete token
    # literal ever sits in this file for a scanner (or a reader) to mistake for real.
    families = {
        "AWS": "AKIA" + "Q" * 16,
        "GitHub token": "ghp_" + "b" * 36,
        "GitHub PAT": "github_pat_" + "c" * 30,
        "Slack": "xoxb-" + "1" * 12,
        "Slack app-level": "xapp-" + "2" * 12,
        "OpenAI project": "sk-proj-" + "g" * 40,
        "npm": "npm_" + "d" * 36,
        "Anthropic": "sk-ant-" + "e" * 30,
        "provider": "sk-" + "f" * 30,
        "PEM": "-----BEGIN RSA PRIVATE KEY-----",
    }
    for label, fixture in families.items():
        ok(f"secret detected: {label}", bool(_scan_secrets(f"note {fixture} here")))
    ok("prose naming a prefix is not a secret",
       not _scan_secrets("tokens start with ghp_ or sk-ant- prefixes"))
    ok("short lookalike is not a secret", not _scan_secrets("sk-abc123"))
    ok("clean prose has no secret finding", not _scan_secrets("plain memory body"))

    # --- characters ---
    ok("bidi override rejected", bool(_scan_chars("a\u202eb")))
    ok("zero-width space rejected", bool(_scan_chars("a\u200bb")))
    ok("C0 control rejected", bool(_scan_chars("a\x01b")))
    ok("C1 control rejected", bool(_scan_chars("a\x85b")))
    ok("DEL rejected", bool(_scan_chars("a\x7fb")))
    ok("line separator rejected", bool(_scan_chars("a\u2028b")))
    ok("CR is not this check's business", not _scan_chars("a\r\nb"))
    ok("emoji variation selector allowed", not _scan_chars("check \u2705\ufe0f done"))
    ok("tab and newline allowed", not _scan_chars("a\tb\nc"))
    ok("korean body allowed", not _scan_chars("한글 본문은 통과한다"))
    ok("one line per distinct kind", len(_scan_chars("\u202e\u202e\u200b")) == 2)

    # --- size ---
    fm = "---\nname: x\ndescription: y\n---\n\n"
    ok("body at the cap passes", not _scan_size(fm + "z" * BODY_CHAR_CAP))
    ok("body one over the cap fails", bool(_scan_size(fm + "z" * (BODY_CHAR_CAP + 1))))
    ok("frontmatter does not count toward the cap",
       not _scan_size("---\nk: " + "v" * 3000 + "\n---\n\n" + "z" * 10))
    ok("body without frontmatter is measured whole",
       bool(_scan_size("z" * (BODY_CHAR_CAP + 1))))
    ok("unterminated frontmatter is measured whole",
       bool(_scan_size("---\nname: x\n" + "z" * (BODY_CHAR_CAP + 1))))
    crlf_fm = "---\r\nname: x\r\ndescription: y\r\n---\r\n\r\n"
    ok("CRLF frontmatter is stripped like LF", len(_body(crlf_fm + "z" * 10)) == 10)
    ok("CRLF body under the cap passes", not _scan_size(crlf_fm + "z" * 10))
    ok("CRLF body over the cap still fails",
       bool(_scan_size(crlf_fm + "z" * (BODY_CHAR_CAP + 1))))
    ok("a --- rule inside the body does not re-split it",
       len(_body(fm + "text\n\n---\n\nmore")) == len("text\n\n---\n\nmore"))
    ok("frontmatter-only file has an empty body", _body("---\nname: x\n---\n") == "")

    # --- lifecycle status ---
    def st(fm_lines, body="body text"):
        return f"---\nname: x\nmetadata:\n{fm_lines}---\n\n{body}"

    for value in STATUS_VALUES:
        ok(f"status '{value}' allowed", not _scan_status(st(f"  type: project\n  status: {value}\n")))
    ok("absent status is not a finding", not _scan_status(st("  type: project\n")))
    ok("unknown status value rejected",
       bool(_scan_status(st("  type: project\n  status: pending\n"))))
    ok("empty status value rejected", bool(_scan_status(st("  type: project\n  status:\n"))))
    ok("quoted status value allowed",
       not _scan_status(st('  type: project\n  status: "superseded"\n')))
    ok("trailing comment does not break the value",
       not _scan_status(st("  type: project\n  status: rejected  # user vetoed\n")))
    ok("status in the body is ignored on a full file",
       not _scan_status(st("  type: project\n", body="status: pending")))
    ok("a prose mention is not a YAML key",
       not _scan_status(st("  type: project\n", body="- `status: pending` is invalid")))
    ok("bad value reported once, not per occurrence",
       len(_scan_status(st("  status: pending\n  status: pending\n"))) == 1)
    ok("CRLF frontmatter status is read",
       bool(_scan_status("---\r\nmetadata:\r\n  status: pending\r\n---\r\n\r\nbody")))
    ok("edit fragment status is checked", bool(_scan_status("  status: pending\n")))
    ok("clean edit fragment passes", not _scan_status("  status: superseded\n"))
    ok("unterminated frontmatter still checks the status",
       bool(_scan_status("---\nmetadata:\n  status: pending\n")))
    ok("MEMORY.md index lines carry no status", not _scan_status("- [T](f.md) — hook\n"))
    # --- braces in frontmatter: refused outright, quoted and block scalars excepted ---
    # Each `True` case is real YAML that `yaml.safe_load` parses as a mapping carrying
    # `status`, and that `STATUS_LINE` cannot see. The list is what two review rounds found
    # by enumerating spellings — the reason the rule is now "is there a brace" instead.
    for label, fmb in (
        ("same line", "metadata: {type: project, status: pending}\n"),
        ("continuation line", "metadata:\n  {type: project, status: pending}\n"),
        ("quoted key", '"metadata": {status: pending}\n'),
        ("anchor before the brace", "metadata: &m {status: pending}\n"),
        ("a tag before the brace", "metadata: !!map {status: pending}\n"),
        ("explicit-key form", "? metadata\n: {status: pending}\n"),
        ("nesting in a flow sequence", "metadata: [{status: pending}]\n"),
        ("a block-sequence item", "things:\n  - {status: pending}\n"),
        ("a space before the colon", "metadata : {status: pending}\n"),
        ("a tab-indented continuation", "metadata:\n\t{status: pending}\n"),
        ("a multi-line flow mapping", "metadata: {\n  status: pending }\n"),
    ):
        ok(f"a brace via {label} is refused",
           any("unquoted" in f
               for f in _scan_status(f"---\nname: x\n{fmb}---\n\nbody")))
    ok("the finding names the line and the way out",
       any("line 3" in f and "block scalar" in f
           for f in _scan_status("---\nname: x\nmetadata: {status: pending}\n---\n\nbody")))
    ok("block mapping still passes",
       not _scan_status(st("  type: project\n  status: active\n")))
    ok("a plain flow sequence carries no brace",
       not _scan_status("---\nname: x\ntags: [a, b]\nmetadata:\n  status: active\n---\n\nbody"))
    ok("a double-quoted scalar holding braces is text",
       not _scan_status('---\ndescription: "{not structure}"\n---\n\nbody'))
    ok("a single-quoted scalar holding braces is text",
       not _scan_status("---\ndescription: '{x}'\n---\n\nbody"))
    ok("a block scalar may quote the syntax it warns about",
       not _scan_status("---\ndescription: |\n  metadata: {status: pending} example\n---\n\nbody"))
    ok("a brace in a trailing comment is not structure",
       not _scan_status(st("  status: active  # use {name}\n")))
    ok("a brace in the body is not frontmatter structure",
       not _scan_status(st("  type: project\n", body="metadata: {status: pending}")))
    ok("an unterminated frontmatter file is a file, not a fragment",
       any("unquoted" in f for f in
           _scan_status("---\nname: x\nmetadata: {status: pending}\n\nbody, no fence")))
    ok("a sequence item's sibling key is not swallowed by its block scalar",
       any("unquoted" in f for f in _scan_status(
           "---\nitems:\n- description: |\n    text\n  metadata: {status: pending}\n---\n\nbody")))
    ok("a sequence item's block scalar still holds literal text",
       not _scan_status(
           "---\nitems:\n- description: |\n    metadata: {status: pending} example\n---\n\nbody"))
    ok("a MEMORY.md index line is not frontmatter", not _scan_status("- [T](f.md) — {hook}\n"))
    # A fence is still a fence with a BOM, a blank line or indentation in front of it.
    # Each of these read as an Edit fragment before `_structure_region`, skipping every
    # structure check on a file that a frontmatter reader parses normally.
    for label, lead in (("a blank line", "\n"), ("spaces", "   "), ("a BOM", "\ufeff")):
        ok(f"{label} before the fence does not disable the check",
           any("unquoted" in f for f in _scan_status(
               f"{lead}---\nname: x\nmetadata: {{status: pending}}\n---\n\nbody")))
    ok("a brace in the body is still not structure",
       not _scan_status("---\nname: x\n---\n\nmetadata: {status: pending}"))
    ok("an unquoted prose brace is refused, and says how to fix it",
       any("quote the value" in f
           for f in _scan_status("---\ndescription: use {name} here\n---\n\nbody")))
    ok("an edit fragment is not graded on structure",
       not _scan_status("metadata: {type: project, status: active}\n"))
    ok("top-level status is flagged as misplaced on a full file",
       any("top level" in f for f in _scan_status(
           "---\nname: x\nstatus: superseded\n---\n\nbody")))
    ok("nested status is not flagged as misplaced",
       not _scan_status(st("  type: project\n  status: superseded\n")))
    ok("a misplaced key with a bad value reports both",
       len(_scan_status("---\nstatus: pending\n---\n\nbody")) == 2)
    ok("placement is not graded on an edit fragment",
       not _scan_status("status: superseded\n"))
    ok("a # without leading whitespace stays part of the value",
       bool(_scan_status(st("  status: active#typo\n"))))
    ok("quoted value with inner padding is accepted",
       not _scan_status(st('  status: "  active  "\n')))
    ok("an invalid value is never echoed verbatim",
       all(families["GitHub token"] not in f
           for f in _scan_status(st(f'  status: {families["GitHub token"]}\n'))))
    ok("a short ordinary typo is still quoted back for the author",
       any("superceded" in f for f in _scan_status(st("  status: superceded\n"))))
    ok("_frontmatter docstring carries no literal control character",
       "\r" not in (_frontmatter.__doc__ or ""))

    # --- hook path ---
    ok("clean write allowed",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem, "content": fm + "fine"}}) == 0)
    ok("secret write blocked",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem, "content": fm + families["GitHub token"]}}) == 2)
    ok("oversize write blocked",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem, "content": fm + "z" * (BODY_CHAR_CAP + 1)}}) == 2)
    ok("windows path is gated too",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": win, "content": fm + families["AWS"]}}) == 2)
    ok("oversize index write allowed (size cap exempt)",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem.replace("note.md", "MEMORY.md"),
                            "content": "- x\n" * 900}}) == 0)
    ok("secret in the index is still blocked",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem.replace("note.md", "MEMORY.md"),
                            "content": families["Slack"]}}) == 2)
    ok("edit fragment with a secret blocked",
       hook({"tool_name": "Edit",
             "tool_input": {"file_path": mem, "new_string": families["npm"]}}) == 2)
    ok("oversize edit fragment allowed (size skipped on Edit)",
       hook({"tool_name": "Edit",
             "tool_input": {"file_path": mem, "new_string": "z" * (BODY_CHAR_CAP + 1)}}) == 0)
    ok("bad status write blocked",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem,
                            "content": st("  type: project\n  status: pending\n")}}) == 2)
    ok("good status write allowed",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem,
                            "content": st("  type: project\n  status: active\n")}}) == 0)
    ok("statusless write allowed",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": mem, "content": st("  type: project\n")}}) == 0)
    ok("bad status edit fragment blocked",
       hook({"tool_name": "Edit",
             "tool_input": {"file_path": mem, "new_string": "  status: stale\n"}}) == 2)
    ok("write outside the store allowed",
       hook({"tool_name": "Write",
             "tool_input": {"file_path": "/repo/notes.md",
                            "content": families["GitHub token"]}}) == 0)
    ok("other tools pass through",
       hook({"tool_name": "Bash", "tool_input": {"command": families["AWS"]}}) == 0)
    ok("missing file_path passes through",
       hook({"tool_name": "Write", "tool_input": {"content": families["AWS"]}}) == 0)
    ok("empty content passes through",
       hook({"tool_name": "Write", "tool_input": {"file_path": mem, "content": ""}}) == 0)

    old, sys.stdin = sys.stdin, io.StringIO("not json")
    try:
        ok("malformed payload fails open", main() == 0)
    finally:
        sys.stdin = old

    # --- CLI path ---
    ok("CLI without an argument is a usage error", _cli_check_file(["--check-file"]) == 2)
    ok("CLI on a missing file is a read error",
       _cli_check_file(["--check-file", "/nonexistent/definitely/x.md"]) == 2)
    old, sys.stdin = sys.stdin, io.StringIO(fm + families["Anthropic"])
    try:
        ok("CLI on stdin reports a finding", _cli_check_file(["--check-file", "-"]) == 1)
    finally:
        sys.stdin = old
    old, sys.stdin = sys.stdin, io.StringIO(fm + "clean body")
    try:
        ok("CLI on clean stdin exits 0", _cli_check_file(["--check-file", "-"]) == 0)
    finally:
        sys.stdin = old

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    # Order matters: --check-file is dispatched first. Its argument is arbitrary caller
    # text, so a membership test for "--test" would let a file named `--test` select the
    # test suite and exit 0 — which the hook wrapper would read as ALLOW.
    if "--check-file" in sys.argv:
        # Direct CLI mode: no never-raise wrapper. A caller that asked for a verdict must
        # not get a silent allow because this file is broken.
        sys.exit(_cli_check_file(sys.argv[1:]))
    elif "--test" in sys.argv:
        _test()
    else:
        _code = 0
        try:
            _code = main()
        except SystemExit as e:
            _code = e.code if isinstance(e.code, int) else 0
        except BaseException:
            pass
        sys.exit(_code)
