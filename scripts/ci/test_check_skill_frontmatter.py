#!/usr/bin/env python3
"""
Unit tests for check_skill_frontmatter.py — the frontmatter validity gate.

The load-bearing case is `plain scalar with a colon-space`: the exact shape that made
`dev/skills/task-review/SKILL.md` load with empty metadata before PR #164.

Run: python3 scripts/ci/test_check_skill_frontmatter.py
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "check_skill_frontmatter.py"
spec = importlib.util.spec_from_file_location("check_skill_frontmatter", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def run_on(root: Path, rel: str, text: str) -> list[str]:
    """Write `text` at `root/rel` and return check_file()'s violations for it."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    original = mod.REPO_ROOT
    mod.REPO_ROOT = root
    try:
        return mod.check_file(path)
    finally:
        mod.REPO_ROOT = original


VALID_SKILL = """---
name: task-review
description: >-
  Post-dev review cycle — commit → reviews (Claude + agy + Codex) → apply →
  retrospect → CI → merge. Flags: --no-hub (local only), --auto (skip
  confirmation).
---

# Dev Review Cycle
"""

# The pre-PR-#164 line, verbatim in shape: an unquoted scalar carrying `: `.
REGRESSION_SKILL = """---
name: task-review
description: Post-dev review cycle — commit → apply → merge. --no-hub: local only. --auto: skip confirmation.
---

# Dev Review Cycle
"""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        print("\nfrontmatter parsing")
        valid = run_on(root, "dev/skills/task-review/SKILL.md", VALID_SKILL)
        check("valid folded scalar passes", valid == [], str(valid))

        regression = run_on(root, "dev/skills/task-review/SKILL.md", REGRESSION_SKILL)
        check(
            "plain scalar with `: ` is rejected (PR #164 regression)",
            len(regression) == 1 and "failed to parse as YAML" in regression[0],
            str(regression),
        )

        unclosed = run_on(
            root, "dev/skills/unclosed/SKILL.md", "---\nname: unclosed\ndescription: x\n"
        )
        check(
            "unclosed frontmatter block is rejected",
            len(unclosed) == 1 and "never closed" in unclosed[0],
            str(unclosed),
        )

        not_mapping = run_on(root, "dev/skills/listy/SKILL.md", "---\n- a\n- b\n---\n")
        check(
            "non-mapping frontmatter is rejected",
            len(not_mapping) == 1 and "not a YAML mapping" in not_mapping[0],
            str(not_mapping),
        )

        print("\nrequired keys")
        empty_desc = run_on(
            root, "dev/skills/empty/SKILL.md", '---\nname: empty\ndescription: ""\n---\n'
        )
        check(
            "empty description is rejected",
            len(empty_desc) == 1 and "is empty" in empty_desc[0],
            str(empty_desc),
        )

        missing_desc = run_on(
            root, "dev/skills/nodesc/SKILL.md", "---\nname: nodesc\n---\n"
        )
        check(
            "missing description is rejected",
            len(missing_desc) == 1 and "missing required key" in missing_desc[0],
            str(missing_desc),
        )

        null_desc = run_on(
            root, "dev/skills/nullval/SKILL.md", "---\nname: nullval\ndescription:\n---\n"
        )
        check(
            "valueless `description:` is rejected as such, not as missing",
            len(null_desc) == 1 and "has no value" in null_desc[0],
            str(null_desc),
        )

        non_string = run_on(
            root, "dev/skills/listdesc/SKILL.md", "---\nname: listdesc\ndescription: [a]\n---\n"
        )
        check(
            "non-string description is rejected",
            len(non_string) == 1 and "must be a string" in non_string[0],
            str(non_string),
        )

        print("\nname/path agreement")
        mismatch = run_on(
            root, "dev/skills/renamed/SKILL.md", "---\nname: old-name\ndescription: x\n---\n"
        )
        check(
            "skill `name:` must match its directory",
            len(mismatch) == 1 and "does not match the path" in mismatch[0],
            str(mismatch),
        )

        agent_ok = run_on(
            root, "prod/agents/persona-actor.md", "---\nname: persona-actor\ndescription: x\n---\n"
        )
        check("agent `name:` matching its file stem passes", agent_ok == [], str(agent_ok))

        agent_bad = run_on(
            root, "prod/agents/persona-actor.md", "---\nname: other\ndescription: x\n---\n"
        )
        check(
            "agent `name:` mismatching its file stem is rejected",
            len(agent_bad) == 1 and "does not match the path" in agent_bad[0],
            str(agent_bad),
        )

        print("\nasset-type shapes")
        command = run_on(
            root,
            "dev/commands/security-overview.md",
            '---\ndescription: "Scan alerts"\nallowed-tools: ["Bash"]\n---\n',
        )
        check("command without `name:` passes", command == [], str(command))

        print("\ndiscovery")
        check(
            "expected_shape routes a skill to name+description",
            mod.expected_shape("dev/skills/x/SKILL.md") == (["name", "description"], "x"),
            str(mod.expected_shape("dev/skills/x/SKILL.md")),
        )
        check(
            "expected_shape routes a command to description only",
            mod.expected_shape("dev/commands/y.md") == (["description"], None),
            str(mod.expected_shape("dev/commands/y.md")),
        )

    total = len(_results)
    passed = sum(_results)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
