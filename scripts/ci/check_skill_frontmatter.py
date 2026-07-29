#!/usr/bin/env python3
"""Frontmatter validity check for shipped plugin assets (skills, agents, commands).

Guards one silent failure mode: an asset whose frontmatter Claude Code cannot read.
The loader does not error — it loads the asset with *empty metadata*, so the
`description:` that drives auto-invocation vanishes with nothing in the log. That is
what happened to `dev/skills/task-review/SKILL.md` before PR #164: an unquoted
`description:` packed `--no-hub: local only. --auto: skip confirmation.` into a plain
scalar, and a plain scalar may not contain a `: ` (colon-space) sequence.

The asset set is enumerated **by path** (`*/skills/*/SKILL.md`, `*/agents/*.md`,
`*/commands/*.md`), not by "files that happen to start with `---`". Content-gated
discovery would skip the two loudest forms of this very bug — an asset with no
frontmatter at all, and one whose `---` is preceded by a UTF-8 BOM — leaving CI green
on exactly the files it exists to catch.

Checks:

(a) Every plugin asset has a delimited frontmatter block, BOM-free, that parses as a
    YAML mapping.
(b) The keys required for that asset type are present and non-empty strings.
(c) `name:` matches the path the loader derives it from (skill directory / agent file
    stem) — the same silent-breakage class, since a rename that misses the frontmatter
    leaves the asset registered under its old name.
(d) Non-asset markdown that carries frontmatter (design docs, references) must still
    parse as YAML, but is held to no asset-specific key requirement.

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
BOM = "﻿"

# Asset kind -> (required keys, whether `name:` must match the path).
ASSET_RULES = {
    "skill": (["name", "description"], True),
    "agent": (["name", "description"], True),
    # Commands take their name from the filename and carry no `name:` key.
    "command": (["description"], False),
}


def list_tracked_markdown(root: Path) -> list[Path]:
    tracked = subprocess.check_output(
        ["git", "-c", "core.quotePath=false", "ls-files", "--", "*.md"],
        text=True,
        cwd=root,
    ).splitlines()
    return sorted(root / rel for rel in tracked)


def classify(rel: str) -> str | None:
    """Return the plugin asset kind for a repo-relative path, or None if not an asset."""
    path = Path(rel)
    if path.name == "SKILL.md" and path.parent.parent.name == "skills":
        return "skill"
    if path.parent.name == "agents":
        return "agent"
    if path.parent.name == "commands":
        return "command"
    return None


def expected_name(kind: str, rel: str) -> str:
    """The name the loader derives from the path."""
    path = Path(rel)
    return path.parent.name if kind == "skill" else path.stem


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (block, error). `block` is the raw YAML between the `---` delimiters."""
    lines = text.splitlines()
    if not lines:
        return None, "file is empty — no frontmatter block"
    if lines[0].startswith(BOM):
        return None, (
            "frontmatter delimiter is preceded by a UTF-8 BOM — the loader reads "
            "`\\ufeff---`, not `---`, and drops all metadata. Rewrite the file as "
            "UTF-8 without BOM"
        )
    if lines[0].strip() != DELIMITER:
        return None, "file does not open with a `---` frontmatter delimiter"

    for i in range(1, len(lines)):
        if lines[i].strip() == DELIMITER:
            return "\n".join(lines[1:i]), ""

    return None, "frontmatter block is never closed by a `---` line"


def check_file(path: Path, root: Path | None = None) -> list[str]:
    """Return a list of violation messages for one file (empty when valid).

    A non-asset markdown file with no frontmatter is not a violation — the caller
    filters those out before reporting.
    """
    root = root if root is not None else REPO_ROOT
    rel = str(path.relative_to(root))
    kind = classify(rel)
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

    if kind is None:
        # Non-asset markdown: parsing is the whole contract, no required keys.
        return []

    problems: list[str] = []
    required, name_must_match_path = ASSET_RULES[kind]

    for key in required:
        value = data.get(key)
        if key not in data:
            problems.append(f"missing required key `{key}:`")
        elif value is None:
            problems.append(f"`{key}:` has no value")
        elif not isinstance(value, str):
            problems.append(f"`{key}:` must be a string, got {type(value).__name__}")
        elif not value.strip():
            problems.append(f"`{key}:` is empty")

    if name_must_match_path:
        expected = expected_name(kind, rel)
        actual = data.get("name")
        if isinstance(actual, str) and actual.strip() != expected:
            problems.append(
                f"`name: {actual.strip()}` does not match the path the loader derives "
                f"it from (expected `{expected}`)"
            )

    return problems


def build_report(root: Path) -> tuple[list[str], bool, int]:
    """Return (report lines, failed, asset count) for a repository root."""
    lines: list[str] = []
    failed = False
    asset_count = 0

    for path in list_tracked_markdown(root):
        rel = str(path.relative_to(root))
        kind = classify(rel)

        if kind is None:
            # Only non-asset files that actually carry frontmatter are in scope.
            try:
                first = path.read_text(encoding="utf-8").split("\n", 1)[0]
            except (OSError, UnicodeDecodeError):
                continue
            if first.lstrip(BOM).strip() != DELIMITER:
                continue
            label = "non-asset frontmatter"
        else:
            asset_count += 1
            label = kind

        problems = check_file(path, root)
        if not problems:
            lines.append(f"OK   {rel} ({label}): frontmatter valid")
            continue
        failed = True
        for msg in problems:
            lines.append(f"ERROR {rel} ({label}): {msg}")

    return lines, failed, asset_count


def main() -> int:
    lines, failed, asset_count = build_report(REPO_ROOT)
    for line in lines:
        print(line)

    print("----")

    if asset_count == 0:
        # Fail closed: a gate that silently covers zero files is indistinguishable
        # from a passing one in the CI summary.
        print(
            "FAIL: discovery found zero plugin assets "
            "(*/skills/*/SKILL.md, */agents/*.md, */commands/*.md). "
            "Either the pathspec regressed or this is not the plugin repo."
        )
        return 1

    if failed:
        print("FAIL: invalid frontmatter found (see ERROR lines above).")
        print(
            "An asset whose frontmatter the loader cannot read still loads — with no "
            "description — so auto-invocation silently stops working."
        )
        return 1

    print(f"OK: {asset_count} plugin assets valid ({len(lines)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
