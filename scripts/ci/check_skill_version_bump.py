#!/usr/bin/env python3
"""
Skill `version:` bump gate for new bundled files.

`docs/conventions.md` → *Skill `version:` Bump Rules* sizes a new bundled file as a minor
bump on the skill's own `version:`. PR #281 added `references/automation.md` to task-grill
and shipped a patch bump; a reviewer caught it only after the merge. This check makes the
rule mechanical for the part a diff can see.

A branch that **adds** a file under `{dev,prod}/skills/<name>/references/` or `scripts/`
must raise that skill's `version:` by at least a minor step over the merge-base with
`origin/main`. Not counted: renames (`git diff -M` reports them as `R`, not `A`), test
files (`scripts/**/test_*`), and `evals/`, `agents/`, `examples/` files — fixtures and
metadata add no documented behavior.

Skipped with a NOTE: a new skill (no `SKILL.md` at base) and a skill whose base
`SKILL.md` has no `version:` key.

Escape hatch: moving existing content out of `SKILL.md` into a new file changes no
behavior, so a patch is correct. Record that on any commit of the branch with a trailer
line `Skill-Bump-Exempt: <skill> — <reason>` (`-` also accepted as the separator). The
reason must be non-empty; the report echoes it.

The diff base is `origin/main`, resolved as `check_skill_triggers.py` resolves it. An
unresolvable base skips locally with a NOTE, and fails under `GITHUB_ACTIONS=true`,
where the job's `fetch-depth: 0` must supply it.

Usage: python3 scripts/ci/check_skill_version_bump.py
Exit: 0 when every counted skill passes or is exempt, 1 on any violation.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

DIFF_BASE = "origin/main"
CI_ENV_VAR = "GITHUB_ACTIONS"

# group(1): skill dir, group(2): path inside the skill
BUNDLED_RE = re.compile(r"^((?:dev|prod)/skills/[^/]+)/((?:references|scripts)/.+)$")
TEST_FILE_RE = re.compile(r"(?:^|/)test_[^/]*$")
VERSION_RE = re.compile(r"^version:\s*[\"']?(\d+)\.(\d+)\.(\d+)", re.MULTILINE)
TRAILER_RE = re.compile(r"^Skill-Bump-Exempt:[ \t]*(\S+)[ \t]+(?:—|-{1,2})[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "core.quotePath=false", *args],
        text=True,
        cwd=root,
        encoding="utf-8",
        stderr=subprocess.DEVNULL,
    )


def resolve_base(root: Path) -> str | None:
    try:
        return _git(root, "merge-base", DIFF_BASE, "HEAD").strip() or None
    except (subprocess.CalledProcessError, OSError):
        return None


def added_bundled_files(root: Path, base: str) -> dict[str, list[str]]:
    """Map skill dir -> counted files this branch added (renames excluded)."""
    out = _git(root, "diff", "--name-only", "-M", "--diff-filter=A", f"{base}...HEAD")
    added: dict[str, list[str]] = {}
    for rel in out.splitlines():
        match = BUNDLED_RE.match(rel.strip())
        if not match or TEST_FILE_RE.search(match.group(2)):
            continue
        added.setdefault(match.group(1), []).append(match.group(2))
    return added


def skill_version(root: Path, rev: str, skill_dir: str) -> tuple[bool, tuple[int, int, int] | None]:
    """Return (SKILL.md exists at rev, parsed version or None)."""
    try:
        text = _git(root, "show", f"{rev}:{skill_dir}/SKILL.md")
    except subprocess.CalledProcessError:
        return False, None
    frontmatter = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
    match = VERSION_RE.search(frontmatter)
    return True, (tuple(int(part) for part in match.groups()) if match else None)  # type: ignore[return-value]


def exemptions(root: Path, base: str) -> dict[str, str]:
    messages = _git(root, "log", "--format=%B", f"{base}..HEAD")
    return {m.group(1): m.group(2) for m in TRAILER_RE.finditer(messages)}


def build_report(root: Path, *, require_diff_base: bool = False) -> tuple[list[str], bool]:
    base = resolve_base(root)
    if base is None:
        reason = f"diff base `{DIFF_BASE}` unresolvable"
        if require_diff_base:
            return [f"ERROR: {reason} — CI must fetch it via fetch-depth: 0."], False
        return [f"NOTE: {reason} — check skipped."], True

    added = added_bundled_files(root, base)
    if not added:
        return ["OK: no new references/ or scripts/ files in any skill."], True

    exempt = exemptions(root, base)
    lines: list[str] = []
    ok = True
    for skill_dir in sorted(added):
        files = ", ".join(sorted(added[skill_dir]))
        name = skill_dir.rsplit("/", 1)[1]
        existed, old = skill_version(root, base, skill_dir)
        if not existed:
            lines.append(f"NOTE: {skill_dir} is new on this branch — skipped.")
            continue
        if old is None:
            lines.append(f"NOTE: {skill_dir} has no `version:` at base — skipped.")
            continue
        _, new = skill_version(root, "HEAD", skill_dir)
        old_s = ".".join(map(str, old))
        new_s = ".".join(map(str, new)) if new else "missing"
        if new and (new[0] > old[0] or (new[0] == old[0] and new[1] > old[1])):
            lines.append(f"OK: {skill_dir} {old_s} -> {new_s} (minor or higher) for {files}.")
        elif name in exempt:
            lines.append(f"EXEMPT: {skill_dir} {old_s} -> {new_s} — {exempt[name]}")
        else:
            ok = False
            lines.append(
                f"ERROR: {skill_dir} adds {files} but `version:` went {old_s} -> {new_s}. "
                "A new bundled file needs a minor bump (docs/conventions.md → Skill `version:` "
                "Bump Rules). If the file only moves existing content, add a commit trailer "
                f"`Skill-Bump-Exempt: {name} — <reason>`."
            )
    return lines, ok


def main() -> int:
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    lines, ok = build_report(root, require_diff_base=os.environ.get(CI_ENV_VAR) == "true")
    print("\n".join(lines))
    print("OK: skill version bumps match new bundled files." if ok else "FAIL: skill version bump check.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
