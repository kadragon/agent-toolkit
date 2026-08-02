#!/usr/bin/env python3
"""check_changelog_entries.py — enforce the CHANGELOG Entry Contract mechanically.

Canonical rule: `dev/skills/harness-init/references/harness-invariants.md` →
*CHANGELOG Entry Contract*. This script enforces only the decidable subset of it:

  1. each `- [done]` line is at most 160 characters
  2. it carries at most one `→ <path>` owning-doc link
  3. that link resolves to a repo-relative path that exists

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

REPO_ROOT = Path(__file__).resolve().parents[2]


def check_file(path: Path) -> list[str]:
    """Return a list of human-readable violations for `path` (empty = clean)."""
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"{path}: could not read: {e}"]

    for lineno, line in enumerate(text.splitlines(), 1):
        if not ENTRY_RE.match(line):
            continue

        if len(line) > MAX_LEN:
            errors.append(
                f"{path}:{lineno}: entry is {len(line)} chars (max {MAX_LEN}) — "
                f"move the detail to the owning docs/*.md and link it: {line[:80]}..."
            )

        links = LINK_RE.findall(line)
        if len(links) > 1:
            errors.append(
                f"{path}:{lineno}: {len(links)} `→` links (max 1) — "
                f"one owning doc per entry: {', '.join(links)}"
            )
        for link in links:
            if not (REPO_ROOT / link).exists():
                errors.append(f"{path}:{lineno}: `→ {link}` does not exist in the repo")

    return errors


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or [REPO_ROOT / "CHANGELOG.md"]

    errors: list[str] = []
    checked = 0
    for path in paths:
        if not path.exists():
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
