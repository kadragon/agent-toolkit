#!/usr/bin/env python3
"""check_changelog_entries.py — enforce the CHANGELOG Entry Contract mechanically.

Canonical rule: `dev/skills/harness-init/references/harness-invariants.md` →
*CHANGELOG Entry Contract*. This script enforces only the decidable subset of it:

  1. each `- [done]` line is at most 160 characters
  2. no indented continuation line hides under an entry (one line means one line)
  3. it carries at most one `→ <path>` owning-doc link
  4. under `## Unreleased`, that link resolves to a repo-relative path that exists

Rule 4 is scoped to `## Unreleased` on purpose: released entries are immutable history,
and retiring a design doc they link to must not turn CI red on an unrelated PR.

"No explanatory clauses" is a judgment call and is deliberately NOT checked here — the
character cap is what actually stops entries from ballooning, and it is the rule prose
kept re-stating. Review owns the rest.

Usage:
  python3 scripts/ci/check_changelog_entries.py [PATH ...]   # default: CHANGELOG.md
"""

import re
import sys
from pathlib import Path

MAX_LEN = 160
ENTRY_RE = re.compile(r"^- \[done\]")
LINK_RE = re.compile(r"→\s*(\S+)")
UNRELEASED_RE = re.compile(r"^##\s+Unreleased\s*$", re.IGNORECASE)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _link_error(link: str) -> str | None:
    """Return why `link` is not a valid owning-doc target, or None if it is fine.

    Anchors (`docs/x.md#section`) are stripped before the existence test — the anchor is
    not part of the path. Absolute paths and `..` escapes are rejected outright rather
    than resolved: `REPO_ROOT / "/etc/passwd"` silently discards REPO_ROOT, so an
    exists() test alone would pass a target that is not in the repo at all.
    """
    target = link.split("#", 1)[0]
    if not target:
        return "is an anchor with no path"
    candidate = Path(target)
    if candidate.is_absolute():
        return "is absolute — the contract requires a repo-relative path"
    root = REPO_ROOT.resolve()  # resolve both sides: /var is a symlink to /private/var
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        return "escapes the repository root"
    if not resolved.exists():
        return "does not exist in the repo"
    return None


def check_file(path: Path, *, check_links: bool = True) -> list[str]:
    """Return a list of human-readable violations for `path` (empty = clean).

    `check_links=False` keeps the length and one-link caps but skips target resolution —
    used for released sections, whose entries are immutable history and must not go red
    when the doc they link to is later retired.
    """
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"{path}: could not read: {e}"]

    lines = text.splitlines()
    # Link targets are only resolved for entries under `## Unreleased` — see check_links.
    unreleased_range = _unreleased_range(lines)

    for lineno, line in enumerate(lines, 1):
        if not ENTRY_RE.match(line):
            continue

        if len(line) > MAX_LEN:
            errors.append(
                f"{path}:{lineno}: entry is {len(line)} chars (max {MAX_LEN}) — "
                f"move the detail to the owning docs/*.md and link it: {line[:80]}..."
            )

        # One line means one line: an indented continuation under an entry is still
        # part of that entry, and slips past a per-physical-line length check.
        if lineno < len(lines):
            nxt = lines[lineno]
            if nxt.strip() and nxt[:1].isspace():
                errors.append(
                    f"{path}:{lineno + 1}: continuation line under the entry above — "
                    f"an entry is one line: {nxt.strip()[:80]}"
                )

        links = LINK_RE.findall(line)
        if len(links) > 1:
            errors.append(
                f"{path}:{lineno}: {len(links)} `→` links (max 1) — "
                f"one owning doc per entry: {', '.join(links)}"
            )
        if not check_links or lineno not in unreleased_range:
            continue
        for link in links:
            reason = _link_error(link)
            if reason:
                errors.append(f"{path}:{lineno}: `→ {link}` {reason}")

    return errors


def _unreleased_range(lines: list[str]) -> range:
    """1-indexed line range covered by `## Unreleased`, empty if the section is absent."""
    start = None
    for i, line in enumerate(lines, 1):
        if start is None:
            if UNRELEASED_RE.match(line):
                start = i
            continue
        if line.startswith("## "):
            return range(start, i)
    return range(start, len(lines) + 1) if start else range(0)


def main(argv: list[str]) -> int:
    explicit = bool(argv)
    paths = [Path(a) for a in argv] or [REPO_ROOT / "CHANGELOG.md"]

    errors: list[str] = []
    checked = 0
    for path in paths:
        if not path.exists():
            # A missing default CHANGELOG.md is a broken gate, not a clean run: the CI
            # job passes no arguments, so silently skipping would look identical to
            # "every entry is compliant" if the file is ever renamed or moved.
            if not explicit:
                print(f"ERROR: {path} not found — the changelog gate has nothing to check.")
                return 1
            print(f"SKIP: {path} not found.")
            continue
        checked += 1
        errors.extend(check_file(path))

    if errors:
        print("ERROR: CHANGELOG Entry Contract violations:")
        for e in errors:
            print(f"  {e}")
        print(
            "Canonical rule: dev/skills/harness-init/references/harness-invariants.md "
            "→ CHANGELOG Entry Contract."
        )
        return 1

    print(f"OK: {checked} changelog file(s) satisfy the CHANGELOG Entry Contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
