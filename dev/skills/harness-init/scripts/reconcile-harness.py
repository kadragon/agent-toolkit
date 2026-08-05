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


def _fence_mask(lines: list) -> list:
    """Per-line bool: True when the line is real content (outside fenced code
    blocks); fence delimiter lines themselves are False.

    A closing fence must use the same character as its opener and be at least as
    long (CommonMark), so a shorter inner fence never closes a longer outer one
    (e.g. a 3-backtick line inside a 4-backtick block stays inside the block).
    """
    mask = []
    fence = None  # opening marker string (e.g. '```' / '````') while a block is open
    for ln in lines:
        m = re.match(r'^\s*(`{3,}|~{3,})', ln)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            mask.append(False)
        else:
            mask.append(fence is None)
    return mask


def _heading_indices(lines: list, mask: list | None = None) -> list:
    """Indices of top-level '# ' heading lines, ignoring fenced code blocks.

    A '#'-prefixed line inside a ``` or ~~~ fence (e.g. a shell comment in an
    example) is content, not a heading, and must not anchor sprint detection.
    Pass a precomputed ``mask`` to avoid re-scanning fences.
    """
    if mask is None:
        mask = _fence_mask(lines)
    return [i for i, ln in enumerate(lines) if mask[i] and re.match(r'^#\s+', ln)]


def _has_sprint_heading(content: str) -> bool:
    """True when content has a top-level '# ' heading outside any code fence.

    Fence-aware replacement for a raw top-level-heading regex: a fenced
    '# comment' in a retained Review Backlog must not read as a sprint heading.
    """
    return bool(_heading_indices(content.splitlines(keepends=True)))


def _sprint_heading_index(lines: list, headings: list | None = None,
                          mask: list | None = None) -> int | None:
    """Index of the sprint Contract's '# ' heading line.

    The sprint block is the top-level '# ' heading whose section (heading through
    the next top-level heading or EOF) owns a 'status:' field.  Falls back to the
    first top-level heading when none owns a status field, and None when there is
    no top-level heading at all.  Both heading detection AND the 'status:' probe
    are fence-aware, so heading-like / status-like lines inside code blocks are
    never matched.  Callers may pass precomputed ``headings``/``mask`` to avoid
    re-scanning fences.
    """
    if mask is None:
        mask = _fence_mask(lines)
    if headings is None:
        headings = _heading_indices(lines, mask)
    if not headings:
        return None
    for k, h in enumerate(headings):
        end = headings[k + 1] if k + 1 < len(headings) else len(lines)
        for i in range(h, end):
            if mask[i] and re.match(r'^status:\s*\S', lines[i], re.IGNORECASE):
                return h
    return headings[0]


def tasks_title(content: str) -> str:
    lines = content.splitlines(keepends=True)
    idx = _sprint_heading_index(lines)
    if idx is None:
        return "untitled sprint"
    m = re.match(r'^#\s+(.+)', lines[idx])
    return (m.group(1).strip() if m else None) or "untitled sprint"


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

    Under the current contract tasks.md holds the Sprint Contract and nothing else
    -- every persistent item, '## Review Backlog' included, lives in backlog.md
    (references/backlog-template.md).  So the usual outcome here is None and the
    caller unlinks the file, which is correct rather than lossy.

    The preserve-the-remainder path stays for a repo mid-migration.  It carries an
    ordering caveat: the sprint block spans from the status-owning '# ' heading to
    the next top-level '# ' heading or EOF, and legitimately contains '##'
    sub-sections (Scope, Acceptance criteria, Covers, Out of scope) -- so the
    boundary cannot be an '##' heading.  Leftover non-sprint content therefore
    survives only when it sits BEFORE the sprint heading; content after it is
    removed with the block.  Move such sections to backlog.md rather than relying on
    their position; task_nodes.py 'prune-tasks' refuses outright on this shape.
    """
    lines = content.splitlines(keepends=True)
    mask = _fence_mask(lines)
    headings = _heading_indices(lines, mask)
    start = _sprint_heading_index(lines, headings, mask)
    if start is None:
        return None  # no sprint heading to isolate -> treat as fully consumed
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
    """Drop a heading only when the whole section it owns has no content.

    Level-aware: a heading owns everything up to the next heading of the SAME OR BROADER
    level, so a parent whose next line is a child heading is not empty when that child
    owns items.  The documented findings shape depends on this -- '## Review Backlog'
    followed immediately by '### PR #N' and its items, and the same for
    '## Security Fixes'.  The previous 'heading followed by a heading' test deleted both
    parents plus '# Backlog' itself, orphaning every finding.

    Children are judged the same way in the same pass: an empty child is dropped, and a
    parent whose children are all empty finds no content either (the scan skips heading
    lines) and is dropped with them.
    """
    lines = backlog.splitlines()
    levels: list[int | None] = []
    for line in lines:
        m = re.match(r'^(#+)\s', line)
        levels.append(len(m.group(1)) if m else None)

    drop = set()
    for i, level in enumerate(levels):
        if level is None:
            continue
        has_content = False
        for j in range(i + 1, len(lines)):
            child_level = levels[j]
            if child_level is not None:
                if child_level <= level:
                    break
                continue
            if lines[j].strip():
                has_content = True
                break
        if not has_content:
            drop.add(i)
    return '\n'.join(line for i, line in enumerate(lines) if i not in drop)


MAX_CHANGELOG_LINE = 160


def append_changelog(title: str) -> None:
    """Insert one `- [done]` line as the first entry under `## Unreleased`.

    Per the CHANGELOG Entry Contract (references/harness-invariants.md), the entry is a
    single line — no summary block. Detail belongs in the owning docs/*.md or the PR body.
    This recovery path cannot know which plugin was bumped, so it writes the version-less
    form; the skill-driven cycle tails add the `(<plugin> vX.Y.Z)` clause themselves.
    """
    if not CHANGELOG.exists():
        return
    entry = f"- [done] {title} ({date.today()})"
    if len(entry) > MAX_CHANGELOG_LINE:
        # The contract's cap is the point of the entry — clamp the title rather than
        # emit a line that violates the rule this script is supposed to uphold.
        keep = MAX_CHANGELOG_LINE - (len(entry) - len(title)) - 1
        entry = f"- [done] {title[:keep].rstrip()}… ({date.today()})"
        print(
            f"WARNING: sprint title exceeds the {MAX_CHANGELOG_LINE}-char CHANGELOG cap; "
            "truncated in the entry. Shorten the tasks.md title.",
            file=sys.stderr,
        )
    body = CHANGELOG.read_text(encoding="utf-8")
    lines = body.splitlines()
    mask = _fence_mask(lines)  # a `## Unreleased` inside a fenced example is not the section
    for i, line in enumerate(lines):
        if mask[i] and re.match(r'^##\s+Unreleased\s*$', line, re.IGNORECASE):
            insert_at = i + 1
            # Keep exactly one blank line between the heading and the first entry.
            if insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
                lines.insert(insert_at, entry)
            else:
                lines[insert_at:insert_at] = ["", entry]
            CHANGELOG.write_text('\n'.join(lines) + '\n', encoding="utf-8")
            return
    # No Unreleased section — create one directly under the file's h1 title. Placing it at
    # EOF would sit it below every released section and stay mis-ordered on every later run,
    # since the next call finds it there (changelogs are newest-first).
    for i, line in enumerate(lines):
        if mask[i] and re.match(r'^#\s+\S', line):
            lines[i + 1:i + 1] = ["", "## Unreleased", "", entry]
            CHANGELOG.write_text('\n'.join(lines) + '\n', encoding="utf-8")
            return
    CHANGELOG.write_text(body.rstrip('\n') + f"\n\n## Unreleased\n\n{entry}\n", encoding="utf-8")


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
            updated = remove_active_markers(backlog, anchors)
            if updated == backlog:
                print(
                    f"WARNING: Sprint '{title}' — no [>] lines matched anchors {anchors!r}. "
                    "Backlog may contain stale active markers.",
                    file=sys.stderr,
                )
            BACKLOG.write_text(updated, encoding="utf-8")
            append_changelog(title)
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

        elif raw_status is None and not _has_sprint_heading(tasks_content):
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
