#!/usr/bin/env python3
"""
Unit tests for check_harness_drift.py's section-reference gate.

The defect under test is PR #181's: the signal taxonomy was renumbered 8 -> 7 and five
`Signal 8` / `§8` references survived the rename, caught by human review only. The
regression case below reproduces exactly that shape — delete `check_section_refs`'s
lookup and it goes red.

Also covered: chained `§2·§3`, heading and **bold callout** anchors, cross-skill
resolution by unique basename, and the three deliberate skip paths (target-repo
filenames the plugin does not bundle, non-markdown targets, and a bare `§N` with no
file named on its line).

Run: python3 scripts/ci/test_check_harness_drift.py
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "check_harness_drift.py"
spec = importlib.util.spec_from_file_location("check_harness_drift", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


TAXONOMY = """# Signal Taxonomy

## 1. New-asset candidate

body

## 7. Instruction-layer overlap

body
"""

NOTES = """# Notes

## 2. Substring collision

body

## 3. Assert a count

body

## 3e. CI Failure Analysis

body

## header.xml Editing Guide

body

> **Validate timing when overwriting original**: run baseline first.
"""


def build_fixture(root: Path) -> dict:
    """Stage a two-skill plugin tree and return the resolver inputs for it."""
    alpha = write(root, "dev/skills/alpha/SKILL.md", "# alpha\n")
    notes = write(root, "dev/skills/alpha/references/notes.md", NOTES)
    beta = write(root, "dev/skills/beta/SKILL.md", "# beta\n")
    taxonomy = write(root, "dev/skills/beta/references/signal-taxonomy.md", TAXONOMY)
    index = mod.build_basename_index([alpha, beta, notes, taxonomy])
    return {"alpha": alpha, "notes": notes, "taxonomy": taxonomy, "index": index}


def run_refs(text: str, source: Path, index: dict) -> list[str]:
    return mod.check_section_refs(text, source, index, {})


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mod.REPO_ROOT = root
        fx = build_fixture(root)
        alpha, notes, index = fx["alpha"], fx["notes"], fx["index"]

        print("\nRegression — PR #181: taxonomy renumbered 8 -> 7, stale refs survive")
        stale = (
            "See `references/signal-taxonomy.md` §8 for the subtypes.\n"
            "Route it to Signal 8 instead.\n"
        )
        problems = run_refs(stale, alpha, index)
        check(
            "stale §8 is reported",
            any("§8" in p and "line 1" in p for p in problems),
            f"got {problems}",
        )
        check(
            "stale Signal 8 is reported",
            any("Signal 8" in p and "line 2" in p for p in problems),
            f"got {problems}",
        )
        live = (
            "See `references/signal-taxonomy.md` §7 for the subtypes.\n"
            "Route it to Signal 7 instead.\n"
        )
        check("live §7 / Signal 7 stay silent", run_refs(live, alpha, index) == [])

        print("\nCross-skill resolution by unique basename")
        # signal-taxonomy.md lives under beta/, referenced from alpha/ — the exact shape
        # that went stale in harness-init -> harness-curate.
        check(
            "dangling ref into another skill is reported",
            run_refs("`dev:beta` -> `references/signal-taxonomy.md` §9", alpha, index) != [],
        )

        print("\nAnchor forms")
        check(
            "chained §2·§3 both resolve",
            run_refs("Detail — `notes.md` §2·§3.", notes, index) == [],
        )
        check(
            "chained §2·§4 reports only the missing one",
            [p for p in run_refs("`notes.md` §2·§4.", notes, index) if "§4" in p]
            and not [p for p in run_refs("`notes.md` §2·§4.", notes, index) if "§2" in p],
        )
        check("letter-suffixed §3e resolves", run_refs("`notes.md` §3e", notes, index) == [])
        check(
            "quoted title matching a heading resolves",
            run_refs('`notes.md` § "header.xml Editing Guide"', notes, index) == [],
        )
        check(
            "quoted title matching a **bold** callout resolves",
            run_refs(
                '`notes.md` §"Validate timing when overwriting original"', notes, index
            )
            == [],
        )
        check(
            "unknown quoted title is reported",
            run_refs('`notes.md` § "No Such Section"', notes, index) != [],
        )

        print("\nSkip paths (must not fire)")
        check(
            "target-repo file the plugin does not bundle",
            run_refs("implement `backlog.md` § 'Add user avatars'", alpha, index) == [],
        )
        check(
            "non-markdown target has no heading structure",
            run_refs("`validate-harness.sh` §11 waives the checks", alpha, index) == [],
        )
        check(
            "bare §N with no file named on the line",
            run_refs("the operator skims past §11 entirely", alpha, index) == [],
        )
        check(
            "unquoted non-numeric §Foo is not a section reference",
            run_refs("Apply the **§Harness ratchet write-back gate**.", alpha, index) == [],
        )
        check(
            "SIGNALS in an uppercase scan-block name is not a signal reference",
            run_refs("blocks: `AGENT-CORRECTION-SIGNALS`, `PROMPTS`", alpha, index) == [],
        )

        print("\nSignal refs without a taxonomy in the tree")
        bare_index = mod.build_basename_index([alpha])
        check(
            "Signal N is skipped when no signal-taxonomy.md is bundled",
            run_refs("Route it to Signal 8 instead.", alpha, bare_index) == [],
        )

    print("\n----")
    failed = _results.count(False)
    if failed:
        print(f"FAIL: {failed}/{len(_results)} checks failed")
        return 1
    print(f"OK: {len(_results)}/{len(_results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
