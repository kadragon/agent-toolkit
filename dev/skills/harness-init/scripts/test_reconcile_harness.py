#!/usr/bin/env python3
"""
Unit tests for reconcile-harness.py.

Run: python test_reconcile_harness.py
"""

import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Load module without executing __main__
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).parent / "reconcile-harness.py"
spec = importlib.util.spec_from_file_location("reconcile_harness", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

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


def test_remove_empty_headings_keeps_nested_findings():
    """REGRESSION: a parent heading whose child owns items must survive.

    The documented findings shape in backlog.md is '## Review Backlog' / '### PR #N' /
    items.  The old 'heading followed by a heading' test deleted both the parent and
    '# Backlog' itself, orphaning every finding on the ordinary idle maintenance path.
    """
    nested = (
        "# Backlog\n\n"
        "## Review Backlog\n\n"
        "### PR #101 — earlier PR (2026-07-01)\n\n"
        "- [ ] [debt] leftover finding\n\n"
        "## Security Fixes — my-webapp\n\n"
        "### Dependabot Alerts\n\n"
        "- [ ] Upgrade jsonwebtoken\n"
    )
    result = mod.remove_empty_headings(nested)
    for keep in ("# Backlog", "## Review Backlog", "### PR #101", "## Security Fixes — my-webapp",
                 "### Dependabot Alerts", "leftover finding", "Upgrade jsonwebtoken"):
        check(f"empty-headings: {keep!r} preserved", keep in result, repr(result))


def test_remove_empty_headings_still_drops_empty_ones():
    """The genuinely-empty cases must still go, including a parent whose children are all empty."""
    result = mod.remove_empty_headings(
        "# Backlog\n\n## Has work\n\n- [ ] real item\n\n## Empty parent\n\n### Empty child\n"
    )
    check("empty-headings: empty child dropped", "### Empty child" not in result, repr(result))
    check("empty-headings: parent of only-empty children dropped", "## Empty parent" not in result)
    check("empty-headings: section with work kept", "## Has work" in result and "real item" in result)
    check("empty-headings: root kept", "# Backlog" in result)


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


def test_tasks_title_ignores_fenced_heading_like_lines():
    """tasks_title resolves to the real sprint heading, not a fenced '# ' line."""
    title = mod.tasks_title(TASKS_FENCED_COMMENT)
    check("title-fenced: real sprint title", title == "Sprint: real sprint", repr(title))


# A fenced 'status:' example under a NON-sprint top-level '# ' heading must not
# make that heading look like the sprint block. Heading detection alone is
# fence-aware; the 'status:' probe must be too, or the wrong section gets stripped.
TASKS_FENCED_STATUS = """\
# Notes

```
status: active
```

# Sprint: real

status: done

**Scope**
- something
"""


def test_strip_status_probe_is_fence_aware():
    """A fenced 'status:' under a non-sprint heading does not anchor the sprint."""
    result = mod.strip_sprint_block(TASKS_FENCED_STATUS)
    check("fenced-status: returns content (not None)", result is not None, repr(result))
    check("fenced-status: non-sprint heading preserved", result and "# Notes" in result)
    check("fenced-status: fenced status example preserved",
          result and "status: active" in result)
    check("fenced-status: real sprint heading removed",
          result and "# Sprint: real" not in result, repr(result))
    check("fenced-status: real status line removed", result and "status: done" not in result)


# Nested fences: a shorter inner fence must NOT close a longer outer one, so a
# '# ' line still inside the outer 4-backtick block is not read as a heading.
TASKS_NESTED_FENCE = """\
## Review Backlog

- [ ] open finding

````md
```
# not a heading
```
````

---

# Sprint: real

status: done

**Scope**
- x
"""


def test_strip_handles_nested_fences():
    """A shorter inner fence does not prematurely close a longer outer fence."""
    result = mod.strip_sprint_block(TASKS_NESTED_FENCE)
    check("nested: returns content (not None)", result is not None, repr(result))
    check("nested: open finding preserved", result and "open finding" in result)
    check("nested: nested fence content preserved", result and "# not a heading" in result)
    check("nested: real sprint heading removed",
          result and "# Sprint: real" not in result, repr(result))


# ---------------------------------------------------------------------------
# main() integration — done / failed branches write remainder, not unlink
# ---------------------------------------------------------------------------

def _read_raw(path: Path) -> str:
    """Read text without Python's universal-newline conversion."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _run_main_in_tmp(tasks_text: str, backlog_text: str, changelog_text: str | None = None) -> dict:
    """Run mod.main() against a throwaway tasks.md/backlog.md and capture results.

    Returns a dict snapshotting file existence/contents and captured streams
    BEFORE the temp dir is removed (TemporaryDirectory cleans up on exit, so all
    reads must happen inside the context).
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        tpath, bpath, cpath = tmp / "tasks.md", tmp / "backlog.md", tmp / "CHANGELOG.md"
        tpath.write_bytes(tasks_text.encode("utf-8"))
        bpath.write_bytes(backlog_text.encode("utf-8"))
        if changelog_text is not None:
            cpath.write_bytes(changelog_text.encode("utf-8"))
        saved = (mod.TASKS, mod.BACKLOG, mod.CHANGELOG)
        mod.TASKS, mod.BACKLOG, mod.CHANGELOG = tpath, bpath, cpath
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                mod.main()
        finally:
            mod.TASKS, mod.BACKLOG, mod.CHANGELOG = saved
        return {
            "tasks_exists": tpath.exists(),
            "tasks_body": _read_raw(tpath) if tpath.exists() else "",
            "backlog_body": _read_raw(bpath),
            "changelog_body": _read_raw(cpath) if cpath.exists() else "",
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
    check("main-done: backlog untouched", r["backlog_body"] == backlog, r["backlog_body"])


def test_main_done_only_sprint_unlinks():
    """done sprint with no other content → tasks.md unlinked (old behaviour)."""
    backlog = "## Now\n- [>] Sprint: solo\n"
    r = _run_main_in_tmp(TASKS_ONLY_SPRINT, backlog)
    check("main-done-solo: tasks.md unlinked", not r["tasks_exists"])


def test_main_done_changelog_single_line_under_unreleased():
    """done sprint → exactly one `- [done]` line inserted under `## Unreleased`.

    CHANGELOG Entry Contract (references/harness-invariants.md): the entry is one line,
    never a `## {date} — {title}` block with a summary paragraph.
    """
    before = "# Changelog\n\n## Unreleased\n\n- [done] earlier thing (2026-01-01)\n"
    backlog = "## Now\n- [>] Sprint: do the thing\n"
    r = _run_main_in_tmp(TASKS_WITH_BACKLOG, backlog, changelog_text=before)
    body = r["changelog_body"]
    added = [ln for ln in body.splitlines() if ln not in before.splitlines()]
    check("changelog: exactly one line added", len(added) == 1, repr(added))
    check("changelog: entry is a `- [done]` bullet",
          bool(added) and added[0].startswith("- [done] "), repr(added))
    check("changelog: no date-heading block", "## 20" not in body, body)
    check("changelog: prior entry preserved", "earlier thing (2026-01-01)" in body, body)
    lines = body.splitlines()
    idx_unreleased = lines.index("## Unreleased")
    check("changelog: entry sits under Unreleased",
          bool(added) and 0 < lines.index(added[0]) - idx_unreleased <= 2, body)


def test_main_done_changelog_creates_unreleased_when_absent():
    """CHANGELOG.md without an `## Unreleased` section → section created, one line under it."""
    before = "# Changelog\n\n## 1.0.0\n\n- [done] shipped (2026-01-01)\n"
    backlog = "## Now\n- [>] Sprint: do the thing\n"
    r = _run_main_in_tmp(TASKS_WITH_BACKLOG, backlog, changelog_text=before)
    body = r["changelog_body"]
    check("changelog-new-section: Unreleased created", "## Unreleased" in body, body)
    check("changelog-new-section: one done entry appended",
          len([ln for ln in body.splitlines() if ln.startswith("- [done] Sprint:")]) == 1, body)
    check("changelog-new-section: existing release untouched",
          "## 1.0.0" in body and "- [done] shipped (2026-01-01)" in body, body)
    check("changelog-new-section: Unreleased placed above released sections",
          body.index("## Unreleased") < body.index("## 1.0.0"), body)


def test_main_done_changelog_title_over_cap_is_clamped():
    """A tasks.md title long enough to blow the 160-char cap is truncated, not emitted raw."""
    long_title = "Sprint: " + ("verbose " * 30).strip()
    tasks = TASKS_ONLY_SPRINT.replace("# Sprint: solo", f"# {long_title}")
    backlog = f"## Now\n- [>] {long_title}\n"
    before = "# Changelog\n\n## Unreleased\n"
    r = _run_main_in_tmp(tasks, backlog, changelog_text=before)
    entries = [ln for ln in r["changelog_body"].splitlines() if ln.startswith("- [done] ")]
    check("changelog-cap: one entry written", len(entries) == 1, repr(entries))
    check("changelog-cap: entry within the 160-char cap",
          bool(entries) and len(entries[0]) <= 160,
          f"{len(entries[0]) if entries else 0} chars")
    check("changelog-cap: truncation reported on stderr", "160-char" in r["stderr"], r["stderr"])


def test_main_done_changelog_skips_fenced_unreleased():
    """A `## Unreleased` inside a fenced example must not absorb the entry.

    Docs that show the changelog format embed a literal `## Unreleased` in a code fence;
    inserting there silently loses the entry from the real section below.
    """
    before = (
        "# Changelog\n\nFormat:\n\n```\n## Unreleased\n\n- [done] example (2026-01-01)\n```\n\n"
        "## Unreleased\n\n- [done] real earlier entry (2026-01-02)\n"
    )
    backlog = "## Now\n- [>] Sprint: do the thing\n"
    r = _run_main_in_tmp(TASKS_WITH_BACKLOG, backlog, changelog_text=before)
    lines = r["changelog_body"].splitlines()
    added = [ln for ln in lines if ln.startswith("- [done] Sprint:")]
    check("changelog-fence: entry added once", len(added) == 1, repr(added))
    # Anchor on the REAL heading, not the fenced one. Anchoring on the opening fence would
    # pass even when the entry lands inside the fenced example — the exact bug being guarded.
    real_heading = len(lines) - 1 - lines[::-1].index("## Unreleased")
    check("changelog-fence: entry lands under the real Unreleased, not the fenced example",
          bool(added) and lines.index(added[0]) > real_heading, r["changelog_body"])
    check("changelog-fence: fenced example untouched",
          "- [done] example (2026-01-01)" in r["changelog_body"], r["changelog_body"])


def test_main_done_no_changelog_is_noop():
    """No CHANGELOG.md → reconcile still completes, nothing created."""
    backlog = "## Now\n- [>] Sprint: do the thing\n"
    r = _run_main_in_tmp(TASKS_WITH_BACKLOG, backlog)
    check("changelog-absent: nothing written", r["changelog_body"] == "", r["changelog_body"])
    check("changelog-absent: backlog untouched", r["backlog_body"] == backlog, r["backlog_body"])


def test_main_failed_preserves_review_backlog():
    """failed sprint with Review Backlog → tasks.md retained, findings survive, `[>]` reverted."""
    failed_tasks = TASKS_WITH_BACKLOG.replace("status: done", "status: failed")
    backlog = "## Now\n- [>] Sprint: do the thing\n- [ ] unrelated\n"
    r = _run_main_in_tmp(failed_tasks, backlog)
    check("main-failed: tasks.md retained", r["tasks_exists"])
    check("main-failed: open finding preserved", "open finding one" in r["tasks_body"])
    check("main-failed: sprint block gone", "# Sprint: do the thing" not in r["tasks_body"])
    check("main-failed: [>] reverted to [ ], line kept",
          "- [ ] Sprint: do the thing" in r["backlog_body"], r["backlog_body"])
    check("main-failed: unrelated queued item untouched",
          "- [ ] unrelated" in r["backlog_body"], r["backlog_body"])
    check("main-failed: no [>] left in backlog",
          "[>]" not in r["backlog_body"], r["backlog_body"])


def test_main_failed_reverts_marker_keeps_line():
    """(a) `status: failed` rewrites every `- [>]` line to `- [ ]` and deletes no line."""
    failed_tasks = TASKS_ONLY_SPRINT.replace("status: done", "status: failed")
    backlog = "## Now\n  - [>]   Sprint: solo\n- [ ] other queued item\n"
    r = _run_main_in_tmp(failed_tasks, backlog)
    check("failed-revert: reverted line present, indentation/spacing preserved",
          "  - [ ]   Sprint: solo" in r["backlog_body"], r["backlog_body"])
    check("failed-revert: sibling queued item untouched",
          "- [ ] other queued item" in r["backlog_body"], r["backlog_body"])
    check("failed-revert: no [>] left", "[>]" not in r["backlog_body"], r["backlog_body"])
    check("failed-revert: no line count lost",
          len(r["backlog_body"].splitlines()) == len(backlog.splitlines()), r["backlog_body"])


def test_main_failed_prunes_empty_headings():
    """(d) failed reconciliation reverts markers and prunes unrelated empty headings."""
    failed_tasks = TASKS_ONLY_SPRINT.replace("status: done", "status: failed")
    backlog = "# Backlog\n\n## Empty\n\n## Live\n- [>] active item\n"
    r = _run_main_in_tmp(failed_tasks, backlog)
    check("failed-empty-heading: empty heading pruned", "## Empty" not in r["backlog_body"], r["backlog_body"])
    check("failed-empty-heading: root retained", "# Backlog" in r["backlog_body"], r["backlog_body"])
    check("failed-empty-heading: active item returned to queue",
          "- [ ] active item" in r["backlog_body"], r["backlog_body"])
    check("failed-empty-heading: trailing newline preserved",
          r["backlog_body"].endswith("\n"), repr(r["backlog_body"]))


def test_main_failed_preserves_schema_root():
    """(e) failed reconciliation never deletes a schema-only root or its EOF newline."""
    failed_tasks = TASKS_ONLY_SPRINT.replace("status: done", "status: failed")
    backlog = "# Backlog\n"
    r = _run_main_in_tmp(failed_tasks, backlog)
    check("failed-root: schema root and newline untouched", r["backlog_body"] == backlog,
          repr(r["backlog_body"]))


def test_main_failed_preserves_crlf():
    """(f) failed cleanup preserves CRLF on every surviving line, not only at EOF."""
    failed_tasks = TASKS_ONLY_SPRINT.replace("status: done", "status: failed")
    backlog = "# Backlog\r\n\r\n## Live\r\n- [>] active item\r\n"
    r = _run_main_in_tmp(failed_tasks, backlog)
    check("failed-crlf: per-line endings preserved",
          r["backlog_body"] == "# Backlog\r\n\r\n## Live\r\n- [ ] active item\r\n",
          repr(r["backlog_body"]))


def test_orphan_sweep_reverts_not_deletes():
    """(b) orphan sweep (`tasks.md` absent) reverts `- [>]` → `- [ ]` instead of deleting the line."""
    backlog = "## Now\n- [>] orphaned sprint\n- [ ] unrelated\n"
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        bpath = tmp / "backlog.md"
        bpath.write_text(backlog, encoding="utf-8")
        saved = (mod.TASKS, mod.BACKLOG, mod.CHANGELOG)
        mod.TASKS, mod.BACKLOG, mod.CHANGELOG = tmp / "tasks.md", bpath, tmp / "CHANGELOG.md"
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                mod.main()
            result = bpath.read_text(encoding="utf-8")
        finally:
            mod.TASKS, mod.BACKLOG, mod.CHANGELOG = saved
    check("orphan-sweep: line kept, marker reverted",
          "- [ ] orphaned sprint" in result, result)
    check("orphan-sweep: unrelated queued item untouched", "- [ ] unrelated" in result, result)
    check("orphan-sweep: no [>] left", "[>]" not in result, result)


def test_revert_orphan_markers_byte_identical_for_open_and_done():
    """(c) `- [ ]` and `- [x]` lines are byte-identical after revert_orphan_markers."""
    backlog = "## Now\n- [ ] queued item\n- [x] done item\n- [>] active item\n"
    result = mod.revert_orphan_markers(backlog)
    check("revert: [ ] line byte-identical", "- [ ] queued item" in result, result)
    check("revert: [x] line byte-identical", "- [x] done item" in result, result)
    check("revert: [>] reverted to [ ]", "- [ ] active item" in result, result)
    check("revert: no [>] left", "[>]" not in result, result)


def test_revert_orphan_markers_skips_markup():
    """(g) fenced and commented examples are not real backlog markers."""
    backlog = """# Backlog

<!--
- [>] commented example
-->

## Real
- [>] real item

```markdown
- [>] fenced example
```
"""
    result = mod.revert_orphan_markers(backlog)
    check("revert-markup: real marker reverted", "- [ ] real item" in result, result)
    check("revert-markup: comment preserved", "- [>] commented example" in result, result)
    check("revert-markup: fence preserved", "- [>] fenced example" in result, result)


def test_main_done_backlog_byte_identical_no_marker_writes():
    """C-1 no longer writes backlog.md at all: [ ] and [>] lines both survive verbatim.

    Regression guard for the dropped [>] marker machinery — backlog line deletion
    is now owned exclusively by task_nodes.py prune-backlog (verbatim-match, with
    an ambiguity guard), not by this script's substring anchor matching.
    """
    backlog = (
        "## Now\n"
        "- [ ] [FEAT] queued item\n"
        "- [>] Sprint: do the thing\n"
    )
    before = "# Changelog\n\n## Unreleased\n"
    r = _run_main_in_tmp(TASKS_ONLY_SPRINT, backlog, changelog_text=before)
    check("byte-identical: backlog.md unchanged", r["backlog_body"] == backlog, r["backlog_body"])
    check("byte-identical: tasks.md unlinked", not r["tasks_exists"])
    check("byte-identical: CHANGELOG entry appended",
          any(ln.startswith("- [done] Sprint: solo") for ln in r["changelog_body"].splitlines()),
          r["changelog_body"])


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


def test_main_statusless_fenced_comment_reports_cleanly():
    """A retained statusless tasks.md whose Review Backlog has a fenced '# comment'
    must NOT be misread as a sprint heading (schema drift). This is the steady
    state after strip_sprint_block on a backlog containing a shell example."""
    statusless = "## Review Backlog\n\n```sh\n# a shell comment\n```\n- [ ] leftover finding\n"
    backlog = "## Now\n- [ ] queued item\n"
    r = _run_main_in_tmp(statusless, backlog)
    check("statusless-fenced: no schema-drift warning",
          "unknown status" not in r["stderr"], r["stderr"])
    check("statusless-fenced: backlog reported",
          "Backlog:" in r["stdout"] or "Backlog clear" in r["stdout"], r["stdout"])
    check("statusless-fenced: tasks.md left intact",
          r["tasks_exists"] and "leftover finding" in r["tasks_body"])


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

SUITES = [
    ("strip_sprint_block: preserves Review Backlog", test_strip_preserves_review_backlog),
    ("strip_sprint_block: only sprint → None", test_strip_only_sprint_returns_none),
    ("strip_sprint_block: ignores fenced heading-like lines", test_strip_ignores_fenced_heading_like_lines),
    ("tasks_title: ignores fenced heading-like lines", test_tasks_title_ignores_fenced_heading_like_lines),
    ("strip_sprint_block: status probe is fence-aware", test_strip_status_probe_is_fence_aware),
    ("strip_sprint_block: handles nested fences", test_strip_handles_nested_fences),
    ("main: done preserves Review Backlog", test_main_done_preserves_review_backlog),
    ("main: done only-sprint unlinks", test_main_done_only_sprint_unlinks),
    ("main: done changelog one line under Unreleased", test_main_done_changelog_single_line_under_unreleased),
    ("main: done changelog creates Unreleased", test_main_done_changelog_creates_unreleased_when_absent),
    ("main: done changelog skips fenced Unreleased", test_main_done_changelog_skips_fenced_unreleased),
    ("main: done changelog clamps over-cap title", test_main_done_changelog_title_over_cap_is_clamped),
    ("main: done without CHANGELOG is no-op", test_main_done_no_changelog_is_noop),
    ("main: failed preserves Review Backlog", test_main_failed_preserves_review_backlog),
    ("main: failed reverts marker, keeps line", test_main_failed_reverts_marker_keeps_line),
    ("main: failed prunes empty headings", test_main_failed_prunes_empty_headings),
    ("main: failed preserves schema root", test_main_failed_preserves_schema_root),
    ("main: failed preserves CRLF", test_main_failed_preserves_crlf),
    ("orphan sweep: reverts, not deletes", test_orphan_sweep_reverts_not_deletes),
    ("revert_orphan_markers: [ ]/[x] byte-identical", test_revert_orphan_markers_byte_identical_for_open_and_done),
    ("revert_orphan_markers: skips markup", test_revert_orphan_markers_skips_markup),
    ("main: done backlog byte-identical, no marker writes", test_main_done_backlog_byte_identical_no_marker_writes),
    ("main: statusless retained reports cleanly", test_main_statusless_retained_reports_cleanly),
    ("main: statusless fenced comment reports cleanly", test_main_statusless_fenced_comment_reports_cleanly),
    ("empty-headings: nested findings preserved", test_remove_empty_headings_keeps_nested_findings),
    ("empty-headings: genuinely empty still dropped", test_remove_empty_headings_still_drops_empty_ones),
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
