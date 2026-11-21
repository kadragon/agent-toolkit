#!/usr/bin/env python3
"""backlog_candidates.py — deterministic candidate-group parser for task-next Step 1.

Usage:
  python3 backlog_candidates.py --tasks PATH --backlog PATH [--ref REV] [--full-scan] [--json]
  python3 backlog_candidates.py --backlog PATH --parked [--json]
  python3 backlog_candidates.py --test

  --ref REV       read --tasks/--backlog as committed at REV (`git show REV:<repo-relative path>`)
                   instead of from this checkout's working tree, and take claim merge-bases
                   against REV instead of HEAD. `task-next --tree` passes its base (origin/HEAD),
                   so this checkout's branch and uncommitted edits never shape the selection.
                   An unresolvable REV, or a backlog absent at REV, is a fatal error.

  --tasks PATH    path to tasks.md (optional file; absent path is treated as empty input,
                   same as the `2>/dev/null` grep fallback it replaces)
  --backlog PATH  path to backlog.md (required — this repo's prereqs guarantee it exists,
                   so a missing/unreadable file here is treated as a real error, not "no candidates")
  --full-scan     run the full-scan algorithm instead of the fast path (see below)
  --json          emit a JSON array of candidate objects instead of the plain-text list
  Claimed items: in candidate modes (not --parked), backlog.md open items that another
  `.worktrees/` worktree has claimed — listed under its tasks.md `## Covers`, or deleted from its
  backlog.md relative to its merge-base with this checkout's HEAD (or --ref) — are dropped, and stderr names
  the count per worktree (`Skipped N item(s) claimed by in-flight worktrees: ...`). See
  `collect_claims()`/`worktree_claims()`. Identical item text in two groups is attributed per
  group: a `## Covers` line is keyed with its h1 block's title, a merge-base deletion of a twin
  with its heading, so a claim on one twin does not hide the other and the surviving twin does not
  mask a deletion (a key naming a group the backlog lacks matches the text anywhere). Phase A
  `status: open` blocks are claim-checked too: a block whose h1 title appears in another
  `.worktrees/` worktree's tasks.md with any other status is skipped and named on stderr
  (`collect_block_claims()`).

  --parked        list the backlog.md open items a blocked/deferred marker parks, instead of
                   candidates: `<backlog path>:<line> [<heading>] <item text>` per item (with
                   --json, an array carrying each marker's kind and payload). The text is the
                   tokenizer's folded form — checkbox prefix dropped, wrapped lines joined,
                   comments and fences blanked — so open the line before editing the item; it is
                   not a verbatim match string. A body over 140 chars is clipped with `…` and its
                   markers kept after it; --json carries the full text. tasks.md is not listed: its checkboxes are never
                   selectable, so nothing there is parked queue work. This is what an all-blocked
                   stop reports, so the user does not have to ask what the blockers are.

Output (plain text, one line per candidate, in the algorithm's selection order):
  [N] <source>: <heading> (<M> items)
  h1 sprint blocks (tasks.md Phase A) omit the "(<M> items)" suffix — they are a scope
  announcement, not an item-counted group.

Empty result (stdout stays empty / `[]`; a diagnosis goes to STDERR): zero candidates has
three very different meanings and silently printing nothing conflates them — the queue is
genuinely clear, every open item is parked, or the file uses a shape this parser cannot see
(prose bullets instead of `- [ ]`, or items sitting above the first heading). Only the first
means "no work". The other two are false negatives that read as "nothing to do" while real
work sits in the file, so `zero_candidate_diagnosis()` names which one applies per source
file. Diagnostics go to stderr specifically so `--json` stdout stays machine-parseable.

Parsing semantics (must match `SKILL.md` Step 1 prose exactly — this script does not
reinterpret it):

  HTML comments: `<!-- ... -->` spans are blanked out before tokenizing (line count preserved,
  so line numbers stay grep-compatible). Format templates parked in a comment — e.g. the
  `## Feature Name` / `- [ ] Simplest case` block harness-init seeds `backlog.md` with — are
  markup, not work, and must never be reported as candidates.

  Fenced code blocks: ```-fenced and ~~~-fenced spans are blanked the same way, immediately after
  the comment pass. A `#`/`##`/`###` line in a code sample is markup too, and a fake heading does
  more than pollute the listing — it truncates the enclosing region (see "Directly owns" below),
  so a real `- [ ]` sitting after the fence stops counting toward its actual heading. Openers are
  3+ backticks/tildes indented at most 3 spaces; a closer needs the same character and at least
  the opener's length; an unclosed fence runs to EOF.

  Phase A (tasks.md h1 sprint blocks): an `# ` heading is a candidate if `status: open`
  is the FIRST `status:` line whose line number falls strictly between this h1 and the next
  h1 (or EOF) — NOT literally the next line in the file. Body content commonly sits between
  the heading and its status line.

  Blocked/deferred marker exclusion (applies everywhere "direct open items" are counted): an
  otherwise-open `- [ ]` item whose text contains a `*(deferred: ...)*` or
  `*(blocked by: <n>-<slug>)*` marker is excluded from the open-item count entirely — same
  effect as if it were `[>]`. A heading whose open items are ALL marked is therefore not a
  candidate (matches `SKILL.md` Step 2 "Deferred items"/"blocked" rules); a heading with a mix
  of marked and unmarked open items is still a candidate, counting only the unmarked ones.
  The marker counts wherever it sits in a multi-line item: `tokenize` folds an item's indented
  continuation lines into its text, so a marker on a wrapped item's last line is seen — including
  when an indented fenced block or HTML comment sits between the item and its marker.

  "Directly owns" (Phase B/C, full-scan rules 2-5): open `- [ ]` checkbox items collected
  from just after a heading up to (not including) the next heading of ANY level 1-3 — not
  just the next heading of the same or broader level. A checkbox sitting after a nested h3
  child does NOT count toward that h3's h2 parent.

  tasks.md contributes h1 sprint blocks and NOTHING else. It is the Sprint Contract, deleted
  whole at sprint close, so no queue lives there — `## Review Backlog` findings now go to
  backlog.md (`harness-init/references/backlog-template.md`). An older tasks.md that still holds
  such a section is reported by `tasks_persistent_sections()` as a migration warning on stderr,
  never selected as a candidate.

  Phase B (backlog.md, FAST PATH ONLY): top-to-bottom, TYPE-AGNOSTIC scan collecting up to 2
  qualifying h2-or-h3 headings in raw document order (h2/h3 interleaved as they appear).
  Skipped entirely if Phase A already produced FAST_PATH_CAP (3) candidates. The fast-path
  total across Phase A + B is capped at FAST_PATH_CAP (3) — matched to `AskUserQuestion`'s
  4-option cap once the mandatory "더 많은 항목 보기" option is appended (3 candidates + 1 = 4).
  A truncation (fewer candidates shown than a full scan would find) is signalled to the
  orchestrator via `truncation_note()`, written to stderr in fast-path mode only — see below.

  Full scan is a DIFFERENT algorithm from Phase B, not a superset call to the same helper:
  rule 1 = all qualifying tasks.md h1 blocks (Phase A, uncapped); rule 2 = ALL qualifying
  backlog.md h3 headings, in document order among h3s only; rule 3 = ALL qualifying backlog.md
  h2 headings, in document order among h2s only. Rules 2 and 3 apply TYPE PRIORITY (all h3
  first, then all h2) — this is NOT the same ordering as Phase B's raw document order across
  types, and the two must stay separate functions (`fast_path()` / `full_scan()`) rather than
  one shared helper, or the divergence silently disappears.

Self-check (--test):
  Exercises the status-line-gap case (Phase A), the direct-items heading-boundary case
  (nested h3 item must not count toward its h2 parent), the all-parked-skip case (every item
  `[x]`/`[>]` under a heading is not a candidate), Phase-B limit truncation (cap 3 total
  across A+B) and `truncation_note` in both directions (truncated -> note, not truncated ->
  None), the Phase-B-vs-full-scan ordering divergence on backlog.md h2/h3
  interleaving, the tasks.md findings-section guard (never a candidate in either algorithm;
  reported by `tasks_persistent_sections`, and a healthy `## Scope` does not trip it),
  and the blocked/deferred-marker exclusion case (all-marked heading is not a
  candidate; mixed marked+unmarked heading counts only the unmarked items), and the
  HTML-comment case (a commented-out template heading + item is not a candidate, and line
  numbers of the real content after it are unshifted), and the fenced-code-block case (a fenced
  `## Fake` between a heading and its items neither becomes a candidate nor truncates the real
  heading's region; tilde fences, info strings, longer-closer nesting, unclosed fences, the
  4-space-indent non-fence, and the comments-before-fences ordering all covered), and the
  multi-line-item case (a marker on a wrapped item's indented continuation line parks the item,
  and still counts across an indented fenced block or HTML comment nested in the item; an
  unindented or blank-line-separated line is not folded in; the token keeps its FIRST line
  number), and the claimed-items case (a `## Covers` claim, a merge-base deletion claim, a line
  added to base after branching left unclaimed, a non-`.worktrees/` worktree ignored, the stderr
  skip line, and the all-claimed diagnosis), the per-group twin attribution, the Phase A block
  claim, `--ref` on a symlinked queue file, and the utf-8 pin on `git show` output (decoding
  forced to ascii for any call that does not request utf-8), and a block titled for one heading
  that covers lines from several (all claimed). Every fixture is an in-memory string except the
  claimed-items, `--ref`, symlink and utf-8 cases, which build throwaway git repos in a tempdir.
  Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Pure-function core (testable without real filesystem)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_STATUS_RE = re.compile(r"^status:\s*(\S+)")
_CHECKBOX_RE = re.compile(r"^-\s*\[([ xX>])\]\s*(.*)$")
# Generalized skip marker: `*(deferred: ...)*` or `*(blocked by: <n>-<slug>)*` — both mean
# "otherwise-open item is not actually actionable yet", same treatment as a `[>]` checkbox.
# Group 1 is the keyword and group 2 the payload (the reason, or the blocker's `<n>-<slug>`).
# `_is_blocked` inspects the payload; `task_nodes.orphaned_blockers` selects `blocked by` markers by
# the keyword and resolves their payload against the items a prune run deleted.
_BLOCK_MARKER_RE = re.compile(r"\*\(\s*(deferred|blocked by)\s*:(.*?)\)\*", re.IGNORECASE)
# `<slug>`, `<n>-<slug>` — a payload that is NOTHING BUT angle-bracket placeholders and separators
# is a documentation example of the syntax, not a blocker anyone can resolve; an item describing
# the marker format in its own prose would otherwise park itself forever, with no blocker to
# clear. A payload that merely embeds a placeholder (`3-migrate-to-<v2>-api`) still names a real
# blocker and must stay parked, so the test is "no alphanumeric survives stripping the
# placeholders", not "contains a placeholder".
_MARKER_PLACEHOLDER_RE = re.compile(r"<[^<>]*>")


def _is_placeholder_payload(payload: str) -> bool:
    """True if `payload` names no resolvable blocker — only `<placeholders>` and separators."""
    return not any(c.isalnum() for c in _MARKER_PLACEHOLDER_RE.sub(" ", payload))
# HTML comments hold format templates (`## Feature Name` / `- [ ] Simplest case`) that must
# never surface as candidates.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Every character `str.splitlines` ends a line at.
_LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"
# Fenced code blocks hold command samples and markdown examples — same problem as comments, but
# fences are line-anchored (a span regex is the wrong tool). Up to 3 leading spaces per
# CommonMark; 4+ makes it an indented code block's content, not a fence opener.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# A plain list bullet that is NOT a checkbox. Never used for candidate selection — it exists
# only so an empty result can tell "this heading has no work" apart from "this heading's work
# is written as prose bullets, which the selector cannot see".
_BULLET_RE = re.compile(r"^\s*[-*+]\s+\S")

# h2 titles shipped tooling used to append to tasks.md, before findings moved to backlog.md.
# Presence of one in tasks.md is a migration signal, never a candidate source. Matched as a
# PREFIX: security-overview writes `## Security Fixes — <repo-name>`.
PERSISTENT_SECTION_TITLES = ("Review Backlog", "Security Fixes")

# The fast path's combined Phase A + Phase B cap. Matched to `AskUserQuestion`'s 4-option cap
# once the mandatory "더 많은 항목 보기" option (SKILL.md Step 1) is appended: 3 candidates + 1 = 4.
FAST_PATH_CAP = 3

# The Sprint Contract's own sections (lowercased). These own open `- [ ]` items legitimately —
# `## Acceptance criteria` is checkboxes by definition — so they are the exception to "an h2 with
# open items in tasks.md is misplaced queue content".
SPRINT_SECTION_TITLES = frozenset(
    {
        "scope",
        "acceptance criteria",
        "out of scope",
        "evaluator feedback",
        "covers",
        "lint/test command",
    }
)


def _is_blocked(text: str) -> bool:
    """True if `text` (the checkbox item body) carries a *resolvable* deferred/blocked-by marker.

    A `blocked by` marker whose payload is nothing but angle-bracket placeholders is prose quoting
    the syntax — an item about the marker format, or a template — so it parks nothing. Without this, an
    item that merely documents `*(blocked by: <slug>)*` is filtered out of candidate selection
    permanently, because there is no blocker to land and no marker anyone would think to clear.

    The escape hatch is scoped to `blocked by` on purpose. A `deferred` payload is free prose that
    may legitimately contain `<v2>` or `<team>`; treating those as placeholders would un-park an
    item somebody deliberately deferred, which is the opposite failure.
    """
    return any(
        not (m.group(1).lower() == "blocked by" and _is_placeholder_payload(m.group(2)))
        for m in _BLOCK_MARKER_RE.finditer(text)
    )


def _strip_html_comments(text: str) -> str:
    """Blank out `<!-- ... -->` spans, preserving line count so token line numbers stay 1-based.

    The trailing-newline guard is the same class of fix as `_scan_fenced_blocks`'s `+ "\\n" if out`
    below, for the same reason: an N-line match holds only N-1 newlines, so when the match ends at
    true EOF with nothing after it, the `"\\n" * count` replacement is one separator short and a
    bare `.sub` drops the file's last line. The guard goes on the INPUT because neither
    output-side variant works — spelling both out, since each fails on a different input and
    picking between them by inspection is how this bug got written in the first place:

      - append unconditionally after `.sub`: fixes the EOF case, but inflates every input that
        already ends in a newline ("a\\n" -> 2 lines, "```\\n" -> 2).
      - append only when the result lacks a trailing newline: never fires, because the
        substituted text already ends in one — so the EOF case stays broken (3 lines, want 4).

    Normalizing the input is correct for both classes at once. Guard the empty string, whose
    line count is already 0.

    "Line" means a `str.splitlines` line, as every caller counts them: a file already ending in
    U+2028 needs no guard, and a comment's breaks include a bare `\\r`, not only `\\n`.
    """
    if text and text[-1] not in _LINE_BREAKS:
        text += "\n"

    # A bare "\r" left at the end of the output would fuse with a following "\n" — the blank's own
    # first break, or the text after a single-line comment — into one "\r\n" break. Tracked on
    # what was emitted, not the source, so back-to-back comments are covered too.
    out, pos, tail = [], 0, ""
    for m in _HTML_COMMENT_RE.finditer(text):
        before = text[pos:m.start()]
        tail = before[-1:] or tail
        breaks = len(m.group(0).splitlines()) - 1
        blank = "\n" * breaks
        if tail == "\r":
            if breaks:
                blank = "\x0b" + blank[1:]
            elif text[m.end():m.end() + 1] == "\n":
                blank = " "
        out += [before, blank]
        tail = blank[-1:] or tail
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def _scan_fenced_blocks(text: str) -> tuple[str, int | None]:
    """Blank out fenced code blocks, preserving line count so token line numbers stay 1-based.

    A `#`/`##`/`###` line inside a ```-fenced sample is markup, not a heading — and treating it as
    one corrupts *selection*, not just reporting: `_region_end` boundaries on the next level-1..3
    heading, so a fake heading truncates the enclosing region and a real `- [ ]` after the fence
    stops counting toward its actual heading.

    Fence rules follow CommonMark where it matters here: an opener is 3+ backticks or 3+ tildes
    indented at most 3 spaces (4+ spaces is indented-code content, not a fence); a closer must use
    the same character, run at least as long as the opener, and carry nothing but whitespace after
    it. An unclosed fence runs to EOF. The delimiter lines are blanked too — they are never
    headings, status lines, or checkboxes, so nothing is lost.

    Returns `(blanked_text, unclosed_opener_line)`. The second element is the whole point of the
    tuple: an unclosed fence is CommonMark-correct to blank through EOF, but an odd number of
    ``` is an ordinary hand-editing typo, and swallowing the rest of a backlog silently is the
    exact false-negative class `zero_candidate_diagnosis` exists to prevent — yet invisible to it,
    since the swallowed headings never become tokens. Callers surface it (see `main`).
    """
    out = []
    fence_char = None
    fence_len = 0
    opened_at = None
    for line in text.splitlines():
        if fence_char is None:
            m = _FENCE_RE.match(line)
            # CommonMark forbids a backtick in a BACKTICK fence's info string (tilde fences allow
            # it). Without this guard an ordinary prose line like ```foo`bar reads as an unclosed
            # opener and blanks the file through EOF — precisely the silent candidate loss this
            # function exists to prevent. Openers only; the closer branch below already requires
            # nothing but whitespace after the run.
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence_char = m.group(1)[0]
                fence_len = len(m.group(1))
                opened_at = len(out) + 1   # 1-based line of this opener
                out.append("")
                continue
            out.append(line)
            continue
        # Inside a fence: only a same-char run at least as long as the opener, with nothing but
        # whitespace after it, closes. A shorter or differently-charactered run is just content.
        m = _FENCE_RE.match(line)
        if m and m.group(1)[0] == fence_char and len(m.group(1)) >= fence_len and not m.group(2).strip():
            fence_char = None
            fence_len = 0
            opened_at = None
        out.append("")
    # The trailing "\n" is required, not cosmetic: when an unclosed fence blanks the file's LAST
    # line, `out` ends in "" and a bare `"\n".join(out)` loses exactly that line on the caller's
    # `.splitlines()` — silently breaking the line-count contract in the one case with no content
    # after the fence to make the drift visible. Guard the empty input, whose join is already "".
    blanked = "\n".join(out) + "\n" if out else ""
    return blanked, opened_at


def _strip_fenced_blocks(text: str) -> str:
    """`_scan_fenced_blocks` without the unclosed-opener line — for callers that only want text."""
    return _scan_fenced_blocks(text)[0]


def unclosed_fence_line(text: str) -> int | None:
    """1-based line of an unbalanced fence opener in `text`, or None.

    Applies the same comments-then-fences order `tokenize` uses, so a ``` parked inside an HTML
    comment is not reported as an unbalanced fence.
    """
    return _scan_fenced_blocks(_strip_html_comments(text))[1]


def tokenize(text: str) -> list[dict]:
    """Classify each line into a typed token: heading / status / checkbox / bullet.

    Unrecognized lines (body prose) are dropped — only heading/status/checkbox matter for
    candidate detection, and every selector filters on `type`, so the diagnosis-only `bullet`
    token is inert to them. Line numbers are 1-based to match grep -n output.

    `<!-- ... -->` spans and fenced code blocks are blanked out first: template/example markup,
    whether parked in a comment or shown in a code sample, is not real content, so it must not
    produce headings or checkbox items.

    Comments are stripped BEFORE fences, and the order is load-bearing: a doc template parked in a
    comment often contains a lone ``` opener, which — if fences ran first — would open a phantom
    unclosed fence and blank the rest of the file.

    A checkbox item wrapped across several lines keeps its indented continuation lines: they are
    folded into the token's `text` (single-space joined), so `_is_blocked` sees the whole item.
    Without this a `*(deferred: ...)*` marker parked on a wrapped item's last line is invisible and
    the item surfaces as an actionable candidate — the exact false positive the marker exists to
    prevent. The token's `line` stays the FIRST line, so grep -n style reporting is unchanged.
    Only indented, non-blank lines continue an item; a blank line, a heading, a status line, a
    checkbox, or a nested bullet ends it (CommonMark lazy continuation is deliberately not
    supported — an unindented line is far more likely to be new prose than a wrapped item).
    The indent test reads the RAW line, so an indented fenced block or HTML comment nested inside
    an item does not close it even though the strippers blank those lines out.
    """
    tokens: list[dict] = []
    open_item: dict | None = None
    raw_lines = text.splitlines()
    for i, line in enumerate(_strip_fenced_blocks(_strip_html_comments(text)).splitlines(), start=1):
        m = _HEADING_RE.match(line)
        if m:
            open_item = None
            tokens.append(
                {"type": "heading", "level": len(m.group(1)), "title": m.group(2).strip(), "line": i}
            )
            continue
        m = _STATUS_RE.match(line)
        if m:
            open_item = None
            tokens.append({"type": "status", "value": m.group(1), "line": i})
            continue
        m = _CHECKBOX_RE.match(line)
        if m:
            open_item = {"type": "checkbox", "state": m.group(1), "text": m.group(2), "line": i}
            tokens.append(open_item)
            continue
        if _BULLET_RE.match(line):
            open_item = None
            tokens.append({"type": "bullet", "line": i})
            continue
        if open_item is not None:
            # Indentation is read from the RAW line, not the masked one: a fenced sample or an HTML
            # comment nested under an item is blanked to "" by the strippers, and testing the masked
            # line would read that as a blank separator and close the item — dropping a
            # `*(deferred: ...)*` marker that follows the block. Folding still uses the masked text,
            # so the code inside the fence never becomes item text.
            raw = raw_lines[i - 1] if i <= len(raw_lines) else ""
            if raw[:1].isspace() and raw.strip():
                if line.strip():
                    open_item["text"] = f"{open_item['text']} {line.strip()}".strip()
                continue
        open_item = None
    return tokens


def _headings(tokens: list[dict], levels: tuple[int, ...] = (1, 2, 3)) -> list[dict]:
    return [t for t in tokens if t["type"] == "heading" and t["level"] in levels]


def _region_end(heading: dict, all_headings: list[dict]) -> float:
    """Line of the next level-1..3 heading after `heading`, or infinity — the region boundary."""
    for h in all_headings:
        if h["line"] > heading["line"]:
            return h["line"]
    return math.inf


def _direct_open_items(tokens: list[dict], heading: dict, all_headings: list[dict]) -> list[dict]:
    """Open checkbox items between `heading` and the next heading of ANY level 1-3.

    all_headings must be the full sorted (by line) list of level-1..3 headings in the same
    token stream — this is what makes a nested h3's items NOT count toward its h2 parent.
    """
    end = _region_end(heading, all_headings)
    items = [
        t
        for t in tokens
        if t["type"] == "checkbox" and heading["line"] < t["line"] < end
    ]
    return [
        t for t in items if t["state"] == " " and not _is_blocked(t["text"]) and not t.get("claimed_by")
    ]


# ---- Phase A: tasks.md h1 sprint blocks ------------------------------------------------

def h1_blocks(tasks_tokens: list[dict]) -> list[tuple[dict, str | None]]:
    """(h1 heading token, value of its FIRST status: line strictly inside the block or None)."""
    h1s = _headings(tasks_tokens, (1,))
    blocks = []
    for idx, h in enumerate(h1s):
        end = h1s[idx + 1]["line"] if idx + 1 < len(h1s) else math.inf
        status_value = None
        for t in tasks_tokens:
            if t["type"] == "status" and h["line"] < t["line"] < end:
                status_value = t["value"]
                break
        blocks.append((h, status_value))
    return blocks


def phase_a_candidates(tasks_tokens: list[dict]) -> list[dict]:
    """h1 blocks whose FIRST status: line strictly between this h1 and the next h1 is 'open'.

    A block another `.worktrees/` run holds (`claimed_by`, set by `mark_claimed_blocks`) is skipped.
    """
    result = []
    for h, status_value in h1_blocks(tasks_tokens):
        if status_value == "open" and not h.get("claimed_by"):
            result.append(
                {"source": "tasks.md", "kind": "h1", "title": h["title"], "line": h["line"], "items": None}
            )
    return result


# ---- Migration check: persistent sections that no longer belong in tasks.md -------------

def _is_persistent_title(title: str) -> bool:
    """Prefix match, so `Security Fixes — my-webapp` counts as `Security Fixes`."""
    stripped = title.strip()
    return any(
        stripped == known or stripped.startswith(known + " ")
        for known in PERSISTENT_SECTION_TITLES
    )


def tasks_persistent_sections(tasks_tokens: list[dict]) -> list[dict]:
    """Headings in tasks.md that hold content meant to outlive the sprint.

    THE single definition of "persistent section". `task_nodes.py` imports this to decide whether
    `prune-tasks` may touch the file, and the CLI below uses it to warn — one predicate, so the
    warning and the refusal can never disagree about the same file. Two guards drifting apart is
    worse than either alone: the warning says "move these or they will be lost" while the pruner,
    not recognising the shape, deletes the h1 block to EOF and unlinks the file.

    `tasks.md` is the Sprint Contract and nothing else — it is deleted whole at sprint close, so
    anything meant to outlive the sprint must live in `backlog.md`. Older repos wrote
    `## Review Backlog` findings here. Those are NOT candidates any more, but dropping them
    silently would hide real queued work, so they are reported instead.

    Takes tokens, not raw text, so fenced code blocks and HTML comments are already masked: a
    `## Review Backlog` inside a ```markdown example is documentation, and blocking cleanup on it
    would be a false refusal with no override.

    A Sprint Contract's own `## Scope` / `## Acceptance criteria` own open checkboxes too, so a
    bare "h2 with open items" test would fire on every healthy sprint. Two narrower tests instead,
    either of which qualifies a heading:

      1. its title is one tooling is known to have written (`PERSISTENT_SECTION_TITLES`), or an
         h3 nested under such a heading — this catches findings appended AFTER the sprint h1, the
         placement that used to destroy them, and fires whether or not the items are still open;
      2. it owns open items and neither it nor its parent h2 is one of the Sprint Contract's own
         sections (`SPRINT_SECTION_TITLES`) — this catches an ad-hoc grab-bag heading anywhere in
         the file, whichever side of the sprint h1 it sits on.
    """
    headings = _headings(tasks_tokens)
    coarse = [h for h in headings if h["level"] in (1, 2)]
    known_end = None  # end line of the persistent section currently open, for its h3 children
    parent_is_sprint_section = False
    result = []
    for h in headings:
        if h["level"] in (1, 2) and known_end is not None and h["line"] >= known_end:
            known_end = None
        if h["level"] in (1, 2):
            parent_is_sprint_section = (
                h["level"] == 2 and h["title"].strip().lower() in SPRINT_SECTION_TITLES
            )
        if h["level"] == 2 and _is_persistent_title(h["title"]):
            known_end = _region_end(h, coarse)
            result.append({"title": h["title"], "line": h["line"], "level": 2})
            continue
        if h["level"] == 3 and known_end is not None and h["line"] < known_end:
            result.append({"title": h["title"], "line": h["line"], "level": 3})
            continue
        if (
            h["level"] in (2, 3)
            and h["title"].strip().lower() not in SPRINT_SECTION_TITLES
            and not (h["level"] == 3 and parent_is_sprint_section)
            and _direct_open_items(tasks_tokens, h, headings)
        ):
            result.append({"title": h["title"], "line": h["line"], "level": h["level"]})
    return result


# ---- Phase C: backlog.md fast-path (type-agnostic, document order) --------------------

def backlog_fast_candidates(backlog_tokens: list[dict], limit: int | None = None) -> list[dict]:
    headings = _headings(backlog_tokens)
    result = []
    for h in headings:
        if h["level"] in (2, 3):
            open_items = _direct_open_items(backlog_tokens, h, headings)
            if open_items:
                result.append(
                    {
                        "source": "backlog.md",
                        "kind": f"h{h['level']}",
                        "title": h["title"],
                        "line": h["line"],
                        "items": len(open_items),
                    }
                )
                if limit is not None and len(result) >= limit:
                    break
    return result


# ---- Full-scan rules 4+5: backlog.md, type-priority (all h3, then all h2) -------------

def backlog_h3_candidates(backlog_tokens: list[dict]) -> list[dict]:
    headings = _headings(backlog_tokens)
    result = []
    for h in headings:
        if h["level"] == 3:
            open_items = _direct_open_items(backlog_tokens, h, headings)
            if open_items:
                result.append(
                    {"source": "backlog.md", "kind": "h3", "title": h["title"], "line": h["line"], "items": len(open_items)}
                )
    return result


def backlog_h2_candidates(backlog_tokens: list[dict]) -> list[dict]:
    headings = _headings(backlog_tokens)
    result = []
    for h in headings:
        if h["level"] == 2:
            open_items = _direct_open_items(backlog_tokens, h, headings)
            if open_items:
                result.append(
                    {"source": "backlog.md", "kind": "h2", "title": h["title"], "line": h["line"], "items": len(open_items)}
                )
    return result


# ---- Orchestrators ----------------------------------------------------------------------

def fast_path(tasks_tokens: list[dict], backlog_tokens: list[dict]) -> list[dict]:
    """Phase A (uncapped) + Phase B (<=2, skipped if A already >= FAST_PATH_CAP), truncated to
    FAST_PATH_CAP total."""
    result: list[dict] = []
    result.extend(phase_a_candidates(tasks_tokens))
    if len(result) < FAST_PATH_CAP:
        result.extend(backlog_fast_candidates(backlog_tokens, limit=2))
    return result[:FAST_PATH_CAP]


def full_scan(tasks_tokens: list[dict], backlog_tokens: list[dict]) -> list[dict]:
    """Rules 1-3 in order, uncapped. Rules 2+3 are type-priority (all h3, then all h2) —
    a genuinely different ordering from Phase B's type-agnostic document order."""
    result: list[dict] = []
    result.extend(phase_a_candidates(tasks_tokens))
    result.extend(backlog_h3_candidates(backlog_tokens))
    result.extend(backlog_h2_candidates(backlog_tokens))
    return result


def format_candidates(candidates: list[dict]) -> list[str]:
    lines = []
    for i, c in enumerate(candidates, start=1):
        if c["kind"] == "h1":
            lines.append(f"[{i}] {c['source']}: {c['title']}")
        else:
            lines.append(f"[{i}] {c['source']}: {c['title']} ({c['items']} items)")
    return lines


REJECTED_HEADING = "rejected — do not re-file"


def _prose_only_headings(tokens: list[dict]) -> list[dict]:
    """Headings that directly own prose bullets but not one checkbox — invisible work.

    This must be judged PER HEADING, not per file. A file-wide "are there any checkboxes?"
    test is wrong on the common real shape: a backlog whose `## Completed` section is full of
    `- [x]` while its open section is written as prose tickets. That file has plenty of
    checkboxes, so a global test reports "all done" — a confidently wrong answer, worse than
    silence, on exactly the case this diagnosis exists to catch.
    """
    headings = _headings(tokens)
    drifted = []
    for h in headings:
        # Plain bullets by design (harness-init backlog-template.md → *Rejected*): decisions,
        # not work, so a checkbox-free region here is the correct shape.
        if h["title"].strip().lower() == REJECTED_HEADING:
            continue
        end = _region_end(h, headings)
        has_box = any(
            t["type"] == "checkbox" and h["line"] < t["line"] < end for t in tokens
        )
        has_bullet = any(
            t["type"] == "bullet" and h["line"] < t["line"] < end for t in tokens
        )
        if has_bullet and not has_box:
            drifted.append(h)
    return drifted


def _diagnose_source(label: str, tokens: list[dict]) -> list[str]:
    """Reasons `label` contributed no candidates — empty list if it has nothing to say."""
    headings = _headings(tokens)
    boxes = [t for t in tokens if t["type"] == "checkbox"]
    bullets = [t for t in tokens if t["type"] == "bullet"]
    if not headings and not boxes and not bullets:
        return []

    msgs = []
    drifted = _prose_only_headings(tokens)
    if drifted:
        shown = ", ".join(f"{h['title']!r} (line {h['line']})" for h in drifted[:3])
        more = f", +{len(drifted) - 3} more" if len(drifted) > 3 else ""
        msgs.append(
            f"{label}: {len(drifted)} heading(s) own prose bullets but no `- [ ]` item — "
            f"{shown}{more}. Only checkbox lines are selectable, and `####`-or-deeper headings "
            "are not headings to this parser (their items attribute to the enclosing "
            "`#`–`###` heading)."
        )

    claimed_blocks = []
    if label == "tasks.md":
        claimed_blocks = [h for h, status in h1_blocks(tokens) if status == "open" and h.get("claimed_by")]
        if claimed_blocks:
            msgs.append(
                f"tasks.md: {len(claimed_blocks)} open sprint block(s) claimed by another `.worktrees/` run — "
                "see the skip line above; resume that worktree to work them."
            )
            h1s = [h for h in headings if h["level"] == 1]
            regions = [(h["line"], _region_end(h, h1s)) for h in claimed_blocks]
            boxes = [t for t in boxes if not any(start < t["line"] < end for start, end in regions)]

    open_boxes = [t for t in boxes if t["state"] == " "]
    claimed = [t for t in open_boxes if t.get("claimed_by")]
    actionable = [t for t in open_boxes if not _is_blocked(t["text"]) and not t.get("claimed_by")]
    first = min((h["line"] for h in headings), default=None)
    # "Unattributed" means literally above the first heading — every item after one sits in
    # some region. Do not describe an attributed-but-unselected item as unattributed: that is
    # a false statement about the file, and the reader acts on it.
    stray = [t for t in actionable if first is None or t["line"] < first]
    attributed = [t for t in actionable if t not in stray]
    if stray:
        where = (
            f" (that heading is at line {first})"
            if first
            else " (the file has no `#`–`###` heading at all)"
        )
        # Say `#`–`###` explicitly: a `####` line may well sit above the item and look like a
        # heading to the reader, so "no heading above it" would be false as written.
        msgs.append(
            f"{label}: {len(stray)} actionable item(s) sit above the first `#`–`###` "
            f"heading{where} — only levels 1–3 count here, so a `####`-or-deeper line above an "
            "item does not attribute it."
        )
    if attributed:
        # The reachability gap differs per file — naming tasks.md's causes while diagnosing
        # backlog.md would be a false statement about the file in front of the reader.
        cause = (
            "tasks.md contributes h1 `status: open` sprint blocks only — items under any `##`/"
            "`###` there are reachable by no rule and belong in backlog.md"
            if label == "tasks.md"
            else "the backlog.md rules cover h2/h3 groups only, so items under a top-level "
            "`# ` heading are reachable by no rule"
        )
        msgs.append(
            f"{label}: {len(attributed)} actionable item(s) are attributed to a heading but no "
            f"phase selected them — {cause}."
        )
    if not actionable:
        # Only reachable when nothing actionable exists, so these never contradict the
        # stray/attributed lines above.
        unclaimed_open = [t for t in open_boxes if not t.get("claimed_by")]
        if claimed:
            msgs.append(
                f"{label}: {len(claimed)} open item(s) claimed by another `.worktrees/` run — "
                "see the skip line above; resume that worktree to work them."
            )
        if unclaimed_open:
            # --parked lists backlog.md only, so the pointer would mislead on tasks.md.
            pointer = (
                " Re-run with --parked to list each item and its blocker."
                if label == "backlog.md"
                else ""
            )
            msgs.append(
                f"{label}: {len(unclaimed_open)} open item(s), all parked by a "
                "`*(blocked by: …)*` / `*(deferred: …)*` marker — clear a blocker to make one "
                f"actionable.{pointer}"
            )
        elif claimed or claimed_blocks:
            pass
        elif boxes and not drifted:
            msgs.append(f"{label}: no open items (all `[x]`/`[>]`).")
        elif not drifted:
            # Headings or plain bullets but not one checkbox: say so, or the caller falls back
            # to "no headings or items at all" — false about a file that has them.
            unheaded = [t for t in bullets if first is None or t["line"] < first]
            if label == "tasks.md":
                # tasks.md is selected by h1 status, never by checkbox.
                msgs.append("tasks.md: no h1 block with `status: open`.")
            elif unheaded:
                # Per-heading drift detection cannot see bullets no heading owns.
                msgs.append(
                    f"{label}: {len(unheaded)} prose bullet(s) sit above the first `#`–`###` "
                    "heading and no `- [ ]` item exists — only checkbox lines are selectable, "
                    "and a `####`-or-deeper line does not count as a heading."
                )
            else:
                msgs.append(f"{label}: no `- [ ]` item at all.")
    return msgs


def parked_items(label: str, tokens: list[dict]) -> list[dict]:
    """Open items in one file that a resolvable blocked/deferred marker parks, in document order.

    The complement of the actionable set, by the same `_is_blocked` test the selectors use. Only
    meaningful for backlog.md, where a checkbox is selectable: there, a listed item is one a
    candidate run skipped for its marker. `heading` is the nearest level-1..3 heading above the
    item, or None for one above the first heading. `text` is the tokenizer's folded item text,
    not the source line.
    """
    out = []
    heading = None
    for t in tokens:
        if t["type"] == "heading":
            heading = t["title"]
        elif t["type"] == "checkbox" and t["state"] == " " and _is_blocked(t["text"]):
            markers = [
                {"kind": m.group(1).lower(), "payload": m.group(2).strip()}
                for m in _BLOCK_MARKER_RE.finditer(t["text"])
                if not (m.group(1).lower() == "blocked by" and _is_placeholder_payload(m.group(2)))
            ]
            out.append(
                {"source": label, "line": t["line"], "heading": heading, "text": t["text"], "markers": markers}
            )
    return out


# A parked item's prose can run to several hundred chars, and the all-blocked stop needs the
# blocker, not the prose: the plain-text line clips the body and keeps every marker. --json and
# the line number still give the full item.
PARKED_TEXT_WIDTH = 140


def _clip_parked_text(text: str) -> str:
    # Placeholder markers are prose quoting the syntax, so they stay in the body and clip with it.
    markers: list[str] = []

    def _lift(m: re.Match) -> str:
        if m.group(1).lower() == "blocked by" and _is_placeholder_payload(m.group(2)):
            return m.group(0)
        markers.append(m.group(0))
        return " "

    body = " ".join(_BLOCK_MARKER_RE.sub(_lift, text).split())
    if len(body) <= PARKED_TEXT_WIDTH:
        return text
    return " ".join([body[:PARKED_TEXT_WIDTH] + "…", *markers])


def format_parked(items: list[dict]) -> list[str]:
    return [
        f"{it['source']}:{it['line']} [{it['heading'] or 'no heading'}] {_clip_parked_text(it['text'])}"
        for it in items
    ]


def truncation_note(shown: int, total: int) -> str | None:
    """One-line stderr note when the fast path's FAST_PATH_CAP hid additional candidates.

    Pure: `shown` is the count `fast_path()` actually returned, `total` is the count a full
    scan would find. Both algorithms qualify a heading by the same test (see module docstring),
    so `total` is a real count, not an estimate — `main()` gets it by calling `full_scan()` on
    the already-tokenized files (no extra file I/O), and calls this only in fast-path mode, never
    with `--full-scan`. Returns None when nothing was hidden (`total <= shown`).
    """
    if total <= shown:
        return None
    hidden = total - shown
    return (
        f"Note: fast path is showing {shown} of {total} candidate group(s) — {hidden} more "
        'exist. Say how many more when offering "더 많은 항목 보기"; run --full-scan to see them all.'
    )


def zero_candidate_diagnosis(tasks_tokens: list[dict], backlog_tokens: list[dict]) -> list[str]:
    """Human-readable reasons an otherwise-valid run produced zero candidates.

    No `--full-scan` reachability probe here: since tasks.md stopped contributing h2/h3 groups,
    both algorithms qualify a heading by the same test and differ only in cap and ordering, so a
    fast path that found nothing proves the full scan finds nothing. Re-adding a tasks.md-only
    full-scan rule would make "fast path found nothing" and "there is nothing" different facts
    again — restore the probe with it.
    """
    lines = []
    for label, tokens in (("tasks.md", tasks_tokens), ("backlog.md", backlog_tokens)):
        lines.extend(_diagnose_source(label, tokens))
    if not lines:
        return ["No candidates: tasks.md and backlog.md have no headings or items at all."]
    return ["No candidates found. Why:"] + [f"  - {m}" for m in lines]


# ---------------------------------------------------------------------------
# Claimed items — other `.worktrees/` runs (concurrent `--tree` cycles)
# ---------------------------------------------------------------------------

_KEY_SEP = "\x1f"


def _qkey(group: str | None, text: str) -> str:
    """Claim key: bare item text, or `group<US>text` when the group tells twins apart."""
    return f"{group}{_KEY_SEP}{text}" if group is not None else text


def _split_key(key: str) -> tuple[str | None, str]:
    if _KEY_SEP in key:
        group, text = key.split(_KEY_SEP, 1)
        return group, text
    return None, key


def item_keys(text: str, under: str | None = None, qualify: object = None) -> set[str]:
    """Match keys for the checkbox items in `text`: the item's FIRST line after `- [?] `, stripped.

    The first line, not the tokenizer's folded text, because `## Covers` copies each item line
    verbatim and a wrapped continuation is not part of that copy. `under` restricts the scan to
    the region of every level-1..3 heading with exactly that title (e.g. "Covers"); the group of
    such an item is the h1 block holding it (task-next writes the selected heading as that h1).
    Otherwise an item's group is its nearest preceding level-1..3 heading.

    `qualify` prefixes the group onto a key (`_qkey`): True qualifies every item, a set qualifies
    only items whose text is in it (twins), None leaves keys bare.
    """
    tokens = tokenize(text)
    raw = text.splitlines()
    headings = _headings(tokens)
    regions = None
    if under is not None:
        regions = [(h["line"], _region_end(h, headings)) for h in headings if h["title"] == under]
    keys = set()
    group = None
    h1_title = None
    for t in tokens:
        if t["type"] == "heading" and t["level"] in (1, 2, 3):
            group = t["title"]
            if t["level"] == 1:
                h1_title = t["title"]
            continue
        if t["type"] != "checkbox":
            continue
        if regions is not None and not any(s < t["line"] < e for s, e in regions):
            continue
        m = _CHECKBOX_RE.match(raw[t["line"] - 1].lstrip())
        if m and m.group(2).strip():
            item = m.group(2).strip()
            g = h1_title if under is not None else group
            if qualify is True or (isinstance(qualify, (set, frozenset)) and item in qualify):
                keys.add(_qkey(g, item))
            else:
                keys.add(item)
    return keys


def _twin_texts(text: str) -> set[str]:
    """Item texts that occur more than once in `text`'s checkbox items (identical twins)."""
    raw = text.splitlines()
    seen: dict[str, int] = {}
    for t in tokenize(text):
        if t["type"] != "checkbox":
            continue
        m = _CHECKBOX_RE.match(raw[t["line"] - 1].lstrip())
        if m and m.group(2).strip():
            seen[m.group(2).strip()] = seen.get(m.group(2).strip(), 0) + 1
    return {k for k, n in seen.items() if n > 1}


def worktree_claims(wt_tasks: str, wt_backlog: str | None, base_backlog: str | None) -> set[str]:
    """Item keys one worktree has claimed — pure, so the rule is testable without git.

    (a) a line under that worktree's `tasks.md` `## Covers`, keyed with its h1 block's title;
    (b) a line present in `backlog.md`
    at the worktree's merge-base but gone from the worktree's own `backlog.md` — this keeps the
    claim alive after cleanup has pruned both files but before merge. A line added to base after
    the worktree branched is absent from the merge-base, so (b) never claims it. Either backlog
    side missing disables (b): an unreadable file is not "every line deleted".

    Identical item text in two groups is told apart per group: a (b) text that occurs more than
    once at the merge-base is keyed with its heading, so deleting one twin claims only that one
    and the surviving twin does not mask the deletion. A text occurring once keeps its bare key.
    `mark_claimed` honours a qualified key's group only for a text that is a twin in the
    backlog being scanned and has a copy under that group; any other qualified key (a text
    occurring once, or a group holding no copy — e.g. an h1 titled for one heading that covers
    lines from several) matches the text in any group.

    A line the worktree reworded (e.g. a blocked-marker sync) also reads as deleted, so its
    original text counts as claimed until that worktree merges. That errs toward skipping, the
    safe side: a double-picked item costs a duplicate cycle, a skipped one waits one merge.
    """
    claimed = item_keys(wt_tasks, under="Covers", qualify=True)
    if wt_backlog is not None and base_backlog is not None:
        twins = _twin_texts(base_backlog)
        claimed |= item_keys(base_backlog, qualify=twins) - item_keys(wt_backlog, qualify=twins)
    return claimed


def block_claims(wt_tasks: str, base_tasks: str | None = None) -> set[str]:
    """h1 titles of `open` blocks one worktree has taken.

    Phase A blocks carry no checkbox to claim: another run holds one by flipping the same h1 to
    `status: active` (or beyond) in its own tasks.md. A block with no status line is not held.
    With `base_tasks` (tasks.md at the worktree's merge-base), only a block that was `open` there
    counts, and it counts while flipped or deleted: a status inherited from base, or a new block
    that only shares a title (a backlog group's `# <heading>`), took nothing; a block cleanup's
    `prune-tasks` removed stays held until merge, as (b) in `worktree_claims` keeps a pruned line.
    Without it (merge-base unknown), every non-open block counts, erring toward skipping.
    """
    blocks = h1_blocks(tokenize(wt_tasks))
    held = {h["title"] for h, status in blocks if status not in (None, "open")}
    if base_tasks is None:
        return held
    was_open = {h["title"] for h, status in h1_blocks(tokenize(base_tasks)) if status == "open"}
    still_open = {h["title"] for h, status in blocks if status == "open"}
    present = {h["title"] for h, _ in blocks}
    return (was_open & (held - still_open)) | (was_open - present)


def _git(cwd: str, *args: str) -> str | None:
    try:
        # utf-8, not the locale: on a cp949 Windows host the default decode of a Korean backlog
        # raises, which `--ref` would then report as a missing file
        r = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def _read_optional(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _repo_rel(path: str, top: str) -> str:
    """`path` relative to the repo top, by its own name: only the directory is resolved through
    symlinks (to match `top`), so a symlinked queue file is looked up where it lives, not at its
    link target."""
    directory = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    return os.path.relpath(os.path.join(directory, os.path.basename(path)), os.path.realpath(top))


def _claimants(listing: str, top: str, include_self: bool) -> list[str]:
    """Worktrees whose claims count: every other `.worktrees/` one, plus (include_self) this
    checkout and the main worktree. `top` is the realpath of this checkout's top level."""
    claimants = [
        wt
        for wt in (ln[len("worktree "):] for ln in listing.splitlines() if ln.startswith("worktree "))
        if "/.worktrees/" in wt and os.path.isdir(wt) and os.path.realpath(wt) != top
    ]
    if include_self:
        # this checkout, and the main worktree (first listed) when run from a linked one
        main_wt = next((ln[len("worktree "):] for ln in listing.splitlines() if ln.startswith("worktree ")), None)
        claimants.append(top)
        if main_wt and os.path.isdir(main_wt) and os.path.realpath(main_wt) != top:
            claimants.append(main_wt)
    return claimants


def collect_block_claims(
    backlog_path: str, tasks_path: str | None, include_self: bool = False, ref: str = "HEAD"
) -> dict[str, set[str]]:
    """{worktree path: h1 titles of `open` blocks it took} — Phase A's counterpart of
    `collect_claims`: same claimant set, repo-relative tasks.md path and merge-base against `ref`."""
    repo = os.path.dirname(os.path.abspath(backlog_path))
    top = _git(repo, "rev-parse", "--show-toplevel")
    listing = _git(repo, "worktree", "list", "--porcelain")
    if top is None or listing is None:
        return {}
    top = os.path.realpath(top.strip())
    tasks_rel = (
        _repo_rel(tasks_path, top)
        if tasks_path
        else os.path.join(os.path.dirname(_repo_rel(backlog_path, top)), "tasks.md")
    )
    claims: dict[str, set[str]] = {}
    for wt in _claimants(listing, top, include_self):
        base_tasks = None
        wt_head = _git(wt, "rev-parse", "HEAD")
        mb = _git(repo, "merge-base", ref, wt_head.strip()) if wt_head else None
        if mb:
            # absent at the merge-base → no open block there → "" (nothing to take)
            base_tasks = _git(repo, "show", f"{mb.strip()}:{tasks_rel.replace(os.sep, '/')}") or ""
        titles = block_claims(_read_optional(os.path.join(wt, tasks_rel)) or "", base_tasks)
        if titles:
            claims[wt] = titles
    return claims


def mark_claimed_blocks(
    tasks_tokens: list[dict], claims: dict[str, set[str]]
) -> dict[str, list[int]]:
    """Tag each `status: open` h1 block another worktree holds with `claimed_by`; return lines."""
    counts: dict[str, list[int]] = {}
    for h, status in h1_blocks(tasks_tokens):
        if status != "open":
            continue
        for wt, titles in claims.items():
            if h["title"] in titles:
                h["claimed_by"] = wt
                counts.setdefault(wt, []).append(h["line"])
                break
    return counts


def collect_claims(
    backlog_path: str, tasks_path: str | None, ref: str = "HEAD", include_self: bool = False
) -> dict[str, set[str]]:
    """{worktree path (as git lists it): claimed item keys} for every OTHER `.worktrees/` worktree.

    Same `/.worktrees/` test as task-next's working tree gate; any other linked worktree is not a
    task cycle and is ignored, as is the worktree this script runs in. Files are read at the same
    repo-relative paths as `--backlog`/`--tasks`, from the worktree's working tree (cleanup is
    uncommitted). The merge-base is taken against `ref` — this checkout's HEAD by default, the
    base a candidate run sits on, or the `--ref` base a `--tree` run selects from (HEAD may then
    be an unrelated feature branch). Not a git repo, or git unavailable → no claims, never an error.

    `include_self` (set with `--ref`) also counts this checkout — and the main worktree, when this
    one is linked — as a claimant, by the same rule:
    a `--tree` run selects past it, so a non-`--tree` cycle in progress here (its `## Covers`, or
    the backlog lines it pruned, committed or not) must still hold its items.
    """
    repo = os.path.dirname(os.path.abspath(backlog_path))
    top = _git(repo, "rev-parse", "--show-toplevel")
    listing = _git(repo, "worktree", "list", "--porcelain")
    if top is None or listing is None:
        return {}
    top = os.path.realpath(top.strip())
    backlog_rel = _repo_rel(backlog_path, top)
    tasks_rel = (
        _repo_rel(tasks_path, top)
        if tasks_path
        else os.path.join(os.path.dirname(backlog_rel), "tasks.md")
    )
    claimants = _claimants(listing, top, include_self)
    claims: dict[str, set[str]] = {}
    for wt in claimants:
        wt_tasks = _read_optional(os.path.join(wt, tasks_rel)) or ""
        wt_backlog = _read_optional(os.path.join(wt, backlog_rel))
        base_backlog = None
        wt_head = _git(wt, "rev-parse", "HEAD")
        mb = _git(repo, "merge-base", ref, wt_head.strip()) if wt_head else None
        if mb:
            base_backlog = _git(repo, "show", f"{mb.strip()}:{backlog_rel.replace(os.sep, '/')}")
        keys = worktree_claims(wt_tasks, wt_backlog, base_backlog)
        if keys:
            claims[wt] = keys
    return claims


def mark_claimed(
    backlog_raw: str, backlog_tokens: list[dict], claims: dict[str, set[str]]
) -> dict[str, list[int]]:
    """Tag each open backlog item a worktree claimed with `claimed_by`; return its line numbers.

    Tagged items drop out of every selector and the zero-candidate diagnosis names them. A key
    claimed by two worktrees is attributed to the first one listed. A group-qualified key
    claims only the item under that heading (see `worktree_claims`). The lines matter, not just a
    count: a group can be partly claimed, and the caller reads the group's lines straight from
    backlog.md in Steps 2-3, so it needs to know which of them to leave out.
    """
    raw = backlog_raw.splitlines()
    # every checkbox's group, so a key's group only matters for a text that is really a twin
    groups_of: dict[str, list[str | None]] = {}
    g = None
    for t in backlog_tokens:
        if t["type"] == "heading" and t["level"] in (1, 2, 3):
            g = t["title"]
        elif t["type"] == "checkbox":
            m = _CHECKBOX_RE.match(raw[t["line"] - 1].lstrip())
            if m:
                groups_of.setdefault(m.group(2).strip(), []).append(g)
    counts: dict[str, list[int]] = {}
    group = None
    for t in backlog_tokens:
        if t["type"] == "heading" and t["level"] in (1, 2, 3):
            group = t["title"]
            continue
        if t["type"] != "checkbox" or t["state"] != " ":
            continue
        m = _CHECKBOX_RE.match(raw[t["line"] - 1].lstrip())
        text = m.group(2).strip() if m else None
        for wt, keys in claims.items():
            # A key's group narrows the match only for a twin (text under 2+ headings) AND only when
            # some copy sits under that group; otherwise the group is unplaceable (a Phase A h1
            # title, or a block titled for one heading that covers lines from several) and the
            # text matches anywhere — the err-toward-skipping side.
            if any(
                kt == text
                and (
                    kg is None
                    or len(groups_of.get(kt, ())) < 2
                    or kg == group
                    or kg not in groups_of.get(kt, ())
                )
                for kg, kt in map(_split_key, keys)
            ):
                t["claimed_by"] = wt
                counts.setdefault(wt, []).append(t["line"])
                break
    return counts


def claimed_skip_note(
    claimed: dict[str, list[int]], top: str | None = None, label: str = "backlog.md",
    what: str = "item(s)", tail: str = " — leave these lines out of scope even when their group is selected",
) -> str | None:
    """One stderr line naming every skipped item as `<label>:<line>`, grouped per worktree."""
    if not claimed:
        return None

    def _name(wt: str) -> str:
        if not top:
            return wt
        rel = os.path.relpath(os.path.realpath(wt), os.path.realpath(top))
        return "this checkout" if rel == "." else rel

    per = "; ".join(
        f"{len(lines)} by {_name(wt)} ({', '.join(f'{label}:{n}' for n in lines)})"
        for wt, lines in claimed.items()
    )
    total = sum(len(v) for v in claimed.values())
    return (
        f"Skipped {total} {what} claimed by in-flight worktrees: {per}{tail}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_file(path: str | None, *, required: bool = False) -> str:
    """Read `path`, or return "" if absent — matching the `2>/dev/null` grep fallback
    this script replaces. `required=True` (backlog.md) treats a missing/unreadable file
    as fatal instead of silently returning "" — tasks.md stays optional (required=False),
    per task-next' own "absent in the idle state" semantics.
    """
    if not path:
        if required:
            sys.stderr.write("Error: --backlog PATH is required\n")
            sys.exit(1)
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as e:
        if required:
            sys.stderr.write(f"Error: could not read required file {path}: {e}\n")
            sys.exit(1)
        return ""


def _read_at_ref(path: str | None, ref: str, *, required: bool = False) -> str:
    """`_read_file` for `--ref`: `path` as committed at `ref`, resolved repo-relative from the
    checkout holding it. Absent at `ref` → "" (tasks.md is optional), or fatal when `required`."""
    if not path:
        return _read_file(path, required=required)
    repo = os.path.dirname(os.path.abspath(path))
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top is None or _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is None:
        sys.stderr.write(f"Error: --ref {ref} does not resolve to a commit in a git checkout of {path}\n")
        sys.exit(1)
    rel = _repo_rel(path, top.strip())
    out = _git(repo, "show", f"{ref}:{rel.replace(os.sep, '/')}")
    if out is None and required:
        sys.stderr.write(f"Error: {rel} does not exist at {ref}\n")
        sys.exit(1)
    return out or ""


def main(argv: list[str]) -> int:
    if "--test" in argv:
        return run_tests()

    tasks_path = None
    backlog_path = None
    ref = None
    full_scan_flag = False
    json_flag = False
    parked_flag = False

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--tasks", "--backlog", "--ref") and i + 1 >= len(argv):
            sys.stderr.write(f"Error: {a} requires an argument\n")
            sys.exit(1)
        if a == "--tasks":
            tasks_path = argv[i + 1]
            i += 2
        elif a == "--backlog":
            backlog_path = argv[i + 1]
            i += 2
        elif a == "--ref":
            ref = argv[i + 1]
            i += 2
        elif a == "--full-scan":
            full_scan_flag = True
            i += 1
        elif a == "--json":
            json_flag = True
            i += 1
        elif a == "--parked":
            parked_flag = True
            i += 1
        else:
            i += 1

    if ref is None:
        tasks_raw = _read_file(tasks_path)
        backlog_raw = _read_file(backlog_path, required=True)
    else:
        tasks_raw = _read_at_ref(tasks_path, ref)
        backlog_raw = _read_at_ref(backlog_path, ref, required=True)
    tasks_tokens = tokenize(tasks_raw)
    backlog_tokens = tokenize(backlog_raw)

    # Unbalanced-fence warning, emitted even when candidates WERE found. A stray odd ``` blanks
    # everything after it, which can hide part of the queue while other groups still surface — so
    # gating this on a zero result would miss the partial case entirely, and `zero_candidate_
    # diagnosis` cannot see it either (the swallowed headings never become tokens). stderr keeps
    # `--json` stdout machine-parseable, same split the diagnosis already uses.
    for label, raw in ((tasks_path or "tasks.md", tasks_raw), (backlog_path or "backlog.md", backlog_raw)):
        n = unclosed_fence_line(raw)
        if n is not None:
            sys.stderr.write(
                f"Warning: unbalanced fence opened at line {n} in {label} — everything after it "
                "was treated as code and is not selectable. Close or remove the fence.\n"
            )

    # Migration warning, emitted even when candidates WERE found. tasks.md no longer contributes
    # anything but h1 sprint blocks, so a leftover findings section is real queued work that this
    # run cannot see — reporting it beats dropping it silently. `prune-tasks` refuses on the same
    # shape, so the two scripts agree on what needs moving.
    stale = tasks_persistent_sections(tasks_tokens)
    if stale:
        shown = ", ".join(f"{s['title']!r} (line {s['line']})" for s in stale[:3])
        more = f", +{len(stale) - 3} more" if len(stale) > 3 else ""
        sys.stderr.write(
            f"Warning: {tasks_path or 'tasks.md'} holds {len(stale)} persistent section(s) that "
            f"belong in backlog.md — {shown}{more}. tasks.md is the Sprint Contract only and is "
            "deleted at sprint close; move these to backlog.md verbatim or they will be lost and "
            "are not selectable here.\n"
        )

    if parked_flag:
        parked = parked_items(backlog_path or "backlog.md", backlog_tokens)
        if json_flag:
            print(json.dumps(parked))
        else:
            for line in format_parked(parked):
                print(line)
        if not parked:
            sys.stderr.write("No open item carries a blocked/deferred marker.\n")
        return 0

    # Claimed items: another `.worktrees/` run already holds them, so selecting one here would start
    # a duplicate cycle. Named on stderr even when candidates remain, so the skip is never silent.
    if backlog_path:  # always true past _read_file(required=True); narrows the type
        counts = mark_claimed(
            backlog_raw,
            backlog_tokens,
            collect_claims(backlog_path, tasks_path, ref or "HEAD", include_self=ref is not None),
        )
        top = _git(os.path.dirname(os.path.abspath(backlog_path)), "rev-parse", "--show-toplevel")
        label = f"{ref}:{backlog_path}" if ref else backlog_path  # line numbers are the ref's
        note = claimed_skip_note(counts, top.strip() if top else None, label)
        if note is not None:
            sys.stderr.write(note + "\n")

    # Phase A blocks: another run holds one by flipping the same h1 to a non-open status in its own
    # tasks.md, so a block still `open` here is a duplicate cycle waiting to happen.
    if tasks_path and backlog_path:
        block_counts = mark_claimed_blocks(
            tasks_tokens, collect_block_claims(
                backlog_path, tasks_path, include_self=ref is not None, ref=ref or "HEAD"
            )
        )
        top = _git(os.path.dirname(os.path.abspath(backlog_path)), "rev-parse", "--show-toplevel")
        label = f"{ref}:{tasks_path}" if ref else tasks_path
        note = claimed_skip_note(
            block_counts, top.strip() if top else None, label, what="sprint block(s)",
            tail=" — another run already took them; do not select",
        )
        if note is not None:
            sys.stderr.write(note + "\n")

    candidates = full_scan(tasks_tokens, backlog_tokens) if full_scan_flag else fast_path(tasks_tokens, backlog_tokens)

    # Truncation signal — fast-path mode only, never with --full-scan (which is already the
    # uncapped total, so shown == total there and the note would be a no-op anyway). Reuses the
    # tasks_tokens/backlog_tokens already parsed above — no extra file I/O.
    if not full_scan_flag:
        total = len(full_scan(tasks_tokens, backlog_tokens))
        note = truncation_note(len(candidates), total)
        if note is not None:
            sys.stderr.write(note + "\n")

    if json_flag:
        print(json.dumps(candidates))
    else:
        for line in format_candidates(candidates):
            print(line)

    # Zero candidates is ambiguous — say which kind of empty this is, on stderr so `--json`
    # stdout stays machine-parseable. Exit code stays 0: an empty queue is not an error.
    if not candidates:
        for line in zero_candidate_diagnosis(tasks_tokens, backlog_tokens):
            sys.stderr.write(line + "\n")
    return 0


# ---------------------------------------------------------------------------
# Self-check (--test) — never touches real files
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


def _test_claimed_items() -> None:
    """Temp-repo fixtures for `collect_claims` — the only test that touches real files (a tempdir)."""
    import tempfile

    # Strip the ambient repo selectors and fence discovery at the temp root (as task_nodes.py's
    # fixtures do): run from a git hook, an inherited GIT_DIR would point every `git -C <tmp>`
    # call — the fixture's commits and collect_claims' own queries — at the real repository.
    selectors = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
    env = {k: v for k, v in os.environ.items() if k not in selectors}
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": os.path.realpath(tempfile.gettempdir()),
    })
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)  # collect_claims/_git run in-process and inherit os.environ
    try:
        _run_claimed_fixtures(env)
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _run_claimed_fixtures(env: dict[str, str]) -> None:
    import tempfile

    def git(cwd: str, *args: str) -> None:
        subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, env=env)

    def write(path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        base = "## Queue\n\n- [ ] item A\n- [ ] item B\n- [ ] item C\n- [ ] item D\n  wrapped tail\n"
        write(os.path.join(repo, "backlog.md"), base)
        git(repo, "add", "backlog.md")
        git(repo, "commit", "-q", "-m", "seed")

        # (a) claim via `## Covers` in the worktree's tasks.md
        wt1 = os.path.join(repo, ".worktrees", "wt1")
        git(repo, "worktree", "add", "-q", "-b", "b1", wt1)
        write(os.path.join(wt1, "tasks.md"), "# A sprint\nstatus: active\n\n## Covers\n\n- [ ] item A\n")
        # (b) claim via a backlog line deleted (uncommitted) relative to merge-base
        wt2 = os.path.join(repo, ".worktrees", "wt2")
        git(repo, "worktree", "add", "-q", "-b", "b2", wt2)
        write(os.path.join(wt2, "backlog.md"), base.replace("- [ ] item B\n", ""))
        # a non-`.worktrees/` worktree claiming C via Covers must be ignored
        other = os.path.join(tmp, "elsewhere")
        git(repo, "worktree", "add", "-q", "-b", "b3", other)
        write(os.path.join(other, "tasks.md"), "# C sprint\n\n## Covers\n\n- [ ] item C\n")
        # a line added to base AFTER the worktrees branched: absent from wt2's backlog and from the
        # merge-base, so it must NOT read as deleted by wt2
        write(os.path.join(repo, "backlog.md"), base + "- [ ] item E\n")
        git(repo, "commit", "-q", "-am", "add E")

        backlog = os.path.join(repo, "backlog.md")
        claims = collect_claims(backlog, None)
        by_name = {os.path.basename(k): v for k, v in claims.items()}
        _assert(by_name.get("wt1") == {_qkey("A sprint", "item A")}, "a `## Covers` line in a .worktrees/ tasks.md is claimed")
        _assert(by_name.get("wt2") == {"item B"}, "a backlog line deleted relative to merge-base is claimed")
        _assert("elsewhere" not in by_name, "a worktree outside .worktrees/ claims nothing")
        _assert(
            all("item E" not in v for v in claims.values()),
            "a line added to base after branching is not claimed",
        )

        raw = open(backlog, encoding="utf-8").read()
        tokens = tokenize(raw)
        counts = mark_claimed(raw, tokens, claims)
        got = full_scan([], tokens)
        _assert(
            [(c["title"], c["items"]) for c in got] == [("Queue", 3)],
            "claimed items drop out of the count: C, D (wrapped) and E remain",
        )
        _assert(
            sorted(n for lines in counts.values() for n in lines) == [3, 4],
            "the skip covers exactly the claimed open items, by line",
        )

        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--backlog", backlog],
            capture_output=True, text=True, cwd=repo, env=env,
        )
        fwd = backlog.replace(os.sep, "/")
        _assert(
            "Skipped 2 item(s) claimed by in-flight worktrees:" in r.stderr.replace(os.sep, "/")
            and f"1 by .worktrees/wt1 ({fwd}:3)" in r.stderr.replace(os.sep, "/")
            and f"1 by .worktrees/wt2 ({fwd}:4)" in r.stderr.replace(os.sep, "/"),
            "the CLI names each skipped line per worktree on stderr, so a partly claimed group "
            "can be scoped",
        )
        _assert(r.stdout.strip() == "[1] backlog.md: Queue (3 items)", "stdout lists only unclaimed items")

        # every open item claimed → the zero-candidate diagnosis says claimed, not "all done"
        all_claimed = "## Queue\n\n- [ ] item A\n"
        t2 = tokenize(all_claimed)
        mark_claimed(all_claimed, t2, {"/x/.worktrees/wt1": {"item A"}})
        diag = "\n".join(zero_candidate_diagnosis([], t2))
        _assert(
            "1 open item(s) claimed by another `.worktrees/` run" in diag and "all `[x]`" not in diag
            and "parked" not in diag,
            "an all-claimed backlog is diagnosed as claimed, not done or parked",
        )

        # --ref: a `--tree` run selects from the base while this checkout sits on an unrelated
        # feature branch with uncommitted queue edits. wt4 branched from main after "add E" and
        # pruned E; this checkout is on `side`, cut from the seed commit, which never had E.
        wt4 = os.path.join(repo, ".worktrees", "wt4")
        git(repo, "worktree", "add", "-q", "-b", "b4", wt4, "main")
        write(os.path.join(wt4, "backlog.md"), base)  # base + E, minus E
        git(repo, "checkout", "-q", "-b", "side", "HEAD~1")
        write(backlog, base + "- [ ] item F uncommitted\n")
        _assert(
            all("item E" not in v for v in collect_claims(backlog, None).values()),
            "default merge-base against HEAD (a branch without E) loses wt4's prune claim",
        )
        _assert(
            {os.path.basename(k): v for k, v in collect_claims(backlog, None, "main").items()}.get("wt4")
            == {"item E"},
            "--ref main takes the merge-base against main, so wt4's pruned E stays claimed",
        )
        # a non-`--tree` cycle in this checkout claims C through its own uncommitted tasks.md
        write(os.path.join(repo, "tasks.md"), "# C sprint\nstatus: active\n\n## Covers\n\n- [ ] item C\n")
        _assert(
            "item C" not in collect_claims(backlog, None, "main").get(os.path.realpath(repo), set()),
            "without include_self this checkout claims nothing (default runs sit in it)",
        )
        _assert(
            collect_claims(backlog, None, "main", include_self=True).get(os.path.realpath(repo))
            == {_qkey("C sprint", "item C")},
            "include_self counts this checkout's `## Covers` as a claim",
        )
        from_wt1 = collect_claims(os.path.join(wt1, "backlog.md"), None, "main", include_self=True)
        _assert(
            {os.path.basename(k.rstrip("/\\")): v for k, v in from_wt1.items()}.get("repo") == {_qkey("C sprint", "item C")},
            "run from a linked worktree, include_self also counts the main worktree's claims",
        )
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--backlog", backlog, "--ref", "main"],
            capture_output=True, text=True, cwd=repo, env=env,
        )
        _assert(
            r.returncode == 0 and r.stdout.strip() == "[1] backlog.md: Queue (1 items)",
            "--ref reads backlog.md as committed at main: the uncommitted F is invisible and A, B, "
            f"C (this checkout), E are claimed (got {r.stdout.strip()!r} / {r.stderr.strip()!r})",
        )
        _assert("1 by this checkout" in r.stderr, "the skip line names this checkout as a claimant")
        _assert(f"main:{backlog}:" in r.stderr, "the skip line labels lines with the ref they index")
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--backlog", backlog, "--ref", "no-such-ref"],
            capture_output=True, text=True, cwd=repo, env=env,
        )
        _assert(r.returncode == 1 and "--ref no-such-ref" in r.stderr, "an unresolvable --ref is fatal")

        _run_claim_extension_fixtures(tmp, env)

        nonrepo = os.path.join(tmp, "plain")
        os.makedirs(nonrepo)
        write(os.path.join(nonrepo, "backlog.md"), base)
        _assert(collect_claims(os.path.join(nonrepo, "backlog.md"), None) == {}, "outside a git repo there are no claims")


def _run_claim_extension_fixtures(tmp: str, env: dict[str, str]) -> None:
    """Twin attribution, Phase A block claims, symlinked queue at --ref, utf-8 pin — own repo."""

    def git(cwd: str, *args: str) -> None:
        subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, env=env)

    def write(path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    # a block titled for ONE heading that covers lines from several must claim them all, and a
    # covered twin whose copies are not under that title is claimed in both places
    multi = "## Alpha\n\n- [ ] a1\n\n## Beta\n\n- [ ] b1\n- [ ] dup\n\n## Gamma\n\n- [ ] g1\n- [ ] dup\n"
    cov_tasks = "# Alpha\nstatus: active\n\n## Covers\n\n- [ ] a1\n- [ ] b1\n- [ ] g1\n- [ ] dup\n"
    mtoks = tokenize(multi)
    mcounts = mark_claimed(multi, mtoks, {"/x/.worktrees/w": worktree_claims(cov_tasks, None, None)})
    _assert(
        sorted(n for ls in mcounts.values() for n in ls) == [3, 7, 8, 12, 13],
        "a `# Alpha` block covering Alpha, Beta and Gamma lines claims them all, twin in both places",
    )

    repo = os.path.join(tmp, "repo2")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    base = "## G1\n\n- [ ] twin\n- [ ] solo\n\n## G2\n\n- [ ] twin\n"
    backlog = os.path.join(repo, "backlog.md")
    tasks = os.path.join(repo, "tasks.md")
    write(backlog, base)
    sprints = "# Sprint X\nstatus: open\n\n# Sprint Y\nstatus: open\n"
    write(tasks, sprints)
    git(repo, "add", "backlog.md", "tasks.md")
    git(repo, "commit", "-q", "-m", "seed")

    wt_cov = os.path.join(repo, ".worktrees", "cov")
    git(repo, "worktree", "add", "-q", "-b", "c1", wt_cov)
    # a backlog-group claim appends its own h1 block to the tracked tasks.md
    write(os.path.join(wt_cov, "tasks.md"), sprints + "\n# G2\nstatus: active\n\n## Covers\n\n- [ ] twin\n")
    wt_del = os.path.join(repo, ".worktrees", "del")
    git(repo, "worktree", "add", "-q", "-b", "c2", wt_del)
    write(os.path.join(wt_del, "backlog.md"), base.replace("## G1\n\n- [ ] twin\n", "## G1\n\n", 1))
    wt_blk = os.path.join(repo, ".worktrees", "blk")
    git(repo, "worktree", "add", "-q", "-b", "c3", wt_blk)
    write(os.path.join(wt_blk, "tasks.md"), "# Sprint X\nbody\nstatus: active\n\n# Sprint Y\nstatus: open\n")

    claims = collect_claims(backlog, None)
    by_name = {os.path.basename(k): v for k, v in claims.items()}
    raw = open(backlog, encoding="utf-8").read()

    def claimed_lines(only: str) -> list[int]:
        toks = tokenize(raw)
        return sorted(n for ls in mark_claimed(raw, toks, {only: by_name[only]}).values() for n in ls)

    _assert(claimed_lines("cov") == [8], "a Covers claim on G2's twin hides G2's copy only, not G1's twin")
    _assert(
        claimed_lines("del") == [3],
        "deleting G1's twin claims G1's copy; G2's surviving twin does not mask the deletion",
    )

    block = collect_block_claims(backlog, tasks)
    _assert(
        {os.path.basename(k): v for k, v in block.items()} == {"blk": {"Sprint X"}},
        "a block open at the merge-base and flipped in another worktree is a block claim; "
        "a new active block (a backlog group's `# G2`) takes no sprint block",
    )
    base_t = "# A\nstatus: open\n\n# B\nstatus: deferred\n\n# C\nstatus: open\n"
    _assert(
        not block_claims(base_t + "\n# New group\nstatus: active\n\n## Covers\n- [ ] new item\n", base_t),
        "appending an active backlog claim block preserves every inherited open sprint",
    )
    _assert(
        not block_claims(base_t + "\n# A\nstatus: active\n\n## Covers\n- [ ] new item\n", base_t),
        "an appended backlog claim does not claim the open sprint with the same title",
    )
    _assert(
        block_claims("# A\nstatus: active\n\n# B\nstatus: deferred\n", base_t) == {"A", "C"},
        "flipped (A) and pruned (C) open blocks are held; B's inherited `deferred` is not",
    )
    _assert(
        block_claims("# B\nstatus: deferred\n") == {"B"},
        "with the merge-base unknown every non-open block counts, erring toward skipping",
    )
    toks = tokenize(open(tasks, encoding="utf-8").read())
    counts = mark_claimed_blocks(toks, block)
    _assert(
        [c["title"] for c in phase_a_candidates(toks)] == ["Sprint Y"] and list(counts.values()) == [[1]],
        "a Phase A open block another worktree took is skipped; the untouched one stays",
    )
    r = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--tasks", tasks, "--backlog", backlog],
        capture_output=True, text=True, cwd=repo, env=env,
    )
    _assert(
        "Skipped 1 sprint block(s) claimed by in-flight worktrees: 1 by .worktrees" in r.stderr and "blk (" in r.stderr
        and f"{tasks}:1" in r.stderr and "Sprint X" not in r.stdout and "Sprint Y" in r.stdout,
        f"the CLI names the skipped sprint block on stderr (got {r.stdout!r} / {r.stderr!r})",
    )

    # --ref with a symlinked backlog: the working-tree path is a link to a file outside the repo,
    # but the ref holds a regular backlog.md. Looked up by its own repo-relative name, not target.
    outside = os.path.join(tmp, "outside")
    os.makedirs(outside)
    write(os.path.join(outside, "shared.md"), "## Real\n\n- [ ] at ref\n")
    link_repo = os.path.join(tmp, "repo3")
    os.makedirs(link_repo)
    git(link_repo, "init", "-q", "-b", "main")
    write(os.path.join(link_repo, "backlog.md"), "## Real\n\n- [ ] at ref\n")
    git(link_repo, "add", "backlog.md")
    git(link_repo, "commit", "-q", "-m", "seed")
    os.remove(os.path.join(link_repo, "backlog.md"))
    try:
        os.symlink(os.path.join(outside, "shared.md"), os.path.join(link_repo, "backlog.md"))
    except (OSError, NotImplementedError, AttributeError):
        print("  SKIP: symlinks unavailable here — --ref symlink fixture not run")
    else:
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--backlog", os.path.join(link_repo, "backlog.md"),
             "--ref", "main"],
            capture_output=True, text=True, cwd=link_repo, env=env,
        )
        _assert(
            r.returncode == 0 and r.stdout.strip() == "[1] backlog.md: Real (1 items)",
            f"--ref reads a symlinked backlog.md at its repo-relative path (got {r.stdout!r} / {r.stderr!r})",
        )

    # utf-8 pin: a Korean line committed at the ref must survive `git show`. subprocess.run is shimmed
    # so any call that does not ask for utf-8 decodes as ascii strictly — what a cp949 or C locale
    # would do to these bytes — and Linux CI's utf-8 locale cannot mask a dropped `encoding=`.
    ko_repo = os.path.join(tmp, "repo4")
    os.makedirs(ko_repo)
    git(ko_repo, "init", "-q", "-b", "main")
    korean = "## 한국어\n\n- [ ] 항목 하나\n"
    write(os.path.join(ko_repo, "backlog.md"), korean)
    git(ko_repo, "add", "backlog.md")
    git(ko_repo, "commit", "-q", "-m", "seed")
    real_run = subprocess.run

    def shim(*args, **kwargs):  # type: ignore[no-untyped-def]
        if str(kwargs.get("encoding", "")).lower().replace("-", "") != "utf8":
            kwargs["encoding"], kwargs["errors"] = "ascii", "strict"
        return real_run(*args, **kwargs)

    subprocess.run = shim  # type: ignore[assignment]
    try:
        try:
            got = _read_at_ref(os.path.join(ko_repo, "backlog.md"), "main", required=True)
        except (UnicodeDecodeError, SystemExit):  # a failed decode surfaces as "absent at ref"
            got = None
    finally:
        subprocess.run = real_run  # type: ignore[assignment]
    _assert(got is not None and got.replace("\r\n", "\n") == korean, "git show output decodes as utf-8 whatever the locale")


def run_tests() -> int:
    global PASS_COUNT, FAIL_COUNT
    PASS_COUNT = 0
    FAIL_COUNT = 0

    print("=== backlog_candidates.py --test ===\n")

    # ---- Test 1: status-line-gap case (Phase A) ----
    print("Test 1: phase_a_candidates — status line separated from h1 by body content")
    tasks_gap = """# Sprint one

Some body prose here.
More context about the sprint.

status: open

## Review Backlog
"""
    tokens = tokenize(tasks_gap)
    result = phase_a_candidates(tokens)
    _assert(
        result == [{"source": "tasks.md", "kind": "h1", "title": "Sprint one", "line": 1, "items": None}],
        "status: open several lines after h1 still matches (gap case)",
    )

    tasks_gap_active = """# Sprint two

status: active
"""
    result = phase_a_candidates(tokenize(tasks_gap_active))
    _assert(result == [], "status: active h1 is not a candidate")

    tasks_two_h1 = """# Sprint A
status: done

# Sprint B
some body
status: open
"""
    result = phase_a_candidates(tokenize(tasks_two_h1))
    _assert(
        [c["title"] for c in result] == ["Sprint B"],
        "status line correctly bound to nearest h1 (not leaking across the next h1 boundary)",
    )

    # ---- Test 2: direct-items heading-boundary case ----
    print("\nTest 2: direct-items boundary — nested h3 item must not count toward h2 parent")
    nested = """## Parent
### Child
- [ ] child item
"""
    tokens = tokenize(nested)
    headings = _headings(tokens)
    parent = next(h for h in headings if h["title"] == "Parent")
    child = next(h for h in headings if h["title"] == "Child")
    parent_items = _direct_open_items(tokens, parent, headings)
    child_items = _direct_open_items(tokens, child, headings)
    _assert(parent_items == [], "item after nested h3 does not count toward h2 parent")
    _assert(len(child_items) == 1, "item after nested h3 counts toward the h3 itself")

    fast = backlog_fast_candidates(tokens)
    _assert(
        [c["title"] for c in fast] == ["Child"],
        "Parent excluded (0 direct items), Child included (1 direct item)",
    )

    # ---- Test 3: all-parked-skip case ----
    print("\nTest 3: all-parked-skip — every item [x]/[>] under a heading is not a candidate")
    parked = """## Parked group
- [x] done item
- [>] deferred item
"""
    tokens = tokenize(parked)
    result = backlog_fast_candidates(tokens)
    _assert(result == [], "heading with only [x]/[>] items is not a candidate")

    mixed = """## Mixed group
- [x] done item
- [ ] open item
"""
    tokens = tokenize(mixed)
    result = backlog_fast_candidates(tokens)
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Mixed group", "line": 1, "items": 1}],
        "heading with >=1 open item alongside parked items is a candidate, counting only open items",
    )

    # ---- Test 3b: blocked/deferred-marker exclusion ----
    print("\nTest 3b: blocked/deferred-marker exclusion — generalizes the [>] skip to inline markers")
    all_deferred = """## Deferred group
- [ ] item one *(deferred: waiting on infra)*
- [ ] item two *(deferred: waiting on infra)*
"""
    tokens = tokenize(all_deferred)
    result = backlog_fast_candidates(tokens)
    _assert(result == [], "heading whose only open items are ALL *(deferred: ...)* is not a candidate")

    all_blocked = """## Blocked group
- [ ] item one *(blocked by: 3-add-auth)*
"""
    tokens = tokenize(all_blocked)
    result = backlog_fast_candidates(tokens)
    _assert(result == [], "heading whose only open item is *(blocked by: <n>-<slug>)* is not a candidate")

    mixed_blocked = """## Mixed blocked group
- [ ] item one *(blocked by: 3-add-auth)*
- [ ] item two
"""
    tokens = tokenize(mixed_blocked)
    result = backlog_fast_candidates(tokens)
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Mixed blocked group", "line": 1, "items": 1}],
        "heading with one blocked + one unblocked open item is a candidate, counting only the unblocked item",
    )

    _assert(_is_blocked("plain item, no marker") is False, "_is_blocked is False for unmarked text")
    _assert(_is_blocked("item *(deferred: reason)*") is True, "_is_blocked is True for deferred marker")
    _assert(_is_blocked("item *(blocked by: 2-slug)*") is True, "_is_blocked is True for blocked-by marker")
    _assert(
        _is_blocked("item *(deferred: waiting on (infra) service)*") is True,
        "_is_blocked is True when the reason text has nested parens (non-greedy match, not [^)]*)",
    )
    _assert(
        _is_blocked("item quoting the `*(blocked by: <slug>)*` syntax") is False,
        "_is_blocked is False for a placeholder payload — prose about the marker parks nothing",
    )
    _assert(
        _is_blocked("template line *(blocked by: <n>-<slug>)*") is False,
        "_is_blocked is False for the `<n>-<slug>` template payload",
    )
    _assert(
        _is_blocked("item *(blocked by: <slug>)* *(blocked by: 3-add-auth)*") is True,
        "one real marker still parks an item that also quotes a placeholder one",
    )
    _assert(
        _is_blocked("item *(blocked by: 3-migrate-to-<v2>-api)*") is True,
        "REGRESSION: a real slug that merely embeds a placeholder still parks the item — the "
        "exemption is for a payload that is nothing BUT placeholders",
    )
    _assert(
        _is_blocked("item *(deferred: waiting on <team> reply)*") is True,
        "REGRESSION: the placeholder escape hatch is scoped to `blocked by` — a real deferral with "
        "angle brackets in its reason stays parked",
    )
    placeholder_prose = """## Marker docs
- [ ] [HARNESS] Warn when a pruned item is still named by a `*(blocked by: <slug>)*` marker
"""
    _assert(
        [c["title"] for c in backlog_fast_candidates(tokenize(placeholder_prose))] == ["Marker docs"],
        "an item whose prose quotes the placeholder marker is still a candidate",
    )

    # ---- Test 3b2: multi-line items — marker on a continuation line still parks the item ----
    print("\nTest 3b2: multi-line items — a marker on a wrapped item's continuation line counts")
    wrapped_deferred = """## Wrapped group
- [ ] Verify the endpoint against real traffic, then replace the whole-body substring
  match with a proper response parse and let absence mean "cancelled".
  *(deferred: needs a captured real response)*
- [ ] Confirm one real booking appears on page 0, then drop the UNVERIFIED marker
  from the doc comment. *(deferred: needs one real booking)*
"""
    tokens = tokenize(wrapped_deferred)
    result = backlog_fast_candidates(tokens)
    _assert(result == [], "heading whose wrapped open items are ALL deferred is not a candidate")

    checkboxes = [t for t in tokens if t["type"] == "checkbox"]
    _assert(len(checkboxes) == 2, "wrapped continuation lines do not create extra checkbox tokens")
    _assert(
        [t["line"] for t in checkboxes] == [2, 5],
        "a folded item keeps the line number of its FIRST line",
    )

    wrapped_mixed = """## Wrapped mixed group
- [ ] wrapped item one
  continues here *(deferred: waiting on infra)*
- [ ] wrapped item two
  continues here with no marker
"""
    tokens = tokenize(wrapped_mixed)
    result = backlog_fast_candidates(tokens)
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Wrapped mixed group", "line": 1, "items": 1}],
        "only the unmarked wrapped item counts toward the open-item total",
    )

    unindented_after = """## Boundary group
- [ ] wrapped item
  still the item
unindented prose *(deferred: not part of the item)*
"""
    tokens = tokenize(unindented_after)
    item = next(t for t in tokens if t["type"] == "checkbox")
    _assert(
        item["text"] == "wrapped item still the item",
        "an unindented following line is prose, not a lazy continuation — it is not folded in",
    )

    blank_break = """## Blank-break group
- [ ] wrapped item

  *(deferred: separated by a blank line)*
"""
    tokens = tokenize(blank_break)
    item = next(t for t in tokens if t["type"] == "checkbox")
    _assert(item["text"] == "wrapped item", "a blank line ends the item — later indented text is not folded in")

    nested_fence = """## Fenced group
- [ ] item with a fenced sample
  ```sh
  echo hi
  ```
  *(deferred: waiting on a captured response)*
"""
    tokens = tokenize(nested_fence)
    item = next(t for t in tokens if t["type"] == "checkbox")
    _assert(
        item["text"] == "item with a fenced sample *(deferred: waiting on a captured response)*",
        "an indented fenced block nested in an item does not close it — the marker after it still folds in",
    )
    _assert(
        backlog_fast_candidates(tokens) == [],
        "an item deferred after a nested fenced block is not surfaced as actionable",
    )

    nested_comment = """## Commented group
- [ ] item with a nested comment
  <!-- an aside -->
  *(deferred: waiting)*
"""
    item = next(t for t in tokenize(nested_comment) if t["type"] == "checkbox")
    _assert(
        item["text"] == "item with a nested comment *(deferred: waiting)*",
        "an indented HTML comment nested in an item does not close it either",
    )

    unindented_fence = """## Top-level fence group
- [ ] item then a top-level fence
```sh
echo hi
```
  *(deferred: not part of the item)*
"""
    item = next(t for t in tokenize(unindented_fence) if t["type"] == "checkbox")
    _assert(
        item["text"] == "item then a top-level fence",
        "an UNindented fence still ends the item — only nested (indented) blocks continue it",
    )

    # ---- Test 3c: HTML-comment stripping ----
    print("\nTest 3c: HTML comments — commented-out template markup is not a candidate")
    commented_template = """# Backlog

Ordered by priority.

<!--
## Feature Name
> Goal: what and why.

- [ ] Simplest case
- [ ] Next case builds on previous
-->

## Real group
- [ ] real item
"""
    tokens = tokenize(commented_template)
    result = backlog_fast_candidates(tokens)
    _assert(
        [c["title"] for c in result] == ["Real group"],
        "heading + items inside <!-- --> are ignored; only real content is a candidate",
    )
    _assert(
        result[0]["line"] == 13,
        "line numbers after a stripped comment are unshifted (comment blanked, not deleted)",
    )

    inline_comment = """## <!-- draft --> Live group
- [ ] item one <!-- - [ ] ghost item -->
"""
    tokens = tokenize(inline_comment)
    result = backlog_fast_candidates(tokens)
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Live group", "line": 1, "items": 1}],
        "single-line comments are stripped in place without dropping the surrounding line",
    )

    # ---- Test 3d: fenced code blocks ----
    print("\nTest 3d: fenced code blocks — headings/items inside a fence are markup, not work")

    # The finding's named fixture: a fenced `## Fake` sits BETWEEN a heading and its items. The
    # bug is not cosmetic — a fake heading truncates the enclosing region (_region_end), so the
    # real item after the fence stops counting toward `Real group` and the group silently drops.
    fenced_between = """## Real group

Some prose before the sample.

```markdown
## Fake heading in a sample
- [ ] fake item
```

- [ ] real item after the fence
"""
    tokens = tokenize(fenced_between)
    result = backlog_fast_candidates(tokens)
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Real group", "line": 1, "items": 1}],
        "a fenced `## Fake` between a heading and its items neither becomes a candidate nor "
        "truncates the real heading's region",
    )
    _assert(
        not any(t["type"] == "heading" and t["title"].startswith("Fake") for t in tokens),
        "no heading token is emitted for a `##` line inside a fence",
    )
    _assert(
        [t["line"] for t in tokens if t["type"] == "checkbox"] == [10],
        "line numbers after a stripped fence are unshifted (fence blanked, not deleted)",
    )

    tilde_and_info = """## Tilde group
~~~python
## Fake in a tilde fence
- [ ] ghost
~~~
- [ ] real item
"""
    result = backlog_fast_candidates(tokenize(tilde_and_info))
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Tilde group", "line": 1, "items": 1}],
        "`~~~` fences carrying an info string are stripped just like backtick fences",
    )

    # A closing fence must be at least as long as its opener, so the shorter inner fences here
    # do NOT close the outer one — otherwise the sample's own `## Fake` leaks back out.
    nested_fence = """## Four group
````
```
## Fake inside a shorter inner fence
```
````
- [ ] real item
"""
    result = backlog_fast_candidates(tokenize(nested_fence))
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Four group", "line": 1, "items": 1}],
        "a shorter inner fence does not close a longer outer fence",
    )

    unclosed_fence = """## Open group
- [ ] real item
```
## Fake after an unclosed fence
- [ ] ghost item
"""
    result = backlog_fast_candidates(tokenize(unclosed_fence))
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Open group", "line": 1, "items": 1}],
        "an unclosed fence blanks through EOF, so nothing after it is selectable",
    )

    # REGRESSION GUARD — a 4-space-indented ``` is an indented code block's content, not a fence
    # opener (CommonMark). Treating it as one would open an unclosed fence and silently blank the
    # rest of a real backlog.
    indented_fence = """## Indent group
    ```
- [ ] real item
"""
    result = backlog_fast_candidates(tokenize(indented_fence))
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Indent group", "line": 1, "items": 1}],
        "a 4-space-indented ``` does not open a fence, so the following item stays selectable",
    )

    # REGRESSION GUARD — comments are stripped BEFORE fences. A lone ``` parked inside a
    # commented-out doc template must not open a phantom fence that swallows the rest of the file.
    fence_inside_comment = """<!--
```
-->
## Real group
- [ ] real item
"""
    result = backlog_fast_candidates(tokenize(fence_inside_comment))
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Real group", "line": 4, "items": 1}],
        "an unbalanced ``` inside an HTML comment does not open a phantom fence",
    )

    # REGRESSION GUARD (qa-verifier) — the line-count contract must hold for EVERY input, not only
    # ones with content after the fence. The candidate/token assertions above cannot see a drop of
    # the file's LAST line (nothing follows it to be mis-numbered), so assert the raw count too.
    for label, fixture in (
        ("fenced_between", fenced_between),
        ("tilde_and_info", tilde_and_info),
        ("nested_fence", nested_fence),
        ("unclosed_fence", unclosed_fence),
        ("indented_fence", indented_fence),
        ("fence_inside_comment", fence_inside_comment),
        ("empty input", ""),
        ("nothing but an unclosed fence", "```\n"),
        ("no trailing newline", "## Group\n- [ ] item"),
        # The fixtures above all end in "\n", so none of them can reach the EOF case in the
        # COMMENT stripper — a comment whose `-->` is the file's last characters. These two do.
        ("comment closing at true EOF", "## Group\n<!--\nx\n-->"),
        ("nothing but a comment at EOF", "<!--\nx\n-->"),
        # `splitlines` ends a line at more than \n, so counting only \n drifts on these.
        ("file ending in U+2028", "## Group\n- [ ] item\u2028"),
        ("bare CR inside a comment", "<!-- a\rb -->\n- [ ] item\n"),
        ("CRLF inside a comment", "<!-- a\r\nb -->\n- [ ] item\n"),
        ("bare CR right before a comment", "a\r<!--\nb -->\n- [ ] item\n"),
        ("bare CR before a one-line comment", "a\r<!-- x -->\nb\n"),
        ("bare CR before adjacent comments", "a\r<!--x--><!--\ny-->\nb\n"),
        ("bare CR before adjacent one-line comments", "a\r<!--x--><!--y-->\nb\n"),
    ):
        _assert(
            len(_strip_fenced_blocks(fixture).splitlines()) == len(fixture.splitlines()),
            f"_strip_fenced_blocks preserves line count exactly ({label})",
        )
        # Same contract, same loop, other stripper: `tokenize` chains comments-then-fences, so a
        # line dropped here shifts every token line number just as surely.
        _assert(
            len(_strip_html_comments(fixture).splitlines()) == len(fixture.splitlines()),
            f"_strip_html_comments preserves line count exactly ({label})",
        )

    # REGRESSION GUARD (codex review) — CommonMark forbids a backtick in a BACKTICK fence's info
    # string. Accepting one turned an ordinary prose line into an unclosed opener that blanked the
    # file through EOF, dropping every real item after it.
    backtick_in_info = """## Real group
```foo`bar
- [ ] real item
"""
    result = backlog_fast_candidates(tokenize(backtick_in_info))
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Real group", "line": 1, "items": 1}],
        "a backtick inside a backtick fence's info string does not open a fence",
    )
    tilde_backtick_info = """## Tilde group
~~~foo`bar
## Fake
~~~
- [ ] real item
"""
    result = backlog_fast_candidates(tokenize(tilde_backtick_info))
    _assert(
        result == [{"source": "backlog.md", "kind": "h2", "title": "Tilde group", "line": 1, "items": 1}],
        "a TILDE fence's info string may contain backticks — still a real fence",
    )

    # REGRESSION GUARD (claude review) — an unclosed fence blanking through EOF is CommonMark-
    # correct, but an odd ``` is a routine typo and the swallowed headings never become tokens, so
    # zero_candidate_diagnosis is structurally blind to it. It must be reported on its own channel.
    _assert(
        unclosed_fence_line(unclosed_fence) == 3,
        "unclosed_fence_line reports the opener's 1-based line",
    )
    _assert(
        unclosed_fence_line(fenced_between) is None
        and unclosed_fence_line(nested_fence) is None
        and unclosed_fence_line("") is None,
        "unclosed_fence_line returns None when every fence is balanced",
    )
    _assert(
        unclosed_fence_line(fence_inside_comment) is None,
        "a ``` parked inside an HTML comment is not reported as an unbalanced fence",
    )
    # The partial case: a stray fence hides SOME work while other groups still surface, so the
    # warning cannot be gated on a zero-candidate result.
    partial_swallow = """## Visible group
- [ ] surfaced item
```sh
## Hidden group
- [ ] swallowed item
"""
    _assert(
        [c["title"] for c in backlog_fast_candidates(tokenize(partial_swallow))] == ["Visible group"]
        and unclosed_fence_line(partial_swallow) == 3,
        "a partial swallow still yields candidates, so the warning must not be zero-gated",
    )

    # ---- Test 4: fast_path — cap FAST_PATH_CAP (3) total across Phase A + B ----
    print("\nTest 4: fast_path — cap 3 total across Phase A + B")
    _assert(FAST_PATH_CAP == 3, "FAST_PATH_CAP is 3")
    tasks_many = """# Sprint 1
status: open

# Sprint 2
status: open
"""
    backlog_many = """## B group 1
- [ ] x
## B group 2
- [ ] y
"""
    tasks_tokens = tokenize(tasks_many)
    backlog_tokens = tokenize(backlog_many)
    result = fast_path(tasks_tokens, backlog_tokens)
    _assert(len(result) == 3, "fast_path truncates combined A+B to 3 candidates")
    _assert(
        [c["title"] for c in result] == ["Sprint 1", "Sprint 2", "B group 1"],
        "truncation keeps A(2) then only the first of B",
    )

    # Phase A alone already at FAST_PATH_CAP (3) -> B fully skipped
    tasks_three = """# S1
status: open

# S2
status: open

# S3
status: open
"""
    result = fast_path(tokenize(tasks_three), tokenize(backlog_many))
    _assert(len(result) == 3, "Phase A alone at 3 still caps combined total at 3")
    _assert(
        all(c["source"] == "tasks.md" and c["kind"] == "h1" for c in result),
        "Phase A already at FAST_PATH_CAP skips Phase B entirely",
    )

    # ---- Test 4b: truncation_note — pure signal in both directions ----
    print("\nTest 4b: truncation_note — note when truncated, None when not")
    _assert(
        truncation_note(3, 3) is None,
        "truncation_note is None when shown == total (nothing hidden)",
    )
    _assert(
        truncation_note(3, 2) is None,
        "truncation_note is None when shown > total (defensive; cannot show more than exists)",
    )
    note = truncation_note(3, 5)
    _assert(
        note is not None and "3" in note and "5" in note and "2" in note,
        "truncation_note names shown, total, and the hidden count when total > shown",
    )
    _assert(
        len(fast_path(tasks_tokens, backlog_tokens)) == 3
        and len(full_scan(tasks_tokens, backlog_tokens)) == 4
        and truncation_note(
            len(fast_path(tasks_tokens, backlog_tokens)),
            len(full_scan(tasks_tokens, backlog_tokens)),
        )
        is not None,
        "end-to-end: a real fast_path/full_scan pair on tasks_many/backlog_many truncates and signals",
    )

    # REGRESSION GUARD: tasks.md findings sections are never candidates, whatever their shape.
    tasks_mixed = """# Sprint one

status: open

## Review Backlog

### PR #101 — earlier PR

- [ ] [debt] leftover finding

## Grab bag

- [ ] [doc] another
"""
    mixed_tokens = tokenize(tasks_mixed)
    _assert(
        [c["title"] for c in fast_path(mixed_tokens, tokenize(""))] == ["Sprint one"]
        and [c["title"] for c in full_scan(mixed_tokens, tokenize(""))] == ["Sprint one"],
        "tasks.md h2/h3 findings are not candidates in either algorithm",
    )
    stale = tasks_persistent_sections(mixed_tokens)
    _assert(
        [s["title"] for s in stale] == ["Review Backlog", "PR #101 — earlier PR", "Grab bag"],
        "tasks_persistent_sections reports the findings sections instead of dropping them",
    )
    _assert(
        tasks_persistent_sections(
            tokenize("# Sprint one\n\nstatus: active\n\n## Scope\n\n- [ ] in scope\n")
        )
        == [],
        "a healthy Sprint Contract's own ## Scope checkboxes raise no migration warning",
    )
    _assert(
        tasks_persistent_sections(
            tokenize("# S\n\nstatus: active\n\n## Scope\n\n### Area A\n\n- [ ] x\n")
        )
        == [],
        "an h3 nested under a Sprint Contract section is contract content, not a findings group",
    )
    # REGRESSION GUARD: the two callers must agree. A grab-bag h2 is the case that used to warn
    # "these will be lost" while prune-tasks deleted the file anyway.
    _assert(
        [s["title"] for s in tasks_persistent_sections(
            tokenize("# S\n\nstatus: active\n\n## Scope\n\n- [ ] a\n\n## Follow-ups\n\n- [ ] leftover\n")
        )] == ["Follow-ups"],
        "an ad-hoc grab-bag h2 with open items is reported, not just the two known titles",
    )
    _assert(
        [s["title"] for s in tasks_persistent_sections(
            tokenize("## Security Fixes — my-webapp\n\n### Dependabot\n\n- [x] done\n")
        )] == ["Security Fixes — my-webapp", "Dependabot"],
        "the ` — <repo>` suffix still matches, and fires even when every item is closed",
    )
    # REGRESSION GUARD: fences and comments are markup. Blocking cleanup on a documentation
    # example would be a false refusal with no override flag.
    _assert(
        tasks_persistent_sections(
            tokenize("# S\n\nstatus: active\n\n```markdown\n## Review Backlog\n```\n")
        )
        == []
        and tasks_persistent_sections(
            tokenize("# S\n\nstatus: active\n\n<!--\n## Security Fixes\n-->\n")
        )
        == [],
        "a findings heading inside a fence or an HTML comment is markup, not a persistent section",
    )

    # ---- Test 5: Phase-B-vs-full-scan ordering divergence ----
    print("\nTest 5: Phase B (type-agnostic doc order) vs full_scan (type-priority h3-then-h2)")
    backlog_interleaved = """## H2-A
- [ ] item a
### H3-B
- [ ] item b
## H2-C
- [ ] item c
"""
    tokens = tokenize(backlog_interleaved)
    phase_b_result = backlog_fast_candidates(tokens, limit=2)
    _assert(
        [c["title"] for c in phase_b_result] == ["H2-A", "H3-B"],
        "Phase B picks first 2 in raw document order, type-agnostic",
    )

    full_scan_backlog_only = backlog_h3_candidates(tokens) + backlog_h2_candidates(tokens)
    _assert(
        [c["title"] for c in full_scan_backlog_only] == ["H3-B", "H2-A", "H2-C"],
        "full-scan rules 2+3 apply type priority: all h3 first, then all h2 — diverges from Phase B order",
    )

    # ---- Test 6: full_scan end-to-end composition ----
    print("\nTest 6: full_scan — rules 1-3 concatenated, uncapped")
    tasks_fs = """# Sprint open
status: open
"""
    result = full_scan(tokenize(tasks_fs), tokenize(backlog_interleaved))
    _assert(
        [c["title"] for c in result] == ["Sprint open", "H3-B", "H2-A", "H2-C"],
        "full_scan concatenates rule1..rule3 in order, uncapped, backlog rules type-prioritized",
    )

    # ---- Test 7: format_candidates — h1 omits item count ----
    print("\nTest 7: format_candidates — h1 sprint blocks omit item count")
    candidates = [
        {"source": "tasks.md", "kind": "h1", "title": "Sprint X", "line": 1, "items": None},
        {"source": "backlog.md", "kind": "h2", "title": "Group Y", "line": 5, "items": 3},
    ]
    lines = format_candidates(candidates)
    _assert(lines[0] == "[1] tasks.md: Sprint X", "h1 line has no item count suffix")
    _assert(lines[1] == "[2] backlog.md: Group Y (3 items)", "non-h1 line includes item count suffix")

    # ---- Test 8: zero_candidate_diagnosis — an empty result says WHICH empty it is ----
    print("\nTest 8: zero_candidate_diagnosis — distinguishes the kinds of empty")

    # 8a: prose-ticket format drift. REGRESSION GUARD — the open section is prose while the
    # Completed section is full of `- [x]`, which is the real shape this was first got wrong
    # on: a file-wide "any checkboxes?" test sees the [x]s and reports "all done", a
    # confidently wrong answer on the exact case the diagnosis exists to catch.
    prose_open_with_done_section = """# Backlog

## Open

### Phase 5 — Audit

#### SEC-5-1: header spoofing
- Done when: obtain the trusted proxy IP, then implement.

#### PERF-5-2: pool params
- Done when: record the prod values in docs/.

## Completed

### Phase 4 — Architecture

- [x] extract the service layer
- [x] drop the CDN dependency
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(prose_open_with_done_section))
    _assert(
        any("prose bullets but no `- [ ]` item" in line for line in out),
        "prose-ticket open work is reported as format drift even when a Completed section has [x]s",
    )
    _assert(
        any("'Phase 5 — Audit' (line 5)" in line for line in out),
        "the drifted heading is named with its line so the reader can go straight to it",
    )
    _assert(
        not any("no open items" in line for line in out),
        "REGRESSION: the [x]-heavy Completed section must not produce an 'all done' verdict",
    )
    _assert(
        not any(line.startswith("  - tasks.md") for line in out),
        "an absent/empty tasks.md contributes no diagnosis line",
    )
    _assert(
        backlog_fast_candidates(tokenize(prose_open_with_done_section)) == [],
        "the fixture really does yield zero candidates (diagnosis is not masking a hit)",
    )

    # 8a-bis: a `####` heading's checkbox attributes to the enclosing `###`, so the `###` is
    # NOT drifted — guards against flagging correctly-formatted h4-nested work.
    h4_nested = """## Open

### Phase 5

#### TICKET-1
- some prose context
- [ ] Done when: the thing works
"""
    _assert(
        _prose_only_headings(tokenize(h4_nested)) == [],
        "a heading whose region holds both prose and a checkbox is not reported as drifted",
    )
    _assert(
        [c["title"] for c in backlog_fast_candidates(tokenize(h4_nested))] == ["Phase 5"],
        "the h4-nested checkbox really does attribute to the enclosing h3",
    )

    # 8a-ter: `## Rejected — do not re-file` holds plain bullets by design (harness-init
    # backlog-template.md): a decision record, not invisible work. Flagging it would nudge the
    # agent to turn rejected entries back into `- [ ]` candidates.
    rejected_only = """## Open
- [x] shipped thing

## Rejected — do not re-file

- **gate X** — discarded by the user. Re-file only with a recorded bypass.
"""
    _assert(
        _prose_only_headings(tokenize(rejected_only)) == [],
        "the Rejected section's plain bullets are not reported as format drift",
    )
    _assert(
        zero_candidate_diagnosis(tokenize(""), tokenize(rejected_only))
        == ["No candidates found. Why:", "  - backlog.md: no open items (all `[x]`/`[>]`)."],
        "a backlog holding only done items and rejected entries reads as empty, not drifted",
    )

    # 8b: every open item parked by a blocked/deferred marker
    all_parked = """## Open
- [ ] fix the thing *(blocked by: 3-upstream-api)*
- [ ] other thing *(deferred: needs ops values)*
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(all_parked))
    _assert(
        any("2 open item(s), all parked" in line and "--parked" in line for line in out),
        "all-parked is reported as parked, with the count and the --parked pointer, not as an empty queue",
    )
    out = zero_candidate_diagnosis(tokenize(all_parked), tokenize(""))
    _assert(
        any("2 open item(s), all parked" in line for line in out)
        and not any("--parked" in line for line in out),
        "tasks.md gets no --parked pointer: that listing covers backlog.md only",
    )

    # 8c: actionable items exist but sit above the first heading
    orphan_items = """- [ ] stray item one
- [ ] stray item two

## Group with nothing
- [x] done
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(orphan_items))
    _assert(
        any("sit above the first `#`–`###` heading" in line for line in out),
        "items above the first heading are reported as unattributed, not as absent",
    )

    # 8g: REGRESSION GUARD — a tasks.md h2 is unreachable by any rule now, but its items ARE
    # attributed to a heading. Reporting them as "not attributed to a heading" is a false
    # statement about the file.
    unreachable_h2 = """# Out-of-Scope Findings

## Plugin validation

- [ ] fix the frontmatter parse error
"""
    tasks_tok = tokenize(unreachable_h2)
    _assert(
        fast_path(tasks_tok, tokenize("")) == [] and full_scan(tasks_tok, tokenize("")) == [],
        "a tasks.md h2 group is reachable by neither algorithm",
    )
    out = zero_candidate_diagnosis(tasks_tok, tokenize(""))
    _assert(
        not any("above the first heading" in line for line in out),
        "REGRESSION: an attributed-but-unselected item must not be called unattributed",
    )
    _assert(
        any("no phase selected them" in line for line in out),
        "attributed-but-unselected is named as its own distinct cause",
    )
    _assert(
        not any("no open items" in line for line in out),
        "REGRESSION: 'no open items' must never accompany a line reporting actionable items",
    )

    # 8h: REGRESSION GUARD (qa-verifier) — the unselected-cause clause must describe the file
    # actually being diagnosed. A backlog.md h1 is unreachable for a completely different
    # reason than a tasks.md `###`, and printing tasks.md's causes here is simply false.
    backlog_h1 = """# Top-level backlog.md heading

- [ ] real actionable item directly under an h1
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(backlog_h1))
    _assert(
        any("backlog.md rules cover h2/h3 groups only" in line for line in out),
        "a backlog.md h1 is explained by the backlog.md rule set, not tasks.md's",
    )
    _assert(
        not any("Review Backlog" in line for line in out),
        "REGRESSION: tasks.md-only causes must not be cited while diagnosing backlog.md",
    )
    tasks_h3 = """## Some group

### Nested group

- [ ] real actionable item
"""
    out = zero_candidate_diagnosis(tokenize(tasks_h3), tokenize(""))
    _assert(
        any("belong in backlog.md" in line for line in out),
        "the tasks.md explanation is still given when tasks.md is the file being diagnosed",
    )

    # 8i: REGRESSION GUARD (qa-verifier) — "above the first heading" must disclose that only
    # levels 1–3 count, since a `####` line can visually sit above the item.
    h4_above_item = """#### h4 preamble, not a heading to this parser
- [ ] stray item that visually sits under an h4

## Real heading
- [x] done already
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(h4_above_item))
    _assert(
        any("only levels 1–3 count here" in line for line in out),
        "REGRESSION: the stray-item message discloses the levels-1-3 restriction",
    )
    _assert(
        not any("items with no heading above them" in line for line in out),
        "REGRESSION: the message no longer claims there is no heading above the item",
    )

    # 8j: the drift message must not name a heading level it did not check
    h4_under_h2 = """## Group directly enclosing an h4

#### TICKET
- prose only, no checkbox
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(h4_under_h2))
    _assert(
        any("enclosing `#`–`###` heading" in line for line in out)
        and not any("enclosing `###`)" in line for line in out),
        "the drift message names the enclosing level generically, not a hardcoded `###`",
    )
    _assert(
        not any(
            "reachable with --full-scan" in line
            for line in zero_candidate_diagnosis(tasks_tok, tokenize(""))
        ),
        "no --full-scan suggestion: both algorithms qualify headings by the same test now",
    )

    # 8d: genuinely clear queue — everything closed
    all_done = """## Group
- [x] done one
- [>] moved on
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(all_done))
    _assert(
        any("no open items" in line for line in out),
        "an all-closed file is reported as genuinely clear",
    )

    # 8e: both files diagnosed independently in one run
    out = zero_candidate_diagnosis(tokenize(all_parked), tokenize(prose_open_with_done_section))
    _assert(
        any(line.startswith("  - tasks.md") for line in out)
        and any(line.startswith("  - backlog.md") for line in out),
        "each source file gets its own diagnosis line when both have something to say",
    )

    # 8f: truly empty inputs still produce a sentence rather than nothing
    out = zero_candidate_diagnosis(tokenize(""), tokenize(""))
    _assert(
        len(out) == 1 and "no headings or items at all" in out[0],
        "empty-in still yields one explanatory line, never an empty diagnosis",
    )

    # 8g: headings and Rejected bullets but not one checkbox — the queue is empty, but the
    # file is not; "no headings or items at all" would be a false statement about it.
    headings_no_boxes = """# Backlog

## Harness

Nothing from this group is queued.

## Rejected — do not re-file

- **gate X** — discarded by the user. Re-file only with a recorded bypass.
"""
    out = zero_candidate_diagnosis(tokenize(""), tokenize(headings_no_boxes))
    _assert(
        out == ["No candidates found. Why:", "  - backlog.md: no `- [ ]` item at all."],
        "a backlog with headings but no checkbox says so, not 'no headings or items at all'",
    )

    # 8h: tasks.md is never selected by checkbox, so its empty-queue line names its own rule.
    prose_sprint = "# Sprint: fix X\nstatus: active\n\nContract written as prose.\n"
    out = zero_candidate_diagnosis(tokenize(prose_sprint), tokenize(""))
    _assert(
        out == ["No candidates found. Why:", "  - tasks.md: no h1 block with `status: open`."],
        "tasks.md's empty-queue line names the h1 `status: open` rule, not checkboxes",
    )

    for contract_body in ("Contract written as prose.\n", "- [ ] Run the contract check.\n"):
        tasks_tokens = tokenize("# Sprint A\nstatus: open\n\n" + contract_body + "\n# Sprint B\nstatus: open\n")
        mark_claimed_blocks(tasks_tokens, {".worktrees/a": {"Sprint A"}, ".worktrees/b": {"Sprint B"}})
        out = zero_candidate_diagnosis(tasks_tokens, tokenize(""))
        _assert(
            not phase_a_candidates(tasks_tokens)
            and out == [
                "No candidates found. Why:",
                "  - tasks.md: 2 open sprint block(s) claimed by another `.worktrees/` run — "
                "see the skip line above; resume that worktree to work them.",
            ],
            f"an all-claimed sprint queue diagnoses sprint blocks even with {contract_body.strip()!r}",
        )

    tasks_tokens = tokenize(
        "- [ ] stray\n\n# Sprint A\nstatus: open\n\n- [ ] run checks\n\n"
        "# Other\n\n## Misplaced items\n- [ ] move to backlog\n"
    )
    mark_claimed_blocks(tasks_tokens, {".worktrees/a": {"Sprint A"}})
    out = zero_candidate_diagnosis(tasks_tokens, tokenize(""))
    _assert(
        any("1 open sprint block(s) claimed" in line for line in out)
        and any("1 actionable item(s) sit above" in line for line in out)
        and any("1 actionable item(s) are attributed" in line for line in out),
        "a claimed sprint does not mask tasks.md diagnostics outside its block",
    )

    # 8i: prose bullets with no `#`–`###` heading above them (none at all, or `####` only) are
    # drift too — `_prose_only_headings` judges per heading, so it never sees them.
    unheaded_prose = "- loose prose ticket one\n#### TICKET-2\n- prose two\n"
    out = zero_candidate_diagnosis(tokenize(""), tokenize(unheaded_prose))
    _assert(
        len(out) == 2
        and out[1].startswith("  - backlog.md: 2 prose bullet(s) sit above the first `#`–`###`")
        and "`####`-or-deeper" in out[1],
        "unheaded prose bullets get the drift explanation, not a bare 'no item' line",
    )

    # ---- Test 9: parked_items — the blockers an all-blocked stop has to report ----
    print("\nTest 9: parked_items — lists what the markers park, and nothing else")
    parked_mix = """- [ ] stray parked *(deferred: before any heading)*

## Auth
- [ ] add login *(blocked by: 3-upstream-api)*
- [ ] actionable one
- [x] done *(blocked by: 3-upstream-api)*
- [>] moved *(deferred: later)*

### Docs
- [ ] document the `*(blocked by: <slug>)*` format
- [ ] wrapped item
  continues here *(deferred: needs ops values)* *(blocked by: sink-lock)*
"""
    got = parked_items("docs/backlog.md", tokenize(parked_mix))
    _assert(
        [(it["line"], it["heading"]) for it in got] == [(1, None), (4, "Auth"), (11, "Docs")],
        "only open, resolvably-marked items are listed, each under its nearest heading",
    )
    _assert(
        got[1]["markers"] == [{"kind": "blocked by", "payload": "3-upstream-api"}]
        and got[2]["markers"]
        == [
            {"kind": "deferred", "payload": "needs ops values"},
            {"kind": "blocked by", "payload": "sink-lock"},
        ],
        "each marker's kind and payload is carried, including several on a wrapped item",
    )
    _assert(
        format_parked(got)[:2]
        == [
            "docs/backlog.md:1 [no heading] stray parked *(deferred: before any heading)*",
            "docs/backlog.md:4 [Auth] add login *(blocked by: 3-upstream-api)*",
        ],
        "the plain-text line carries the given source path, line, heading and item text",
    )
    long_body = "x" * 300
    long_item = f"- [ ] {long_body} *(deferred: needs ops values)* *(blocked by: sink-lock)*\n"
    long_got = parked_items("backlog.md", tokenize(long_item))
    long_line = format_parked(long_got)[0]
    _assert(
        long_line
        == f"backlog.md:1 [no heading] {'x' * PARKED_TEXT_WIDTH}… "
        "*(deferred: needs ops values)* *(blocked by: sink-lock)*",
        "a long item's body is clipped to PARKED_TEXT_WIDTH and every marker still follows it",
    )
    _assert(
        long_got[0]["text"].startswith(long_body),
        "--json keeps the full item text; only the plain-text line is clipped",
    )
    short_body_long_marker = f"short prose *(deferred: {'y' * 150})* tail"
    _assert(
        _clip_parked_text(short_body_long_marker) == short_body_long_marker,
        "a body within the width is left verbatim, however long its markers run",
    )
    quoted = f"{'a ' * 40}quotes *(blocked by: <slug>)* syntax {'b ' * 60}*(deferred: x)*"
    _assert(
        _clip_parked_text(quoted).startswith(f"{'a ' * 40}quotes *(blocked by: <slug>)* syntax")
        and _clip_parked_text(quoted).endswith("… *(deferred: x)*"),
        "a placeholder marker stays in the body as prose; only real markers move after the clip",
    )
    _assert(
        got[2]["text"] == "wrapped item continues here *(deferred: needs ops values)* *(blocked by: sink-lock)*",
        "a wrapped item's text is the folded form, at its first line number",
    )
    _assert(json.loads(json.dumps(got)) == got, "parked items round-trip through JSON for --json")
    _assert(
        len(parked_items("backlog.md", tokenize(all_parked))) == 2,
        "the count matches the all-parked diagnosis for the same input",
    )
    _assert(parked_items("backlog.md", tokenize(all_done)) == [], "a file with no parked item lists nothing")

    # ---- Test 10: claimed items — other `.worktrees/` runs (temp git repo) ----
    print("\nTest 10: items claimed by another .worktrees/ run are skipped and named")
    _test_claimed_items()

    print(f"\n=== Results: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL ===")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
