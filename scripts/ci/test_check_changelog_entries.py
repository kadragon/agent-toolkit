#!/usr/bin/env python3
"""
Unit tests for check_changelog_entries.py.

The defect under test is PR #188's: a 185-character `## Unreleased` entry shipped in the
very cycle whose diff re-stated the ≤160 rule, and only qa-verifier caught it. The
over-length case below reproduces exactly that shape — raise MAX_LEN and it goes red.

Also covered: the boundary at exactly 160, the one-link cap, dead `→` link targets, and
the two deliberate skip paths (non-entry lines, and a missing changelog file).

Run: python3 scripts/ci/test_check_changelog_entries.py
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "check_changelog_entries.py"
spec = importlib.util.spec_from_file_location("check_changelog_entries", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def errors_for(root: Path, body: str) -> list[str]:
    """Write `body` as a changelog under `root` and return its violations."""
    path = root / "CHANGELOG.md"
    path.write_text(body, encoding="utf-8")
    return mod.check_file(path)


def entry(title: str, link: str = "") -> str:
    return f"- [done] {title} (dev v1.0.0) (2026-01-01)" + (f" → {link}" if link else "")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # check_file resolves links against the repo root; point it at the fixture.
        original_root = mod.REPO_ROOT
        mod.REPO_ROOT = root
        (root / "docs").mkdir()
        (root / "docs" / "real.md").write_text("x", encoding="utf-8")
        (root / "docs" / "other.md").write_text("x", encoding="utf-8")

        try:
            print("\n-- length cap --")
            short = entry("a short title", "docs/real.md")
            check("a compliant entry passes", errors_for(root, short) == [],
                  f"got {errors_for(root, short)}")

            over = entry("x" * 200)
            errs = errors_for(root, over)
            check("a 200-char entry is rejected", len(errs) == 1 and "max 160" in errs[0],
                  f"got {errs}")

            exact = entry("y" * (160 - len(entry(""))))
            check("exactly 160 chars is accepted",
                  len(exact) == 160 and errors_for(root, exact) == [],
                  f"len={len(exact)} errs={errors_for(root, exact)}")

            over_by_one = entry("y" * (161 - len(entry(""))))
            check("161 chars is rejected",
                  len(over_by_one) == 161 and len(errors_for(root, over_by_one)) == 1,
                  f"len={len(over_by_one)} errs={errors_for(root, over_by_one)}")

            print("\n-- link rules --")
            two_links = "- [done] t (2026-01-01) → docs/real.md → docs/other.md"
            errs = errors_for(root, two_links)
            check("two `→` links are rejected",
                  any("max 1" in e for e in errs), f"got {errs}")

            dead = entry("t", "docs/gone.md")
            errs = errors_for(root, dead)
            check("a dead `→` target is rejected",
                  any("does not exist" in e for e in errs), f"got {errs}")

            check("no link at all is fine", errors_for(root, entry("t")) == [])

            print("\n-- skip paths --")
            prose = "# Changelog\n\n## Unreleased\n\n" + "z" * 300 + "\n"
            check("non-entry lines are not length-checked",
                  errors_for(root, prose) == [], f"got {errors_for(root, prose)}")

            check("a `- [ ]` backlog-style line is not an entry",
                  errors_for(root, "- [ ] " + "z" * 300) == [])

            missing = root / "nope" / "CHANGELOG.md"
            check("a missing file is skipped, not failed",
                  mod.main([str(missing)]) == 0)

            print("\n-- end-to-end --")
            errors_for(root, over)
            check("main() exits 1 on a violation",
                  mod.main([str(root / "CHANGELOG.md")]) == 1)
            errors_for(root, short)
            check("main() exits 0 on a clean file",
                  mod.main([str(root / "CHANGELOG.md")]) == 0)
        finally:
            mod.REPO_ROOT = original_root

    passed = sum(_results)
    total = len(_results)
    print(f"\n=== Results: {passed} PASS, {total - passed} FAIL ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
