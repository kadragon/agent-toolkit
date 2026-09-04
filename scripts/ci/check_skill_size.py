#!/usr/bin/env python3
"""SKILL.md line-count cap, ratcheting downward.

A SKILL.md is loaded whole every time its skill fires, so its length is a per-invocation
tax the model pays before doing any work. `task-next` grew from 386 to 602 lines over
35 commits with no gate in the way; the AGENTS.md size policy (100/200 lines) had no
counterpart for skills. This check is that counterpart.

Rules, over every tracked `*/skills/*/SKILL.md`:

- At most CAP lines — unless the file is listed in the ratchet (`skill-size-ratchet.json`,
  beside this script) with a ceiling. A listed file may not exceed its ceiling.
- The ratchet only goes down: a listed file that shrank below its ceiling is reported so
  the ceiling gets lowered in the same change; a listed file now at or under CAP must be
  removed from the ratchet. Both are errors, so the file cannot quietly regrow.

Usage: python3 scripts/ci/check_skill_size.py [--test]
Exit: 0 clean, 1 any violation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

CAP = 250
RATCHET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill-size-ratchet.json")


def tracked_skills(root: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "-C", root, "-c", "core.quotePath=false", "ls-files", "--", "*/skills/*/SKILL.md"],
        text=True,
    )
    return sorted(p for p in out.splitlines() if p.strip())


def line_count(path: str) -> int:
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def load_ratchet(path: str) -> dict[str, int]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not all(isinstance(v, int) for v in data.values()):
        raise SystemExit(f"ERROR: {path} must map skill path -> integer ceiling")
    return data


def check(root: str, skills: list[str], ratchet: dict[str, int], cap: int = CAP) -> list[str]:
    problems: list[str] = []
    for rel in skills:
        n = line_count(os.path.join(root, rel))
        ceiling = ratchet.get(rel)
        if ceiling is None:
            if n > cap:
                problems.append(f"{rel}: {n} lines > cap {cap} — trim it, or list it in the ratchet with its current count")
        else:
            if n > ceiling:
                problems.append(f"{rel}: {n} lines > ratchet ceiling {ceiling} — the ratchet only goes down")
            elif n <= cap:
                problems.append(f"{rel}: {n} lines is within cap {cap} — remove it from the ratchet")
            elif n < ceiling:
                problems.append(f"{rel}: {n} lines < ratchet ceiling {ceiling} — lower the ceiling to {n}")
    for rel in ratchet:
        if rel not in skills:
            problems.append(f"{rel}: listed in the ratchet but not a tracked SKILL.md — remove the entry")
    return problems


def run_tests() -> int:
    import shutil
    import tempfile

    results = []

    def t(name, cond):
        results.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    tmp = tempfile.mkdtemp()
    try:
        def write(rel, lines):
            p = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write("x\n" * lines)
            return rel

        small = write("dev/skills/a/SKILL.md", 10)
        big = write("dev/skills/b/SKILL.md", 40)
        skills = [small, big]
        t("under cap, unlisted: clean", check(tmp, [small], {}, cap=20) == [])
        t("over cap, unlisted: flagged", any("> cap" in p for p in check(tmp, [big], {}, cap=20)))
        t("over cap, listed at ceiling: clean", check(tmp, [big], {big: 40}, cap=20) == [])
        t("over ceiling: flagged", any("ratchet ceiling" in p for p in check(tmp, [big], {big: 30}, cap=20)))
        t("shrank below ceiling: asks to lower", any("lower the ceiling to 40" in p for p in check(tmp, [big], {big: 50}, cap=20)))
        t("listed but within cap: asks to remove", any("remove it from the ratchet" in p for p in check(tmp, [small], {small: 30}, cap=20)))
        t("listed but untracked: flagged", any("not a tracked" in p for p in check(tmp, skills, {"dev/skills/z/SKILL.md": 300}, cap=20)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main() -> int:
    if "--test" in sys.argv[1:]:
        return run_tests()
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    skills = tracked_skills(root)
    problems = check(root, skills, load_ratchet(RATCHET))
    for p in problems:
        print(f"ERROR: {p}")
    if problems:
        return 1
    print(f"OK: {len(skills)} SKILL.md files within {CAP} lines (or their ratchet ceiling).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
