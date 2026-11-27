#!/usr/bin/env python3
"""migrate_backlog.py — move a github.com repo's backlog.md queue onto GitHub issues.

Usage:
  python3 migrate_backlog.py [--repo PATH] [--json]            # dry run (default): print the plan
  python3 migrate_backlog.py [--repo PATH] --apply [--json]    # file the issues, delete confirmed lines
  python3 migrate_backlog.py --test

Mapping (docs/design/github-issues-queue.md → Migration):
  - each open `- [ ]` item → one issue: title = the item's first sentence (markers stripped),
    body = the rest of the item with its wrapped lines and nested sub-bullets;
  - a `##`/`###` heading with ≥2 open items → a parent issue (the heading) with each item as a
    sub-issue; a role section's own items (Review Backlog, Security Fixes, Someday) stay lone issues
    and carry the role label (`review`, `security`, `someday`);
  - `*(blocked by: <slug>)*` → a dependency on the issue filed for the heading (or item) the slug
    names; a slug that matches nothing, or more than one heading, refuses the item;
  - `*(deferred: …)*` → label `deferred` plus a `Deferred: <reason>` body line;
  - `## Rejected — do not re-file` bullets → issues closed as not planned with the reason comment
    `queue_backend.py rejected` reads (filed `deferred` first, so a failed close never leaves a
    selectable issue);
  - `## Security Fixes` items on a public repo (or unknown visibility) → refused and listed;
  - `[x]` items are dropped (the CHANGELOG is the closure record); `[>]` items and plain bullets
    outside the Rejected section stay in place and are listed.

Each issue's `create` key is `backlog-migrated:<sha1 of heading path + item>`, so a re-run reuses
the issues already filed and completes their missing relations (`queue_backend.py create` is
retry-safe). `--apply` files under the standing `queue-write` grant, then deletes a backlog.md line only
once its issue exists and every parent/blocker relation it needs is confirmed; unconfirmed lines
stay. The deletion is a working-tree change for the user to commit; the file is deleted when only
headings remain.

Exit: 0 = dry run printed, or every planned line migrated (refused lines are listed, not an error);
1 = error; 3 = --apply left unconfirmed lines in backlog.md (re-run to finish).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backlog_candidates as bc  # noqa: E402
import queue_backend as qb  # noqa: E402
import task_nodes as tn  # noqa: E402

KEY_PREFIX = "backlog-migrated:"
TITLE_MAX = 240  # GitHub caps titles at 256; a longer first sentence is cut and kept whole in the body
EXIT_OK, EXIT_ERROR, EXIT_PARTIAL = 0, 1, 3
ROLE_LABELS = (("review backlog", "review"), ("security fixes", "security"), ("someday", "someday"))
REJECT_DEFAULT_REASON = "rejected in backlog.md before the move to issues"
# a sentence ends at . ! ? followed by whitespace and a capital, digit, code span, quote or bracket
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[*])")
_ABBREV_RE = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|cf|approx|incl|no|fig)\.)$", re.IGNORECASE)
_MARKER_SPAN_RE = re.compile(bc._BLOCK_MARKER_RE.pattern, re.IGNORECASE | re.DOTALL)
_PLAIN_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")


class MigrateError(Exception):
    """Reported on stderr with exit 1."""


def migration_key(*parts: str) -> str:
    return KEY_PREFIX + hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def _role(path: list[dict]) -> str | None:
    for h in path:
        title = h["title"].lower()
        for prefix, label in ROLE_LABELS:
            if title.startswith(prefix):
                return label
    return None


def _is_role_heading(h: dict) -> bool:
    return any(h["title"].lower().startswith(prefix) for prefix, _ in ROLE_LABELS)


def _is_rejected(h: dict) -> bool:
    return h["title"].strip().lower() == bc.REJECTED_HEADING


def _paths(headings: list[dict]) -> dict[int, list[dict]]:
    """{heading line: [outermost … this heading]}."""
    stack: list[dict] = []
    out: dict[int, list[dict]] = {}
    for h in headings:
        while stack and stack[-1]["level"] >= h["level"]:
            stack.pop()
        stack.append(h)
        out[h["line"]] = list(stack)
    return out


def _owner_heading(headings: list[dict], line: int) -> dict | None:
    above = [h for h in headings if h["line"] < line]
    return above[-1] if above else None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _item_span(lines: list[str], masked: list[str], owners: dict[int, int], i: int) -> list[int]:
    """0-based line indices of the item opened at `i`: its wrapped lines (`tokenize`'s folding) and the
    nested sub-bullets right after them — what `task_nodes.prune_lines` deletes with it."""
    span = sorted(j for j, o in owners.items() if o == i)
    stop = span[-1]
    content = _indent(masked[i]) + 2
    while (stop + 1 < len(lines) and lines[stop + 1].strip() and _indent(lines[stop + 1]) >= content
           and not tn._CHECKBOX_LINE_RE.match(masked[stop + 1])):
        stop += 1
        span.append(stop)
    return span


def _strip_markers(text: str) -> str:
    return _MARKER_SPAN_RE.sub(lambda m: m.group(0) if m.group(1).lower() == "blocked by"
                               and bc._is_placeholder_payload(m.group(2)) else "", text)


def split_title(text: str) -> tuple[str, str]:
    """(title, rest): the first sentence of `text` as one line, and what follows it. A sentence past
    `TITLE_MAX` is cut at a word with an ellipsis and the whole text becomes the rest."""
    end = None
    for m in _SENTENCE_END_RE.finditer(text):
        if not _ABBREV_RE.search(text[:m.start()]):
            end = m
            break
    head, rest = (text[:end.start()], text[end.end():]) if end else (text, "")
    title = " ".join(head.split())
    if len(title) > TITLE_MAX:
        cut = title[:TITLE_MAX - 1]
        title = (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(",;:—- ") + "…"
        rest = text
    return title, rest.strip()


def _body(parts: list[str]) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _source_line(path: list[dict]) -> str:
    trail = " → ".join(h["title"] for h in path if h["level"] > 1)
    return "Migrated from `backlog.md`" + (f" → {trail}." if trail else ".")


def _rejected_entries(lines: list[str], masked: list[str], headings: list[dict]) -> list[dict]:
    """Plain bullets under `## Rejected — do not re-file`, with their wrapped lines."""
    out: list[dict] = []
    for h in headings:
        if not _is_rejected(h):
            continue
        end = bc._region_end(h, [x for x in headings if x["level"] <= h["level"]])
        i = h["line"]  # 0-based index of the line after the heading
        stop = len(lines) if end == float("inf") else int(end) - 1
        while i < stop:
            m = _PLAIN_BULLET_RE.match(masked[i])
            if m and not bc._CHECKBOX_RE.match(masked[i]) and masked[i] == lines[i]:
                span = [i]
                while i + 1 < stop and lines[i + 1][:1].isspace() and lines[i + 1].strip():
                    i += 1
                    span.append(i)
                text = " ".join(lines[j].strip() for j in span)[2:].strip()
                out.append({"heading": h, "span": span, "text": text})
            i += 1
    return out


def _prunable(text: str, line: str) -> str | None:
    """None when `prune_lines` can delete this item line on its own, else its reason."""
    _, problems = tn.prune_lines(text, [line])
    return "; ".join(problems) if problems else None


def _resolve_blocker(payload: str, groups: list[dict], items: list[dict], me: dict) -> tuple[str, Any]:
    """('heading', group) | ('item', item) | ('none', reason) for one blocked-by payload."""
    tokens = tn._blocker_tokens(payload)
    if not tokens:
        return "none", f"blocker {payload.strip()!r} names nothing resolvable"
    exact = [g for g in groups if tn._blocker_tokens(g["heading"]["title"]) == tokens]
    hits = exact or [g for g in groups if tn._contains_run(tn._slug_tokens(g["heading"]["title"]), tokens)]
    if len(hits) == 1:
        return "heading", hits[0]
    if len(hits) > 1:
        return "none", f"blocker {payload.strip()!r} matches {len(hits)} headings"
    found = [it for it in items if it is not me and tn._contains_run(tn._slug_tokens(it["clean"]), tokens)]
    if len(found) == 1:
        return "item", found[0]
    if len(found) > 1:
        return "none", f"blocker {payload.strip()!r} matches {len(found)} items"
    return "none", f"blocker {payload.strip()!r} matches no heading or item in backlog.md"


def build_plan(text: str, visibility: str) -> dict:
    """The issue plan for `text` (backlog.md). Pure: no gh, no file writes."""
    lines = text.splitlines()
    masked = bc._strip_fenced_blocks(bc._strip_html_comments(text)).splitlines()
    if len(masked) != len(lines):
        raise MigrateError("internal: masked line count does not match backlog.md")
    tokens = bc.tokenize(text)
    headings = bc._headings(tokens)
    paths = _paths(headings)
    owners, _ = tn._line_owners(text)

    items: list[dict] = []
    left: list[dict] = []
    done: list[dict] = []
    refused: list[dict] = []
    for t in tokens:
        if t["type"] != "checkbox":
            continue
        i = t["line"] - 1
        h = _owner_heading(headings, t["line"])
        path = paths[h["line"]] if h else []
        entry = {"line": t["line"], "source": lines[i], "text": t["text"]}
        if t["state"] in "xX":
            done.append(entry)
            continue
        if t["state"] == ">":
            left.append(dict(entry, reason="[>] item (moved to a sprint): not migrated"))
            continue
        span = _item_span(lines, masked, owners, i)
        raw_body = lines[i].split("]", 1)[1].strip() + "\n" + textwrap.dedent("\n".join(lines[j] for j in span[1:]))
        markers = list(_MARKER_SPAN_RE.finditer(raw_body))
        deferred = [" ".join(m.group(2).split()) for m in markers if m.group(1).lower() == "deferred"]
        blockers = [m.group(2) for m in markers if m.group(1).lower() == "blocked by"
                    and not bc._is_placeholder_payload(m.group(2))]
        clean = _strip_markers(raw_body)
        title, rest = split_title(clean)
        role = _role(path)
        items.append(dict(entry, heading=h, path=path, span=span, role=role, deferred=deferred,
                          blockers=blockers, clean=" ".join(clean.split()), title=title, rest=rest,
                          key=migration_key(*(x["title"] for x in path), t["text"])))

    for t in tokens:  # plain bullets outside the Rejected section are not queue items
        if t["type"] == "bullet":
            h = _owner_heading(headings, t["line"])
            in_item = owners.get(t["line"] - 1) is not None or any(t["line"] - 1 in it["span"] for it in items)
            if not in_item and not (h and _is_rejected(h)) and _PLAIN_BULLET_RE.match(masked[t["line"] - 1]):
                left.append({"line": t["line"], "source": lines[t["line"] - 1],
                             "reason": "plain bullet (not a - [ ] item): not migrated"})

    bad: dict[int, str] = {}
    for it in items:
        why = _prunable(text, it["source"])
        if why:
            bad[it["line"]] = f"cannot be deleted mechanically ({why})"
        elif it["role"] == "security" and visibility != "private":
            bad[it["line"]] = (f"security item on a {visibility} repository: never filed there "
                               "(report it privately, or fix it with /dev:task-new)")

    # Groups and blockers depend on which items are refused, and a refusal can cascade to an item
    # blocked by it, so settle both to a fixpoint.
    while True:
        live = [it for it in items if it["line"] not in bad]
        by_heading: dict[int, list[dict]] = {}
        for it in live:
            h = it["heading"]
            lone = h is None or h["level"] == 1 or _is_role_heading(h)
            if not lone:
                by_heading.setdefault(h["line"], []).append(it)
        groups = [{"heading": next(it["heading"] for it in its), "items": its}
                  for _, its in sorted(by_heading.items())]
        all_groups = groups + [{"heading": h, "items": []} for h in headings
                               if h["level"] > 1 and not _is_role_heading(h) and not _is_rejected(h)
                               and h["line"] not in by_heading]
        parent_of: dict[int, str] = {}
        parents: list[dict] = []
        for g in groups:
            if len(g["items"]) >= 2:
                path = paths[g["heading"]["line"]]
                key = migration_key("group", *(x["title"] for x in path))
                parents.append({"key": key, "heading": g["heading"], "path": path})
                for it in g["items"]:
                    parent_of[it["line"]] = key
        group_key = {g["heading"]["line"]: (parent_of[g["items"][0]["line"]] if len(g["items"]) >= 2
                                            else g["items"][0]["key"] if g["items"] else None)
                     for g in all_groups}
        changed = False
        for it in live:
            keys, notes = [], []
            for payload in it["blockers"]:
                kind, hit = _resolve_blocker(payload, all_groups, items, it)
                if kind == "none":
                    bad[it["line"]] = str(hit)
                    changed = True
                    break
                if kind == "heading":
                    key = group_key[hit["heading"]["line"]]
                    if key is None:
                        any_open = any(x["heading"] is hit["heading"] for x in items)
                        if any_open:  # its open items were refused: the dependency cannot be filed
                            bad[it["line"]] = f"blocker {payload.strip()!r} is refused itself"
                            changed = True
                            break
                        notes.append(f"blocker {payload.strip()!r} has no open item left: dependency dropped")
                        continue
                else:
                    if hit["line"] in bad:
                        bad[it["line"]] = f"blocker {payload.strip()!r} is refused itself"
                        changed = True
                        break
                    key = hit["key"]
                if key != it["key"] and key != parent_of.get(it["line"]) and key not in keys:
                    keys.append(key)
            it["blocked_by"], it["notes"] = keys, notes
        if not changed:
            break

    issues: list[dict] = []
    for p in parents:
        h = p["heading"]
        role = _role(p["path"])
        members = [it for it in items if parent_of.get(it["line"]) == p["key"]]
        issues.append({"kind": "parent", "key": p["key"], "title": h["title"],
                       "body": _body([_heading_notes(lines, masked, headings, h, items), _source_line(p["path"])]),
                       "labels": [role] if role else [], "parent_key": None, "blocked_by": [],
                       "line": h["line"], "lines": [], "children": [m["line"] for m in members]})
    for it in items:
        if it["line"] in bad:
            refused.append({"line": it["line"], "source": it["source"], "reason": bad[it["line"]]})
            continue
        labels = ([it["role"]] if it["role"] else []) + (["deferred"] if it["deferred"] else [])
        h = it["heading"]
        notes = "" if it["line"] in parent_of or h is None or _is_role_heading(h) or h["level"] == 1 \
            else _heading_notes(lines, masked, headings, h, items)
        body = _body([it["rest"], f"Deferred: {'; '.join(it['deferred'])}" if it["deferred"] else "",
                      notes, _source_line(it["path"])])
        issues.append({"kind": "item", "key": it["key"], "title": it["title"], "body": body, "labels": labels,
                       "parent_key": parent_of.get(it["line"]), "blocked_by": it["blocked_by"],
                       "line": it["line"], "lines": [j + 1 for j in it["span"]], "source": it["source"],
                       "notes": it["notes"]})
    for r in _rejected_entries(lines, masked, headings):
        title, reason, bar = qb._split_rejected(r["text"])
        title = split_title(title)[0] if len(title) > TITLE_MAX else title
        body = _body([f"Reason: {reason}" if reason else "", f"Re-file only with: {bar}" if bar else "",
                      "Deferred: rejected before the move to issues; closed as not planned on migration",
                      _source_line(paths[r["heading"]["line"]])])
        issues.append({"kind": "rejected", "key": migration_key("rejected", r["text"]), "title": title or r["text"][:TITLE_MAX],
                       "body": body, "labels": ["deferred"], "parent_key": None, "blocked_by": [],
                       "line": r["span"][0] + 1, "lines": [j + 1 for j in r["span"]], "source": lines[r["span"][0]],
                       "reason": reason or REJECT_DEFAULT_REASON, "refile_bar": bar})
    issues.sort(key=lambda x: (x["line"], x["kind"] != "parent"))
    refused.sort(key=lambda x: x["line"])
    left.sort(key=lambda x: x["line"])
    return {"visibility": visibility, "source_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
            "issues": issues, "refused": refused, "left": left, "done": done}


def _heading_notes(lines: list[str], masked: list[str], headings: list[dict], h: dict, items: list[dict]) -> str:
    """Prose under `h` before its next heading that belongs to no item (lost with the heading otherwise)."""
    end = bc._region_end(h, headings)
    stop = len(lines) if end == float("inf") else int(end) - 1
    owned = {j for it in items for j in it["span"]}
    prose = [lines[j] for j in range(h["line"], stop) if j not in owned and masked[j].strip()
             and not bc._CHECKBOX_RE.match(masked[j])]
    return textwrap.dedent("\n".join(prose)).strip()


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _draft(issue: dict) -> dict:
    return {k: issue[k] for k in ("key", "title", "body", "labels", "parent_key", "blocked_by")}


def _delete_lines(text: str, plan: dict, confirmed: set[str]) -> tuple[str, list[str]]:
    """Remove confirmed rejected bullets, then prune confirmed items and every [x] line."""
    lines = text.splitlines(keepends=True)
    drop: set[int] = set()
    rejected = [i for i in plan["issues"] if i["kind"] == "rejected"]
    for r in rejected:
        if r["key"] in confirmed:
            drop.update(j - 1 for j in r["lines"])
    if drop:
        kept = [ln for j, ln in enumerate(lines) if j not in drop]
        # a Rejected heading this run emptied goes too, with the blank lines it leaves
        masked_kept = bc._strip_fenced_blocks(bc._strip_html_comments("".join(kept))).splitlines()
        heads = [h for h in bc._headings(bc.tokenize("".join(kept))) if _is_rejected(h)]
        for h in reversed(heads):
            end = bc._region_end(h, [x for x in bc._headings(bc.tokenize("".join(kept))) if x["level"] <= h["level"]])
            stop = len(kept) if end == float("inf") else int(end) - 1
            region = masked_kept[h["line"]:stop]
            if all(not x.strip() or x.strip() == "" for x in region) and all(r["key"] in confirmed for r in rejected):
                del kept[h["line"] - 1:stop]
                masked_kept = bc._strip_fenced_blocks(bc._strip_html_comments("".join(kept))).splitlines()
        text = "".join(kept)
    targets = [i["source"] for i in plan["issues"] if i["kind"] == "item" and i["key"] in confirmed]
    targets += [d["source"] for d in plan["done"]]
    if not targets:
        return text, []
    return tn.prune_lines(text, targets)


def _only_headings(text: str) -> bool:
    masked = bc._strip_fenced_blocks(bc._strip_html_comments(text)).splitlines()
    return all(not ln.strip() or bc._HEADING_RE.match(ln) for ln in masked)


def _deletable(plan: dict, confirmed: set[str]) -> set[str]:
    """Confirmed keys whose lines may go now. A group's lines go together, and a blocker's lines stay
    while an item blocked by it stays: a re-run rebuilds the plan from what is left in backlog.md,
    so a heading a kept item names must still be there to resolve to the same issue key."""
    issues = [i for i in plan["issues"] if i["kind"] in ("item", "parent")]
    members: dict[str, set[str]] = {}
    for i in issues:
        if i["parent_key"]:
            members.setdefault(i["parent_key"], {i["parent_key"]}).add(i["key"])
    group = {k: g for g in members.values() for k in g}
    keep = {i["key"] for i in issues if i["key"] not in confirmed}
    while True:
        grown = set(keep)
        for i in issues:
            if i["key"] in grown:
                grown |= group.get(i["key"], set())
                for b in i["blocked_by"]:
                    grown |= group.get(b, {b})
        if grown == keep:
            break
        keep = grown
    return {k for k in confirmed if k not in keep}


def apply_plan(repo: str, plan: dict, runner=qb.gh_runner) -> dict:
    path = os.path.join(repo, "backlog.md")
    report: dict = {"created": [], "incomplete": [], "pending": [], "rejected_closed": [], "deleted": [],
                    "kept": [], "file_deleted": False}
    drafts = [_draft(i) for i in plan["issues"]]
    if not drafts:
        res = {"created": [], "incomplete": [], "pending": []}
    else:
        res = qb.github_create({"contract": qb.CONTRACT, "repo": repo, "items": drafts}, runner)
    report.update(created=res["created"], incomplete=res["incomplete"], pending=res["pending"])
    if res.get("error"):
        report["error"] = res["error"]
    if res.get("pending_path"):
        report["pending_path"] = res["pending_path"]
    unsettled = set(res["pending"]) | {i["key"] for i in res["incomplete"]}
    refs = {c["key"]: c["ref"] for c in res["created"]}
    confirmed = {k for k in refs if k not in unsettled}

    deletable = _deletable(plan, confirmed)
    rejected = [i for i in plan["issues"] if i["kind"] == "rejected" and i["key"] in confirmed]
    if rejected:
        try:
            closed = {e["ref"] for e in qb.github_rejected({"repo": repo}, runner)["entries"]}
        except qb.QueueError as e:
            closed = None
            report.setdefault("error", str(e))
        for r in rejected:
            ref = refs[r["key"]]
            if closed is None:
                confirmed.discard(r["key"])
                deletable.discard(r["key"])
                continue
            if ref not in closed:
                try:
                    qb.github_reject({"repo": repo, "ref": ref, "reason": r["reason"],
                                      "refile_bar": r["refile_bar"] or None}, runner)
                except qb.QueueError as e:
                    confirmed.discard(r["key"])
                    deletable.discard(r["key"])
                    report["incomplete"].append({"key": r["key"], "relation": "close", "ref": ref, "error": str(e)})
                    continue
            report["rejected_closed"].append(ref)

    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    if hashlib.sha1(text.encode("utf-8")).hexdigest() != plan["source_sha1"]:
        raise MigrateError("backlog.md changed while migrating; no line was deleted. The filed issues are "
                           "reused on a re-run — run migrate_backlog.py --apply again")
    new_text, problems = _delete_lines(text, plan, deletable)
    if problems:
        raise MigrateError("no line was deleted; prune refused: " + "; ".join(problems))
    by_key = {i["key"]: i for i in plan["issues"]}
    for key in sorted(deletable, key=lambda k: by_key[k]["line"]):
        if by_key[key]["kind"] != "parent":
            report["deleted"].append({"line": by_key[key]["line"], "ref": refs[key], "title": by_key[key]["title"]})
    report["deleted"] += [{"line": d["line"], "ref": None, "title": "[x] " + d["text"]} for d in plan["done"]]
    report["kept"] = [{"line": i["line"], "key": i["key"], "title": i["title"],
                       "reason": "issue or relation not confirmed" if i["key"] not in confirmed
                       else "filed; kept until the items it groups or blocks are confirmed"}
                      for i in plan["issues"] if i["kind"] != "parent" and i["key"] not in deletable]
    if _only_headings(new_text):
        os.remove(path)
        report["file_deleted"] = True
    elif new_text != text:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_text)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def visibility(repo: str, runner=qb.gh_runner) -> str:
    code, data = qb.github_op("describe", {"contract": qb.CONTRACT, "repo": repo}, runner)
    return data["visibility"] if code == qb.EXIT_OK and data else "unknown"


def render_plan(plan: dict, target: str, path: str) -> str:
    out = [f"migrate_backlog: {path} → {target} ({plan['visibility']})", ""]
    issues = plan["issues"]
    by_key = {i["key"]: i for i in issues}

    def label(i: dict) -> str:
        return f" [{', '.join(i['labels'])}]" if i["labels"] else ""

    out.append(f"Issues to file ({sum(i['kind'] != 'rejected' for i in issues)}):")
    for i in issues:
        if i["kind"] == "rejected":
            continue
        indent = "    └ " if i["parent_key"] else "  "
        what = "parent " if i["kind"] == "parent" else ""
        out.append(f"{indent}L{i['line']:<4} {what}{i['title']}{label(i)}")
        for b in i["blocked_by"]:
            out.append(f"{' ' * len(indent)}       blocked by L{by_key[b]['line']}: {by_key[b]['title']}")
        for n in i.get("notes") or []:
            out.append(f"{' ' * len(indent)}       note: {n}")
    rej = [i for i in issues if i["kind"] == "rejected"]
    if rej:
        out += ["", f"Rejected → closed as not planned ({len(rej)}):"]
        out += [f"  L{i['line']:<4} {i['title']} — {i['reason']}" for i in rej]
    for name, rows in (("Refused, kept in backlog.md", plan["refused"]), ("Left in place", plan["left"])):
        if rows:
            out += ["", f"{name} ({len(rows)}):"]
            out += [f"  L{r['line']:<4} {r['reason']}: {r['source'].strip()[:100]}" for r in rows]
    if plan["done"]:
        out += ["", f"[x] lines deleted with the migration ({len(plan['done'])}):"]
        out += [f"  L{d['line']:<4} {d['source'].strip()[:100]}" for d in plan["done"]]
    return "\n".join(out)


def _opt(argv: list[str], name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            raise MigrateError(f"{name} needs a value")
        return argv[i + 1]
    return None


def main(argv: list[str], runner=qb.gh_runner) -> int:
    if argv[:1] == ["--test"]:
        return run_tests()
    known = {"--apply", "--json", "--repo"}
    unknown = [a for i, a in enumerate(argv) if a.startswith("--") and a not in known]
    if unknown:
        sys.stderr.write(f"migrate_backlog: unknown option {unknown[0]}\nusage: migrate_backlog.py "
                         "[--repo PATH] [--apply] [--json] | --test\n")
        return EXIT_ERROR
    try:
        repo = _opt(argv, "--repo") or qb._git(os.getcwd(), "rev-parse", "--show-toplevel")
        if not repo:
            raise MigrateError("not inside a git repository; pass --repo")
        repo = os.path.abspath(repo)
        owner, name = qb.github_slug(repo)
        path = os.path.join(repo, "backlog.md")
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except FileNotFoundError:
            raise MigrateError(f"{path} does not exist: nothing to migrate") from None
        if bc.unclosed_fence_line(text):
            raise MigrateError(f"{path} has an unclosed code fence at line {bc.unclosed_fence_line(text)}; fix it first")
        apply = "--apply" in argv
        vis = visibility(repo, runner) if apply else _try_visibility(repo, runner)
        plan = build_plan(text, vis)
        if not apply:
            if "--json" in argv:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print(render_plan(plan, f"{owner}/{name}", path))
                print("\nDry run: nothing was filed. Check the plan against backlog.md, then re-run with --apply.")
            return EXIT_OK
        report = apply_plan(repo, plan, runner)
    except (MigrateError, qb.QueueError) as e:
        sys.stderr.write(f"migrate_backlog: {e}\n")
        return EXIT_ERROR
    report["refused"] = plan["refused"]
    report["left"] = plan["left"]
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_report(report, path))
    return EXIT_PARTIAL if report["kept"] or report.get("error") else EXIT_OK


def _try_visibility(repo: str, runner) -> str:
    try:
        return visibility(repo, runner)
    except qb.QueueError as e:
        sys.stderr.write(f"migrate_backlog: visibility unknown ({e}); security items are refused in this plan\n")
        return "unknown"


def _render_report(report: dict, path: str) -> str:
    out = [f"migrate_backlog --apply: {path}"]
    made = [c for c in report["created"] if not c["reused"]]
    out.append(f"  filed {len(made)} issue(s), reused {len(report['created']) - len(made)}")
    if report["rejected_closed"]:
        out.append(f"  closed as not planned: {', '.join(report['rejected_closed'])}")
    out.append(f"  deleted {len(report['deleted'])} backlog.md item(s)"
               + ("; backlog.md deleted (nothing left)" if report["file_deleted"] else ""))
    for k in report["kept"]:
        out.append(f"  kept L{k['line']}: {k['title']} — {k['reason']}")
    for r in report["refused"]:
        out.append(f"  refused L{r['line']}: {r['reason']}")
    for i in report["incomplete"]:
        out.append(f"  incomplete {i['key']}: {i['relation']} {i.get('ref') or ''} {i.get('error', '')}".rstrip())
    if report.get("error"):
        out.append(f"  error: {report['error']}")
    if report.get("pending_path"):
        out.append(f"  pending drafts: {report['pending_path']}")
    if report["kept"] or report.get("error"):
        out.append("  Re-run migrate_backlog.py --apply to finish: filed issues are reused, not duplicated.")
    out.append("  Commit the backlog.md change yourself.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Self-check (--test) — temp repos and a fake gh only
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0


def _assert(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {label}")
    else:
        FAIL += 1
        print(f"  FAIL: {label}")


FIXTURE = """# Backlog

<!-- template
## Feature Name
- [ ] Simplest case
-->

## 1 — alpha feature

- [ ] [FEAT] First alpha item. More detail here.
  Wrapped continuation line.
  - nested note
- [ ] [FEAT] Second alpha item

## 2 — beta work

- [ ] [FIX] Beta fix needs alpha. Body text. *(blocked by: 1-alpha-feature)*

## 3 — gamma

- [ ] [DOCS] Gamma doc waits on a missing ticket *(blocked by: 9-missing-ticket)*

## 4 — delta

- [ ] [DOCS] Delta waits on gamma *(blocked by: 3-gamma)*

## Review Backlog

### PR #5 — thing (2026-01-01)

- [ ] [debt] Deferred thing, e.g. Firefox only. Needs a browser. *(deferred: needs a
  real browser)*
- [x] [debt] Done thing

### PR #6 — other

- [ ] [debt] Lone review item — `src/x.py`
- [>] [debt] Item already in a sprint

## Security Fixes — repo

- [ ] [SECURITY] Patch CVE-1 in lib

## Someday

- [ ] Someday idea one
- [ ] Someday idea two
- a plain note, not an item

## Rejected — do not re-file

- **Use a database** (2026-01-01) — overkill for a static site. Re-file only with a write path.
"""


class _FakeGh(qb._FakeGitHub):
    """`_FakeGitHub` plus `describe` and a switch that refuses every addBlockedBy."""

    def __init__(self, private: bool = False):
        super().__init__(private=private)
        self.refuse_blockers = False

    def _graphql(self, query, v):
        if query == qb.DESCRIBE_QUERY:
            return self._ok({"data": {"repository": {"isPrivate": self.private}}})
        if query == qb.ADD_BLOCKED_BY and self.refuse_blockers:
            return self._ok({"data": None, "errors": [{"message": "dependency limit reached"}]})
        return super()._graphql(query, v)


def run_tests() -> int:
    import tempfile

    print("=== migrate_backlog.py --test ===\n")
    selectors = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", qb.ENV_VAR, "XDG_CONFIG_HOME"}
    env = {k: v for k, v in os.environ.items() if k not in selectors}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})
    saved_env = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)

    def git(cwd: str, *args: str) -> None:
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull,
                        "-C", cwd, *args], check=True, capture_output=True)

    def write(path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def read(path: str) -> str:
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def make_repo(tmp: str, name: str, origin: str) -> str:
        repo = os.path.realpath(os.path.join(tmp, name))
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        write(os.path.join(repo, "backlog.md"), FIXTURE)
        git(repo, "add", "backlog.md")
        git(repo, "commit", "-q", "--no-verify", "-m", "base")
        git(repo, "remote", "add", "origin", origin)
        return repo

    try:
        with tempfile.TemporaryDirectory() as tmp:
            _plan_tests()
            _apply_tests(tmp, make_repo, read, write)
            _warning_tests(tmp, make_repo)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


def quiet(fn, *args, **kwargs):
    """Call `fn` with stdout captured: the CLI's report is not test output."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _by_title(plan: dict, prefix: str) -> dict:
    hits = [i for i in plan["issues"] if i["title"].startswith(prefix)]
    assert len(hits) == 1, (prefix, [i["title"] for i in plan["issues"]])
    return hits[0]


def _plan_tests() -> None:
    print("Test 1: plan — groups, blockers, deferred, rejected, security, keys")
    plan = build_plan(FIXTURE, "public")
    parent = _by_title(plan, "1 — alpha feature")
    first = _by_title(plan, "[FEAT] First alpha item.")
    second = _by_title(plan, "[FEAT] Second alpha item")
    _assert(parent["kind"] == "parent" and first["parent_key"] == parent["key"] == second["parent_key"],
            "a heading with 2 open items → parent issue + 2 sub-issues")
    _assert(first["body"].startswith("More detail here.\nWrapped continuation line.\n- nested note")
            and "Migrated from `backlog.md` → 1 — alpha feature." in first["body"],
            "title = first sentence; body = the rest, wrapped lines, nested bullets and the source")
    beta = _by_title(plan, "[FIX] Beta fix needs alpha.")
    _assert(beta["blocked_by"] == [parent["key"]] and beta["parent_key"] is None and "blocked by" not in beta["body"],
            "blocked by a ticket slug → a dependency on that heading's parent issue; marker stripped")
    refused = {r["line"]: r["reason"] for r in plan["refused"]}
    gamma_line = next(n for n, ln in enumerate(FIXTURE.splitlines(), 1) if "Gamma doc" in ln)
    delta_line = gamma_line + 4
    _assert("matches no heading" in refused.get(gamma_line, ""), "a blocker slug that matches nothing refuses the item")
    _assert("refused itself" in refused.get(delta_line, ""), "an item blocked by a refused item is refused too")
    deferred = _by_title(plan, "[debt] Deferred thing, e.g. Firefox only.")
    _assert(deferred["labels"] == ["review", "deferred"] and "Deferred: needs a real browser" in deferred["body"]
            and "*(deferred" not in deferred["body"],
            "deferred → label + Deferred: line (a wrapped marker too); e.g. does not end the title")
    lone = _by_title(plan, "[debt] Lone review item")
    _assert(lone["parent_key"] is None and lone["labels"] == ["review"], "a 1-item review heading → lone issue, label review")
    someday = [i for i in plan["issues"] if i["title"].startswith("Someday idea")]
    _assert(len(someday) == 2 and all(i["parent_key"] is None and i["labels"] == ["someday"] for i in someday),
            "a role section's own items stay lone issues with the role label")
    security_line = next(n for n, ln in enumerate(FIXTURE.splitlines(), 1) if "CVE-1" in ln)
    _assert("public" in refused.get(security_line, ""), "a Security Fixes item on a public repo is refused")
    priv = build_plan(FIXTURE, "private")
    _assert(_by_title(priv, "[SECURITY] Patch CVE-1")["labels"] == ["security"],
            "the same item on a private repo is filed with label security")
    _assert("unknown" in {r["line"]: r["reason"] for r in build_plan(FIXTURE, "unknown")["refused"]}[security_line],
            "unknown visibility refuses security items too")
    rej = _by_title(plan, "Use a database")
    _assert(rej["kind"] == "rejected" and rej["reason"] == "overkill for a static site."
            and rej["refile_bar"] == "a write path" and rej["labels"] == ["deferred"],
            "a Rejected bullet → a deferred issue to close not planned, with reason and re-file bar")
    _assert(not any("Simplest case" in i["title"] for i in plan["issues"]), "an item inside an HTML comment is not migrated")
    _assert([d["text"] for d in plan["done"]] == ["[debt] Done thing"], "[x] items are listed for deletion, not filed")
    left = [r["source"] for r in plan["left"]]
    _assert(any("[>]" in s for s in left) and any("plain note" in s for s in left),
            "[>] items and plain bullets are left in place and listed")
    keys = [i["key"] for i in plan["issues"]]
    _assert(all(re.fullmatch(r"backlog-migrated:[0-9a-f]{40}", k) for k in keys) and len(set(keys)) == len(keys)
            and keys == [i["key"] for i in build_plan(FIXTURE, "public")["issues"]],
            "keys are backlog-migrated:<sha1>, unique, and stable across runs")
    long = "- [ ] [FEAT] " + "word " * 60 + "end. Second sentence."
    t, rest = split_title(long[6:])
    _assert(len(t) <= TITLE_MAX and t.endswith("…") and rest.startswith("[FEAT] word"),
            "an over-long first sentence is cut with an ellipsis and kept whole in the body")


def _apply_tests(tmp: str, make_repo, read, write) -> None:
    print("\nTest 2: --apply — files, closes rejected, deletes confirmed lines only")
    repo = make_repo(tmp, "apply", "https://github.com/owner/repo.git")
    path = os.path.join(repo, "backlog.md")
    gh = _FakeGh()
    plan = build_plan(read(path), visibility(repo, gh))
    report = apply_plan(repo, plan, gh)
    text = read(path)
    by_title = {i["title"]: n for n, i in gh.issues.items()}
    parent_n = by_title["1 — alpha feature"]
    _assert(gh.issues[by_title["[FEAT] First alpha item."]]["parent"] == parent_n
            and gh.issues[by_title["[FEAT] Second alpha item"]]["parent"] == parent_n,
            "sub-issues are linked to their parent")
    _assert(gh.issues[by_title["[FIX] Beta fix needs alpha."]]["blockedBy"] == [parent_n],
            "the blocked-by marker became addBlockedBy on the heading's issue")
    rej = gh.issues[by_title["Use a database"]]
    _assert(rej["state"] == "CLOSED" and rej["stateReason"] == "NOT_PLANNED"
            and any("Reason: overkill for a static site." in c["body"] for c in rej["comments"]),
            "a rejected entry is closed not planned with the reason comment")
    listed = qb.github_rejected({"repo": repo}, gh)["entries"]
    _assert([e["title"] for e in listed] == ["Use a database"] and listed[0]["refile_bar"] == "a write path",
            "queue_backend rejected lists the migrated entry")
    _assert(all(qb.QUEUE_LABEL in i["labels"] for i in gh.issues.values()), "every filed issue carries task-queue")
    _assert(not any(s in text for s in ("First alpha", "Beta fix", "Lone review", "Someday idea", "Use a database",
                                        "Done thing", "nested note", "Wrapped continuation")),
            "confirmed items, their wrapped lines, [x] lines and rejected bullets are deleted")
    _assert(all(s in text for s in ("Gamma doc", "Delta waits", "CVE-1", "[>] [debt] Item already", "plain note")),
            "refused, [>] and plain-bullet lines stay")
    _assert("## 1 — alpha feature" not in text and "## Rejected" not in text and "## 3 — gamma" in text,
            "emptied headings go; headings with surviving lines stay")
    _assert(not report["kept"] and not report.get("error"), "a clean apply keeps nothing it planned to move")

    print("\nTest 3: --apply — re-run reuses; a partial run keeps every unconfirmed line")
    repo = make_repo(tmp, "partial", "git@github.com:owner/repo.git")
    path = os.path.join(repo, "backlog.md")
    gh = _FakeGh()
    gh.refuse_blockers = True
    report = apply_plan(repo, build_plan(read(path), "public"), gh)
    text = read(path)
    _assert("Beta fix" in text and "First alpha" in text and "Second alpha" in text and "Lone review" not in text,
            "a failed blocker relation keeps that line and its blocker's group (so a re-run resolves it); others go")
    kept = {k["title"]: k["reason"] for k in report["kept"]}
    _assert(kept.get("[FIX] Beta fix needs alpha.") == "issue or relation not confirmed"
            and kept.get("[FEAT] First alpha item.", "").startswith("filed; kept until"),
            "the report names the unconfirmed line and the filed lines held for it")
    _assert(quiet(main, ["--repo", repo, "--apply", "--json"], runner=gh) == EXIT_PARTIAL, "the CLI exits 3 on a partial run")
    gh.refuse_blockers = False
    n_before = len(gh.issues)
    report = apply_plan(repo, build_plan(read(path), "public"), gh)
    beta_n = next(n for n, i in gh.issues.items() if i["title"].startswith("[FIX] Beta"))
    _assert(len(gh.issues) == n_before and all(c["reused"] for c in report["created"])
            and bool(gh.issues[beta_n]["blockedBy"]) and "Beta fix" not in read(path) and "First alpha" not in read(path),
            "a re-run reuses the filed issue, completes the relation and deletes the line")

    repo = make_repo(tmp, "dropped", "git@github.com:owner/repo.git")
    path = os.path.join(repo, "backlog.md")
    gh = _FakeGh()
    gh.fail_after = 12  # gh dies part-way through filing
    report = apply_plan(repo, build_plan(read(path), "public"), gh)
    survivors = read(path)
    _assert(bool(report.get("error")) and "Someday idea two" in survivors and "Use a database" in survivors,
            "gh failing mid-run → unfiled items stay in backlog.md")
    gh.fail_after = None
    gh.calls.clear()
    n_before = len(gh.issues)
    report = apply_plan(repo, build_plan(read(path), "public"), gh)
    titles = [i["title"] for i in gh.issues.values()]
    _assert(len(titles) == len(set(titles)), "re-run after a dropped gh files no duplicate issue")
    _assert("Someday idea two" not in read(path) and not report["kept"], "the re-run finishes the migration")

    print("\nTest 4: --apply — file deleted when only headings remain; changed file refuses deletion")
    repo = make_repo(tmp, "empty", "git@github.com:owner/repo.git")
    path = os.path.join(repo, "backlog.md")
    write(path, "# Backlog\n\n## 7 — one\n\n- [ ] [FEAT] Only item\n\n## Someday\n\n- [ ] Idea\n")
    gh = _FakeGh()
    report = apply_plan(repo, build_plan(read(path), "public"), gh)
    _assert(report["file_deleted"] and not os.path.exists(path), "nothing left → backlog.md is deleted")
    write(path, "# Backlog\n\n- [ ] [FEAT] Moving target\n")
    plan = build_plan(read(path), "public")
    write(path, "# Backlog\n\n- [ ] [FEAT] Moving target\n- [ ] [FEAT] added meanwhile\n")
    try:
        apply_plan(repo, plan, gh)
        changed = False
    except MigrateError as e:
        changed = "changed while migrating" in str(e)
    _assert(changed and "added meanwhile" in read(path), "a backlog.md edited mid-run is never pruned")
    _assert(quiet(main, ["--repo", repo, "--json"], runner=gh) == EXIT_OK and "Moving target" in read(path),
            "the default run is a dry run: nothing deleted")


def _warning_tests(tmp: str, make_repo) -> None:
    print("\nTest 5: queue_backend list warns on a github.com repo still on the file queue")
    repo = make_repo(tmp, "warn", "https://github.com/owner/repo.git")
    code, data = qb.handle("list", {"contract": 1, "repo": repo, "full_scan": True}, {})
    assert data is not None
    n = qb.backlog_open_items(repo)
    want = f"backlog.md has {n} open item(s); this repo stays on the file queue until you run migrate_backlog.py"
    _assert(code == 0 and want in data["warnings"], f"the warning names the open item count ({n})")
    other = make_repo(tmp, "elsewhere", "https://git.example.org/owner/repo.git")
    code, data = qb.handle("list", {"contract": 1, "repo": other, "full_scan": True}, {"XDG_CONFIG_HOME": tmp})
    assert data is not None
    _assert(code == 0 and not any("migrate_backlog" in w for w in data["warnings"]),
            "a non-GitHub repo on the file queue gets no migration warning")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
