#!/usr/bin/env python3
"""backlog_candidates.py — deterministic candidate-group parser for next-tasks Step 1.

Usage:
  python3 backlog_candidates.py --tasks PATH --backlog PATH [--full-scan] [--json]
  python3 backlog_candidates.py --test

  --tasks PATH    path to tasks.md (optional file; absent path is treated as empty input,
                   same as the `2>/dev/null` grep fallback it replaces)
  --backlog PATH  path to backlog.md (required — this repo's prereqs guarantee it exists,
                   so a missing/unreadable file here is treated as a real error, not "no candidates")
  --full-scan     run the full-scan algorithm instead of the fast path (see below)
  --json          emit a JSON array of candidate objects instead of the plain-text list

Output (plain text, one line per candidate, in the algorithm's selection order):
  [N] <source>: <heading> (<M> items)
  h1 sprint blocks (tasks.md Phase A) omit the "(<M> items)" suffix — they are a scope
  announcement, not an item-counted group.

Parsing semantics (must match `SKILL.md` Step 1 prose exactly — this script does not
reinterpret it):

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

  "Directly owns" (Phase B/C, full-scan rules 2-5): open `- [ ]` checkbox items collected
  from just after a heading up to (not including) the next heading of ANY level 1-3 — not
  just the next heading of the same or broader level. A checkbox sitting after a nested h3
  child does NOT count toward that h3's h2 parent.

  Phase B (tasks.md, fast path only): up to 3 h3 sub-headings under `## Review Backlog`
  (document order) that directly own >=1 open item. Skipped entirely if Phase A already
  produced 5 candidates.

  Phase C (backlog.md, FAST PATH ONLY): top-to-bottom, TYPE-AGNOSTIC scan collecting up to 2
  qualifying h2-or-h3 headings in raw document order (h2/h3 interleaved as they appear).
  Skipped entirely if Phase A + Phase B already produced 5 candidates. The fast-path total
  across Phase A + B + C is capped at 5.

  Full scan is a DIFFERENT algorithm from Phase C, not a superset call to the same helper:
  rule 1 = all qualifying tasks.md h1 blocks (Phase A, uncapped); rule 2 = all qualifying
  tasks.md h3 headings under Review Backlog (uncapped); rule 3 = all qualifying tasks.md h2
  headings outside Review Backlog; rule 4 = ALL qualifying backlog.md h3 headings, in document
  order among h3s only; rule 5 = ALL qualifying backlog.md h2 headings, in document order among
  h2s only. Rules 4 and 5 apply TYPE PRIORITY (all h3 first, then all h2) — this is NOT the
  same ordering as Phase C's raw document order across types, and the two must stay separate
  functions (`fast_path()` / `full_scan()`) rather than one shared helper, or the divergence
  silently disappears.

Self-check (--test):
  Exercises the status-line-gap case (Phase A), the direct-items heading-boundary case
  (nested h3 item must not count toward its h2 parent), the all-parked-skip case (every item
  `[x]`/`[>]` under a heading is not a candidate), Phase-B/C limit truncation (cap 5 total
  across A+B+C), the Phase-C-vs-full-scan ordering divergence on backlog.md h2/h3
  interleaving, and the blocked/deferred-marker exclusion case (all-marked heading is not a
  candidate; mixed marked+unmarked heading counts only the unmarked items). All fixtures are
  in-memory strings — no real files touched. Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import json
import math
import re
import sys


# ---------------------------------------------------------------------------
# Pure-function core (testable without real filesystem)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_STATUS_RE = re.compile(r"^status:\s*(\S+)")
_CHECKBOX_RE = re.compile(r"^-\s*\[([ xX>])\]\s*(.*)$")
# Generalized skip marker: `*(deferred: ...)*` or `*(blocked by: <n>-<slug>)*` — both mean
# "otherwise-open item is not actually actionable yet", same treatment as a `[>]` checkbox.
_BLOCK_MARKER_RE = re.compile(r"\*\(\s*(?:deferred|blocked by)\s*:.*?\)\*", re.IGNORECASE)


def _is_blocked(text: str) -> bool:
    """True if `text` (the checkbox item body) carries a deferred/blocked-by marker."""
    return bool(_BLOCK_MARKER_RE.search(text))


def tokenize(text: str) -> list[dict]:
    """Classify each line into a typed token: heading / status / checkbox.

    Unrecognized lines (body prose) are dropped — only the three token types matter for
    candidate detection. Line numbers are 1-based to match grep -n output.
    """
    tokens: list[dict] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = _HEADING_RE.match(line)
        if m:
            tokens.append(
                {"type": "heading", "level": len(m.group(1)), "title": m.group(2).strip(), "line": i}
            )
            continue
        m = _STATUS_RE.match(line)
        if m:
            tokens.append({"type": "status", "value": m.group(1), "line": i})
            continue
        m = _CHECKBOX_RE.match(line)
        if m:
            tokens.append({"type": "checkbox", "state": m.group(1), "text": m.group(2), "line": i})
            continue
    return tokens


def _headings(tokens: list[dict], levels: tuple[int, ...] = (1, 2, 3)) -> list[dict]:
    return [t for t in tokens if t["type"] == "heading" and t["level"] in levels]


def _direct_open_items(tokens: list[dict], heading: dict, all_headings: list[dict]) -> list[dict]:
    """Open checkbox items between `heading` and the next heading of ANY level 1-3.

    all_headings must be the full sorted (by line) list of level-1..3 headings in the same
    token stream — this is what makes a nested h3's items NOT count toward its h2 parent.
    """
    end = math.inf
    for h in all_headings:
        if h["line"] > heading["line"]:
            end = h["line"]
            break
    items = [
        t
        for t in tokens
        if t["type"] == "checkbox" and heading["line"] < t["line"] < end
    ]
    return [t for t in items if t["state"] == " " and not _is_blocked(t["text"])]


# ---- Phase A: tasks.md h1 sprint blocks ------------------------------------------------

def phase_a_candidates(tasks_tokens: list[dict]) -> list[dict]:
    """h1 blocks whose FIRST status: line strictly between this h1 and the next h1 is 'open'."""
    h1s = _headings(tasks_tokens, (1,))
    result = []
    for idx, h in enumerate(h1s):
        end = h1s[idx + 1]["line"] if idx + 1 < len(h1s) else math.inf
        status_value = None
        for t in tasks_tokens:
            if t["type"] == "status" and h["line"] < t["line"] < end:
                status_value = t["value"]
                break
        if status_value == "open":
            result.append(
                {"source": "tasks.md", "kind": "h1", "title": h["title"], "line": h["line"], "items": None}
            )
    return result


# ---- Phase B / full-scan rule 2: tasks.md Review Backlog h3s --------------------------

def review_backlog_h3_candidates(tasks_tokens: list[dict], limit: int | None = None) -> list[dict]:
    headings = _headings(tasks_tokens)
    rb = next((h for h in headings if h["level"] == 2 and h["title"] == "Review Backlog"), None)
    if rb is None:
        return []
    rb_end = math.inf
    for h in headings:
        if h["line"] > rb["line"] and h["level"] in (1, 2):
            rb_end = h["line"]
            break
    result = []
    for h in headings:
        if h["level"] == 3 and rb["line"] < h["line"] < rb_end:
            open_items = _direct_open_items(tasks_tokens, h, headings)
            if open_items:
                result.append(
                    {
                        "source": "tasks.md",
                        "kind": "h3",
                        "title": h["title"],
                        "line": h["line"],
                        "items": len(open_items),
                    }
                )
                if limit is not None and len(result) >= limit:
                    break
    return result


# ---- Full-scan rule 3: tasks.md h2 outside Review Backlog ------------------------------

def h2_outside_review_backlog_candidates(tasks_tokens: list[dict]) -> list[dict]:
    headings = _headings(tasks_tokens)
    result = []
    for h in headings:
        if h["level"] == 2 and h["title"] != "Review Backlog":
            open_items = _direct_open_items(tasks_tokens, h, headings)
            if open_items:
                result.append(
                    {
                        "source": "tasks.md",
                        "kind": "h2",
                        "title": h["title"],
                        "line": h["line"],
                        "items": len(open_items),
                    }
                )
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
    """Phase A (uncapped) + Phase B (<=3, skipped if A already >=5) +
    Phase C (<=2, skipped if A+B already >=5), truncated to 5 total."""
    result: list[dict] = []
    result.extend(phase_a_candidates(tasks_tokens))
    if len(result) < 5:
        result.extend(review_backlog_h3_candidates(tasks_tokens, limit=3))
    if len(result) < 5:
        result.extend(backlog_fast_candidates(backlog_tokens, limit=2))
    return result[:5]


def full_scan(tasks_tokens: list[dict], backlog_tokens: list[dict]) -> list[dict]:
    """Rules 1-5 in order, uncapped. Rules 4+5 are type-priority (all h3, then all h2) —
    a genuinely different ordering from Phase C's type-agnostic document order."""
    result: list[dict] = []
    result.extend(phase_a_candidates(tasks_tokens))
    result.extend(review_backlog_h3_candidates(tasks_tokens))
    result.extend(h2_outside_review_backlog_candidates(tasks_tokens))
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_file(path: str | None, *, required: bool = False) -> str:
    """Read `path`, or return "" if absent — matching the `2>/dev/null` grep fallback
    this script replaces. `required=True` (backlog.md) treats a missing/unreadable file
    as fatal instead of silently returning "" — tasks.md stays optional (required=False),
    per next-tasks' own "absent in the idle state" semantics.
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


def main(argv: list[str]) -> int:
    if "--test" in argv:
        return run_tests()

    tasks_path = None
    backlog_path = None
    full_scan_flag = False
    json_flag = False

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--tasks", "--backlog") and i + 1 >= len(argv):
            sys.stderr.write(f"Error: {a} requires a path argument\n")
            sys.exit(1)
        if a == "--tasks":
            tasks_path = argv[i + 1]
            i += 2
        elif a == "--backlog":
            backlog_path = argv[i + 1]
            i += 2
        elif a == "--full-scan":
            full_scan_flag = True
            i += 1
        elif a == "--json":
            json_flag = True
            i += 1
        else:
            i += 1

    tasks_tokens = tokenize(_read_file(tasks_path))
    backlog_tokens = tokenize(_read_file(backlog_path, required=True))

    candidates = full_scan(tasks_tokens, backlog_tokens) if full_scan_flag else fast_path(tasks_tokens, backlog_tokens)

    if json_flag:
        print(json.dumps(candidates))
    else:
        for line in format_candidates(candidates):
            print(line)
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

    # ---- Test 4: Phase-B/C limit truncation (cap 5 total across A+B+C) ----
    print("\nTest 4: fast_path — cap 5 total across Phase A + B + C")
    tasks_many = """# Sprint 1
status: open

# Sprint 2
status: open

# Sprint 3
status: open

# Sprint 4
status: open

## Review Backlog
### RB item 1
- [ ] a
### RB item 2
- [ ] b
### RB item 3
- [ ] c
"""
    backlog_many = """## B group 1
- [ ] x
## B group 2
- [ ] y
"""
    tasks_tokens = tokenize(tasks_many)
    backlog_tokens = tokenize(backlog_many)
    result = fast_path(tasks_tokens, backlog_tokens)
    _assert(len(result) == 5, "fast_path truncates combined A+B+C to 5 candidates")
    _assert(
        [c["title"] for c in result] == ["Sprint 1", "Sprint 2", "Sprint 3", "Sprint 4", "RB item 1"],
        "truncation keeps A(4) then only the first of B, C entirely skipped",
    )

    # Phase A alone already at 5 -> B and C fully skipped
    tasks_five = """# S1
status: open

# S2
status: open

# S3
status: open

# S4
status: open

# S5
status: open

## Review Backlog
### RB item
- [ ] a
"""
    result = fast_path(tokenize(tasks_five), tokenize(backlog_many))
    _assert(len(result) == 5, "Phase A alone at 5 still caps combined total at 5")
    _assert(
        all(c["source"] == "tasks.md" and c["kind"] == "h1" for c in result),
        "Phase A already at 5 skips Phase B and Phase C entirely",
    )

    # ---- Test 5: Phase-C-vs-full-scan ordering divergence ----
    print("\nTest 5: Phase C (type-agnostic doc order) vs full_scan (type-priority h3-then-h2)")
    backlog_interleaved = """## H2-A
- [ ] item a
### H3-B
- [ ] item b
## H2-C
- [ ] item c
"""
    tokens = tokenize(backlog_interleaved)
    phase_c_result = backlog_fast_candidates(tokens, limit=2)
    _assert(
        [c["title"] for c in phase_c_result] == ["H2-A", "H3-B"],
        "Phase C picks first 2 in raw document order, type-agnostic",
    )

    full_scan_backlog_only = backlog_h3_candidates(tokens) + backlog_h2_candidates(tokens)
    _assert(
        [c["title"] for c in full_scan_backlog_only] == ["H3-B", "H2-A", "H2-C"],
        "full-scan rules 4+5 apply type priority: all h3 first, then all h2 — diverges from Phase C order",
    )

    # ---- Test 6: full_scan end-to-end composition ----
    print("\nTest 6: full_scan — rules 1-5 concatenated, uncapped")
    tasks_fs = """# Sprint open
status: open

## Review Backlog
### RB a
- [ ] x
### RB b
- [ ] y

## Grab bag
- [ ] z
"""
    result = full_scan(tokenize(tasks_fs), tokenize(backlog_interleaved))
    _assert(
        [c["title"] for c in result]
        == ["Sprint open", "RB a", "RB b", "Grab bag", "H3-B", "H2-A", "H2-C"],
        "full_scan concatenates rule1..rule5 in order, uncapped, backlog rules type-prioritized",
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

    print(f"\n=== Results: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL ===")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
