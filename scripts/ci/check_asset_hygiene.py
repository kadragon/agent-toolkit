#!/usr/bin/env python3
"""Hygiene checks for shipped plugin assets (dev/, prod/).

Everything under `dev/` and `prod/` is installed into other repositories and loaded
verbatim into an agent's context. Three checks run over every tracked file under those
roots, catching defects no other job in `harness-check.yml` sees. (a) and (b) are two
shapes of one risk — text that reads differently to a reviewer than to the model — and
(c) is a separate one:

(a) Invisible and control characters — bidirectional overrides, zero-width
    characters, C0/C1 controls. In shipped agent instructions these are a
    prompt-injection vector: what a reviewer reads and what the model receives can
    differ. `\\r` is deliberately NOT checked here — the *Executable line ending
    check* job owns CRLF, and reporting it twice under two names helps nobody.
    U+FE0F (variation selector) is allowed: the repo uses it legitimately as an
    emoji presentation modifier.

(b) Cyrillic homoglyphs adjacent to ASCII — the trojan-source shape, where `а`
    (U+0430) is substituted into an otherwise-Latin identifier so `аdmin` reads as
    `admin`. Greek is deliberately OUT of scope even though it carries lookalikes:
    `dev/skills/repo-dependabot/scripts/consolidate-deps.py` uses `α` in `1.0.0α` at
    six sites as an intentional non-ASCII version-parsing fixture, every one of them
    adjacent to ASCII digits. A Greek rule of this shape would fail a legitimate test
    on its first run, and weakening that test to satisfy a linter is precisely the
    move this repo forbids. Cyrillic is the real substitution vector and the tree
    holds zero occurrences, so the rule starts there. Add Greek only against a
    recorded case.

(c) Hardcoded personal paths — `/Users/<name>`, `C:\\Users\\<name>`, `/home/<name>`.
    These leak the author's machine layout into another user's repo and silently
    break there. Documentation and test fixtures legitimately need path-shaped
    examples, so a placeholder allowlist (`me`, `someone`, `<name>`, `$USER`, …)
    carries them; the eight path-shaped strings in the tree today are all
    placeholders of exactly that kind.

Derived from the ECC harness repo (`affaan-m/ECC`), which enforces (a)/(b) and (c) as
two separate CI validators. They walk the same corpus with the same reader, so they
land here as one checker rather than two near-identical ones.

Run: python3 scripts/ci/check_asset_hygiene.py
"""

import re
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Shipped plugin roots. Anything outside these is repo tooling, not installed anywhere.
CORPUS_ROOTS = ("dev", "prod")


def _forbidden_chars() -> dict[int, str]:
    """Codepoint -> short reason, for characters banned anywhere in a shipped asset."""
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

    # Zero-width and invisible characters. U+200D (ZWJ) is valid inside emoji
    # sequences, but the tree holds none, so the ban costs nothing today; revisit
    # against a real need rather than pre-emptively carving it out.
    for cp in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF):
        banned[cp] = "zero-width/invisible character"

    # Invisible line breaks. Renderers disagree on them, and Python's own
    # `splitlines()` treats them as newlines — see check_forbidden_chars.
    for cp in (0x2028, 0x2029):
        banned[cp] = "line/paragraph separator"

    return banned


FORBIDDEN_CHARS = _forbidden_chars()

# A Cyrillic codepoint touching an ASCII letter or digit on either side.
CYRILLIC_ADJACENT_RE = re.compile(
    r"[A-Za-z0-9][\u0400-\u04FF]|[\u0400-\u04FF][A-Za-z0-9]"
)

# `/Users/<seg>`, `/c/Users/<seg>`, `/home/<seg>`, `C:\Users\<seg>`. The optional second
# word exists for `/c/Users/First Last`, a real comment in this repo explaining why a
# space in a home path breaks IFS splitting; check_personal_paths falls back to the first
# word so that tail cannot swallow ordinary prose into a false positive.
#
# The drive-letter forms accept `users` in either case — Windows paths are case-insensitive
# and shell snippets routinely lowercase them, so `c:\users\someone` is a real leak shape.
# Bare `/Users/` stays case-sensitive on purpose: macOS always capitalises it, while
# lowercase `/users/...` is overwhelmingly a REST path (`GET /users/123`), and matching that
# would fire this gate on ordinary API documentation.
PERSONAL_PATH_RE = re.compile(
    r"(?:/c/[Uu]sers/|/Users/|/home/|[A-Za-z]:\\[Uu]sers\\)"
    r"(?P<seg>[A-Za-z0-9_.<>${}%-]+(?:[ ][A-Za-z0-9_.-]+)?)"
)

# Segments that are plainly examples rather than a real account name. Lowercased.
PLACEHOLDER_SEGMENTS = {
    "me",
    "you",
    "user",
    "username",
    "someone",
    "name",
    "first last",
    "test",
    "runner",
}


def is_placeholder_segment(segment: str) -> bool:
    """True when a path segment is an example rather than someone's account name."""
    normalized = segment.strip().lower()
    if normalized in PLACEHOLDER_SEGMENTS:
        return True
    # An elision — `/Users/.../SKILL.md`, `C:\Users\...\Temp`. Scoped to dots alone: an
    # earlier "no letter or digit" spelling also waved through `_`, `---` and every other
    # punctuation-only segment, which is a false negative in the direction that matters.
    if normalized and set(normalized) <= {"."}:
        return True
    # `<name>`, `${HOME_USER}`, `$USER`, `%USERNAME%` — a substitution, not a name.
    if normalized.startswith("<") and normalized.endswith(">"):
        return True
    if normalized.startswith("$"):
        return True
    if normalized.startswith("%") and normalized.endswith("%"):
        return True
    return False


def char_label(char: str) -> str:
    """`U+202E RIGHT-TO-LEFT OVERRIDE`, falling back when the name table has no entry."""
    try:
        name = unicodedata.name(char)
    except ValueError:
        name = "<unnamed>"
    return f"U+{ord(char):04X} {name}"


def check_forbidden_chars(text: str) -> list[str]:
    """(a) Invisible and control characters.

    Walks the raw text rather than `splitlines()`, which is not merely a style choice:
    `splitlines()` breaks on U+000B, U+000C, U+001C-U+001E, U+0085, U+2028 and U+2029 as
    well as `\\n`, and *consumes* them. Every one of those is a character this check
    exists to catch, so the obvious per-line loop silently drops them — the scan would
    report clean on a file whose only defect is a C1 NEL. Line numbers therefore
    advance on `\\n` alone.
    """
    findings: list[str] = []
    lineno = 1
    column = 0
    for char in text:
        if char == "\n":
            lineno += 1
            column = 0
            continue
        column += 1
        reason = FORBIDDEN_CHARS.get(ord(char))
        if reason:
            findings.append(f"line {lineno} col {column}: {reason} {char_label(char)}")
    return findings


def check_cyrillic_homoglyphs(text: str) -> list[str]:
    """(b) Cyrillic letter substituted into an otherwise-ASCII token.

    Splits on `\\n` alone rather than using `splitlines()`, so line numbers agree with
    check_forbidden_chars: `splitlines()` would also break on the invisible separators
    that check bans, and a file carrying one would get two different line numbers for
    two findings on the same physical line.
    """
    findings: list[str] = []
    for lineno, line in enumerate(text.split("\n"), 1):
        for match in CYRILLIC_ADJACENT_RE.finditer(line):
            cyrillic = next(c for c in match.group(0) if ord(c) >= 0x0400)
            findings.append(
                f"line {lineno}: {char_label(cyrillic)} adjacent to ASCII in "
                f"{match.group(0)!r} — Cyrillic homoglyph in a Latin token"
            )
    return findings


def check_personal_paths(text: str) -> list[str]:
    """(c) Hardcoded home directory of a specific account.

    Splits on `\\n` alone, for the same line-number agreement as check_cyrillic_homoglyphs.

    The regex's optional second word exists only for `/c/Users/First Last`, but it fires on
    any path followed by a space and a word — so `On macOS /Users/me is the home directory`
    captured `me is`, which is in no allowlist, and the gate failed a doc whose author did
    exactly the right thing. The first word is therefore tested too, and the reported path
    is trimmed back to it, so a real violation still reads as the path and nothing else.
    """
    findings: list[str] = []
    for lineno, line in enumerate(text.split("\n"), 1):
        for match in PERSONAL_PATH_RE.finditer(line):
            segment = match.group("seg")
            first_word = segment.split(" ")[0]
            if is_placeholder_segment(segment) or is_placeholder_segment(first_word):
                continue
            reported = match.group(0)
            if first_word != segment:
                reported = reported[: reported.rindex(" ")]
            findings.append(
                f"line {lineno}: hardcoded personal path {reported!r} — "
                f"use ~, $HOME or a placeholder segment instead"
            )
    return findings


def find_asset_files() -> list[Path]:
    """Every *tracked* file under the shipped plugin roots.

    `git ls-files` rather than `rglob`, for two reasons. It is the corpus the sibling
    line-ending and JSON-encoding jobs in `harness-check.yml` already select, so the three
    agree on what "shipped" means; and it ties the scan to what is actually published — a
    developer's local `.venv`, editor backup or scratch file under `dev/` would otherwise
    fail the check locally while CI stayed green. Untracked means unshipped. It also drops
    the need to special-case `__pycache__`, which is never tracked.
    """
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files", "--", *CORPUS_ROOTS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def read_text(path: Path) -> str | None:
    """UTF-8 text, or None for a binary file — a decode failure is not this gate's defect."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def empty_corpus_errors(files: list[Path]) -> list[str]:
    """Roots that contributed nothing — a coverage failure, never a pass.

    `docs/conventions.md` → *Validator Discovery*: "An empty target set is a **failure**,
    not a pass. A gate that silently covers zero files is indistinguishable from a passing
    one in the CI summary." Checked per root, not just in total, so deleting or renaming
    one plugin cannot leave this gate quietly scanning the other and reporting green.
    """
    covered = {path.relative_to(REPO_ROOT).parts[0] for path in files}
    return [
        f"corpus root {root!r} contributed no tracked files — the gate would pass "
        f"without scanning it"
        for root in CORPUS_ROOTS
        if root not in covered
    ]


def main() -> int:
    files = find_asset_files()
    scanned = 0
    hard_fail = False

    for msg in empty_corpus_errors(files):
        print(f"ERROR [empty-corpus]: {msg}")
        hard_fail = True

    for path in files:
        text = read_text(path)
        if text is None:
            continue
        scanned += 1
        rel = path.relative_to(REPO_ROOT).as_posix()

        for msg in check_forbidden_chars(text):
            print(f"ERROR {rel} [forbidden-char]: {msg}")
            hard_fail = True
        for msg in check_cyrillic_homoglyphs(text):
            print(f"ERROR {rel} [cyrillic-homoglyph]: {msg}")
            hard_fail = True
        for msg in check_personal_paths(text):
            print(f"ERROR {rel} [personal-path]: {msg}")
            hard_fail = True

    # Violations only above: an OK line per file is unreadable across this many assets.
    print("----")
    print(f"Scanned {scanned} text file(s) under {'/, '.join(CORPUS_ROOTS)}/.")
    if hard_fail:
        print("FAIL: shipped-asset hygiene violations found (see ERROR lines above).")
        return 1
    if scanned == 0:
        print("FAIL: no text files scanned — an empty target set is a failure, not a pass.")
        return 1
    print("OK: no forbidden characters, Cyrillic homoglyphs or personal paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
