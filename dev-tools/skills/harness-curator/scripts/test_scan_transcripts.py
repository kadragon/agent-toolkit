#!/usr/bin/env python3
"""
Unit tests for scan_transcripts.py — resolve_project_dir() exact-match priority.

Run: python test_scan_transcripts.py
"""

import os
import sys
import tempfile
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent / "scan_transcripts.py"
spec = importlib.util.spec_from_file_location("scan_transcripts", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def test_resolve_prefers_exact_match_over_higher_file_count_fuzzy_match():
    """Exact encode_project() dir wins even when a fuzzy sibling has more files."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/knue-patis"
        exact_name = mod.encode_project(path)
        exact_dir = os.path.join(proj_root, exact_name)
        os.mkdir(exact_dir)
        open(os.path.join(exact_dir, "session1.jsonl"), "w").close()

        fuzzy_name = exact_name.replace("-", "_", 1)
        fuzzy_dir = os.path.join(proj_root, fuzzy_name)
        os.mkdir(fuzzy_dir)
        for i in range(5):
            open(os.path.join(fuzzy_dir, f"session{i}.jsonl"), "w").close()

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir returns exact dir despite fuzzy dir having more files",
            resolved == exact_dir,
            f"expected {exact_dir!r}, got {resolved!r}",
        )


def test_resolve_falls_back_to_fuzzy_when_exact_absent():
    """No exact dir → fuzzy match by loose key, picking the most populated candidate."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/knue-patis"
        exact_name = mod.encode_project(path)

        fuzzy_name = exact_name.replace("-", "_", 1)
        fuzzy_dir = os.path.join(proj_root, fuzzy_name)
        os.mkdir(fuzzy_dir)
        open(os.path.join(fuzzy_dir, "session0.jsonl"), "w").close()

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir falls back to fuzzy match when exact dir absent",
            resolved == fuzzy_dir,
            f"expected {fuzzy_dir!r}, got {resolved!r}",
        )


def test_resolve_falls_back_to_exact_path_when_nothing_matches():
    """No exact dir, no fuzzy sibling → returns the (nonexistent) exact path."""
    with tempfile.TemporaryDirectory() as proj_root:
        path = "/dev/workspace/totally-unrelated"
        exact = os.path.join(proj_root, mod.encode_project(path))

        resolved = mod.resolve_project_dir(path, proj_root)
        check(
            "resolve_project_dir returns exact path when nothing matches",
            resolved == exact,
            f"expected {exact!r}, got {resolved!r}",
        )


SUITES = [
    (
        "resolve_project_dir: exact match beats higher-file-count fuzzy match",
        test_resolve_prefers_exact_match_over_higher_file_count_fuzzy_match,
    ),
    (
        "resolve_project_dir: falls back to fuzzy match when exact absent",
        test_resolve_falls_back_to_fuzzy_when_exact_absent,
    ),
    (
        "resolve_project_dir: falls back to exact path when nothing matches",
        test_resolve_falls_back_to_exact_path_when_nothing_matches,
    ),
]

if __name__ == "__main__":
    for suite_name, fn in SUITES:
        print(f"\n[{suite_name}]")
        try:
            fn()
        except AttributeError as e:
            print(f"  {FAIL}  AttributeError: {e}  (function not yet implemented)")
            _results.append(False)
        except Exception as e:
            print(f"  {FAIL}  Unexpected: {e}")
            _results.append(False)

    total = len(_results)
    passed = sum(_results)
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)
