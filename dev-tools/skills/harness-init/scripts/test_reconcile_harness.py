#!/usr/bin/env python3
"""
Unit tests for reconcile-harness.py — multi-anchor support (## Covers).

Run: python test_reconcile_harness.py
"""

import io
import sys
import contextlib
import tempfile
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
# Helpers — thin wrappers around mod.* for readable test assertions
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
    check("failed: note appended to both", result.count("ci-fail") == 2)


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
# tasks_anchors() — edge cases
# ---------------------------------------------------------------------------

def test_tasks_anchors_blank_line_before_bullets():
    """## Covers with blank line before bullets still parses correctly."""
    tasks = """\
# Bundle: blank-line test

status: active

## Covers

- [FIX] mktemp guard
- [FIX] trap on exit

## Scope
fix two files
"""
    anchors = tasks_anchors(tasks)
    check("blank-line-covers: returns 2 items", len(anchors) == 2, str(anchors))
    check("blank-line-covers: first anchor", anchors[0] == "[FIX] mktemp guard", repr(anchors[0]))
    check("blank-line-covers: second anchor", anchors[1] == "[FIX] trap on exit", repr(anchors[1]))


def test_tasks_anchors_empty_covers_fallback():
    """## Covers present but no bullets → falls back to title."""
    tasks = """\
# My Sprint

status: active

## Covers

## Scope
content here
"""
    anchors = tasks_anchors(tasks)
    check("empty-covers: falls back to 1-item list", len(anchors) == 1, str(anchors))
    check("empty-covers: value is title", anchors[0] == "My Sprint", repr(anchors[0]))


# ---------------------------------------------------------------------------
# remove_active_markers() / revert_active_markers() — edge cases
# ---------------------------------------------------------------------------

def test_remove_does_not_touch_queued_items():
    """[ ] lines are never removed even when text matches an anchor."""
    backlog = "## Now\n- [ ] [FIX] mktemp guard in codex-review.sh\n"
    anchors = ["[FIX] mktemp guard in codex-review.sh"]
    result = remove_active_markers(backlog, anchors)
    check("noop-queued: [ ] item preserved despite anchor match", "- [ ] [FIX] mktemp guard" in result)


def test_remove_case_insensitive():
    """Anchor match is case-insensitive."""
    backlog = "## Now\n- [>] [FIX] MKTEMP Guard in codex-review.sh\n"
    anchors = ["[fix] mktemp guard in codex-review.sh"]
    result = remove_active_markers(backlog, anchors)
    check("case-insensitive: lowercase anchor matches uppercase [>] line", "[>]" not in result)


# ---------------------------------------------------------------------------
# backward-compat shims — direct invocation
# ---------------------------------------------------------------------------

def test_shims_direct():
    """Single-title shim functions delegate to multi-anchor variants correctly."""
    backlog = "## Now\n- [>] Fix: codex review\n- [ ] [FEAT] other\n"
    result_rm = mod.remove_active_marker(backlog, "Fix: codex review")
    check("shim-rm: [>] removed", "[>]" not in result_rm)
    check("shim-rm: [ ] preserved", "- [ ] [FEAT] other" in result_rm)
    result_rv = mod.revert_active_marker(backlog, "Fix: codex review", "shim-note")
    check("shim-rv: [>] → [ ]", "[>]" not in result_rv)
    check("shim-rv: note present", "shim-note" in result_rv)


# ---------------------------------------------------------------------------
# strip_sprint_block() — preserve ## Review Backlog on sprint completion
# ---------------------------------------------------------------------------

TASKS_WITH_BACKLOG = """\
## Review Backlog

### PR #99 — findings
- [ ] open finding one
- [ ] open finding two

---

# Sprint: do the thing

status: done

**Scope**
- something

**Acceptance criteria**
- [x] did it
"""

TASKS_ONLY_SPRINT = """\
# Sprint: solo

status: done

**Scope**
- x
"""


def test_strip_preserves_review_backlog():
    """strip_sprint_block removes the Sprint Contract but keeps ## Review Backlog."""
    result = mod.strip_sprint_block(TASKS_WITH_BACKLOG)
    check("strip: returns content (not None)", result is not None, repr(result))
    check("strip: first open finding preserved", result and "open finding one" in result)
    check("strip: second open finding preserved", result and "open finding two" in result)
    check("strip: Review Backlog heading preserved", result and "## Review Backlog" in result)
    check("strip: sprint heading removed", result and "# Sprint: do the thing" not in result)
    check("strip: status line removed", result and "status: done" not in result)
    check("strip: trailing --- separator trimmed", result and not result.rstrip().endswith("---"))


def test_strip_only_sprint_returns_none():
    """tasks.md whose only content is the sprint block → None (caller unlinks)."""
    result = mod.strip_sprint_block(TASKS_ONLY_SPRINT)
    check("strip-solo: returns None", result is None, repr(result))


# A fenced code block under ## Review Backlog containing a '# ...' line must NOT
# be misread as the sprint heading. Before the status-gated fix, the first
# '^#\s+' match landed on the fenced comment line, truncating Review Backlog
# content and leaving the real Sprint Contract un-stripped.
TASKS_FENCED_COMMENT = """\
## Review Backlog

### PR #99 — findings
- [ ] open finding one

```sh
# this is a shell comment, not a sprint heading
echo hello
```

- [ ] open finding two

---

# Sprint: real sprint

status: done

**Scope**
- something
"""


def test_strip_ignores_fenced_heading_like_lines():
    """A '#' line inside a fenced code block is not treated as the sprint heading."""
    result = mod.strip_sprint_block(TASKS_FENCED_COMMENT)
    check("fenced: returns content (not None)", result is not None, repr(result))
    check("fenced: real sprint heading removed",
          result and "# Sprint: real sprint" not in result, repr(result))
    check("fenced: status line removed", result and "status: done" not in result)
    check("fenced: first open finding preserved", result and "open finding one" in result)
    check("fenced: second open finding preserved", result and "open finding two" in result)
    check("fenced: fenced comment line preserved",
          result and "this is a shell comment" in result)
    check("fenced: code fence preserved", result and "echo hello" in result)


# ---------------------------------------------------------------------------
# main() integration — done / failed branches write remainder, not unlink
# ---------------------------------------------------------------------------

def _run_main_in_tmp(tasks_text: str, backlog_text: str) -> dict:
    """Run mod.main() against a throwaway tasks.md/backlog.md and capture results.

    Returns a dict snapshotting file existence/contents and captured streams
    BEFORE the temp dir is removed (TemporaryDirectory cleans up on exit, so all
    reads must happen inside the context).
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        tpath, bpath = tmp / "tasks.md", tmp / "backlog.md"
        tpath.write_text(tasks_text, encoding="utf-8")
        bpath.write_text(backlog_text, encoding="utf-8")
        saved = (mod.TASKS, mod.BACKLOG, mod.CHANGELOG)
        mod.TASKS, mod.BACKLOG, mod.CHANGELOG = tpath, bpath, tmp / "CHANGELOG.md"
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                mod.main()
        finally:
            mod.TASKS, mod.BACKLOG, mod.CHANGELOG = saved
        return {
            "tasks_exists": tpath.exists(),
            "tasks_body": tpath.read_text(encoding="utf-8") if tpath.exists() else "",
            "backlog_body": bpath.read_text(encoding="utf-8"),
            "stdout": out.getvalue(),
            "stderr": err.getvalue(),
        }


def test_main_done_preserves_review_backlog():
    """done sprint with Review Backlog → tasks.md retained, findings survive."""
    backlog = "## Now\n- [>] Sprint: do the thing\n- [ ] unrelated\n"
    r = _run_main_in_tmp(TASKS_WITH_BACKLOG, backlog)
    check("main-done: tasks.md retained", r["tasks_exists"])
    check("main-done: open finding preserved", "open finding one" in r["tasks_body"])
    check("main-done: sprint block gone", "# Sprint: do the thing" not in r["tasks_body"])
    check("main-done: backlog [>] removed", "[>] Sprint: do the thing" not in r["backlog_body"])


def test_main_done_only_sprint_unlinks():
    """done sprint with no other content → tasks.md unlinked (old behaviour)."""
    backlog = "## Now\n- [>] Sprint: solo\n"
    r = _run_main_in_tmp(TASKS_ONLY_SPRINT, backlog)
    check("main-done-solo: tasks.md unlinked", not r["tasks_exists"])


def test_main_failed_preserves_review_backlog():
    """failed sprint with Review Backlog → tasks.md retained, findings survive."""
    failed_tasks = TASKS_WITH_BACKLOG.replace("status: done", "status: failed")
    backlog = "## Now\n- [>] Sprint: do the thing\n- [ ] unrelated\n"
    r = _run_main_in_tmp(failed_tasks, backlog)
    check("main-failed: tasks.md retained", r["tasks_exists"])
    check("main-failed: open finding preserved", "open finding one" in r["tasks_body"])
    check("main-failed: sprint block gone", "# Sprint: do the thing" not in r["tasks_body"])
    check("main-failed: backlog [>] reverted to [ ]", "[ ] Sprint: do the thing" in r["backlog_body"])


def test_main_statusless_retained_reports_cleanly():
    """A retained Review-Backlog-only tasks.md (no status, no '# ' heading) — the
    steady state left by this fix after a prior sprint completion — must report
    normally, NOT emit a schema-drift warning and return early."""
    statusless = "## Review Backlog\n\n### PR #99\n- [ ] leftover finding\n"
    backlog = "## Now\n- [ ] queued item\n"
    r = _run_main_in_tmp(statusless, backlog)
    check("statusless: no schema-drift warning", "unknown status" not in r["stderr"], r["stderr"])
    check("statusless: backlog reported",
          "Backlog:" in r["stdout"] or "Backlog clear" in r["stdout"], r["stdout"])
    check("statusless: tasks.md left intact",
          r["tasks_exists"] and "leftover finding" in r["tasks_body"])


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

SUITES = [
    ("tasks_anchors: ## Covers", test_tasks_anchors_covers),
    ("tasks_anchors: fallback to title", test_tasks_anchors_fallback),
    ("tasks_anchors: trims bullet prefix", test_tasks_anchors_covers_trims_bullets),
    ("tasks_anchors: blank line before bullets", test_tasks_anchors_blank_line_before_bullets),
    ("tasks_anchors: empty Covers fallback", test_tasks_anchors_empty_covers_fallback),
    ("remove_active_markers: done removes all", test_remove_both_anchors_on_done),
    ("remove_active_markers: single no collateral", test_remove_single_anchor_no_unrelated_strike),
    ("remove_active_markers: backward compat", test_remove_backward_compat_single_title),
    ("remove_active_markers: no-op on queued items", test_remove_does_not_touch_queued_items),
    ("remove_active_markers: case-insensitive", test_remove_case_insensitive),
    ("revert_active_markers: failed reverts all", test_revert_both_anchors_on_failed),
    ("revert_active_markers: backward compat", test_revert_backward_compat_single_title),
    ("shims: direct invocation", test_shims_direct),
    ("strip_sprint_block: preserves Review Backlog", test_strip_preserves_review_backlog),
    ("strip_sprint_block: only sprint → None", test_strip_only_sprint_returns_none),
    ("strip_sprint_block: ignores fenced heading-like lines", test_strip_ignores_fenced_heading_like_lines),
    ("main: done preserves Review Backlog", test_main_done_preserves_review_backlog),
    ("main: done only-sprint unlinks", test_main_done_only_sprint_unlinks),
    ("main: failed preserves Review Backlog", test_main_failed_preserves_review_backlog),
    ("main: statusless retained reports cleanly", test_main_statusless_retained_reports_cleanly),
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
