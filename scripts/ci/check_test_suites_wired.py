#!/usr/bin/env python3
"""Every bundled test suite must be run by CI.

A suite nothing runs proves nothing: harness-curate found fifteen self-tests (hooks, curate,
task-next, every prod script) passing locally while `harness-check.yml` never invoked them, so
a regression in any of them would have merged green.

A tracked `*.py` under dev/, prod/ or scripts/ is a suite when its basename starts with `test_`
or it dispatches a quoted `--test` / `--selftest` / `--self-test` flag. It is wired when an
enabled step's `run:` command is `python3 <path>`, carrying that flag for a self-test — a plain
invocation of a dual-mode script runs the check, not its tests. Only `run:` values count, so a
YAML comment, a step `name:`, or an `if: false` job or step does not wire anything.

Usage: python3 scripts/ci/check_test_suites_wired.py [--test]   (needs PyYAML)
Exit: 0 clean, 1 any unwired suite.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys

import yaml

WORKFLOW = ".github/workflows/harness-check.yml"
SELF_TEST = re.compile(r"""["'](--test|--self-?test)["']""")


def find_suites(sources: dict[str, str]) -> dict[str, str | None]:
    """Map each suite path to the flag that runs it (None: the file is the test)."""
    suites = {}
    for path, text in sources.items():
        if os.path.basename(path).startswith("test_"):
            suites[path] = None
        elif m := SELF_TEST.search(text):
            suites[path] = m.group(1)
    return suites


def disabled(node: dict) -> bool:
    return node.get("if") is False or str(node.get("if", "")).strip().lower() == "false"


def invocations(workflow: str) -> set[tuple[str, tuple[str, ...]]]:
    """(script, args) for every `python3 <script> ...` line of an enabled step's `run:`."""
    found = set()
    for job in (yaml.safe_load(workflow) or {}).get("jobs", {}).values():
        if disabled(job):
            continue
        for step in job.get("steps", []):
            if disabled(step) or not isinstance(step.get("run"), str):
                continue
            for line in step["run"].splitlines():
                try:
                    argv = shlex.split(line, comments=True)
                except ValueError:
                    continue
                if len(argv) >= 2 and argv[0] == "python3" and argv[1].endswith(".py"):
                    found.add((argv[1], tuple(argv[2:])))
    return found


def check(suites: dict[str, str | None], workflow: str) -> list[str]:
    runs = invocations(workflow)
    problems = []
    for path, flag in sorted(suites.items()):
        if not any(p == path and (flag is None or flag in args) for p, args in runs):
            cmd = f"python3 {path}" + (f" {flag}" if flag else "")
            problems.append(f"{path}: test suite not run by {WORKFLOW} — add a `{cmd}` step")
    return problems


def tracked_sources(root: str) -> dict[str, str]:
    out = subprocess.check_output(
        ["git", "-C", root, "-c", "core.quotePath=false", "ls-files", "--",
         "dev/*.py", "prod/*.py", "scripts/*.py"],
        text=True,
    )
    sources = {}
    for rel in out.splitlines():
        # A tracked file deleted in the working tree (not yet `git rm`-ed) is no suite to run.
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                sources[rel] = f.read()
        except FileNotFoundError:
            continue
    return sources


def run_tests() -> int:
    results = []

    def t(name, cond):
        results.append((name, bool(cond)))
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    def wf(*runs, job_if=None, step_if=None):
        step = {"run": "\n".join(runs)}
        if step_if is not None:
            step["if"] = step_if
        job = {"steps": [step]}
        if job_if is not None:
            job["if"] = job_if
        return yaml.safe_dump({"jobs": {"j": job}})

    flag = 'if sys.argv[1:] == ["--test"]:\n'
    tool = find_suites({"prod/s/tool.py": flag})
    test_a = find_suites({"dev/s/test_a.py": ""})
    t("test_ file unwired: flagged", check(test_a, wf("echo hi")) != [])
    t("test_ file wired: clean", check(test_a, wf("python3 dev/s/test_a.py")) == [])
    t("--test self-test unwired: flagged", check(tool, wf("echo hi")) != [])
    t("--test self-test wired with its flag: clean",
      check(tool, wf("python3 prod/s/tool.py --test")) == [])
    t("--test self-test run without its flag: flagged",
      check(tool, wf("python3 prod/s/tool.py")) != [])
    t("single-quoted '--test' counts as a suite",
      find_suites({"p/t.py": "add_argument('--test')"}) == {"p/t.py": "--test"})
    sel = find_suites({"dev/s/c.py": "if '--selftest' in sys.argv:"})
    t("--selftest counts as a suite, flag kept", sel == {"dev/s/c.py": "--selftest"})
    t("--selftest wired with its flag: clean", check(sel, wf("python3 dev/s/c.py --selftest")) == [])
    t("plain helper (no test_, no flag): ignored", find_suites({"dev/s/h.py": "print('hi')"}) == {})
    t("prose mention without quotes is not a suite",
      find_suites({"dev/s/d.py": "# run with --test later"}) == {})
    t("path prefix of a wired file is not wired",
      check(test_a, wf("python3 dev/s/test_a.py.bak")) != [])
    t("shell-commented run line: flagged", check(test_a, wf("# python3 dev/s/test_a.py")) != [])
    t("YAML comment / step name only: flagged",
      check(test_a, "jobs:\n  j:\n    steps:\n      # run: python3 dev/s/test_a.py\n"
                    "      - name: python3 dev/s/test_a.py\n        run: echo skipped\n") != [])
    t("step if: false: flagged", check(test_a, wf("python3 dev/s/test_a.py", step_if=False)) != [])
    t("job if: false: flagged", check(test_a, wf("python3 dev/s/test_a.py", job_if="false")) != [])

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main() -> int:
    if "--test" in sys.argv[1:]:
        return run_tests()
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    with open(os.path.join(root, WORKFLOW), encoding="utf-8") as f:
        workflow = f.read()
    suites = find_suites(tracked_sources(root))
    problems = check(suites, workflow)
    for p in problems:
        print(f"ERROR: {p}")
    if problems:
        return 1
    print(f"OK: all {len(suites)} test suites run by {WORKFLOW}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
