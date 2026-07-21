#!/usr/bin/env python3
"""Harness ratchet checks for shipped plugin skills (dev/, prod/).

Two independent checks, run over every `{plugin}/skills/*/SKILL.md`:

(a) Plugin-root portability — shared skill instructions and references must not
    depend on hook-only plugin root variables to locate bundled files.

(b) Capture-before-use — every `$VAR` / `${VAR}` (uppercase) referenced
    inside a fenced ```bash/```sh code block must have a `VAR=` capture
    earlier in the *same* block. Platform env vars (HOME, PATH) are allowlisted.

Scope note: plugin-root portability violations are unconditional errors.
Capture-before-use violations are HARD-FAIL only for HARD_FAIL_SKILLS (skills
fixed in an earlier sprint). Other skills report WARN so pre-existing debt
remains visible without blocking CI. Extend HARD_FAIL_SKILLS as each skill is
brought into compliance.

Usage: python3 scripts/ci/check_harness_drift.py
Exit: 0 if no hard-fail violations, 1 otherwise. Always prints a full report.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)

SKILL_GLOBS = ["dev/skills/*/SKILL.md", "prod/skills/*/SKILL.md"]
REFERENCE_GLOBS = [
    "dev/skills/*/references/*.md",
    "prod/skills/*/references/*.md",
]

# Skills fixed in the skill-review-findings sprint — violations here block CI.
# All other skills are warn-only until brought into compliance separately.
HARD_FAIL_SKILLS = {"harness-init", "task-next", "hwpx", "task-review"}

ALLOWLIST_VARS = {"HOME", "PATH"}
FORBIDDEN_SKILL_ROOT_VARS = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")

FENCE_RE = re.compile(r"```(bash|sh|shell)\n(.*?)```", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
VAR_USE_RE = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")
VAR_CAPTURE_RE = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=")


def find_skill_files() -> list[Path]:
    files: list[Path] = []
    for pattern in SKILL_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    return files


def find_reference_files() -> list[tuple[str, Path]]:
    """Return (skill_name, path) pairs for `references/*.md` docs split out of a SKILL.md.

    These aren't matched by SKILL_GLOBS (no frontmatter, live in a subdir) but can carry
    fenced bash moved out of a HARD_FAIL_SKILLS SKILL.md — check capture-before-use here too.
    """
    files: list[tuple[str, Path]] = []
    for pattern in REFERENCE_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            skill_name = path.parent.parent.name
            files.append((skill_name, path))
    return files


def parse_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (name, description) parsed from a SKILL.md frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, ""

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, ""

    fm_lines = lines[1:end]
    name = None
    description_parts: list[str] = []
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
            i += 1
            continue
        if line.startswith("description:"):
            rest = line.split(":", 1)[1].strip()
            if rest and rest not in (">-", ">", "|-", "|"):
                description_parts.append(rest)
            i += 1
            # Folded/block scalar: consume indented continuation lines.
            while i < len(fm_lines) and (fm_lines[i].startswith(" ") or fm_lines[i].strip() == ""):
                description_parts.append(fm_lines[i].strip())
                i += 1
            continue
        i += 1
    return name, " ".join(p for p in description_parts if p)


def check_capture_before_use(text: str) -> list[str]:
    """Return list of capture-before-use violation messages (empty = clean)."""
    problems = []
    for block_num, m in enumerate(FENCE_RE.finditer(text), start=1):
        captured = set(ALLOWLIST_VARS)
        block_lines = m.group(2).splitlines()
        for line in block_lines:
            # Ignore full-line and inline comments — commented-out $VAR is not a use.
            line = line.split("#", 1)[0]
            for var in VAR_USE_RE.findall(line):
                if var not in captured:
                    problems.append(
                        f"block #{block_num}: ${{{var}}} used before capture — line: {line.strip()!r}"
                    )
            cap = VAR_CAPTURE_RE.match(line)
            if cap:
                captured.add(cap.group(1))
    return problems


def check_plugin_root_portability(text: str) -> list[str]:
    """Reject hook-only root variables from shared skill instructions.

    Scoped to fenced code blocks + inline code spans — a prose-only mention
    (e.g. migration notes) must not hard-fail CI.
    """
    code_text = "\n".join(m.group(1) for m in CODE_FENCE_RE.finditer(text))
    code_text += "\n" + "\n".join(m.group(1) for m in INLINE_CODE_RE.finditer(text))
    return [
        f"hook-only root variable {token!r} is not portable in shared skill instructions"
        for token in FORBIDDEN_SKILL_ROOT_VARS
        if re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])", code_text)
    ]


def main() -> int:
    skill_files = find_skill_files()
    if not skill_files:
        print("SKIP: no skill files found")
        return 0

    hard_fail = False
    for path in skill_files:
        text = path.read_text()
        name, _ = parse_frontmatter(text)
        rel = path.relative_to(REPO_ROOT)
        if not name:
            print(f"WARN {rel}: could not parse `name:` from frontmatter — skipping")
            continue

        severity = "ERROR" if name in HARD_FAIL_SKILLS else "WARN"

        portability = check_plugin_root_portability(text)
        capture = check_capture_before_use(text)

        if not portability and not capture:
            print(
                f"OK   {rel} ({name}): plugin-root portability "
                "+ capture-before-use clean"
            )
            continue

        for msg in portability:
            print(f"ERROR {rel} ({name}) [plugin-root-portability]: {msg}")
        for msg in capture:
            print(f"{severity} {rel} ({name}) [capture-before-use]: {msg}")

        if portability:
            hard_fail = True
        if severity == "ERROR" and capture:
            hard_fail = True

    # WARN-only: these files weren't scanned at all before (no frontmatter, glob
    # miss), so surfacing them is new visibility. Promoting straight to hard-fail
    # would retroactively block CI on pre-existing debt in untouched reference
    # docs (e.g. hwpx's $SKILL_DIR pattern) — track those via backlog, not here.
    for skill_name, path in find_reference_files():
        text = path.read_text()
        rel = path.relative_to(REPO_ROOT)
        portability = check_plugin_root_portability(text)
        capture = check_capture_before_use(text)

        if not portability and not capture:
            print(
                f"OK   {rel} ({skill_name}): plugin-root portability "
                "+ capture-before-use clean"
            )
            continue

        for msg in portability:
            print(f"ERROR {rel} ({skill_name}) [plugin-root-portability]: {msg}")
        for msg in capture:
            print(f"WARN {rel} ({skill_name}) [capture-before-use]: {msg}")

        if portability:
            hard_fail = True

    print("----")
    if hard_fail:
        print("FAIL: portability or hard-fail violations found (see ERROR lines above).")
        return 1
    print("OK: no hard-fail violations (WARN-only items are tracked separately).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
