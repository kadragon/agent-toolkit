#!/usr/bin/env python3
"""Every bundled test suite must be run by CI.

A suite nothing runs proves nothing: harness-curate found fifteen self-tests (hooks, curate,
task-next, every prod script) passing locally while `harness-check.yml` never invoked them, so
a regression in any of them would have merged green.

A tracked `*.py` under dev/, prod/ or scripts/ is a suite when its basename starts with `test_`
or it dispatches a `"--test"` self-test. It is wired when the workflow has a
`python3 <path>` command for it.

Usage: python3 scripts/ci/check_test_suites_wired.py [--test]
Exit: 0 clean, 1 any unwired suite.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

WORKFLOW = ".github/workflows/harness-check.yml"
SELF_TEST = re.compile(r"""["']--test["']""")
INVOKED = re.compile(r"python3\s+([\w./-]+\.py)(?![\w./-])")


def is_suite(path: str, text: str) -> bool:
    return os.path.basename(path).startswith("test_") or bool(SELF_TEST.search(text))


def check(sources: dict[str, str], workflow: str) -> list[str]:
    wired = set(INVOKED.findall(workflow))
    return [
        f"{path}: test suite not run by {WORKFLOW} — add a `python3 {path}` step"
        for path, text in sorted(sources.items())
        if is_suite(path, text) and path not in wired
    ]


def tracked_sources(root: str) -> dict[str, str]:
    out = subprocess.check_output(
        ["git", "-C", root, "-c", "core.quotePath=false", "ls-files", "--",
         "dev/*.py", "prod/*.py", "scripts/*.py"],
        text=True,
    )
    sources = {}
    for rel in out.splitlines():
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            sources[rel] = f.read()
    return sources


def run_tests() -> int:
    results = []

    def t(name, cond):
        results.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    flag = 'if sys.argv[1:] == ["--test"]:\n'
    t("test_ file unwired: flagged",
      check({"dev/s/test_a.py": ""}, "") != [])
    t("test_ file wired: clean",
      check({"dev/s/test_a.py": ""}, "run: python3 dev/s/test_a.py\n") == [])
    t("--test self-test unwired: flagged",
      check({"prod/s/tool.py": flag}, "") != [])
    t("--test self-test wired with its flag: clean",
      check({"prod/s/tool.py": flag}, "run: python3 prod/s/tool.py --test\n") == [])
    t("single-quoted '--test' counts as a suite",
      check({"prod/s/tool.py": "add_argument('--test')"}, "") != [])
    t("plain helper (no test_, no --test): ignored",
      check({"dev/s/helper.py": "print('hi')"}, "") == [])
    t("prose mention without quotes is not a suite",
      check({"dev/s/doc.py": "# run with --test later"}, "") == [])
    t("path prefix of a wired file is not wired",
      check({"dev/s/test_a.py": ""}, "run: python3 dev/s/test_a.py.bak\n") != [])

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main() -> int:
    if "--test" in sys.argv[1:]:
        return run_tests()
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    with open(os.path.join(root, WORKFLOW), encoding="utf-8") as f:
        workflow = f.read()
    sources = tracked_sources(root)
    problems = check(sources, workflow)
    for p in problems:
        print(f"ERROR: {p}")
    if problems:
        return 1
    suites = sum(is_suite(p, s) for p, s in sources.items())
    print(f"OK: all {suites} test suites run by {WORKFLOW}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
