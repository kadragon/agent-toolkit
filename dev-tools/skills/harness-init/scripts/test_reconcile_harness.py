#!/usr/bin/env python3
"""
Unit tests for reconcile-harness.py — multi-anchor support (## Covers).

Run: python test_reconcile_harness.py
"""

import sys
import importlib.util
from pathlib import Path

# ---------------------------------------------------------------------------
# Load module without executing __main__
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).parent / "reconcile-harness.py"
spec = importlib.util.spec_from_file_location("reconcile_harness", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# ---------------------------------------------------------------------------
# Helpers (shims that will be added in GREEN phase)
# ---------------------------------------------------------------------------

def tasks_anchors(content: str) -> list:
    """Extract anchors from ## Covers bullets, or fall back to [tasks_title]."""
    return mod.tasks_anchors(content)


def remove_active_markers(backlog: str, anchors: list) -> str:
    return mod.remove_active_markers(backlog, anchors)


def revert_active_markers(backlog: str, anchors: list, note: str) -> str:
    return mod.revert_active_markers(backlog, anchors, note)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


# ---------------------------------------------------------------------------
# tasks_anchors()
# ---------------------------------------------------------------------------

def test_tasks_anchors_covers():
    """## Covers section returns its bullet texts."""
    tasks = """\
# Bundle: fix mktemp + trap

status: active

## Covers
- [FIX] mktemp guard
- [FIX] trap on exit

## Scope
fix two shell files
"""
    anchors = tasks_anchors(tasks)
    check("covers: returns list length 2", len(anchors) == 2, str(anchors))
    check("covers: first anchor", anchors[0] == "[FIX] mktemp guard", repr(anchors[0]))
    check("covers: second anchor", anchors[1] == "[FIX] trap on exit", repr(anchors[1]))


def test_tasks_anchors_fallback():
    """No ## Covers → single-element list [title]."""
    tasks = """\
# Fix: codex review

status: active
"""
    anchors = tasks_anchors(tasks)
    check("fallback: returns list length 1", len(anchors) == 1, str(anchors))
    check("fallback: element is title", anchors[0] == "Fix: codex review", repr(anchors[0]))


def test_tasks_anchors_covers_trims_bullets():
    """Bullet prefix (- ) is stripped from anchor text."""
    tasks = """\
# Bundle

status: active

## Covers
-   [FEAT] new skill
- [DOCS] update readme

"""
    anchors = tasks_anchors(tasks)
    check("trims bullet: first", anchors[0] == "[FEAT] new skill", repr(anchors[0]))
    check("trims bullet: second", anchors[1] == "[DOCS] update readme", repr(anchors[1]))


# ---------------------------------------------------------------------------
# remove_active_markers() — multi-anchor done
# ---------------------------------------------------------------------------

BACKLOG_MULTI = """\
## Now
- [>] [FIX] mktemp guard in codex-review.sh
- [>] [FIX] trap on exit in codex-review.sh
- [ ] [FEAT] new thing

## Next
- [ ] [DOCS] readme update
"""


def test_remove_both_anchors_on_done():
    """status: done with ## Covers removes all matching [>] lines."""
    anchors = ["[FIX] mktemp guard in codex-review.sh", "[FIX] trap on exit in codex-review.sh"]
    result = remove_active_markers(BACKLOG_MULTI, anchors)
    check("done: first [>] removed", "[>] [FIX] mktemp guard" not in result)
    check("done: second [>] removed", "[>] [FIX] trap on exit" not in result)
    check("done: unrelated [ ] preserved", "- [ ] [FEAT] new thing" in result)
    check("done: next [ ] preserved", "- [ ] [DOCS] readme update" in result)


def test_remove_single_anchor_no_unrelated_strike():
    """Removing one anchor does not affect an unrelated [>] line."""
    backlog = """\
## Now
- [>] [FIX] mktemp guard in codex-review.sh
- [>] [FEAT] some unrelated feature
"""
    anchors = ["[FIX] mktemp guard in codex-review.sh"]
    result = remove_active_markers(backlog, anchors)
    check("single: target removed", "[>] [FIX] mktemp guard" not in result)
    check("single: unrelated preserved", "[>] [FEAT] some unrelated feature" in result)


def test_remove_backward_compat_single_title():
    """Single-anchor list (fallback) matches identically to old remove_active_marker."""
    backlog = """\
## Now
- [>] Fix: codex review
- [ ] [FEAT] other
"""
    # Old behaviour: title "Fix: codex review" → removes that [>] line
    anchors = ["Fix: codex review"]
    result = remove_active_markers(backlog, anchors)
    check("compat: matched [>] removed", "[>] Fix: codex review" not in result)
    check("compat: unrelated [ ] kept", "- [ ] [FEAT] other" in result)


# ---------------------------------------------------------------------------
# revert_active_markers() — multi-anchor failed
# ---------------------------------------------------------------------------

def test_revert_both_anchors_on_failed():
    """status: failed with ## Covers reverts all matching [>] lines → [ ]."""
    anchors = ["[FIX] mktemp guard in codex-review.sh", "[FIX] trap on exit in codex-review.sh"]
    result = revert_active_markers(BACKLOG_MULTI, anchors, "ci-fail")
    check("failed: first reverted to [ ]",
          "- [ ] [FIX] mktemp guard in codex-review.sh" in result or
          "[ ] [FIX] mktemp guard in codex-review.sh" in result)
    check("failed: second reverted to [ ]",
          "- [ ] [FIX] trap on exit in codex-review.sh" in result or
          "[ ] [FIX] trap on exit in codex-review.sh" in result)
    check("failed: no [>] lines remain for anchors",
          "[>] [FIX] mktemp guard" not in result and "[>] [FIX] trap on exit" not in result)
    check("failed: unrelated [ ] preserved", "- [ ] [FEAT] new thing" in result)
    check("failed: note appended to first", "ci-fail" in result)


def test_revert_backward_compat_single_title():
    """Single-anchor revert matches old revert_active_marker behaviour."""
    backlog = """\
## Now
- [>] Fix: codex review
"""
    anchors = ["Fix: codex review"]
    result = revert_active_markers(backlog, anchors, "failed-qa")
    check("compat-revert: [>] → [ ]", "[>]" not in result)
    check("compat-revert: [ ] present", "[ ] Fix: codex review" in result)
    check("compat-revert: note present", "failed-qa" in result)


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

SUITES = [
    ("tasks_anchors: ## Covers", test_tasks_anchors_covers),
    ("tasks_anchors: fallback to title", test_tasks_anchors_fallback),
    ("tasks_anchors: trims bullet prefix", test_tasks_anchors_covers_trims_bullets),
    ("remove_active_markers: done removes all", test_remove_both_anchors_on_done),
    ("remove_active_markers: single no collateral", test_remove_single_anchor_no_unrelated_strike),
    ("remove_active_markers: backward compat", test_remove_backward_compat_single_title),
    ("revert_active_markers: failed reverts all", test_revert_both_anchors_on_failed),
    ("revert_active_markers: backward compat", test_revert_backward_compat_single_title),
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
