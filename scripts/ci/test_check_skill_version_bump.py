#!/usr/bin/env python3
"""
Unit tests for check_skill_version_bump.py — the skill `version:` minor-bump gate for new
bundled files.

Load-bearing cases:

* a new `references/` or `scripts/` file with only a patch bump fails and names the skill;
* a minor or major bump passes;
* same-skill renames, `scripts/` test support, and `evals/`/`agents/`/`examples/` files are not
  counted, while `references/test_*` files and moves from another skill are;
* a `---` inside a frontmatter value does not hide `version:`;
* a `Skill-Bump-Exempt: <skill> — <reason>` trailer (`-` separator and `<plugin>:<name>` key
  also accepted) exempts that skill only, and an empty reason exempts nothing;
* a new skill, or one with no `version:` key at base, is skipped;
* an unresolvable diff base skips locally and FAILS under `require_diff_base`.

Every case builds a throwaway repo with a real `origin/main` ref. Commits use
`--no-verify` and a neutralized `core.hooksPath`, so no global hook reaches the fixture.

Run: python3 scripts/ci/test_check_skill_version_bump.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_skill_version_bump.py"
spec = importlib.util.spec_from_file_location("check_skill_version_bump", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            *args,
        ],
        cwd=root,
        check=True,
    )


def make_repo(tmp: Path, base_files: dict, head_files: dict, message: str = "head") -> Path:
    """Commit `base_files` as `origin/main`, then apply `head_files` (None deletes) on top."""
    _git(tmp, "init", "-q")
    for rel, content in base_files.items():
        write(tmp, rel, content)
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "--no-verify", "-m", "base")
    _git(tmp, "update-ref", "refs/remotes/origin/main", "HEAD")
    for rel, content in head_files.items():
        if content is None:
            (tmp / rel).unlink()
        else:
            write(tmp, rel, content)
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "--no-verify", "-m", message)
    return tmp


def skill_md(name: str, version: str | None) -> str:
    version_line = f"version: {version}\n" if version else ""
    return f"---\nname: {name}\ndescription: test skill\n{version_line}---\n\n# {name}\n"


REF_TEXT = "# Reference\n\nSome guidance that is long enough to be detected as a rename.\n" * 3


def run(base: dict, head: dict, message: str = "head", **kwargs) -> tuple[str, bool]:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(Path(tmp), base, head, message)
        lines, ok = mod.build_report(root, **kwargs)
    return "\n".join(lines), ok


def base_skill(version: str | None = "1.1.2") -> dict:
    return {"dev/skills/grill/SKILL.md": skill_md("grill", version)}


def test_patch_bump_fails():
    report, ok = run(
        base_skill(),
        {
            "dev/skills/grill/SKILL.md": skill_md("grill", "1.1.3"),
            "dev/skills/grill/references/automation.md": REF_TEXT,
        },
    )
    check("new reference + patch bump fails", not ok, report)
    check("failure names the skill", "dev/skills/grill" in report, report)
    check("failure names the file", "references/automation.md" in report, report)

    report, ok = run(
        base_skill(),
        {"dev/skills/grill/scripts/run.py": "print('x')\n"},
    )
    check("new script + no bump fails", not ok, report)


def test_minor_or_major_passes():
    for version in ("1.2.0", "2.0.0"):
        report, ok = run(
            base_skill(),
            {
                "dev/skills/grill/SKILL.md": skill_md("grill", version),
                "dev/skills/grill/references/automation.md": REF_TEXT,
            },
        )
        check(f"new reference + bump to {version} passes", ok, report)


def test_uncounted_files_pass():
    report, ok = run(
        base_skill(),
        {
            "dev/skills/grill/scripts/test_run.py": "assert True\n",
            "dev/skills/grill/evals/workflow-cases.json": "[]\n",
            "dev/skills/grill/agents/openai.yaml": "name: grill\n",
        },
    )
    check("test_* script, evals/, agents/ additions pass with no bump", ok, report)

    base = base_skill()
    base["dev/skills/grill/references/old.md"] = REF_TEXT
    report, ok = run(
        base,
        {
            "dev/skills/grill/references/old.md": None,
            "dev/skills/grill/references/new.md": REF_TEXT,
        },
    )
    check("renamed reference passes with no bump", ok, report)


def test_exempt_trailer():
    head = {
        "dev/skills/grill/SKILL.md": skill_md("grill", "1.1.3"),
        "dev/skills/grill/references/automation.md": REF_TEXT,
    }
    report, ok = run(
        base_skill(), head, "[REFACTOR] split\n\nSkill-Bump-Exempt: grill — content moved out of SKILL.md\n"
    )
    check("trailer for the skill exempts it", ok, report)
    check("exemption reason is echoed", "content moved out of SKILL.md" in report, report)

    report, ok = run(base_skill(), head, "x\n\nSkill-Bump-Exempt: other - unrelated\n")
    check("trailer for another skill does not exempt", not ok, report)

    report, ok = run(base_skill(), head, "x\n\nSkill-Bump-Exempt: grill —\n")
    check("trailer with empty reason does not exempt", not ok, report)


def test_review_regressions():
    report, ok = run(base_skill(), {"dev/skills/grill/references/test_strategy.md": REF_TEXT})
    check("references/test_* still counts", not ok, report)

    report, ok = run(
        base_skill(),
        {
            "dev/skills/grill/scripts/fixtures/case.json": "{}\n",
            "dev/skills/grill/scripts/testdata/in.txt": "x\n",
            "dev/skills/grill/examples/demo.md": REF_TEXT,
        },
    )
    check("scripts fixtures/testdata and examples/ are not counted", ok, report)

    base = base_skill()
    base["dev/skills/other/SKILL.md"] = skill_md("other", "1.0.0")
    base["dev/skills/other/references/shared.md"] = REF_TEXT
    report, ok = run(
        base,
        {
            "dev/skills/other/references/shared.md": None,
            "dev/skills/grill/references/shared.md": REF_TEXT,
        },
    )
    check("move from another skill counts as new", not ok, report)

    base = {"dev/skills/grill/SKILL.md": "---\nname: grill\ndescription: a --- b\nversion: 1.1.2\n---\n\n# grill\n"}
    report, ok = run(base, {"dev/skills/grill/references/a.md": REF_TEXT})
    check("`---` inside a frontmatter value does not hide the version", not ok, report)


def test_trailer_forms():
    head = {"dev/skills/grill/references/a.md": REF_TEXT}
    report, ok = run(base_skill(), head, "x\n\nSkill-Bump-Exempt: grill - moved out of SKILL.md\n")
    check("`-` separator exempts a matching skill", ok, report)

    report, ok = run(base_skill(), head, "x\n\nSkill-Bump-Exempt: dev:grill — moved\n")
    check("`<plugin>:<name>` key exempts that plugin's skill", ok, report)

    report, ok = run(base_skill(), head, "x\n\nSkill-Bump-Exempt: prod:grill — moved\n")
    check("another plugin's key does not exempt", not ok, report)


def test_skipped_skills():
    report, ok = run(
        {"README.md": "x\n"},
        {
            "dev/skills/fresh/SKILL.md": skill_md("fresh", "1.0.0"),
            "dev/skills/fresh/references/a.md": REF_TEXT,
        },
    )
    check("new skill is skipped", ok, report)

    report, ok = run(
        base_skill(version=None),
        {"dev/skills/grill/references/a.md": REF_TEXT},
    )
    check("skill with no version key at base is skipped", ok, report)
    check("skip is reported as a note", "NOTE" in report, report)


def test_unresolvable_base():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _git(root, "init", "-q")
        write(root, "README.md", "x\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "--no-verify", "-m", "only")
        lines, ok = mod.build_report(root)
        check("missing origin/main skips locally", ok, "\n".join(lines))
        lines, ok = mod.build_report(root, require_diff_base=True)
        check("missing origin/main fails when required", not ok, "\n".join(lines))


def main():
    test_patch_bump_fails()
    test_minor_or_major_passes()
    test_uncounted_files_pass()
    test_exempt_trailer()
    test_review_regressions()
    test_trailer_forms()
    test_skipped_skills()
    test_unresolvable_base()

    total = len(_results)
    passed = sum(_results)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
