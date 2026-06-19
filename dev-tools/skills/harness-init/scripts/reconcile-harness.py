#!/usr/bin/env python3
"""
C) Harness Reconciliation

Syncs tasks.md status into backlog.md and reports sprint/backlog state.

Exit codes:
  0  Normal completion
  1  Unexpected exception (uncaught)
"""

import re
import sys
from datetime import date
from pathlib import Path

TASKS = Path("tasks.md")
BACKLOG = Path("backlog.md")
CHANGELOG = Path("CHANGELOG.md")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def tasks_field(content: str, field: str) -> str | None:
    """Extract a single-line field value, e.g. 'status: active' → 'active'."""
    m = re.search(rf'^{re.escape(field)}:\s*(.+)', content, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _heading_indices(lines: list) -> list:
    """Indices of top-level '# ' heading lines, ignoring fenced code blocks.

    A '#'-prefixed line inside a ``` or ~~~ fence (e.g. a shell comment in an
    example) is content, not a heading, and must not anchor sprint detection.
    """
    indices = []
    fence = None  # the fence marker char (' ` ' or '~') while inside a block
    for i, ln in enumerate(lines):
        m = re.match(r'^\s*(`{3,}|~{3,})', ln)
        if m:
            marker = m.group(1)[0]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None and re.match(r'^#\s+', ln):
            indices.append(i)
    return indices


def _sprint_heading_index(lines: list) -> int | None:
    """Index of the sprint Contract's '# ' heading line.

    The sprint block is the top-level '# ' heading whose section (heading through
    the next top-level heading or EOF) owns a 'status:' field.  Falls back to the
    first top-level heading when none owns a status field, and None when there is
    no top-level heading at all.  Fence-aware via _heading_indices so heading-like
    lines inside code blocks are never matched.
    """
    headings = _heading_indices(lines)
    if not headings:
        return None
    for k, h in enumerate(headings):
        end = headings[k + 1] if k + 1 < len(headings) else len(lines)
        section = "".join(lines[h:end])
        if re.search(r'^status:\s*\S', section, re.MULTILINE | re.IGNORECASE):
            return h
    return headings[0]


def tasks_title(content: str) -> str:
    lines = content.splitlines(keepends=True)
    idx = _sprint_heading_index(lines)
    if idx is None:
        return "untitled sprint"
    m = re.match(r'^#\s+(.+)', lines[idx])
    return (m.group(1).strip() if m else None) or "untitled sprint"


def sprint_summary(content: str) -> str:
    """Extract Acceptance Criteria or first meaningful body paragraph as summary."""
    m = re.search(r'Acceptance Criteria[:\s]+(.*?)(?=\n#|\Z)', content, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1).strip()
        # Collapse to first 120 chars
        return text[:120].replace('\n', ' ')
    return "sprint completed"


def tasks_anchors(content: str) -> list:
    """Return backlog anchors for this sprint.

    If tasks.md has a '## Covers' section, return its bullet texts (one per
    bundled backlog item).  Otherwise fall back to [tasks_title(content)] so
    single-item sprints behave exactly as before.  Also falls back if the
    '## Covers' section is present but contains no non-empty bullet lines
    after stripping the dash prefix.
    """
    m = re.search(r'^## Covers\s*\n(?:[ \t]*\n)*((?:[ \t]*-[ \t]*.+\n?)+)', content, re.MULTILINE)
    if m:
        bullets = []
        for line in m.group(1).splitlines():
            text = line.strip()
            if text.startswith('-'):
                text = text[1:].strip()
                if text:
                    bullets.append(text)
        if bullets:
            return bullets
        print("WARNING: ## Covers found but yielded no usable bullets; falling back to title anchor", file=sys.stderr)
    return [tasks_title(content)]


def remove_active_markers(backlog: str, anchors: list) -> str:
    """Remove every [>] line whose text contains any anchor from the list."""
    lines = backlog.splitlines(keepends=True)
    result = []
    for line in lines:
        if re.match(r'\s*-\s*\[>\]', line):
            if any(anchor.lower() in line.lower() for anchor in anchors):
                continue  # drop matched active item
        result.append(line)
    return "".join(result)


def revert_active_markers(backlog: str, anchors: list, note: str) -> str:
    """Revert [>] → [ ] for every line matching any anchor, appending evaluator note."""
    lines = backlog.splitlines(keepends=True)
    result = []
    for line in lines:
        if re.match(r'\s*-\s*\[>\]', line) and any(anchor.lower() in line.lower() for anchor in anchors):
            reverted = re.sub(r'\[>\]', '[ ]', line, count=1).rstrip('\n')
            result.append(f"{reverted}  <!-- {note} -->\n")
        else:
            result.append(line)
    return "".join(result)


# Keep single-title shims for any external callers; main() uses the multi-anchor versions.
def remove_active_marker(backlog: str, title: str) -> str:
    """Remove the [>] line whose text contains the sprint title."""
    return remove_active_markers(backlog, [title])


def revert_active_marker(backlog: str, title: str, note: str) -> str:
    """Revert [>] → [ ] for the matching sprint, appending a short evaluator note."""
    return revert_active_markers(backlog, [title], note)


def strip_sprint_block(content: str) -> str | None:
    """Remove the Sprint Contract block from tasks.md, preserving everything else.

    The Sprint Contract is the top-level '# ' heading section that owns the
    'status:' field.  Removes that heading through the next top-level '# '
    heading (or EOF), then trims any now-trailing horizontal-rule separators and
    blank tail.  Returns the remaining content (newline-terminated), or None when
    nothing meaningful (only whitespace / '---' separators) is left -- in which
    case the caller unlinks tasks.md exactly as the pre-fix behaviour did.

    Heading detection is fence-aware (see _heading_indices): a '#'-prefixed line
    inside a ``` or ~~~ code block is content, not a heading, so example shell
    comments under '## Review Backlog' no longer get misread as the sprint heading.

    Ordering invariant: non-sprint content (e.g. '## Review Backlog') MUST appear
    BEFORE the Sprint Contract '# ' heading.  The sprint block spans from the
    status-owning '# ' heading to the next top-level '# ' heading or EOF, and
    legitimately contains '##' sub-sections (Scope, Acceptance criteria, Covers,
    Out of scope) -- so the boundary cannot be an '##' heading.  Any content placed
    AFTER the sprint heading is therefore treated as part of the sprint block and
    removed with it.  The next-tasks / harness-init templates always emit Review
    Backlog above the sprint, which satisfies this.

    This preserves unrelated open '## Review Backlog' items that previously were
    destroyed by an unconditional TASKS.unlink() on sprint completion.
    """
    lines = content.splitlines(keepends=True)
    start = _sprint_heading_index(lines)
    if start is None:
        return None  # no sprint heading to isolate -> treat as fully consumed
    headings = _heading_indices(lines)
    end = next((h for h in headings if h > start), len(lines))
    remainder = "".join(lines[:start] + lines[end:])
    # Drop separators / blank lines left dangling at the new end of file.
    remainder = re.sub(r'\s*(?:-{3,}\s*)*\Z', '', remainder)
    if not remainder.strip():
        return None
    return remainder + "\n"


def remove_orphan_markers(backlog: str) -> str:
    """Remove all remaining [>] lines when no tasks.md exists."""
    return re.sub(r'^\s*-\s*\[>\].*\n?', '', backlog, flags=re.MULTILINE)


def remove_empty_headings(backlog: str) -> str:
    """Drop headings immediately followed by another heading or end-of-file."""
    lines = backlog.splitlines()
    result = []
    for i, line in enumerate(lines):
        if re.match(r'^#+\s', line):
            following = [ln for ln in lines[i + 1:] if ln.strip()]
            if not following or re.match(r'^#+\s', following[0]):
                continue
        result.append(line)
    return '\n'.join(result)


def append_changelog(title: str, summary: str) -> None:
    if not CHANGELOG.exists():
        return
    entry = f"\n## {date.today()} — {title}\n\n{summary}\n"
    CHANGELOG.write_text(CHANGELOG.read_text(encoding="utf-8") + entry, encoding="utf-8")


def count_items(backlog: str) -> tuple[int, int]:
    queued = len(re.findall(r'^\s*-\s*\[\s\]', backlog, re.MULTILINE))
    active = len(re.findall(r'^\s*-\s*\[>\]', backlog, re.MULTILINE))
    return queued, active


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    tasks_content = read(TASKS)

    # C-1: Sync tasks.md -> backlog.md
    if tasks_content is not None:
        raw_status = tasks_field(tasks_content, "status")
        status = raw_status.lower() if raw_status else None
        title = tasks_title(tasks_content)
        anchors = tasks_anchors(tasks_content)
        backlog = read(BACKLOG) or ""

        if status == "done":
            summary = sprint_summary(tasks_content)
            updated = remove_active_markers(backlog, anchors)
            if updated == backlog:
                print(
                    f"WARNING: Sprint '{title}' — no [>] lines matched anchors {anchors!r}. "
                    "Backlog may contain stale active markers.",
                    file=sys.stderr,
                )
            BACKLOG.write_text(updated, encoding="utf-8")
            append_changelog(title, summary)
            remainder = strip_sprint_block(tasks_content)
            if remainder is None:
                TASKS.unlink()
                print(f"Sprint '{title}' done. tasks.md removed.")
            else:
                TASKS.write_text(remainder, encoding="utf-8")
                print(f"Sprint '{title}' done. Sprint block stripped; tasks.md retained.")

        elif status == "failed":
            fb = tasks_field(tasks_content, "Evaluator Feedback") or "failed"
            note = fb[:80]
            updated = revert_active_markers(backlog, anchors, note)
            if updated == backlog:
                print(
                    f"WARNING: Sprint '{title}' — no [>] lines matched anchors {anchors!r}. "
                    "Backlog active markers may not have been reverted.",
                    file=sys.stderr,
                )
            BACKLOG.write_text(updated, encoding="utf-8")
            remainder = strip_sprint_block(tasks_content)
            if remainder is None:
                TASKS.unlink()
                print(f"Sprint '{title}' failed. Reverted to backlog.")
            else:
                TASKS.write_text(remainder, encoding="utf-8")
                print(f"Sprint '{title}' failed. Reverted to backlog; Sprint block stripped, tasks.md retained.")

        elif status in ("active", "evaluating"):
            print(f"Sprint active: {title}")
            return

        elif raw_status is None and not re.search(r'^#\s+', tasks_content, re.MULTILINE):
            # Retained Review-Backlog-only tasks.md: a prior sprint completion
            # stripped the contract block via strip_sprint_block(), leaving no
            # '# ' heading and no status. This is the expected steady state, not
            # schema drift -- fall through to C-3 reporting instead of warning and
            # returning early.
            pass

        else:
            # Schema drift (missing or unrecognized status on a file that still
            # carries a '# ' sprint heading). Surface it but do not abort --
            # downstream sync sections (D-1 schema check, E, F) still need to run,
            # and parallel callers cancel on non-zero exit.
            shown = raw_status if raw_status is not None else "missing"
            print(
                f"tasks.md has unknown status '{shown}' -- leaving intact. "
                "Fix the 'status:' line (active|evaluating|done|failed).",
                file=sys.stderr,
            )
            return

    else:
        # C-2: tasks.md absent — clean orphan markers from backlog
        if not BACKLOG.exists():
            print("Backlog clear.")
            return

        content = BACKLOG.read_text(encoding="utf-8")
        cleaned = remove_orphan_markers(content)
        cleaned = remove_empty_headings(cleaned)
        if cleaned != content:
            BACKLOG.write_text(cleaned, encoding="utf-8")

    # C-3: Report
    if not BACKLOG.exists():
        print("Backlog clear.")
        return

    queued, active = count_items(BACKLOG.read_text(encoding="utf-8"))
    if queued == 0 and active == 0:
        print("Backlog clear.")
    else:
        print(f"Backlog: {queued} queued, {active} active")


if __name__ == "__main__":
    main()
