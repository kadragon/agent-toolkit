#!/usr/bin/env python3
"""task_nodes.py — the deterministic nodes of the `task-next` / `task-new` code cycle.

Branch derivation, CHANGELOG `## Unreleased` insertion and backlog/tasks line deletion are
transforms with one correct output for a given input. Leaving them as prose means every run
re-reads and re-interprets the rule; putting them here means the rule is executed, not recalled.
`task-new` invokes this same file as a bundled sibling
(`$SKILL_DIR/../task-next/scripts/task_nodes.py`) — both skills ship in the `dev` plugin and are
always co-installed, so there is exactly one copy of each rule.

Usage:
  python3 task_nodes.py branch --title TITLE [--tag TAG] [--max-slug N] < items
  python3 task_nodes.py changelog --file PATH --title TITLE [--plugin P --version V]
                                  [--units N] [--link PATH] [--date YYYY-MM-DD]
  python3 task_nodes.py prune-backlog --file PATH < items
  python3 task_nodes.py prune-tasks --file PATH (--block TITLE | < items)
  python3 task_nodes.py --test

  branch          Print `<type>/<slug>`. Item lines on stdin supply the `[TYPE]` tag: all items
                  sharing one tag give that prefix (lowercased); mixed or absent tags fall back
                  to `fix` and say so on stderr. `--tag` skips stdin derivation entirely.
                  Does NOT run git — the caller does `git checkout -b "$(...)"`.

  changelog       Compose one entry and insert it as the FIRST line under `## Unreleased`,
                  creating that section (and the file) when absent. Prints the inserted line.
                  An identical line already under `## Unreleased` is left alone (re-run safe).

  prune-backlog   Delete the verbatim `- [ ]` lines given on stdin, then delete any heading
                  this run left with an entirely blank region, or with nothing left but its own
                  intro prose. Refuses (exit 1) on a line that matches nothing, rather than
                  deleting an approximation of it.

  prune-tasks     Same deletion pass, plus `--block TITLE` to delete a whole h1 sprint block.
                  Deletes the file when nothing but blank lines is left — safe only because
                  tasks.md is the Sprint Contract and nothing else, so it refuses (exit 1) on a
                  tasks.md still holding a `## Review Backlog` / `## Security Fixes` section and
                  names the migration to backlog.md.

Deliberate non-goal — the CHANGELOG character cap is NOT enforced here. Its single enforcement
point is `MAX_LEN` in the repo's `scripts/ci/check_changelog_entries.py`; a second hardcoded copy
inside a shipped script is exactly the drift that single-sourcing removed. This script composes
and places the line; the cap, and every judgment the *CHANGELOG Entry Contract* states (no
explanatory clauses, no file lists), stay where they already live.

Heading detection is imported from the sibling `backlog_candidates.py` so the two scripts agree
on what a heading is — fenced code blocks and HTML comments are markup in both, and a `## Fake`
inside a sample must not become a deletion boundary here either.

Self-check (--test): exits 0 on PASS, 1 on FAIL. All fixtures are in-memory or in a tempdir.
"""

from __future__ import annotations

import datetime
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backlog_candidates import (  # noqa: E402
    _headings,
    _strip_fenced_blocks,
    _strip_html_comments,
    tasks_persistent_sections,
    tokenize,
)

# `[FEAT]`, `[HARNESS]`, … as written at the head of a checkbox item's text.
_TAG_RE = re.compile(r"\[([A-Z][A-Z_-]*)\]")
_CHECKBOX_LINE_RE = re.compile(r"^\s*-\s*\[[ xX>]\]\s*(.*)$")
DEFAULT_MAX_SLUG = 48
FALLBACK_TAG = "fix"


# ---------------------------------------------------------------------------
# branch
# ---------------------------------------------------------------------------

def slugify(title: str, max_len: int = DEFAULT_MAX_SLUG) -> str:
    """Lowercase kebab slug, truncated at a word boundary.

    A leading `[TYPE]` tag is dropped: it is already encoded in the branch prefix, so
    `harness/harness-script-…` would say it twice.
    """
    text = _TAG_RE.sub(" ", title)
    text = text.replace("`", " ").replace("*", " ")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    # Prefer a word boundary, but never return an empty slug for a single very long token.
    return cut.rsplit("-", 1)[0] if "-" in cut else cut


def derive_tag(item_lines: list[str]) -> tuple[str, str | None]:
    """Return `(prefix, warning)` for the branch type prefix.

    All items sharing one `[TYPE]` tag give that tag lowercased. Mixed tags, or no tag at all,
    fall back to `fix` with a warning — matching the SKILL.md rule this replaces.
    """
    tags = []
    for raw in item_lines:
        m = _CHECKBOX_LINE_RE.match(raw)
        body = m.group(1) if m else raw
        found = _TAG_RE.match(body.strip())
        if found:
            tags.append(found.group(1).lower())
    if not tags:
        return FALLBACK_TAG, f"No [TYPE] tag on any item — defaulting branch prefix to `{FALLBACK_TAG}/`"
    unique = sorted(set(tags))
    if len(unique) > 1:
        return (
            FALLBACK_TAG,
            f"Items carry mixed [TYPE] tags ({', '.join(unique)}) — defaulting branch prefix to `{FALLBACK_TAG}/`",
        )
    if len(tags) != len(item_lines):
        return (
            unique[0],
            f"{len(item_lines) - len(tags)} of {len(item_lines)} items carry no [TYPE] tag — "
            f"using the shared tag `{unique[0]}/` from the rest",
        )
    return unique[0], None


def branch_name(title: str, item_lines: list[str], tag: str | None = None, max_slug: int = DEFAULT_MAX_SLUG) -> tuple[str, str | None]:
    warning = None
    if tag is None:
        tag, warning = derive_tag(item_lines)
    slug = slugify(title, max_slug)
    if not slug:
        return "", "Title produced an empty slug — pass a title with at least one alphanumeric character"
    return f"{tag.lower()}/{slug}", warning


# ---------------------------------------------------------------------------
# changelog
# ---------------------------------------------------------------------------

UNRELEASED_HEADING = "## Unreleased"


# ---------------------------------------------------------------------------
# Line-ending-preserving split/join
# ---------------------------------------------------------------------------
#
# `text.splitlines()` + `"\n".join(...)` rewrites every line ending in the file, so a CRLF
# checkout comes back LF-only — including regions this run never touched. Markdown is not
# LF-pinned in this repo (`docs/conventions.md` → the CRLF note; `bump-version.sh` carries the
# same guard), so each line's own terminator is carried alongside it and re-emitted verbatim.
# Only a line that had no terminator at all — the last line of a file with no trailing newline —
# gets the file's dominant ending.

def _split(text: str) -> tuple[list[str], list[str]]:
    """`(bodies, terminators)`, index-aligned. `terminators[i]` is "" only at a newline-less EOF."""
    bodies, eols = [], []
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        bodies.append(body)
        eols.append(raw[len(body):])
    return bodies, eols


def _dominant_eol(eols: list[str]) -> str:
    return "\r\n" if eols.count("\r\n") > eols.count("\n") else "\n"


def _join(bodies: list[str], eols: list[str], default: str) -> str:
    return "".join(body + (eol or default) for body, eol in zip(bodies, eols))


def compose_entry(
    title: str,
    *,
    plugin: str | None = None,
    version: str | None = None,
    units: int | None = None,
    link: str | None = None,
    date: str | None = None,
) -> str:
    """`- [done] <title> [(<N> units)] [(<plugin> v<X.Y.Z>)] (<date>) [→ <link>]`."""
    parts = [f"- [done] {title.strip()}"]
    if units is not None:
        parts.append(f"({units} units)")
    if plugin and version:
        parts.append(f"({plugin} v{version.lstrip('v')})")
    parts.append(f"({date or datetime.date.today().isoformat()})")
    line = " ".join(parts)
    if link:
        line += f" → {link}"
    return line


def insert_changelog_entry(text: str, entry: str) -> tuple[str, bool]:
    """Insert `entry` as the first line under `## Unreleased`. Returns `(new_text, inserted)`.

    Creates the section (after a leading `# ` title if there is one) and the whole file when
    absent. An identical entry already present under `## Unreleased` is left alone so a re-run
    after a partial cycle does not double-log.
    """
    lines, eols = _split(text)
    eol = _dominant_eol(eols)
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == UNRELEASED_HEADING), None)

    def splice(at: int, block: list[str]) -> None:
        lines[at:at] = block
        eols[at:at] = [eol] * len(block)

    if idx is None:
        if not lines:
            return f"# Changelog{eol}{eol}{UNRELEASED_HEADING}{eol}{eol}{entry}{eol}", True
        # After a leading `# ` title (and the blank line under it), else at the very top.
        at = 0
        if lines[0].startswith("# "):
            at = 1
            while at < len(lines) and not lines[at].strip():
                at += 1
        block = [UNRELEASED_HEADING, "", entry, ""]
        if at > 0 and lines[at - 1].strip():
            block = ["", *block]
        splice(at, block)
        return _join(lines, eols, eol), True

    # Section end: the next heading of any level, or EOF.
    end = next(
        (i for i in range(idx + 1, len(lines)) if lines[i].startswith("#")),
        len(lines),
    )
    if any(lines[i].strip() == entry.strip() for i in range(idx + 1, end)):
        return text, False

    at = idx + 1
    while at < end and not lines[at].strip():
        at += 1
    if at == idx + 1:
        splice(at, [""])
        at += 1
    splice(at, [entry])
    return _join(lines, eols, eol), True


# ---------------------------------------------------------------------------
# prune (shared by prune-backlog and prune-tasks)
# ---------------------------------------------------------------------------

def _heading_levels(text: str) -> dict[int, int]:
    """`{0-based line index: heading level}` for real level-1..3 headings.

    Fenced and commented `##` lines are markup per `backlog_candidates` semantics and must not
    become deletion boundaries here either — a fake heading would otherwise split a section and
    make a still-populated region look empty.
    """
    return {h["line"] - 1: h["level"] for h in _headings(tokenize(text))}


def _region_blank(lines: list[str], start: int, levels: dict[int, int]) -> bool:
    """True if `start`'s whole section is blank — its own items AND everything nested under it.

    The section ends at the next heading of level <= `start`'s, NOT the next heading of any
    level. Ending at any heading would stop the scan at `start`'s own surviving child, report
    the parent as empty, and delete it — orphaning that child. Because a surviving child's
    heading line is itself non-blank, this span test protects the parent automatically; a child
    the same run dropped is already blanked and correctly does not.
    """
    level = levels.get(start, 1)
    end = next(
        (h for h in sorted(levels) if h > start and levels[h] <= level),
        len(lines),
    )
    return all(not lines[i].strip() for i in range(start + 1, min(end, len(lines))))


_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s|\d+\.\s)")


def _region_prose_only(lines: list[str], start: int, levels: dict[int, int]) -> bool:
    """True if `start`'s region holds only prose — at least one non-blank line, and none of them
    a heading or a list item.

    Same level-aware span as `_region_blank` (see its docstring): the region ends at the next
    heading of level <= `start`'s, not the next heading of any level, so a surviving child
    heading's own body is never mistaken for `start`'s. A surviving `[x]`/`[>]` line IS a list
    item, so it keeps `start` alive here exactly as it does for `_region_blank`; a surviving
    child heading is itself excluded by the "no heading line" half of this test.

    `lines` must already have fenced/commented spans blanked out (the same `masked` view line
    matching uses) — otherwise a fenced sample with no real prose reads as content and a heading
    holding nothing but an illustrative example would be wrongly deleted.
    """
    level = levels.get(start, 1)
    end = next(
        (h for h in sorted(levels) if h > start and levels[h] <= level),
        len(lines),
    )
    region = lines[start + 1:min(end, len(lines))]
    if not any(ln.strip() for ln in region):
        return False
    for i, ln in enumerate(region, start=start + 1):
        if not ln.strip():
            continue
        if i in levels or _LIST_ITEM_RE.match(ln):
            return False
    return True


def _collapse_gap_blanks(lines: list[str], origin: list[int]) -> list[int]:
    """Source indices to keep, collapsing only the blank runs a deletion created.

    `origin[i]` is the source index of `lines[i]`; a jump in that sequence means something was
    removed between them. Only those seams are collapsed, so the diff stays scoped to the edit.
    Returning indices rather than text lets the caller carry each line's own terminator through.
    """
    out: list[int] = []
    i = 0
    while i < len(lines):
        if lines[i].strip():
            out.append(origin[i])
            i += 1
            continue
        j = i
        while j < len(lines) and not lines[j].strip():
            j += 1
        # A seam exists if lines were dropped just before, inside, or just after this blank run.
        contiguous = all(origin[k + 1] == origin[k] + 1 for k in range(i, j - 1))
        seam = (
            (i > 0 and origin[i] != origin[i - 1] + 1)
            or not contiguous
            or (j < len(lines) and origin[j] != origin[j - 1] + 1)
        )
        keep = 1 if (seam and j - i > 1) else j - i
        # A seam at the very end of the file leaves no separator worth keeping.
        if seam and j >= len(lines):
            keep = 0
        out.extend(origin[i:i + keep])
        i = j
    return out


def prune_lines(text: str, targets: list[str]) -> tuple[str, list[str]]:
    """Delete each verbatim line in `targets`, then any heading this run left blank or prose-only.

    A heading whose region this run drained down to nothing, or down to only its intro prose
    (no surviving item, no surviving child heading), is deleted along with that region — see
    `_region_blank` and `_region_prose_only`. A section this run never touched, or one where a
    child heading or an `[x]`/`[>]` item survives, keeps its heading untouched either way.

    Returns `(new_text, problems)`. `problems` is non-empty when a target matched nothing — or
    matched more than once, which is the more dangerous case: two sections can hold identically
    worded items, only one of which is done, and deleting both silently discards live work. Both
    are fatal to the whole run; the caller must not delete an approximate or an ambiguous match.
    """
    lines, eols = _split(text)
    default_eol = _dominant_eol(eols)
    # Match against the same masked view heading detection uses: a `- [ ]` inside a fenced sample
    # or an HTML comment is markup, not work. harness-init seeds `backlog.md` with a commented-out
    # `- [ ] Simplest case` template, so without this an item worded like the template is either
    # deleted from the comment or — since the ambiguity guard above — blocks its own deletion.
    masked = _strip_fenced_blocks(_strip_html_comments(text)).splitlines()
    if len(masked) != len(lines):  # line-count contract broken upstream; fail safe, do not guess
        return text, ["internal: masked line count does not match the source file"]
    wanted = [t.rstrip() for t in targets if t.strip()]
    problems = []
    drop: set[int] = set()
    for target in wanted:
        hits = [i for i, ln in enumerate(masked) if ln.rstrip() == target]
        if not hits:
            problems.append(f"no line matches verbatim: {target!r}")
        elif len(hits) > 1:
            where = ", ".join(str(i + 1) for i in hits)
            problems.append(
                f"{len(hits)} lines match verbatim (lines {where}) — ambiguous, refusing to guess "
                f"which one is done; disambiguate the wording first: {target!r}"
            )
        else:
            drop.add(hits[0])
    if problems:
        return text, problems

    # Headings whose region this run may have emptied — computed on the ORIGINAL text so a
    # heading that was already empty before the run is left alone (deliberate history).
    levels = _heading_levels(text)
    heads = sorted(levels)
    owned: set[int] = set()
    for i in sorted(drop):
        prior = [h for h in heads if h < i]
        if prior:
            owned.add(prior[-1])

    # Cascade: deleting an h3 can empty its h2 parent, but only if the parent holds nothing else —
    # including no surviving child heading, which `_region_blank`'s level-aware span enforces.
    # A heading left with intro prose only (no surviving item, no surviving child) cascades the
    # same way, but its prose lines are non-blank and must be dropped along with the heading —
    # otherwise the dangling description this fix exists to remove would stay behind.
    while True:
        surviving = [ln if i not in drop else "" for i, ln in enumerate(lines)]
        masked_surviving = [ln if i not in drop else "" for i, ln in enumerate(masked)]
        alive = {h: lv for h, lv in levels.items() if h not in drop}
        # Keep a schema root h1 out of the blank cascade, and keep a first non-h1 heading only when
        # it has no child headings. A standalone `## Group` with child sections is an ordinary
        # container and must still disappear when its last child drains.
        # A `# Backlog` root owns the queue schema, so once its last item drains the whole file must
        # not be rewritten byte-empty — even when it has no standing preamble prose. The prose-only
        # path below retains its broader first-heading exemption for the documented root behavior.
        root_h1 = heads[0] if heads and levels.get(heads[0]) == 1 else None
        root_non_h1 = None
        if heads and root_h1 is None:
            root_level = levels[heads[0]]
            has_child = False
            for h in heads[1:]:
                if levels[h] <= root_level:
                    break
                has_child = True
                break
            if not has_child:
                root_non_h1 = heads[0]
        root_heading = root_h1 if root_h1 is not None else root_non_h1
        newly = {
            h for h in owned
            if h not in drop and h != root_heading
            and _region_blank(surviving, h, alive)
        }
        prose_only = {
            h for h in owned
            if h not in drop and h not in newly and (not heads or h != heads[0])
            and _region_prose_only(masked_surviving, h, alive)
        }
        if not newly and not prose_only:
            break
        drop.update(newly)
        for h in prose_only:
            level = alive.get(h, 1)
            end = next((x for x in sorted(alive) if x > h and alive[x] <= level), len(lines))
            drop.update(range(h, min(end, len(lines))))
        for h in newly | prose_only:
            prior = [x for x in heads if x < h and x not in drop]
            if prior:
                owned.add(prior[-1])

    kept = [i for i in range(len(lines)) if i not in drop]
    final = _collapse_gap_blanks([lines[i] for i in kept], kept)
    out = _join([lines[i] for i in final], [eols[i] for i in final], default_eol)
    return (out if out.strip() else ""), []


def persistent_sections(text: str) -> list[str]:
    """Titles of findings sections that must not be in `tasks.md`.

    `tasks.md` is the Sprint Contract and is deleted whole at sprint close, so anything meant to
    outlive the sprint belongs in `backlog.md`. An h1 block runs to the next h1 or EOF, which means
    a findings section placed after the sprint heading is deleted with it — and a file left with
    nothing is unlinked outright. Rather than guess a safe boundary inside a file that should not
    need one, `prune-tasks` refuses on this shape and names the migration.

    Thin wrapper over `backlog_candidates.tasks_persistent_sections` on purpose: that function is
    the single definition, so the pruner's refusal and the candidate scanner's warning cannot
    disagree about the same file. Do not re-derive the rule here.
    """
    return [s["title"] for s in tasks_persistent_sections(tokenize(text))]


def prune_h1_block(text: str, title: str) -> tuple[str, list[str]]:
    """Delete the whole `# <title>` block — heading, `status:` line, and body — up to the next h1.

    Correct only because `tasks.md` holds the Sprint Contract and nothing else; `cmd_prune` blocks
    the mixed-content case up front via `persistent_sections`.
    """
    lines, eols = _split(text)
    default_eol = _dominant_eol(eols)
    tok = tokenize(text)
    h1s = [t for t in tok if t["type"] == "heading" and t["level"] == 1]
    start = next((t["line"] - 1 for t in h1s if t["title"].strip() == title.strip()), None)
    if start is None:
        titles = ", ".join(repr(t["title"]) for t in h1s) or "none"
        return text, [f"no h1 block titled {title!r} (h1 blocks present: {titles})"]
    end = next((t["line"] - 1 for t in h1s if t["line"] - 1 > start), len(lines))
    kept = [i for i in range(len(lines)) if not (start <= i < end)]
    final = _collapse_gap_blanks([lines[i] for i in kept], kept)
    out = _join([lines[i] for i in final], [eols[i] for i in final], default_eol)
    return (out if out.strip() else ""), []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_stdin_lines() -> list[str]:
    if sys.stdin is None or sys.stdin.isatty():
        return []
    return [ln for ln in sys.stdin.read().splitlines() if ln.strip()]


def _opt(argv: list[str], name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            sys.stderr.write(f"Error: {name} requires a value\n")
            sys.exit(1)
        return argv[i + 1]
    return None


def _require(value: str | None, name: str) -> str:
    if value is None:
        sys.stderr.write(f"Error: {name} is required\n")
        sys.exit(1)
    return value


def cmd_branch(argv: list[str]) -> int:
    title = _require(_opt(argv, "--title"), "--title")
    max_slug = int(_opt(argv, "--max-slug") or DEFAULT_MAX_SLUG)
    # Resolve --tag BEFORE touching stdin: with a tag there is nothing to derive, and an inherited
    # open pipe (task-new's documented invocation passes no stdin redirect) would block the read
    # forever. `isatty()` alone does not cover that case.
    tag = _opt(argv, "--tag")
    items = [] if tag else _read_stdin_lines()
    name, warning = branch_name(title, items, tag, max_slug)
    if not name:
        sys.stderr.write(f"Error: {warning}\n")
        return 1
    if warning:
        sys.stderr.write(f"Warning: {warning}\n")
    print(name)
    return 0


def cmd_changelog(argv: list[str]) -> int:
    path = Path(_opt(argv, "--file") or "CHANGELOG.md")
    units = _opt(argv, "--units")
    entry = compose_entry(
        _require(_opt(argv, "--title"), "--title"),
        plugin=_opt(argv, "--plugin"),
        version=_opt(argv, "--version"),
        units=int(units) if units is not None else None,
        link=_opt(argv, "--link"),
        date=_opt(argv, "--date"),
    )
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    new_text, inserted = insert_changelog_entry(text, entry)
    if inserted:
        path.write_text(new_text, encoding="utf-8")
    else:
        sys.stderr.write("Note: an identical entry is already under ## Unreleased — left as is\n")
    print(entry)
    return 0


def _write_or_delete(path: Path, text: str, delete_if_empty: bool) -> str:
    if not text.strip() and delete_if_empty:
        os.remove(path)
        return f"{path}: deleted (no content left)"
    path.write_text(text, encoding="utf-8")
    return f"{path}: updated"


def cmd_prune(argv: list[str], *, delete_if_empty: bool) -> int:
    path = Path(_require(_opt(argv, "--file"), "--file"))
    if not path.is_file():
        sys.stderr.write(f"Error: not a file: {path}\n")
        return 1
    text = path.read_text(encoding="utf-8")
    if delete_if_empty:
        stale = persistent_sections(text)
        if stale:
            names = ", ".join(f"`## {s}`" for s in stale)
            sys.stderr.write(
                f"Error: {path} holds persistent section(s) {names}, which belong in backlog.md.\n"
                "tasks.md is the Sprint Contract only and is deleted at sprint close, so pruning "
                "here would destroy them.\n"
                "Move those sections to backlog.md verbatim, then re-run. Nothing was deleted.\n"
            )
            return 1
    block = _opt(argv, "--block")
    if block is not None:
        new_text, problems = prune_h1_block(text, block)
    else:
        targets = _read_stdin_lines()
        if not targets:
            sys.stderr.write("Error: no lines on stdin to delete (and no --block given)\n")
            return 1
        new_text, problems = prune_lines(text, targets)
    if problems:
        for p in problems:
            sys.stderr.write(f"Error: {p}\n")
        sys.stderr.write("Nothing was deleted — fix the input and re-run.\n")
        return 1
    print(_write_or_delete(path, new_text, delete_if_empty))
    return 0


USAGE = (
    "Usage: task_nodes.py {branch|changelog|prune-backlog|prune-tasks|--test} [options]\n"
    "       see the module docstring for each subcommand's flags\n"
)


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(USAGE)
        return 1
    cmd, rest = argv[0], argv[1:]
    if cmd == "--test":
        return run_tests()
    if cmd == "branch":
        return cmd_branch(rest)
    if cmd == "changelog":
        return cmd_changelog(rest)
    if cmd == "prune-backlog":
        return cmd_prune(rest, delete_if_empty=False)
    if cmd == "prune-tasks":
        return cmd_prune(rest, delete_if_empty=True)
    sys.stderr.write(f"Unknown subcommand: {cmd}\n{USAGE}")
    return 1


# ---------------------------------------------------------------------------
# Self-check (--test)
# ---------------------------------------------------------------------------

PASS_COUNT = 0
FAIL_COUNT = 0


def _assert(condition: bool, label: str) -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS: {label}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL: {label}")


def run_tests() -> int:
    global PASS_COUNT, FAIL_COUNT
    PASS_COUNT = 0
    FAIL_COUNT = 0
    print("=== task_nodes.py --test ===\n")

    # ---- branch ----
    print("Test 1: branch — tag derivation and slugification")
    shared = [
        "- [ ] [HARNESS] script the nodes",
        "- [ ] [HARNESS] and the other nodes",
    ]
    name, warn = branch_name("Script the deterministic `task-*` nodes", shared)
    _assert(name == "harness/script-the-deterministic-task-nodes", f"shared tag gives its prefix (got {name!r})")
    _assert(warn is None, "a clean shared tag emits no warning")

    mixed = ["- [ ] [FIX] a", "- [ ] [FEAT] b"]
    name, warn = branch_name("Two different things", mixed)
    _assert(name.startswith("fix/"), "mixed tags fall back to fix/")
    _assert(warn is not None and "mixed" in warn, "mixed tags warn on stderr")

    name, warn = branch_name("Untagged finding from a review", ["- [ ] no tag here"])
    _assert(name == "fix/untagged-finding-from-a-review", "untagged items fall back to fix/")
    _assert(warn is not None and "No [TYPE] tag" in warn, "untagged items warn on stderr")

    name, warn = branch_name("Partly tagged", ["- [ ] [FIX] a", "- [ ] b"])
    _assert(name.startswith("fix/") and warn is not None and "carry no [TYPE] tag" in warn,
            "a partially tagged group uses the shared tag and says how many lacked one")

    _assert(branch_name("Anything", [], tag="REFACTOR")[0].startswith("refactor/"),
            "--tag overrides stdin derivation")

    # REGRESSION GUARD (claude review, PR #192) — with --tag there is nothing to derive from
    # stdin, and an inherited open pipe (task-new passes no redirect) blocks the read forever.
    with tempfile.TemporaryDirectory() as _td:
        _r, _w = os.pipe()
        _proc = subprocess.Popen(
            [sys.executable, __file__, "branch", "--title", "some title", "--tag", "FIX"],
            stdin=_r, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=_td,
        )
        os.close(_r)
        try:
            _out, _ = _proc.communicate(timeout=10)
            _assert(_out.decode().strip() == "fix/some-title",
                    "--tag short-circuits the stdin read — no hang on an inherited open pipe")
        except subprocess.TimeoutExpired:
            _proc.kill()
            _assert(False, "--tag short-circuits the stdin read — no hang on an inherited open pipe")
        finally:
            os.close(_w)
    _assert(slugify("[HARNESS] Leading tag is dropped") == "leading-tag-is-dropped",
            "a leading [TYPE] tag is not repeated in the slug")
    _assert(slugify("a" * 80) == "a" * DEFAULT_MAX_SLUG,
            "a single over-long token is hard-truncated rather than emptied")
    _assert(len(slugify("one two three four five six seven eight nine ten")) <= DEFAULT_MAX_SLUG,
            "a long title is truncated at a word boundary within the cap")
    _assert(branch_name("!!!", [])[0] == "", "a title with no alphanumerics is an error, not an empty slug")

    # ---- changelog ----
    print("\nTest 2: changelog — composition and insertion")
    _assert(
        compose_entry("a thing", plugin="dev", version="4.0.32", date="2026-08-03")
        == "- [done] a thing (dev v4.0.32) (2026-08-03)",
        "the standard shape composes exactly as the Entry Contract states",
    )
    _assert(
        compose_entry("b", date="2026-08-03") == "- [done] b (2026-08-03)",
        "the plugin/version clause is dropped in a repo with no versioned plugin",
    )
    _assert(
        compose_entry("c", plugin="dev", version="v1.2.3", units=3, link="docs/x.md", date="2026-08-03")
        == "- [done] c (3 units) (dev v1.2.3) (2026-08-03) → docs/x.md",
        "units and link clauses land in the batch-mode order, and a leading v is not doubled",
    )

    existing = "# Changelog\n\n## Unreleased\n\n- [done] older (2026-08-01)\n"
    out, inserted = insert_changelog_entry(existing, "- [done] newer (2026-08-03)")
    _assert(inserted, "a new entry is inserted")
    _assert(
        out.splitlines()[4:6] == ["- [done] newer (2026-08-03)", "- [done] older (2026-08-01)"],
        "the new entry lands FIRST under ## Unreleased, above the previous newest",
    )
    out2, inserted2 = insert_changelog_entry(out, "- [done] newer (2026-08-03)")
    _assert(not inserted2 and out2 == out, "an identical entry already present is left alone (re-run safe)")

    no_section = "# Changelog\n\n## 4.0.0\n\n- [done] shipped (2026-01-01)\n"
    out, _ = insert_changelog_entry(no_section, "- [done] fresh (2026-08-03)")
    lines = out.splitlines()
    _assert(
        lines.index("## Unreleased") < lines.index("## 4.0.0"),
        "an absent ## Unreleased is created above the existing version sections",
    )
    _assert(
        lines[lines.index("## Unreleased") + 2] == "- [done] fresh (2026-08-03)",
        "the entry lands under the section it just created",
    )
    out, _ = insert_changelog_entry("", "- [done] first ever (2026-08-03)")
    _assert(
        out == "# Changelog\n\n## Unreleased\n\n- [done] first ever (2026-08-03)\n",
        "an absent file is created with a title, the section, and the entry",
    )
    empty_section = "# Changelog\n\n## Unreleased\n\n## 4.0.0\n"
    out, _ = insert_changelog_entry(empty_section, "- [done] x (2026-08-03)")
    _assert(
        out.splitlines()[:5] == ["# Changelog", "", "## Unreleased", "", "- [done] x (2026-08-03)"],
        "an existing but empty ## Unreleased takes the entry without eating the next heading",
    )

    # ---- prune ----
    print("\nTest 3: prune — verbatim deletion, emptied headings, untouched history")
    backlog = """# Backlog

## Group one

Preamble prose that outlives its items.

### Sub A

- [ ] [FIX] the only item under Sub A

### Sub B

- [ ] [FIX] one
- [ ] [FIX] two

## Group two

- [ ] [FEAT] lonely item
"""
    out, problems = prune_lines(backlog, ["- [ ] [FIX] the only item under Sub A"])
    _assert(problems == [], "a verbatim match produces no problems")
    _assert("### Sub A" not in out, "the heading this run emptied is deleted")
    _assert("## Group one" in out and "Preamble prose" in out,
            "the parent h2 survives because its preamble is still content")
    _assert("### Sub B" in out and "- [ ] [FIX] one" in out, "sibling groups are untouched")

    out, problems = prune_lines(backlog, ["- [ ] [FEAT] lonely item"])
    _assert("## Group two" not in out, "an h2 whose only content was the deleted item is deleted too")

    out, problems = prune_lines(backlog, ["- [ ] [FIX] one"])
    _assert(problems == [] and "### Sub B" in out and "- [ ] [FIX] two" in out,
            "a heading with a remaining item is kept")

    _, problems = prune_lines(backlog, ["- [ ] [FIX] the only item under sub a"])
    _assert(len(problems) == 1 and "no line matches verbatim" in problems[0],
            "a near-miss target is refused, not approximated")
    unchanged, problems = prune_lines(backlog, ["- [ ] nope"])
    _assert(unchanged == backlog, "a refused run deletes nothing at all")

    # REGRESSION GUARD (agy review, PR #192) — every fixture above gives the parent h2 a preamble,
    # which hid this: with no preamble, `_region_blank` used to stop at the parent's own surviving
    # child h3, call the parent empty, and delete it — orphaning that child. The section must end
    # at the next heading of level <= its own, not the next heading of any level.
    siblings = """## Group

### Sub A

- [ ] [FIX] item A

### Sub B

- [ ] [FIX] item B
"""
    out, _ = prune_lines(siblings, ["- [ ] [FIX] item A"])
    _assert("## Group" in out, "a parent with a surviving child h3 is NOT deleted, even with no preamble")
    _assert("### Sub A" not in out, "the emptied child h3 is still deleted")
    _assert("### Sub B" in out and "- [ ] [FIX] item B" in out, "the surviving child is not orphaned")

    out, _ = prune_lines(siblings, ["- [ ] [FIX] item A", "- [ ] [FIX] item B"])
    _assert("## Group" not in out and out == "",
            "emptying every child still cascades the parent away — the fix does not block a full cascade")

    history = """## Shipped

- [x] done long ago

## Live

- [ ] [FIX] current
"""
    out, _ = prune_lines(history, ["- [ ] [FIX] current"])
    _assert("## Shipped" in out and "- [x] done long ago" in out,
            "a heading holding only [x] history is NOT deleted — this run did not empty it")
    _assert("## Live" not in out, "the heading this run did empty IS deleted")

    # `_region_prose_only` — a heading drained to nothing but its own intro prose (PR #197).
    # Root heading ('# Root') is present so '## Group with intro prose' is NOT `heads[0]` and is
    # therefore not exempt from the prose-only cascade (PR #203 restricted that exemption to the
    # file's actual first heading — see the (f)/(g) fixtures below).
    prose_group = """# Root

## Group with intro prose

Intro prose that describes the group.

- [ ] [FIX] the only item

## Untouched prose-only section

Just a Source: line, no items — deliberate history, never touched by this run.
"""
    out, _ = prune_lines(prose_group, ["- [ ] [FIX] the only item"])
    _assert("## Group with intro prose" not in out and "Intro prose that describes" not in out,
            "(a) a heading drained to prose-only: heading AND its intro prose are both dropped")
    _assert("## Untouched prose-only section" in out and "Just a Source: line" in out,
            "(d) a prose-only section this run never touched keeps its heading and prose")

    prose_survivor = """## Group with intro prose

Intro prose that describes the group.

- [x] done already
- [ ] [FIX] the only open item
"""
    out, _ = prune_lines(prose_survivor, ["- [ ] [FIX] the only open item"])
    _assert("## Group with intro prose" in out and "Intro prose that describes" in out
            and "- [x] done already" in out,
            "(b) a surviving [x] item keeps the heading and its intro prose")

    prose_child_survives = """## Parent group

Intro prose for the parent.

- [ ] [FIX] parent-level item

### Sub child

- [ ] [FIX] child item
"""
    out, _ = prune_lines(prose_child_survives, ["- [ ] [FIX] parent-level item"])
    _assert("## Parent group" in out and "Intro prose for the parent." in out,
            "(c) a surviving child heading keeps the parent heading and its intro prose")

    _assert("### Sub child" in out and "- [ ] [FIX] child item" in out,
            "(c) the surviving child itself is untouched")

    # (e) The root heading is exempt: draining the file's last item must not take `# Backlog` and
    # its standing preamble with it. `backlog.md` is a prerequisite that must keep its schema.
    root_preamble = """# Backlog

Queue of work not yet in flight. Do not delete this file.

## Now

- [ ] [FIX] only item
"""
    out, _ = prune_lines(root_preamble, ["- [ ] [FIX] only item"])
    _assert("# Backlog" in out and "Do not delete this file." in out,
            "(e) the root heading and its preamble prose survive draining the last item")
    _assert("## Now" not in out, "(e) the drained h2 under the root is still deleted")

    # REGRESSION GUARD — the root exemption also covers a schema-only root with no preamble. The
    # non-root prose-only section is removed, but the first heading remains so backlog.md is never
    # rewritten byte-empty.
    root_without_preamble = """# Backlog

# Other

Intro prose for other.

- [ ] drain me
"""
    out, _ = prune_lines(root_without_preamble, ["- [ ] drain me"])
    _assert("# Backlog" in out, "(e2) a schema-only root survives without preamble prose")
    _assert("# Other" not in out and "Intro prose for other." not in out,
            "(e2) the drained non-root prose-only section still cascades away")

    # REGRESSION GUARD (codex review, PR #203) — the exemption above must cover only the file's
    # FIRST heading, not every h1. A second top-level heading ('# Other') is not the root and must
    # cascade like any other prose-only section once its last item drains.
    non_root_h1 = """# Backlog

Root preamble.

# Other

Intro prose for other.

## Group

- [ ] drain me
"""
    out, _ = prune_lines(non_root_h1, ["- [ ] drain me"])
    _assert("# Backlog" in out and "Root preamble." in out,
            "(f) the file's actual root heading and its preamble survive")
    _assert("## Group" not in out, "(f) the drained h2 is deleted")
    _assert("# Other" not in out and "Intro prose for other." not in out,
            "(f) a non-root h1 drained to prose-only cascades away — it is not exempt")

    # A file whose first heading is an h2 (no h1 at all): that h2 IS the root and must be exempt.
    no_h1_root = """## Overview

Preamble with no h1 wrapper.

- [ ] [FIX] only item
"""
    out, _ = prune_lines(no_h1_root, ["- [ ] [FIX] only item"])
    _assert("## Overview" in out and "Preamble with no h1 wrapper." in out,
            "(g) the file's first heading is exempt even when it is not an h1")

    no_h1_schema_only = "## Overview\n\n- [ ] only item\n"
    out, _ = prune_lines(no_h1_schema_only, ["- [ ] only item"])
    _assert("## Overview" in out, "(g2) a schema-only non-h1 root is not rewritten byte-empty")

    # REGRESSION GUARD (claude review, PR #192) — heading detection honours fences/comments but
    # line matching did not, so the commented-out `- [ ] Simplest case` template harness-init
    # seeds into backlog.md collided with a real item worded the same way. With the ambiguity
    # guard above that collision blocks a legitimate deletion outright.
    commented_template = """# Backlog

<!--
## Feature Name
- [ ] Simplest case
-->

## Real group

- [ ] Simplest case
"""
    out, problems = prune_lines(commented_template, ["- [ ] Simplest case"])
    _assert(problems == [], "a commented-out template line is not a competing match")
    _assert("## Real group" not in out and "<!--" in out,
            "the real item is deleted (emptying its heading) while the comment is left intact")

    fenced_item = """## Real group

```markdown
- [ ] Simplest case
```

- [ ] Simplest case
"""
    out, problems = prune_lines(fenced_item, ["- [ ] Simplest case"])
    _assert(problems == [] and "```markdown" in out,
            "a fenced sample line is not a competing match either, and survives the deletion")

    fenced = """## Real group

```markdown
## Fake heading in a sample
```

- [ ] [FIX] real item after a fence
"""
    out, _ = prune_lines(fenced, ["- [ ] [FIX] real item after a fence"])
    _assert("## Real group" in out and "## Fake heading in a sample" in out,
            "a fenced `##` is not a deletion boundary, so the real heading is not falsely emptied")

    seam = "## A\n\n- [ ] x\n- [ ] y\n\n## B\n\n- [ ] z\n"
    out, _ = prune_lines(seam, ["- [ ] x"])
    _assert(out == "## A\n\n- [ ] y\n\n## B\n\n- [ ] z\n",
            "deleting one of several items leaves the surrounding blank lines exactly as they were")

    # REGRESSION GUARD (qa-verifier) — two sections can hold identically worded items with only
    # one of them done. Deleting both silently discards live work, so an ambiguous match is fatal.
    # The zero-match case was already refused; the multi-match case is strictly more dangerous.
    duplicate = """## Group A

- [ ] [FIX] update the docs

## Group B

- [ ] [FIX] update the docs
"""
    unchanged, problems = prune_lines(duplicate, ["- [ ] [FIX] update the docs"])
    _assert(len(problems) == 1 and "2 lines match verbatim" in problems[0],
            "a target matching two lines is refused as ambiguous, not applied to both")
    _assert(bool(problems) and "lines 3, 7" in problems[0],
            "the ambiguity message names the 1-based line numbers so the caller can disambiguate")
    _assert(unchanged == duplicate, "an ambiguous run deletes nothing at all")

    # REGRESSION GUARD (qa-verifier) — markdown is not LF-pinned here (docs/conventions.md), so a
    # Windows checkout arrives CRLF. Rewriting every terminator would touch regions this run never
    # edited, breaking the byte-identical guarantee for untouched sections.
    crlf = "## A\r\n\r\n- [ ] x\r\n- [ ] y\r\n\r\n## B\r\n\r\n- [ ] z\r\n"
    out, _ = prune_lines(crlf, ["- [ ] x"])
    _assert(out == "## A\r\n\r\n- [ ] y\r\n\r\n## B\r\n\r\n- [ ] z\r\n",
            "CRLF survives prune_lines — every surviving line keeps its own terminator")
    _assert("\n" not in out.replace("\r\n", ""), "no bare LF is introduced into a CRLF file")

    crlf_block = "# One\r\n\r\nstatus: active\r\n\r\n# Two\r\n\r\nstatus: open\r\n"
    out, _ = prune_h1_block(crlf_block, "One")
    _assert(out == "# Two\r\n\r\nstatus: open\r\n", "CRLF survives prune_h1_block")

    crlf_log = "# Changelog\r\n\r\n## Unreleased\r\n\r\n- [done] older (2026-08-01)\r\n"
    out, _ = insert_changelog_entry(crlf_log, "- [done] newer (2026-08-03)")
    _assert(
        out == "# Changelog\r\n\r\n## Unreleased\r\n\r\n- [done] newer (2026-08-03)\r\n"
               "- [done] older (2026-08-01)\r\n",
        "CRLF survives insert_changelog_entry, and the inserted line uses the file's own ending",
    )
    mixed = "# Changelog\n\n## Unreleased\n"
    out, _ = insert_changelog_entry(mixed, "- [done] x (2026-08-03)")
    _assert("\r" not in out, "an LF file stays LF — the dominant ending decides, not a hardcoded one")

    no_final_newline = "## A\n\n- [ ] x\n- [ ] y"
    out, _ = prune_lines(no_final_newline, ["- [ ] x"])
    _assert(out == "## A\n\n- [ ] y\n",
            "a file with no trailing newline gains one from the dominant ending, losing no content")

    # ---- prune-tasks h1 block ----
    print("\nTest 4: prune-tasks — h1 sprint blocks")
    tasks = """# Sprint one

status: active

## Scope

body content

# Sprint two

status: open
"""
    out, problems = prune_h1_block(tasks, "Sprint one")
    _assert(problems == [] and out.startswith("# Sprint two"),
            "the whole h1 block — heading, status, body — is deleted up to the next h1")
    _assert("## Scope" not in out and "body content" not in out, "the block's body goes with it")

    out, problems = prune_h1_block(tasks, "Sprint three")
    _assert(len(problems) == 1 and "no h1 block titled" in problems[0] and "'Sprint one'" in problems[0],
            "a missing title is refused and the available titles are named")

    only, _ = prune_h1_block("# Only\n\nstatus: active\n", "Only")
    _assert(only == "", "deleting the last block leaves an empty string, which the CLI turns into a file delete")

    # ---- CLI file handling ----
    print("\nTest 5: CLI — file write and delete-if-empty")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "tasks.md"
        p.write_text("# Only\n\nstatus: active\n", encoding="utf-8")
        msg = _write_or_delete(p, "", delete_if_empty=True)
        _assert(not p.exists() and "deleted" in msg, "prune-tasks deletes a file left with no content")

        b = Path(td) / "backlog.md"
        b.write_text("# Backlog\n", encoding="utf-8")
        _write_or_delete(b, "", delete_if_empty=False)
        _assert(b.exists() and b.read_text(encoding="utf-8") == "",
                "prune-backlog never deletes backlog.md — it is a prerequisite file")

        # REGRESSION GUARD: the mixed-content shape that used to delete all of tasks.md.
        # `## Review Backlog` sits AFTER the sprint h1, so the h1-to-EOF boundary swallows it and
        # `delete_if_empty` unlinks the file. prune-tasks must refuse and change nothing.
        mixed = Path(td) / "tasks.md"
        mixed_text = (
            "# Fix the thing\n\nstatus: active\n\n## Covers\n\n- [ ] [FIX] a\n\n"
            "## Review Backlog\n\n### PR #101 — earlier PR (2026-07-01)\n\n"
            "- [ ] [debt] leftover finding\n"
        )
        mixed.write_text(mixed_text, encoding="utf-8")
        rc = main(["prune-tasks", "--file", str(mixed), "--block", "Fix the thing"])
        _assert(
            rc == 1 and mixed.exists() and mixed.read_text(encoding="utf-8") == mixed_text,
            "prune-tasks refuses a tasks.md holding a persistent section, leaving it untouched",
        )
        _assert(
            persistent_sections(mixed_text) == ["Review Backlog", "PR #101 — earlier PR (2026-07-01)"]
            and persistent_sections("# S\n\nstatus: active\n\n## Scope\n\n- [ ] x\n") == []
            and persistent_sections("## Security Fixes — my-webapp\n\n- [ ] rotate\n")
            == ["Security Fixes — my-webapp"],
            "the guard matches findings sections (suffix and all), not a contract's ## Scope",
        )
        # REGRESSION GUARD: the pruner and the candidate scanner share ONE predicate. Before
        # this, a grab-bag h2 was warned about by one and deleted by the other.
        grab = "# S\n\nstatus: active\n\n## Scope\n\n- [ ] a\n\n## Follow-ups\n\n- [ ] leftover\n"
        gr = Path(td) / "grab.md"
        gr.write_text(grab, encoding="utf-8")
        rc = main(["prune-tasks", "--file", str(gr), "--block", "S"])
        _assert(
            rc == 1 and gr.exists() and gr.read_text(encoding="utf-8") == grab,
            "prune-tasks refuses an ad-hoc grab-bag section too, not only the two known titles",
        )
        _assert(
            persistent_sections("# S\n\nstatus: active\n\n```markdown\n## Review Backlog\n```\n")
            == [],
            "a findings heading inside a fence does not trigger a false refusal",
        )
        # prune-backlog must NOT refuse — backlog.md is where these sections belong.
        bl = Path(td) / "bl.md"
        bl.write_text("## Review Backlog\n\n- [ ] [debt] one\n- [ ] [debt] two\n", encoding="utf-8")
        real_stdin, sys.stdin = sys.stdin, io.StringIO("- [ ] [debt] one\n")
        try:
            rc = main(["prune-backlog", "--file", str(bl)])
        finally:
            sys.stdin = real_stdin
        _assert(
            rc == 0 and "- [ ] [debt] two" in bl.read_text(encoding="utf-8"),
            "prune-backlog still prunes a `## Review Backlog` section in backlog.md",
        )

        c = Path(td) / "CHANGELOG.md"
        rc = main(["changelog", "--file", str(c), "--title", "t", "--plugin", "dev",
                   "--version", "1.0.0", "--date", "2026-08-03"])
        _assert(rc == 0 and c.read_text(encoding="utf-8").endswith("- [done] t (dev v1.0.0) (2026-08-03)\n"),
                "the changelog subcommand creates the file end-to-end")

    print(f"\n=== Results: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL ===")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
