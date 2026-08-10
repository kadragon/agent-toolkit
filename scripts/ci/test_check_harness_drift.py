#!/usr/bin/env python3
"""
Unit tests for check_harness_drift.py's reference gates.

The defect under test is PR #181's: the signal taxonomy was renumbered 8 -> 7 and five
`Signal 8` / `§8` references survived the rename, caught by human review only. The
regression case below reproduces exactly that shape — delete `check_section_refs`'s
lookup and it goes red.

Also covered: chained `§2·§3`, heading and **bold callout** anchors, cross-skill
resolution by unique basename, and the three deliberate skip paths (target-repo
filenames the plugin does not bundle, non-markdown targets, and a bare `§N` with no
file named on its line).

Bundled-script and bundled-with attribution resolution are covered in their own blocks
at the end; the latter reproduces PR #211's stale `delegation-template.md` pointer.

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

        print("\nAnchor forms (referenced cross-asset, from the skill's own SKILL.md)")
        chained = run_refs("`references/notes.md` §2·§4.", alpha, index)
        check(
            "chained §2·§3 both resolve",
            run_refs("Detail — `references/notes.md` §2·§3.", alpha, index) == [],
        )
        check(
            "chained §2·§4 reports only the missing one",
            [p for p in chained if "§4" in p] and not [p for p in chained if "§2" in p],
            f"got {chained}",
        )
        check(
            "letter-suffixed §3e resolves",
            run_refs("`references/notes.md` §3e", alpha, index) == [],
        )
        check(
            "quoted title matching a heading resolves",
            run_refs('`references/notes.md` § "header.xml Editing Guide"', alpha, index) == [],
        )
        check(
            "quoted title matching a **bold** callout resolves",
            run_refs(
                '`references/notes.md` §"Validate timing when overwriting original"',
                alpha,
                index,
            )
            == [],
        )
        check(
            "unknown quoted title is reported",
            run_refs('`references/notes.md` § "No Such Section"', alpha, index) != [],
        )
        check(
            "a uniquely-named file referencing itself is still graded",
            run_refs("`notes.md` § \"No Such Section\"", notes, index) != [],
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
        check(
            "Signal N in a file that never reaches for the taxonomy is not graded",
            run_refs("The rubric scores Signal 9 highest.", notes, index) == [],
        )
        check(
            "...but is graded once the same file names the taxonomy",
            run_refs(
                "See `references/signal-taxonomy.md` §7.\nThe rubric scores Signal 9 highest.",
                notes,
                index,
            )
            != [],
        )

        print("\nFail closed on a bundled references/ target that no longer exists")
        gone = run_refs("See `references/deleted-doc.md` §2 for detail.", alpha, index)
        check("missing references/ target is reported", gone != [], f"got {gone}")
        check(
            "the message names the unresolvable file",
            gone and "deleted-doc.md" in gone[0],
            f"got {gone}",
        )

        print("\nAmbiguous basename does not resolve to the referrer")
        # `SKILL.md` collides across skills; probing source.parent first would grade the
        # reference against the referring file's own anchors.
        check(
            "cross-skill `SKILL.md` §N is skipped, not mis-resolved",
            run_refs("`dev:beta` -> `SKILL.md` §1 covers it", alpha, index) == [],
        )

    print("\nBundled-script references resolve against the owning skill")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        skill = write(root, "dev/skills/alpha/SKILL.md", "placeholder")
        write(root, "dev/skills/alpha/scripts/present.py", "print()")
        write(root, "dev/skills/beta/scripts/elsewhere.py", "print()")

        def run_scripts(text):
            return mod.check_bundled_script_refs(text, skill)

        check(
            "a bundled script that exists passes",
            run_scripts('python3 "$SKILL_DIR/scripts/present.py" --flag') == [],
        )
        missing = run_scripts('python3 "$SKILL_DIR/scripts/absent.py"')
        check("a missing bundled script is reported", missing != [], f"got {missing}")
        check(
            "the message names the unresolvable script",
            missing and "absent.py" in missing[0],
            f"got {missing}",
        )
        # The whole point of the guard: a directory-only check passes here, a file check
        # does not. `scripts/` exists in this skill, `elsewhere.py` is another skill's.
        check(
            "another skill's script does not satisfy the reference",
            run_scripts('python3 "$SKILL_DIR/scripts/elsewhere.py"') != [],
        )
        check(
            "the `$SKILL_DIR/scripts/...` prose placeholder is not graded",
            run_scripts("scripts live under `$SKILL_DIR/scripts/...`") == [],
        )
        check(
            "${SKILL_DIR} brace form is matched too",
            run_scripts('python3 "${SKILL_DIR}/scripts/absent.py"') != [],
        )

        # Sibling form: two skills in one plugin sharing one copy of a script. The reference is
        # as breakable as an own-skill one, so it must be graded, not silently skipped.
        check(
            "a sibling skill's bundled script resolves",
            run_scripts('python3 "$SKILL_DIR/../beta/scripts/elsewhere.py"') == [],
        )
        sib_missing = run_scripts('python3 "$SKILL_DIR/../beta/scripts/absent.py"')
        check(
            "a missing sibling script is reported, not skipped",
            sib_missing != [] and "../beta/scripts/absent.py" in sib_missing[0],
            f"got {sib_missing}",
        )
        check(
            "a reference to a sibling skill that does not exist at all is reported",
            run_scripts('python3 "$SKILL_DIR/../gamma/scripts/present.py"') != [],
        )
        check(
            "the sibling path is not also graded as an own-skill reference",
            run_scripts('python3 "$SKILL_DIR/../beta/scripts/elsewhere.py"') == [],
        )

    print("\nBundled-with attributions name the skill that really holds the file")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        skill = write(root, "dev/skills/task-next/SKILL.md", "placeholder")
        write(root, "dev/skills/harness-curate/references/delegation-template.md", "x")
        write(root, "dev/skills/harness-init/references/harness-invariants.md", "x")
        write(root, "prod/skills/hwpx/references/tables.md", "x")

        def run_with(text):
            return mod.check_bundled_with_refs(text, skill)

        check(
            "a correct attribution passes",
            run_with("`harness-invariants.md` (bundled with `dev:harness-init`).") == [],
        )
        # The PR #211 defect verbatim: task-review's rule copied into task-next, stale
        # pointer and all. Delete the owner lookup and this goes green.
        wrong = run_with("`delegation-template.md` (bundled with `dev:harness-init`).")
        check("regression — PR #211: a wrong owner is reported", wrong != [], f"got {wrong}")
        check(
            "the message names the real owner",
            wrong and "dev:harness-curate" in wrong[0],
            f"got {wrong}",
        )
        check(
            "an attribution to a skill that does not exist is reported",
            run_with("`delegation-template.md` (bundled with `dev:nonesuch`).") != [],
        )
        check(
            "a file no skill bundles is reported, not skipped",
            run_with("`invented.md` (bundled with `dev:harness-init`).") != [],
        )
        check(
            "a cross-plugin attribution resolves",
            run_with("`tables.md` (bundled with `prod:hwpx`).") == [],
        )
        check(
            "an attribution with no filename in reach is skipped",
            run_with("that rule (bundled with `dev:harness-init`) applies here.") == [],
        )
        check(
            "a hard-wrapped filename on the line above still resolves",
            run_with("see `delegation-template.md`\n(bundled with `dev:harness-curate`).") == [],
        )
        check(
            "a hard-wrapped filename on the line above is still graded",
            run_with("see `delegation-template.md`\n(bundled with `dev:harness-init`).") != [],
        )
        # Contest round on PR #214: an attribution that spells out no filename of its own
        # must not bind to target-repo prose earlier on the line. `backlog.md`, `tasks.md`
        # and `docs/workflows.md` are pervasive in task-next/task-new and are not shipped
        # by any skill, so binding to them turns a legitimate sentence into a CI hard-fail.
        check(
            "an unnamed attribution does not bind to target-repo prose on the same line",
            run_with(
                "Append the item to `backlog.md` using the delegation template "
                "(bundled with `dev:harness-curate`)."
            )
            == [],
        )
        check(
            "an unnamed attribution does not bind to a target-repo file on the line above",
            run_with(
                "See `docs/workflows.md` for the cycle, then follow the template\n"
                "(bundled with `dev:harness-curate`)."
            )
            == [],
        )
        # Adjacency must not become a licence to skip: an unresolvable name the attribution
        # really does spell out still fails closed (deleted or renamed bundled asset).
        check(
            "adjacency does not weaken the fail-closed case",
            run_with("`invented.md` (bundled with `dev:harness-init`).") != [],
        )

        # The wrap fallback must not reach across a paragraph break: an unrelated file
        # named in the paragraph above is not what this attribution is talking about.
        check(
            "a filename in a preceding paragraph is not attached across a blank line",
            run_with("`delegation-template.md` lives elsewhere.\n\n"
                     "that rule (bundled with `dev:harness-init`) applies here.") == [],
        )
        check(
            "the filename nearest the attribution wins over an earlier one",
            run_with(
                "unlike `harness-invariants.md`, `delegation-template.md` "
                "(bundled with `dev:harness-curate`) lives elsewhere."
            )
            == [],
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
