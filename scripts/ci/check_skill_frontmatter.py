#!/usr/bin/env python3
"""Frontmatter validity check for shipped plugin assets (skills, agents, commands).

Guards one silent failure mode: frontmatter that does not parse as YAML. Claude Code
still loads such an asset — it just loads with *empty metadata*, so the `description:`
that drives auto-invocation vanishes with no error at runtime. That is what happened
to `dev/skills/task-review/SKILL.md` before PR #164: an unquoted `description:` packed
`--no-hub: local only. --auto: skip confirmation.` into a plain scalar, and a plain
scalar may not contain a `: ` (colon-space) sequence.

Checks, over every tracked `*.md` whose first line is `---`:

(a) The frontmatter block is delimited and parses as a YAML mapping.
(b) The keys required for that asset type are present and non-empty strings.
(c) `name:` matches the path the loader derives it from (skill directory / agent
    file stem) — the same silent-breakage class, since a rename that misses the
    frontmatter leaves the asset registered under its old name.

Discovery is by file content, not a hardcoded glob, so a newly added skill/agent/
command is covered without touching this script.

Usage: python3 scripts/ci/check_skill_frontmatter.py
Exit: 0 if every file is valid, 1 if any violation, 2 if PyYAML is unavailable.
Always prints a full report.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard, not logic
    print(
        "ERROR: PyYAML required — this check parses frontmatter with the same "
        "strictness the loader does.\n"
        "  CI:    pip install pyyaml\n"
        "  local: python3 -m venv .venv && .venv/bin/pip install pyyaml "
        "(system python3 is PEP 668 externally-managed on macOS)",
        file=sys.stderr,
    )
    sys.exit(2)

REPO_ROOT = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)

DELIMITER = "---"


def find_frontmatter_files() -> list[Path]:
    """Every tracked `*.md` that opens with a `---` delimiter."""
    tracked = subprocess.check_output(
        ["git", "-c", "core.quotePath=false", "ls-files", "--", "*.md"],
        text=True,
        cwd=REPO_ROOT,
    ).splitlines()

    files: list[Path] = []
    for rel in tracked:
        path = REPO_ROOT / rel
        try:
            first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        except (OSError, UnicodeDecodeError):
            continue
        if first.strip() == DELIMITER:
            files.append(path)
    return sorted(files)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (block, error). `block` is the raw YAML between the `---` delimiters."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != DELIMITER:
        return None, "file does not open with a `---` frontmatter delimiter"

    for i in range(1, len(lines)):
        if lines[i].strip() == DELIMITER:
            return "\n".join(lines[1:i]), ""

    return None, "frontmatter block is never closed by a `---` line"


def expected_shape(rel: str) -> tuple[list[str], str | None]:
    """Return (required keys, expected `name` value) for an asset path.

    `commands/*.md` take their name from the filename and carry no `name:` key, so
    only `description` is required there.
    """
    path = Path(rel)
    parts = path.parts

    if path.name == "SKILL.md" and "skills" in parts:
        return ["name", "description"], path.parent.name
    if "agents" in parts:
        return ["name", "description"], path.stem
    if "commands" in parts:
        return ["description"], None
    return ["description"], None


def check_file(path: Path) -> list[str]:
    """Return a list of violation messages for one file (empty when valid)."""
    rel = str(path.relative_to(REPO_ROOT))
    text = path.read_text(encoding="utf-8")

    block, error = split_frontmatter(text)
    if block is None:
        return [error]

    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ")
        return [
            "frontmatter failed to parse as YAML — the asset would load with empty "
            f"metadata: {detail}"
        ]

    if not isinstance(data, dict):
        return [f"frontmatter is not a YAML mapping (parsed as {type(data).__name__})"]

    problems: list[str] = []
    required, expected_name = expected_shape(rel)

    for key in required:
        value = data.get(key)
        if key not in data:
            problems.append(f"missing required key `{key}:`")
        elif value is None:
            problems.append(f"`{key}:` has no value")
        elif not isinstance(value, str):
            problems.append(
                f"`{key}:` must be a string, got {type(value).__name__}"
            )
        elif not value.strip():
            problems.append(f"`{key}:` is empty")

    if expected_name is not None:
        actual = data.get("name")
        if isinstance(actual, str) and actual.strip() != expected_name:
            problems.append(
                f"`name: {actual.strip()}` does not match the path the loader derives "
                f"it from (expected `{expected_name}`)"
            )

    return problems


def main() -> int:
    files = find_frontmatter_files()
    if not files:
        print("SKIP: no tracked markdown files carry frontmatter")
        return 0

    failed = False
    for path in files:
        rel = path.relative_to(REPO_ROOT)
        problems = check_file(path)
        if not problems:
            print(f"OK   {rel}: frontmatter parses, required keys present")
            continue
        failed = True
        for msg in problems:
            print(f"ERROR {rel}: {msg}")

    print("----")
    if failed:
        print("FAIL: invalid frontmatter found (see ERROR lines above).")
        print(
            "An asset whose frontmatter does not parse still loads — with no "
            "description — so auto-invocation silently stops working."
        )
        return 1
    print(f"OK: {len(files)} frontmatter blocks valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
