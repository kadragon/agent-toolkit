#!/usr/bin/env python3
"""queue_backend.py — the one entry point for task-queue access (contract version 1).

Usage:
  python3 queue_backend.py <op>      # one JSON request on stdin, one JSON response on stdout
  python3 queue_backend.py --test

Contract: `../references/queue-backend-contract.md` (ops, request/response fields, exit codes).
Exit 0 = ok, 2 = op unsupported by the resolved backend, 1 = error. Diagnostics go to stderr.
Every request carries `"contract": 1` and `"repo": "<abs toplevel>"`.

Backend resolution, first match wins:
  1. `AGENT_QUEUE_BACKEND` — `backlog`, `github`, or an adapter command (shell-split).
  2. `origin` host `github.com` → `github`, unless `backlog.md` still has open `- [ ]`
     items (including parked items) or legacy `- [>]` items with a file sprint claim.
  3. `${XDG_CONFIG_HOME:-~/.config}/agent-toolkit/queue-backends.json`
     (`{"hosts": {"<origin host>": ["cmd", "arg", ...]}}`) → that adapter command.
  4. `backlog`.

`backlog` is built in: `list` runs `backlog_candidates.py` and maps its JSON onto the contract,
`show` and `rejected` read `backlog.md` directly, and `create` answers `{"edit_file":
"backlog.md"}` so the caller keeps its hand-edit path. `github` reads `describe`, `list`,
`inventory`, `show` and `rejected` from `gh api graphql` and writes
`create`/`reject`/`defer`/`publish` through
`gh api` (an injectable runner, so `--test` needs no network); `gh` missing or unauthenticated is
exit 1 on a read. A `create` that cannot finish (gh failing mid-write, an incomplete relation, or
`"queue_limits": "no-queue-write"`) keeps the unfiled drafts in
`$(git rev-parse --git-common-dir)/agent-queue/pending.json`; `publish` posts them later. An adapter command receives `<op>` as its last argument and
the request on stdin; its stdout and exit code pass through.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import contextmanager
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backlog_candidates as bc  # noqa: E402

CONTRACT = 1
BACKLOG_OPS = ("describe", "list", "show", "create", "rejected")
OPS = (*BACKLOG_OPS, "reject", "defer", "publish", "inventory")
EXIT_OK, EXIT_ERROR, EXIT_UNSUPPORTED = 0, 1, 2
ENV_VAR = "AGENT_QUEUE_BACKEND"
LEGACY_BACKLOG_WARNING = ("backlog.md has {n} open item(s); this repo stays on the file queue until you run "
                          "migrate_backlog.py")
_TAG_RE = re.compile(r"^\[([^\[\]\s]+)\]")
_REFILE_RE = re.compile(r"\s*re-file\s+only\s*(?:with|if|when)?\s*", re.IGNORECASE)


class QueueError(Exception):
    """An error the CLI reports on stderr with exit 1."""


class GhUnavailable(QueueError):
    """`gh` failed to start, authenticate or answer; a write stops and its drafts go pending."""

    partial: dict | None = None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _git(repo: str, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", check=False)
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def origin_host(url: str | None) -> str | None:
    """Host of a git remote URL: `https://h/x`, `ssh://u@h:22/x`, or scp-like `u@h:x`."""
    if not url:
        return None
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]*@)?(\[[^\]]+\]|[^/:]+)", url)
    if m:
        return m.group(1).lower()
    m = re.match(r"^(?:[^@/]+@)?([^/:]+):(?!//)", url)
    if m and not re.match(r"^[a-zA-Z]:[\\/]", url):  # not a Windows drive path
        return m.group(1).lower()
    return None


def registry_path(env: dict[str, str]) -> str:
    base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "agent-toolkit", "queue-backends.json")


def _registry_command(host: str, env: dict[str, str]) -> list[str] | None:
    path = registry_path(env)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise QueueError(f"unreadable queue backend registry {path}: {e}") from e
    if not isinstance(data, dict) or not isinstance(hosts := data.get("hosts", {}), dict):
        raise QueueError(f"{path}: hosts must be an object")
    cmd = hosts.get(host)
    if cmd is None:
        return None
    if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
        raise QueueError(f"{path}: hosts[{host!r}] must be a non-empty list of strings")
    return cmd


def _backlog_items(repo: str, rev: str | None = None) -> tuple[int, list[str]]:
    if rev:
        sha = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
        if not sha:
            raise QueueError(f"ref {rev!r} does not resolve to a commit in {repo}")
        text = _git(repo, "show", f"{sha}:backlog.md") or ""
    else:
        path = os.path.join(repo, "backlog.md")
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            return 0, []
        except (OSError, ValueError) as e:  # unreadable is not "empty": never flip to github on it
            raise QueueError(f"cannot read {path}: {e}") from e
    items = [t for t in bc.tokenize(text) if t["type"] == "checkbox"]
    lines = text.splitlines()
    open_count = sum(1 for item in items if item["state"] == " ")
    in_flight = [lines[item["line"] - 1].split("]", 1)[1].strip() for item in items if item["state"] == ">"]
    return open_count, in_flight


def backlog_open_items(repo: str, rev: str | None = None) -> int:
    """Count unchecked file items, including parked items and excluding legacy in-flight items."""
    return _backlog_items(repo, rev)[0]


def _has_file_claim(repo: str, rev: str | None, in_flight: list[str]) -> bool:
    if rev:
        entry = _git(repo, "ls-tree", rev, "--", "tasks.md")
        if entry is None:
            raise QueueError(f"cannot inspect tasks.md at {rev}")
        if not entry:
            return False
        tasks = _git(repo, "show", f"{rev}:tasks.md")
        if tasks is None or entry.split()[1] != "blob":
            raise QueueError(f"cannot read tasks.md at {rev}")
    else:
        path = os.path.join(repo, "tasks.md")
        try:
            with open(path, encoding="utf-8") as fh:
                tasks = fh.read()
        except FileNotFoundError:
            return False
        except (OSError, ValueError) as e:
            raise QueueError(f"cannot read {path}: {e}") from e
    return bool(tasks and not bc.item_keys(tasks, under="Covers").isdisjoint(in_flight))


def resolve(repo: str, env: dict[str, str] | None = None, rev: str | None = None) -> dict:
    """{"backend": "backlog"|"github"|"adapter", "source": <rule>, "command": [...] (adapter)}."""
    env = dict(os.environ) if env is None else env
    explicit = (env.get(ENV_VAR) or "").strip()
    if explicit:
        if explicit in ("backlog", "github"):
            return {"backend": explicit, "source": "env"}
        return {"backend": "adapter", "source": "env", "command": split_command(explicit)}
    host = origin_host(_git(repo, "remote", "get-url", "origin"))
    if host == "github.com":
        open_items, in_flight = _backlog_items(repo, rev)
        active_items = len(in_flight)
        if open_items or (in_flight and _has_file_claim(repo, rev, in_flight)):
            return {"backend": "backlog", "source": "github-open-backlog",
                    "open_items": open_items, "active_items": active_items}
        if active_items:
            return {"backend": "github", "source": "github-host", "active_items": active_items}
        return {"backend": "github", "source": "github-host"}
    if host:
        cmd = _registry_command(host, env)
        if cmd:
            return {"backend": "adapter", "source": "registry", "command": cmd}
    return {"backend": "backlog", "source": "fallback"}


def split_command(line: str, posix: bool | None = None) -> list[str]:
    """Shell-split an adapter command line; Windows mode keeps backslashes in paths."""
    posix = os.name != "nt" if posix is None else posix
    try:
        parts = shlex.split(line, posix=posix)
    except ValueError as e:
        raise QueueError(f"{ENV_VAR} is not a valid command line ({e}): {line!r}") from e
    if not posix:  # non-POSIX mode keeps the quotes around a quoted argument
        parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    return parts


# ---------------------------------------------------------------------------
# Built-in `backlog` backend
# ---------------------------------------------------------------------------

def _ref(label: str, line: int) -> str:
    return f"{label}:{line}"


def _tag(texts: list[str]) -> str:
    tags = {m.group(1) if (m := _TAG_RE.match(t.strip())) else "" for t in texts}
    return tags.pop() if len(tags) == 1 else ""


def _run_candidates(args: list[str]) -> tuple[Any, list[str]]:
    script = os.path.join(HERE, "backlog_candidates.py")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, script, *args], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, check=False)
    warnings = [line for line in out.stderr.splitlines() if line.strip()]
    if out.returncode != 0:
        raise QueueError("backlog_candidates.py failed: " + ("; ".join(warnings) or f"exit {out.returncode}"))
    try:
        return json.loads(out.stdout), warnings
    except ValueError as e:
        raise QueueError(f"backlog_candidates.py printed no JSON: {e}") from e


def _paths(req: dict) -> tuple[str, str]:
    repo = req["repo"]
    tasks = req.get("tasks") or os.path.join(repo, "tasks.md")
    if not os.path.isabs(tasks):
        tasks = os.path.join(repo, tasks)
    return os.path.join(repo, "backlog.md"), tasks


def _resolve_rev(req: dict, key: str) -> str | None:
    """The commit SHA `req[key]` names, or None when absent; an unresolvable rev is an error."""
    rev = req.get(key)
    if not rev:
        return None
    sha = _git(req["repo"], "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if not sha:
        raise QueueError(f"{key} {rev!r} does not resolve to a commit in {req['repo']}")
    return sha


def _read_queue(path: str, rev: str | None, optional: bool = False) -> str:
    if rev:
        return bc._read_at_ref(path, rev, required=not optional)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError as e:
        if optional:
            return ""
        raise QueueError(f"cannot read {path}: {e}") from e
    except OSError as e:
        raise QueueError(f"cannot read {path}: {e}") from e


def backlog_list(req: dict) -> dict:
    """`backlog_candidates.py --json --counts` mapped onto contract v1 `list`."""
    backlog, tasks = _paths(req)
    rev = _resolve_rev(req, "ref")  # pinned to one SHA, so both reads below see the same commit
    base = ["--tasks", tasks, "--backlog", backlog] + (["--ref", rev] if rev else [])
    raw, warnings = _run_candidates(base + ["--json", "--counts"] + (["--full-scan"] if req.get("full_scan") else []))

    # items[] and claimed[] come from the same tokenizer and claim scan main() runs, so they match
    # the candidate counts; the subprocess stays the selection authority.
    backlog_raw = _read_queue(backlog, rev)
    tokens = bc.tokenize(backlog_raw)
    claims = bc.collect_claims(backlog, tasks, rev or "HEAD", include_self=rev is not None)
    claimed_lines = bc.mark_claimed(backlog_raw, tokens, claims)
    block_lines = bc.mark_claimed_blocks(
        bc.tokenize(_read_queue(tasks, rev, optional=True)),
        bc.collect_block_claims(backlog, tasks, include_self=rev is not None, ref=rev or "HEAD"),
    )
    headings = bc._headings(tokens)
    by_line = {h["line"]: h for h in headings}

    candidates = []
    for c in raw:
        label = c["source"]
        if c["kind"] == "h1":
            items: list[str] = []
        else:
            heading = by_line.get(c["line"])
            items = [t["text"] for t in bc._direct_open_items(tokens, heading, headings)] if heading else []
            if heading is None or heading["title"] != c["title"] or len(items) != c["items"]:
                # The working-tree queue changed between the two reads: never pair one group's
                # title with another group's items.
                raise QueueError(f"{label} changed while listing ({label}:{c['line']}); retry")
        ref = _ref(label, c["line"])
        candidates.append({
            "id": ref, "ref": ref, "title": c["title"], "tag": _tag(items), "labels": [],
            "items": items, "url": "",
            "counts": {"open": c.get("open", 0), "deferred": c.get("deferred", 0), "blocked": c.get("blocked", 0)},
        })

    parked = []
    if req.get("parked"):
        rows, more = _run_candidates(base + ["--parked", "--json"])
        warnings.extend(w for w in more if w not in warnings)
        for row in rows:
            for marker in row["markers"]:
                kind = "blocked" if marker["kind"] == "blocked by" else marker["kind"]
                parked.append({"ref": _ref("backlog.md", row["line"]), "kind": kind, "payload": marker["payload"]})

    claimed = [
        {"ref": _ref(label, line), "by": wt}
        for label, found in (("tasks.md", block_lines), ("backlog.md", claimed_lines))
        for wt, lines in found.items() for line in lines
    ]
    return {"candidates": candidates, "parked": parked, "claimed": claimed, "warnings": warnings, "rev": rev}


_FILE_REF_RE = re.compile(r"(backlog\.md|tasks\.md):(\d+)")


def _parse_ref(ref: object) -> tuple[str, int]:
    m = _FILE_REF_RE.fullmatch(ref) if isinstance(ref, str) else None
    if not m:
        raise QueueError(f"ref must be backlog.md:<line> or tasks.md:<line>, got {ref!r}")
    return m.group(1), int(m.group(2))


def _strip_marker(m: re.Match) -> str:
    """Drop a real marker from a title; keep a placeholder (`<n>-<slug>`) as literal prose."""
    return m.group(0) if m.group(1).lower() == "blocked by" and bc._is_placeholder_payload(m.group(2)) else " "


def backlog_show(req: dict) -> dict:
    label, line = _parse_ref(req.get("ref"))
    backlog, tasks = _paths(req)
    path = backlog if label == "backlog.md" else tasks
    raw = _read_queue(path, _resolve_rev(req, "rev"))
    tokens = bc.tokenize(raw)
    lines = raw.splitlines()
    headings = bc._headings(tokens)
    token = next((t for t in tokens if t["line"] == line and t["type"] in ("heading", "checkbox")), None)
    if token is None:
        raise QueueError(f"{label}:{line} is not a heading or checkbox item")
    if token["type"] == "heading":
        # a tasks.md h1 sprint block owns its `##` sections up to the next h1
        bounds = [h for h in headings if h["level"] == 1] if label == "tasks.md" and token["level"] == 1 else headings
        end = bc._region_end(token, bounds)
        body_lines = lines[line:] if end == float("inf") else lines[line:int(end) - 1]
        outer = [h for h in headings if h["line"] < line and h["level"] < token["level"]]
        return {
            "ref": _ref(label, line), "title": token["title"], "body": "\n".join(body_lines).strip("\n"),
            "labels": [], "blocked_by": [], "parent": _ref(label, outer[-1]["line"]) if outer else None,
            "url": "",
        }
    body_lines = [lines[line - 1]]
    for nxt in lines[line:]:
        if not (nxt[:1].isspace() and nxt.strip()):
            break
        body_lines.append(nxt)
    blocked_by = [
        m.group(2).strip() for m in bc._BLOCK_MARKER_RE.finditer(token["text"])
        if m.group(1).lower() == "blocked by" and not bc._is_placeholder_payload(m.group(2))
    ]
    above = [h for h in headings if h["line"] < line]
    return {
        "ref": _ref(label, line), "title": " ".join(bc._BLOCK_MARKER_RE.sub(_strip_marker, token["text"]).split()),
        "body": "\n".join(body_lines), "labels": [], "blocked_by": blocked_by,
        "parent": _ref(label, above[-1]["line"]) if above else None, "url": "",
    }


def _split_rejected(text: str) -> tuple[str, str, str]:
    """`**title** (...) — reason. Re-file only with <bar>.` → (title, reason, refile_bar)."""
    m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", text)
    if m:
        title, rest = m.group(1).strip(), m.group(2)
        parts = re.split(r"\s*— ", rest, maxsplit=1)
        rest = parts[1] if len(parts) > 1 else rest
    else:
        title, sep, rest = text.partition(" — ")
        title = title.strip()
        rest = rest if sep else ""
    parts = _REFILE_RE.split(rest, maxsplit=1)
    reason = parts[0].strip()
    bar = parts[1].strip().rstrip(".").strip() if len(parts) > 1 else ""
    return title, reason, bar


def backlog_rejected(req: dict) -> dict:
    backlog, _ = _paths(req)
    raw = _read_queue(backlog, _resolve_rev(req, "rev"))
    masked = bc._strip_fenced_blocks(bc._strip_html_comments(raw)).splitlines()
    entries: list[dict] = []
    inside = False
    current: dict | None = None
    for i, line in enumerate(masked, start=1):
        h = bc._HEADING_RE.match(line)
        if h:
            inside = h.group(2).strip().lower() == bc.REJECTED_HEADING
            current = None
            continue
        if not inside:
            continue
        b = re.match(r"^[-*+]\s+(.*)$", line)
        if b and not bc._CHECKBOX_RE.match(line):
            current = {"line": i, "text": b.group(1).strip()}
            entries.append(current)
        elif current is not None and line[:1].isspace() and line.strip():
            current["text"] += " " + line.strip()
        else:
            current = None
    out = []
    for e in entries:
        title, reason, bar = _split_rejected(e["text"])
        out.append({"ref": _ref("backlog.md", e["line"]), "title": title, "reason": reason, "refile_bar": bar})
    return {"entries": out}


def backlog_op(op: str, req: dict) -> tuple[int, dict | None]:
    if op == "describe":
        return EXIT_OK, {
            "backend": "backlog", "contract": CONTRACT, "visibility": "unknown",
            "ops": list(BACKLOG_OPS), "close_ref_template": None,
        }
    if op == "list":
        return EXIT_OK, backlog_list(req)
    if op == "show":
        return EXIT_OK, backlog_show(req)
    if op == "create":
        return EXIT_OK, {"edit_file": "backlog.md"}
    if op == "rejected":
        return EXIT_OK, backlog_rejected(req)
    return EXIT_UNSUPPORTED, None


# ---------------------------------------------------------------------------
# Built-in `github` backend (read path)
# ---------------------------------------------------------------------------

GITHUB_OPS = OPS
QUEUE_LABEL = "task-queue"
TRUSTED_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")
PAGE_SIZE = 50
MAX_PAGES = 20  # per connection; reaching it marks the result incomplete, never an empty queue
_CLOSING_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+(?:([\w.-]+/[\w.-]+))?#(\d+)\b", re.IGNORECASE)
_REF_RE = re.compile(r"(?<![\w/#])#(\d+)\b")
_DEFERRED_LINE_RE = re.compile(r"^\s*Deferred:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)

_NODE_SEL = {
    "labels": "name",
    "blockedBy": "number state repository { nameWithOwner }",
    "subIssues": "id number title state repository { nameWithOwner }",
    "closedByPullRequestsReferences": "number url state authorAssociation",
}
_CONN_ARGS = {"closedByPullRequestsReferences": ", includeClosedPrs: false"}


def _conn(name: str, first: int, after: bool = False) -> str:
    cursor = ", after: $after" if after else ""
    return (f"{name}(first: {first}{cursor}{_CONN_ARGS.get(name, '')}) "
            f"{{ pageInfo {{ hasNextPage endCursor }} nodes {{ {_NODE_SEL[name]} }} }}")


_ISSUE_FIELDS = ("number title body url state authorAssociation repository { nameWithOwner } "
                 "parent { number repository { nameWithOwner } } "
                 + " ".join(_conn(name, PAGE_SIZE) for name in _NODE_SEL))
LIST_QUERY = (
    "query($owner: String!, $name: String!, $after: String) { repository(owner: $owner, name: $name) { "
    f"isPrivate issues(first: {PAGE_SIZE}, after: $after, states: OPEN, labels: [\"{QUEUE_LABEL}\"], "
    "orderBy: {field: CREATED_AT, direction: ASC}) { pageInfo { hasNextPage endCursor } "
    f"nodes {{ {_ISSUE_FIELDS} }} }} }} }}"
)
INVENTORY_QUERY = (
    "query($owner: String!, $name: String!, $after: String) { repository(owner: $owner, name: $name) { "
    f"issues(first: {PAGE_SIZE}, after: $after, states: OPEN, labels: [\"{QUEUE_LABEL}\"], "
    "orderBy: {field: CREATED_AT, direction: ASC}) { pageInfo { hasNextPage endCursor } "
    "nodes { number title body url authorAssociation } } } }"
)
SHOW_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) { "
    f"issue(number: $number) {{ {_ISSUE_FIELDS} }} }} }}"
)
DESCRIBE_QUERY = "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { visibility } }"
UNREAD_CHILDREN_QUERY = (
    "query($ids: [ID!]!) { nodes(ids: $ids) { ... on Issue { id authorAssociation "
    "labels(first: 100) { pageInfo { hasNextPage } nodes { name } } } } }"
)


def _conn_query(name: str) -> str:
    return ("query($owner: String!, $name: String!, $number: Int!, $after: String) { "
            "repository(owner: $owner, name: $name) { issue(number: $number) { "
            f"{_conn(name, 100, after=True)} }} }} }}")


def gh_runner(args: list[str]) -> tuple[int, str, str]:
    if args[:1] == ["api"]:
        args = ["api", "--hostname", "github.com", *args[1:]]
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", check=False)
    except OSError as e:
        raise GhUnavailable("the github queue backend needs the GitHub CLI: install `gh`, then run "
                         f"`gh auth login` ({e}); it never falls back to backlog.md") from e
    return out.returncode, out.stdout, out.stderr


def _graphql(runner, query: str, variables: dict) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    code, out, err = runner(args)
    if code != 0:
        low = err.lower()
        if code == 4 or "gh auth login" in low or "not logged in" in low or "authentication" in low:
            raise QueueError("gh is not authenticated for github.com: run `gh auth login`; "
                             "the github queue backend never falls back to backlog.md")
        raise QueueError(f"gh api graphql failed (exit {code}): {err.strip()}")
    try:
        data = json.loads(out)
    except ValueError as e:
        raise QueueError(f"gh api graphql printed no JSON: {e}") from e
    if data.get("errors"):
        raise QueueError("GitHub GraphQL error: " + "; ".join(str(e.get("message", e)) for e in data["errors"]))
    return data.get("data") or {}


def github_slug(repo: str) -> tuple[str, str]:
    """(owner, name) of the repo's `origin` on github.com."""
    url = _git(repo, "remote", "get-url", "origin")
    if origin_host(url) != "github.com":
        raise QueueError(f"the github queue backend needs a github.com origin in {repo}, got {url!r}")
    # path after scheme://[user@]host[:port]/ or scp-like [user@]host:
    m = (re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/]+/+([^/]+)/([^/]+?)(?:\.git)?/*$", url or "")
         or re.match(r"^(?:[^@/]+@)?[^/:]+:/*([^/]+)/([^/]+?)(?:\.git)?/*$", url or ""))
    if not m:
        raise QueueError(f"cannot read owner/name from origin {url!r}")
    return m.group(1), m.group(2)


def _repository(data: dict, owner: str, name: str) -> dict:
    repo = data.get("repository")
    if repo is None:
        raise QueueError(f"github.com/{owner}/{name} not found or not readable by the gh account")
    return repo


def _complete_connections(runner, owner: str, name: str, issue: dict, max_pages: int) -> bool:
    """Page every nested connection selection depends on; False when a page limit cut one short."""
    for conn in _NODE_SEL:
        c = issue[conn]
        pages = 1
        while c["pageInfo"]["hasNextPage"]:
            if pages >= max_pages:
                return False
            nxt = _repository(_graphql(runner, _conn_query(conn), {
                "owner": owner, "name": name, "number": issue["number"], "after": c["pageInfo"]["endCursor"],
            }), owner, name)["issue"][conn]
            c["nodes"].extend(nxt["nodes"])
            c["pageInfo"] = nxt["pageInfo"]
            pages += 1
    return True


def _fetch_queue(runner, owner: str, name: str, max_pages: int) -> tuple[bool, list[dict], bool]:
    """(is_private, open task-queue issues with complete connections where possible, truncated)."""
    issues: list[dict] = []
    after = None
    pages = 0
    is_private = False
    while True:
        if pages >= max_pages:
            return is_private, issues, True
        repo = _repository(_graphql(runner, LIST_QUERY, {"owner": owner, "name": name, "after": after}), owner, name)
        is_private = bool(repo.get("isPrivate"))
        issues.extend(repo["issues"]["nodes"])
        pages += 1
        if not repo["issues"]["pageInfo"]["hasNextPage"]:
            return is_private, issues, False
        after = repo["issues"]["pageInfo"]["endCursor"]


def _labels(issue: dict) -> list[str]:
    return [n["name"] for n in issue["labels"]["nodes"]]


def _trusted(issue: dict) -> bool:
    return issue.get("authorAssociation") in TRUSTED_AUTHORS and QUEUE_LABEL in _labels(issue)


def _deferred_reason(issue: dict) -> str:
    body = issue.get("body") or ""
    _, reason = _migration_body_and_deferral(body)
    if reason:
        return reason
    m = _DEFERRED_LINE_RE.search(body)
    return m.group(1) if m else ""


def default_branch(repo: str) -> str | None:
    """The default branch as `dispatch.py` resolves it: `origin/HEAD`, else `main`/`master` when
    that remote branch exists; None when unresolvable."""
    head = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head and head.startswith("refs/remotes/origin/"):
        return head[len("refs/remotes/origin/"):]
    for name in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"):
            return name
    return None


_COVERS_REF_RE = re.compile(r"^\s*[-*+]\s+#(\d+)\b")


def _covers_refs(tasks_text: str) -> set[int]:
    """Only a Covers item's leading ref counts: a `#N` quoted in the copied title is not a claim."""
    tokens = bc.tokenize(tasks_text)
    headings = bc._headings(tokens)
    lines = tasks_text.splitlines()
    found: set[int] = set()
    for h in headings:
        if h["title"] != "Covers":
            continue
        end = bc._region_end(h, headings)
        stop = len(lines) if end == float("inf") else int(end) - 1
        for line in lines[h["line"]:stop]:
            m = _COVERS_REF_RE.match(line)
            if m:
                found.add(int(m.group(1)))
    return found


def _archived_covers_refs(worktree: str, common: str) -> set[int]:
    git_dir = _git(worktree, "rev-parse", "--git-dir")
    if not git_dir:
        return set()
    registration = os.path.join(worktree, git_dir, "task-cycle-contract")
    saved_branch, _, key = (bc._read_optional(registration) or "").partition("\n")
    key = key.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", key) or saved_branch != _git(
        worktree, "symbolic-ref", "--quiet", "--short", "HEAD"
    ):
        return set()
    archive = os.path.join(common, "task-cycle", key, "contract.md")
    return _covers_refs(bc._read_optional(archive) or "")


def github_claims(repo: str, slug: str, issues: list[dict], include_self: bool,
                  warnings: list[str]) -> dict[int, str]:
    """{issue number: claimant} from the three claim sources; none needs a remote write.

    (a) a worktree's `## Covers` in tasks.md or its branch's archived contract;
    (b) an open PR that closes it;
    (c) a commit on the local default branch, not yet on `origin`, carrying its closing keyword.
    """
    claims: dict[int, str] = {}
    top = _git(repo, "rev-parse", "--show-toplevel")
    listing = _git(repo, "worktree", "list", "--porcelain")
    if top is not None and listing is not None:
        common = _git(repo, "rev-parse", "--git-common-dir")
        for wt in bc._claimants(listing, os.path.realpath(top), include_self):
            text = bc._read_optional(os.path.join(wt, "tasks.md")) or ""
            refs = _covers_refs(text)
            if common:
                refs.update(_archived_covers_refs(wt, os.path.join(repo, common)))
            for n in sorted(refs):
                claims.setdefault(n, wt)
    for issue in issues:
        for pr in issue["closedByPullRequestsReferences"]["nodes"]:
            if pr.get("state") != "OPEN":
                continue
            if pr.get("authorAssociation") not in TRUSTED_AUTHORS:  # a stranger's PR cannot park an item
                warnings.append(f"ignored claim on #{issue['number']} by {pr.get('url')}: PR author association "
                                f"{pr.get('authorAssociation')} is not OWNER/MEMBER/COLLABORATOR")
                continue
            claims.setdefault(issue["number"], pr.get("url") or f"PR #{pr['number']}")
            break
    default = default_branch(repo)
    if default is None:
        warnings.append("cannot resolve origin's default branch (no origin/HEAD, origin/main or origin/master); "
                        "unpushed closing commits were not checked as claims")
    elif _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{default}"):
        log = _git(repo, "log", "--format=%B%x00", f"refs/remotes/origin/{default}..refs/heads/{default}") or ""
        for m in _CLOSING_RE.finditer(log):
            if m.group(1) is None or m.group(1).lower() == slug.lower():
                claims.setdefault(int(m.group(2)), f"{default} (unpushed commit)")
    return claims


def github_list(req: dict, runner=gh_runner, max_pages: int = MAX_PAGES) -> dict:
    """Open `task-queue` issues mapped onto contract v1 `list` (GitHub mapping in the contract doc)."""
    repo = req["repo"]
    owner, name = github_slug(repo)
    slug = f"{owner}/{name}".lower()
    _, issues, truncated = _fetch_queue(runner, owner, name, max_pages)
    warnings: list[str] = []
    incomplete = truncated
    if truncated:
        warnings.append(f"incomplete: stopped after {max_pages} pages of open {QUEUE_LABEL} issues; "
                        "later issues were not read")

    def ref(node: dict) -> str:
        own = node["repository"]["nameWithOwner"]
        return f"#{node['number']}" if own.lower() == slug else f"{own}#{node['number']}"

    queued: dict[int, dict] = {}
    partial: set[int] = set()
    seen = {issue["number"] for issue in issues}
    for issue in issues:
        if issue["authorAssociation"] not in TRUSTED_AUTHORS:
            warnings.append(f"skipped #{issue['number']}: author association {issue['authorAssociation']} "
                            "is not OWNER/MEMBER/COLLABORATOR")
            continue
        if not _complete_connections(runner, owner, name, issue, max_pages):
            partial.add(issue["number"])
            incomplete = True
            warnings.append(f"incomplete: #{issue['number']} has more linked items than {max_pages} pages; "
                            "left out of selection")
        if not _trusted(issue):  # labels are re-read in full now: the label filter stays authoritative
            continue
        queued[issue["number"]] = issue
    claims = github_claims(repo, slug, list(queued.values()), bool(req.get("ref")), warnings)

    def is_queued_parent(issue: dict) -> bool:
        p = issue.get("parent")
        return bool(p) and p["repository"]["nameWithOwner"].lower() == slug and p["number"] in queued

    blocked = {n: [ref(b) for b in i["blockedBy"]["nodes"] if b["state"] == "OPEN"] for n, i in queued.items()}
    deferred = {n for n, i in queued.items() if "deferred" in _labels(i)}
    parked: list[dict] = []
    for n, issue in sorted(queued.items()):
        if n in partial:
            continue
        if blocked[n]:
            parked.append({"ref": f"#{n}", "kind": "blocked", "payload": ", ".join(blocked[n])})
        if n in deferred:
            parked.append({"ref": f"#{n}", "kind": "deferred", "payload": _deferred_reason(issue)})

    parents = {n: issue for n, issue in queued.items()
               if n not in partial and not is_queued_parent(issue) and n not in claims
               and not blocked[n] and n not in deferred}
    missing_children = set()
    if truncated:
        missing_children = {s["id"] for issue in parents.values() for s in issue["subIssues"]["nodes"]
                            if s["state"] == "OPEN" and s["repository"]["nameWithOwner"].lower() == slug
                            and s["number"] not in seen}
    unread_children = _issue_details(runner, UNREAD_CHILDREN_QUERY, sorted(missing_children))

    def why_not(sub: dict) -> str | None:
        if sub["repository"]["nameWithOwner"].lower() != slug:
            return "in another repository"
        n = sub["number"]
        if n in partial:
            return "incomplete read"
        if truncated and n not in seen:
            unread = unread_children[sub["id"]]
            if unread["authorAssociation"] in TRUSTED_AUTHORS and (
                QUEUE_LABEL in _labels(unread) or unread["labels"]["pageInfo"]["hasNextPage"]
            ):
                return "incomplete read"
        if n not in queued:
            return f"not a trusted {QUEUE_LABEL} issue"
        if n in claims:
            return "claimed"
        if blocked[n]:
            return "blocked"
        if n in deferred:
            return "deferred"
        return None

    candidates: list[dict] = []
    for n, issue in sorted(parents.items()):
        p = issue.get("parent")
        if truncated and p and p["repository"]["nameWithOwner"].lower() == slug and p["number"] not in seen:
            # its parent may be a queue item on a page never read: never let a sub-issue stand alone
            warnings.append(f"incomplete: #{n} left out; its parent #{p['number']} was not read")
            continue
        subs = [s for s in issue["subIssues"]["nodes"] if s["state"] == "OPEN"]
        entry = {"id": f"#{n}", "ref": f"#{n}", "title": issue["title"], "labels": _labels(issue),
                 "url": issue["url"]}
        if not subs:
            entry.update(tag=_tag([issue["title"]]), items=[issue["title"]], item_refs=[f"#{n}"],
                         excluded=[], counts={"open": 1, "deferred": 0, "blocked": 0})
            candidates.append(entry)
            continue
        reasons = [(s, why_not(s)) for s in subs]
        unread = [ref(s) for s, why in reasons if why == "incomplete read"]
        if unread:
            warnings.append(f"incomplete: #{n} left out; incomplete read of sub-issues {', '.join(unread)}")
            continue
        eligible = [s for s, why in reasons if why is None]
        excluded = [{"ref": ref(s), "reason": why} for s, why in reasons if why is not None]
        counts = {"open": len(subs),
                  "deferred": sum(1 for _, why in reasons if why == "deferred"),
                  "blocked": sum(1 for _, why in reasons if why == "blocked")}
        if eligible:
            titles = [s["title"] for s in eligible]
            entry.update(tag=_tag(titles), items=titles, item_refs=[ref(s) for s in eligible],
                         excluded=excluded, counts=counts)
            candidates.append(entry)
        elif any(e["reason"] != "claimed" for e in excluded):
            others = [e for e in excluded if e["reason"] != "claimed"]
            kind = "deferred" if all(e["reason"] == "deferred" for e in others) else "blocked"
            parked.append({"ref": f"#{n}", "kind": kind, "payload": "no eligible sub-issue: "
                           + ", ".join(f"{e['ref']} {e['reason']}" for e in excluded)})

    # Fast path: oldest first, `someday` last, cap 3. Full scan: uncapped, same order — issues have
    # no h3/h2 heading kinds, so the backlog's type priority reduces to issue number.
    candidates.sort(key=lambda c: ("someday" in c["labels"], int(c["ref"][1:])))
    if not req.get("full_scan"):
        candidates = candidates[:bc.FAST_PATH_CAP]
    if incomplete and not candidates:
        raise QueueError("incomplete queue read and no candidate found: " + "; ".join(
            w for w in warnings if w.startswith("incomplete")))
    claimed = [{"ref": f"#{n}", "by": by} for n, by in sorted(claims.items()) if n in queued]
    return {"candidates": candidates, "parked": parked if req.get("parked") else [], "claimed": claimed,
            "warnings": warnings, "incomplete": incomplete}


def _parse_issue_ref(ref: object) -> int:
    m = re.fullmatch(r"#?(\d+)", ref.strip()) if isinstance(ref, str) else None
    if not m:
        raise QueueError(f"ref must be #<issue number>, got {ref!r}")
    return int(m.group(1))


def github_show(req: dict, runner=gh_runner, max_pages: int = MAX_PAGES) -> dict:
    owner, name = github_slug(req["repo"])
    slug = f"{owner}/{name}".lower()
    number = _parse_issue_ref(req.get("ref"))
    issue = _repository(_graphql(runner, SHOW_QUERY, {"owner": owner, "name": name, "number": number}),
                        owner, name).get("issue")
    if issue is None:
        raise QueueError(f"#{number} is not an issue in {owner}/{name}")
    if not _complete_connections(runner, owner, name, issue, max_pages):
        raise QueueError(f"#{number} has more linked items than {max_pages} pages; not shown incomplete")
    if not _trusted(issue):  # an untrusted body never reaches an unattended cycle
        raise QueueError(f"#{number} is not a trusted queue item (needs the {QUEUE_LABEL} label and an "
                         f"OWNER/MEMBER/COLLABORATOR author, got {issue['authorAssociation']})")

    def ref(node: dict) -> str:
        own = node["repository"]["nameWithOwner"]
        return f"#{node['number']}" if own.lower() == slug else f"{own}#{node['number']}"

    parent = issue.get("parent")
    return {
        "ref": f"#{number}", "title": issue["title"], "body": issue.get("body") or "",
        "labels": _labels(issue), "blocked_by": [ref(b) for b in issue["blockedBy"]["nodes"] if b["state"] == "OPEN"],
        "parent": ref(parent) if parent else None, "url": issue["url"], "state": issue["state"],
    }


# ---------------------------------------------------------------------------
# `github` write path: create, rejected, reject, defer, publish (+ pending store)
# ---------------------------------------------------------------------------

class GhRejected(QueueError):
    """GitHub refused a write as invalid (HTTP 400/422): retrying the same draft cannot succeed."""


NO_QUEUE_WRITE = "no-queue-write"
QUEUE_LIMITS = ("none", NO_QUEUE_WRITE)
_KEY_MARKER = "<!-- queue-key: {} -->"
_ALERT_MARKER = "<!-- gh-alert: {} -->"
_ALERT_ID = r"(?:dependabot|code-scanning|secret-scanning)/[1-9][0-9]*"
_ALERT_KEY_PREFIX = "gh-alert/"
MIGRATION_KEY_PREFIX = "backlog-migrated:"
_ALERT_MARKER_RE = re.compile(r"<!-- gh-alert: (" + _ALERT_ID + r") -->")
# the marker create appends on its own last line; a body quoting the syntax earlier never wins
_KEY_RE = re.compile(r"^<!-- queue-key: (.+?) -->\r?$", re.MULTILINE)
_REJECT_MARKER = "<!-- queue-rejected -->"
_ISSUE_REF_RE = re.compile(r"^(?:([\w.-]+/[\w.-]+))?#(\d+)$")

# No label filter: an issue whose relations were still being filed carries no `task-queue` label
# yet (so selection never sees it half-linked), and a retry must still find it by its key.
KEYS_QUERY = (
    "query($owner: String!, $name: String!, $after: String) { repository(owner: $owner, name: $name) { "
    "issues(first: 100, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) "
    "{ pageInfo { hasNextPage endCursor } "
    "nodes { id number url title body state stateReason authorAssociation } } } }"
)
KEY_RELATIONS_QUERY = (
    "query($ids: [ID!]!) { nodes(ids: $ids) { ... on Issue { id labels(first: 100) { nodes { name } } "
    "parent { number repository { nameWithOwner } } "
    "blockedBy(first: 100) { nodes { number repository { nameWithOwner } } } } } }"
)
NODE_QUERY = ("query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) { "
              "issue(number: $number) { id number body authorAssociation labels(first: 100) { nodes { name } } } } }")
REJECTED_QUERY = (
    "query($owner: String!, $name: String!, $after: String) { repository(owner: $owner, name: $name) { "
    f"issues(first: 100, after: $after, states: CLOSED, labels: [\"{QUEUE_LABEL}\"], "
    "orderBy: {field: CREATED_AT, direction: ASC}) { pageInfo { hasNextPage endCursor } "
    "nodes { id number title url stateReason authorAssociation } } } }"
)
REJECTION_COMMENTS_QUERY = (
    "query($ids: [ID!]!) { nodes(ids: $ids) { ... on Issue { id "
    "comments(last: 50) { nodes { body authorAssociation } } } } }"
)
ADD_SUB_ISSUE = ("mutation($parent: ID!, $child: ID!) { addSubIssue(input: {issueId: $parent, subIssueId: $child}) "
                 "{ issue { number } } }")
ADD_BLOCKED_BY = ("mutation($issue: ID!, $blocker: ID!) { addBlockedBy(input: {issueId: $issue, "
                  "blockingIssueId: $blocker}) { issue { number } } }")


def _gh_failed(code: int, err: str, what: str) -> QueueError:
    low = err.lower()
    if code == 4 or "gh auth login" in low or "not logged in" in low or "authentication" in low:
        return GhUnavailable("gh is not authenticated for github.com: run `gh auth login`; "
                             "the github queue backend never falls back to backlog.md")
    if re.search(r"HTTP (400|422)\b", err):
        return GhRejected(f"{what} was refused: {err.strip()}")
    return GhUnavailable(f"{what} failed (exit {code}): {err.strip()}")


def _gql(runner, query: str, variables: dict) -> tuple[dict, list[str]]:
    """GraphQL call for the write path: (data, error messages). A transport failure raises."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if isinstance(value, list):
            for entry in value:
                args += ["-f", f"{key}[]={entry}"]
        elif value is not None:
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    code, out, err = runner(args)
    if code != 0:
        raise _gh_failed(code, err, "gh api graphql")
    try:
        data = json.loads(out)
    except ValueError as e:
        raise GhUnavailable(f"gh api graphql printed no JSON: {e}") from e
    return data.get("data") or {}, [str(e.get("message", e)) for e in data.get("errors") or []]


def _rest(runner, method: str, path: str, fields: dict | None = None, arrays: dict | None = None,
          missing_ok: bool = False) -> dict | None:
    """`gh api --method <M> <path>`; string fields go as `-f` (never `@file`-expanded)."""
    args = ["api", "--method", method, path]
    for key, value in (fields or {}).items():
        args += ["-f", f"{key}={value}"]
    for key, values in (arrays or {}).items():
        for value in values:
            args += ["-f", f"{key}[]={value}"]
    code, out, err = runner(args)
    if code != 0:
        if missing_ok and "HTTP 404" in err:
            return None
        raise _gh_failed(code, err, f"gh api {method} {path}")
    try:
        return json.loads(out) if out.strip() else {}
    except ValueError as e:
        raise GhUnavailable(f"gh api {method} {path} printed no JSON: {e}") from e


def ensure_labels(runner, owner: str, name: str, labels) -> list[str]:
    """Create each label that is missing (label bootstrap); returns the ones created."""
    from urllib.parse import quote
    made = []
    labels_path = f"repos/{owner}/{name}/labels"
    for label in sorted(set(labels)):
        label_path = f"{labels_path}/{quote(label, safe='')}"
        if _rest(runner, "GET", label_path, missing_ok=True) is not None:
            continue
        try:
            _rest(runner, "POST", labels_path, {"name": label})
        except GhRejected as exc:
            if "HTTP 422" not in str(exc) or _rest(runner, "GET", label_path, missing_ok=True) is None:
                raise
        else:
            made.append(label)
    return made


def _node_key(repo_name: str, number: int) -> tuple[str, int]:
    return repo_name.lower(), number


def _issue_pages(runner, query: str, owner: str, name: str):
    after = None
    cursors = set()
    while True:
        data, errors = _gql(runner, query, {"owner": owner, "name": name, "after": after})
        if errors:
            raise GhUnavailable("GitHub GraphQL error: " + "; ".join(errors))
        conn = _repository(data, owner, name)["issues"]
        yield conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return
        after = conn["pageInfo"]["endCursor"]
        if not after or after in cursors:
            raise GhUnavailable("GitHub issues pagination did not advance")
        cursors.add(after)


def github_inventory(req: dict, runner=gh_runner) -> dict:
    """All trusted open queue issues, independent of claims or selection eligibility."""
    owner, name = github_slug(req["repo"])
    entries = []
    for page in _issue_pages(runner, INVENTORY_QUERY, owner, name):
        for issue in page:
            if issue["authorAssociation"] in TRUSTED_AUTHORS:
                entries.append({
                    "ref": f"#{issue['number']}", "title": issue["title"],
                    "body": issue.get("body") or "", "url": issue["url"],
                })
    return {"entries": entries}


def _issue_details(runner, query: str, ids: list[str]) -> dict[str, dict]:
    details = {}
    for start in range(0, len(ids), PAGE_SIZE):
        batch = set(ids[start:start + PAGE_SIZE])
        data, errors = _gql(runner, query, {"ids": sorted(batch)})
        if errors:
            raise GhUnavailable("GitHub GraphQL error: " + "; ".join(errors))
        nodes = {node["id"]: node for node in data.get("nodes", []) if node and "id" in node}
        if nodes.keys() != batch:
            raise GhUnavailable("GitHub returned incomplete issue details")
        details.update(nodes)
    return details


def _refile_match(index: dict[str, dict], key: str) -> tuple[str, dict | None]:
    marker_key = key
    found = index.get(marker_key)
    while found and found.get("state") == "CLOSED" and found.get("stateReason") == "COMPLETED":
        marker_key = f"{key}:after:{found['number']}"
        found = index.get(marker_key)
    return marker_key, found


def _item_match(index: dict[str, dict], item: dict) -> tuple[str, dict | None]:
    key = item["key"]
    return _refile_match(index, key) if item.get("refile_completed") else (key, index.get(key))


def key_index(runner, owner: str, name: str, items: list[dict]) -> dict[str, dict]:
    batch = {item["key"] for item in items}
    targets = {target for item in items for target in [item["parent_key"], *item["blocked_by"]]
               if target and not _ISSUE_REF_RE.match(target)}
    wanted = batch | targets
    refile = {item["key"] for item in items if item.get("refile_completed")}
    index: dict[str, dict] = {}
    # Search results can lag a successful POST whose response was lost. Use the issue connection
    # as the source of truth, and only read relation details for matches that will be reused.
    for page in _issue_pages(runner, KEYS_QUERY, owner, name):
        for issue in page:
            if issue.get("authorAssociation") not in TRUSTED_AUTHORS:
                continue
            body = issue.get("body") or ""
            keys = _KEY_RE.findall(body)
            if keys and not keys[-1].startswith(_ALERT_KEY_PREFIX):
                key = keys[-1]
                if key in wanted or key.rpartition(":after:")[0] in refile:
                    index.setdefault(key, issue)
            if lines := body.rstrip().splitlines():
                if marker := _ALERT_MARKER_RE.fullmatch(lines[-1]):
                    key = _ALERT_KEY_PREFIX + marker[1]
                    if key in wanted:
                        index.setdefault(key, issue)
        if wanted <= index.keys() and all(_refile_match(index, key)[1] for key in refile):
            break
    return index


def _validate_items(items: object) -> list[dict]:
    """Shape checks that need no gh, so a draft that can never be filed is refused, not stored."""
    if not isinstance(items, list) or not items:
        raise QueueError("create needs a non-empty items[]")
    out, keys = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise QueueError("each create item must be an object")
        key, title, body = item.get("key"), item.get("title"), item.get("body")
        if not (isinstance(key, str) and key.strip() and "-->" not in key and "\n" not in key):
            raise QueueError(f"item key must be a one-line string without '-->', got {key!r}")
        if key in keys:
            raise QueueError(f"duplicate item key {key!r}")
        keys.add(key)
        if not (isinstance(title, str) and title.strip()):
            raise QueueError(f"item {key!r} needs a title")
        if body is not None and not isinstance(body, str):
            raise QueueError(f"item {key!r}: body must be a string")
        labels = item.get("labels") or []
        blocked = item.get("blocked_by") or []
        parent = item.get("parent_key")
        if not (isinstance(labels, list) and all(isinstance(x, str) and x for x in labels)):
            raise QueueError(f"item {key!r}: labels must be a list of names")
        if not (isinstance(blocked, list) and all(isinstance(x, str) and x for x in blocked)):
            raise QueueError(f"item {key!r}: blocked_by must be a list of keys or refs")
        if parent is not None and not (isinstance(parent, str) and parent):
            raise QueueError(f"item {key!r}: parent_key must be a key or ref")
        if key == parent or key in blocked:
            raise QueueError(f"item {key!r} names itself as its parent or blocker")
        if key.startswith(_ALERT_KEY_PREFIX):
            if not re.fullmatch(_ALERT_ID, key.removeprefix(_ALERT_KEY_PREFIX)):
                raise QueueError(f"invalid GitHub alert key {key!r}")
            if parent or blocked or "security" not in labels:
                raise QueueError(f"alert {key!r} needs the security label and no queue relations")
        refile = item.get("refile_completed", False)
        if not isinstance(refile, bool):
            raise QueueError(f"item {key!r}: refile_completed must be a boolean")
        draft = {"key": key, "title": title, "body": body or "", "labels": labels,
                 "parent_key": parent, "blocked_by": blocked}
        if refile:
            if key.startswith(_ALERT_KEY_PREFIX):
                raise QueueError(f"alert {key!r} cannot use refile_completed")
            draft["refile_completed"] = True
        out.append(draft)
    return out


def pending_path(repo: str) -> str:
    common = _git(repo, "rev-parse", "--git-common-dir")
    if not common:
        raise QueueError(f"{repo} is not a git repository; the pending store lives in its git common dir")
    return os.path.join(os.path.normpath(os.path.join(repo, common)), "agent-queue", "pending.json")


QUEUE_LOCK_TIMEOUT = 10


@contextmanager
def _queue_write_lock(repo: str):
    """Hold the Git common dir's lock across lookup, filing and pending-store updates."""
    path = os.path.join(os.path.dirname(pending_path(repo)), "write.lock")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = open(path, "a+b")
    except OSError as e:
        raise QueueError(f"cannot open queue writer lock {path}: {e}") from e
    with lock:
        deadline = time.monotonic() + QUEUE_LOCK_TIMEOUT
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    raise QueueError(f"cannot acquire queue writer lock {path}: {e}") from e
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise QueueError(f"timed out waiting for queue writer lock {path}; retry the operation") from e
                time.sleep(min(0.05, remaining))
        yield


def read_pending(repo: str) -> list[dict]:
    path = pending_path(repo)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise QueueError(f"pending store {path} is unreadable: {e}") from e
    return list(data.get("items") or [])


def write_pending(repo: str, items: list[dict]) -> str:
    """Replace the pending store with `items` (caller holds the lock); empty removes the file."""
    import tempfile
    path = pending_path(repo)
    if not items:
        if os.path.exists(path):
            os.remove(path)
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix="pending.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"version": 1, "items": items}, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def _draft(item: dict) -> dict:
    draft = {k: item[k] for k in ("key", "title", "body", "labels", "parent_key", "blocked_by")}
    if item.get("refile_completed"):
        draft["refile_completed"] = True
    return draft


def _issue_body(body: str, marker: str) -> str:
    return (body.rstrip() + "\n\n" if body.strip() else "") + marker


def _migration_body_and_deferral(body: str) -> tuple[str, str]:
    body = body.replace("\r\n", "\n").rstrip()
    prefix, separator, reason = body.rpartition("\n\nDeferred: ")
    if separator and reason and "\n" not in reason:
        marker = _KEY_RE.fullmatch(prefix.rsplit("\n", 1)[-1])
        if marker and marker[1].startswith(MIGRATION_KEY_PREFIX):
            return prefix, reason
    return body, ""


def _matches_migrated_content(item: dict, marker_key: str, found: dict) -> bool:
    expected = _issue_body(item["body"], _KEY_MARKER.format(marker_key)).replace("\r\n", "\n")
    actual, _ = _migration_body_and_deferral(found["body"] or "")
    return found["title"] == item["title"] and actual == expected


def _post_items(owner: str, name: str, items: list[dict], runner, from_store: bool,
                withheld: frozenset[str] = frozenset()) -> dict:
    """Retry-safe create of validated `items`. Returns created/incomplete/done/refused; a transport
    failure re-raises with the partial result attached as `partial`."""
    slug = f"{owner}/{name}".lower()
    result: dict = {"created": [], "incomplete": [], "done": set(), "refused": set()}
    try:
        index = key_index(runner, owner, name, items)
        batch = {i["key"] for i in items}
        issues: dict[str, dict] = {}
        ready = []
        for item in items:
            key = item["key"]
            if key.startswith(_ALERT_KEY_PREFIX) and key in index:
                found = index[key]
                issues[key] = found
                result["created"].append({"key": key, "ref": f"#{found['number']}", "url": found["url"],
                                          "reused": True})
                result["done"].add(key)
                continue
            if key.startswith(MIGRATION_KEY_PREFIX):
                marker_key, found = _item_match(index, item)
                if found and not _matches_migrated_content(item, marker_key, found):
                    result["incomplete"].append({
                        "key": key, "relation": "content", "ref": f"#{found['number']}",
                        "error": "migration issue title or body differs; reconcile it with backlog.md and retry",
                    })
                    result["refused"].add(key)
                    continue
            unknown = [t for t in [item["parent_key"]] * bool(item["parent_key"]) + item["blocked_by"]
                       if not (_ISSUE_REF_RE.match(t) or t in batch or t in index)]
            invalid = [target for target in unknown if target not in withheld]
            if invalid and not from_store:
                raise QueueError(f"item {item['key']!r} names {invalid[0]!r}: not a batch key, a known "
                                 "queue-key or an issue ref (#N / owner/name#N)")
            if unknown:  # one bad stored draft never blocks the rest of the store
                result["incomplete"].append({"key": item["key"], "relation": "target", "ref": unknown[0],
                                             "error": "not a batch key, a known queue-key or an issue ref"})
                continue
            ready.append(item)
        if not ready:
            return result
        detail_ids = {
            found["id"] for item in ready if (found := _item_match(index, item)[1])
            and not (item.get("refile_completed") and found.get("state") == "CLOSED")
        }
        details = _issue_details(runner, KEY_RELATIONS_QUERY, sorted(detail_ids))
        ensure_labels(runner, owner, name, [QUEUE_LABEL] + [x for i in ready for x in i["labels"]])
        for item in ready:
            key = item["key"]
            marker_key, found = _item_match(index, item)
            if item.get("refile_completed") and found and found.get("state") == "CLOSED":
                result["incomplete"].append({"key": key, "relation": "rejected",
                                             "ref": f"#{found['number']}", "error": "issue closed without completion"})
                result["refused"].add(key)
                continue
            reused = found is not None
            if found is not None:
                found = {**found, **details.get(found["id"], {})}
            else:
                # An item with relations is filed without `task-queue` and labelled only once every
                # relation landed, so selection never offers it before its blockers are recorded.
                linked = bool(item["parent_key"] or item["blocked_by"])
                labels = sorted(set(item["labels"]) | (set() if linked else {QUEUE_LABEL}))
                marker = (_ALERT_MARKER.format(key.removeprefix(_ALERT_KEY_PREFIX))
                          if key.startswith(_ALERT_KEY_PREFIX) else _KEY_MARKER.format(marker_key))
                body = _issue_body(item["body"], marker)
                try:
                    made = _rest(runner, "POST", f"repos/{owner}/{name}/issues", {"title": item["title"], "body": body},
                                 {"labels": labels} if labels else None) or {}
                except GhRejected as e:
                    result["incomplete"].append({"key": item["key"], "relation": "create", "ref": None,
                                                 "error": str(e)})
                    result["refused"].add(item["key"])
                    continue
                if not all(k in made for k in ("node_id", "number", "html_url")):
                    raise GhUnavailable(f"creating {item['key']!r} returned no issue: {made!r}")
                found = {"id": made["node_id"], "number": made["number"], "url": made["html_url"],
                         "labels": {"nodes": [{"name": x} for x in labels]},
                         "parent": None, "blockedBy": {"nodes": []}}
                index[marker_key] = found
            issues[key] = found
            result["created"].append({"key": key, "ref": f"#{found['number']}", "url": found["url"],
                                      "reused": reused})

        node_ids: dict[tuple[str, int], str] = {}

        def target_node(target: str) -> tuple[tuple[str, int], str, str | None]:
            """(node key, display ref, node id or None when it does not exist)."""
            m = _ISSUE_REF_RE.match(target)
            if not m:
                issue = issues.get(target) or index[target]
                return _node_key(slug, issue["number"]), f"#{issue['number']}", issue["id"]
            repo_name = (m.group(1) or slug).lower()
            nk = _node_key(repo_name, int(m.group(2)))
            ref = f"#{m.group(2)}" if repo_name == slug else f"{m.group(1)}#{m.group(2)}"
            if nk not in node_ids:
                o, n = repo_name.split("/", 1)
                data, _ = _gql(runner, NODE_QUERY, {"owner": o, "name": n, "number": int(m.group(2))})
                node = (data.get("repository") or {}).get("issue")
                node_ids[nk] = node["id"] if node else ""
            return nk, ref, node_ids[nk] or None

        for item in ready:
            if item["key"] not in issues:
                continue
            issue = issues[item["key"]]
            missing = []
            relations = ([("parent", item["parent_key"])] if item["parent_key"] else []) + \
                [("blocked_by", b) for b in item["blocked_by"]]
            have_parent = issue.get("parent")
            have_blockers = {_node_key(b["repository"]["nameWithOwner"], b["number"])
                             for b in issue["blockedBy"]["nodes"]}
            for kind, target in relations:
                if target in batch and target not in issues:
                    missing.append({"key": item["key"], "relation": kind, "ref": None,
                                    "error": f"{target!r} was not filed"})
                    continue
                nk, ref, node_id = target_node(target)
                if kind == "parent" and have_parent and \
                        _node_key(have_parent["repository"]["nameWithOwner"], have_parent["number"]) == nk:
                    continue
                if kind == "blocked_by" and nk in have_blockers:
                    continue
                if node_id is None:
                    missing.append({"key": item["key"], "relation": kind, "ref": ref, "error": "issue not found"})
                    continue
                if kind == "parent":
                    _, errors = _gql(runner, ADD_SUB_ISSUE, {"parent": node_id, "child": issue["id"]})
                else:
                    _, errors = _gql(runner, ADD_BLOCKED_BY, {"issue": issue["id"], "blocker": node_id})
                if errors:
                    missing.append({"key": item["key"], "relation": kind, "ref": ref, "error": "; ".join(errors)})
                elif kind == "blocked_by":
                    have_blockers.add(nk)
                else:
                    have_parent = {"number": nk[1], "repository": {"nameWithOwner": nk[0]}}
            if not missing and QUEUE_LABEL not in [n["name"] for n in issue["labels"]["nodes"]]:
                _rest(runner, "POST", f"repos/{owner}/{name}/issues/{issue['number']}/labels",
                      arrays={"labels": [QUEUE_LABEL]})
            result["incomplete"].extend(missing)
            if not missing:
                result["done"].add(item["key"])
    except GhUnavailable as e:
        e.partial = result
        raise
    return result


def github_create(req: dict, runner=gh_runner) -> dict:
    with _queue_write_lock(req["repo"]):
        return _github_create(req, runner, github_slug(req["repo"]))


def _github_create(req: dict, runner, slug: tuple[str, str], items: list[dict] | None = None) -> dict:
    """File drafts with the write lock held. Drafts that are not
    fully filed (gh unavailable mid-write, an incomplete relation, `no-queue-write`) are kept in
    the pending store — the failure path only. A draft GitHub
    refused as invalid (HTTP 400/422) is reported in `incomplete[]` and not stored: a retry of the
    same draft cannot succeed. Migration content conflicts also retire drafts until reconciled."""
    from_store = items is not None
    items = _validate_items(req.get("items") if items is None else items)
    repo = req["repo"]
    limits = req.get("queue_limits") or "none"
    if limits not in QUEUE_LIMITS:
        raise QueueError(f"queue_limits must be one of {', '.join(QUEUE_LIMITS)}, got {limits!r}")
    owner, name = slug
    target = f"{owner}/{name}".lower()
    out: dict = {"created": [], "incomplete": [], "pending": []}
    alert_keys = {item["key"] for item in items if item["key"].startswith(_ALERT_KEY_PREFIX)}
    finding_keys = {item["key"] for item in items if any(label.casefold() == "security" for label in item["labels"])}
    finding_keys -= alert_keys
    if from_store and limits == NO_QUEUE_WRITE and not finding_keys:
        return out | {"pending": [item["key"] for item in items], "pending_path": pending_path(repo)}
    withheld: set[str] = set()
    visibility = None
    visibility_error = "GitHub security alerts can only be filed on a confirmed private repository"
    if finding_keys or (alert_keys and limits != NO_QUEUE_WRITE):
        try:
            visibility = _github_visibility(owner, name, runner)
        except QueueError as e:
            visibility_error = str(e)
            if alert_keys and not from_store and limits != NO_QUEUE_WRITE:
                limits = NO_QUEUE_WRITE
                out["error"] = visibility_error
        if visibility != "private":
            withheld.update(finding_keys)
            if finding_keys:
                out["withheld_security"] = len(finding_keys)
        if alert_keys and visibility != "private" and (limits != NO_QUEUE_WRITE or visibility is not None):
            withheld.update(alert_keys)
            out["incomplete"] = [{"key": item["key"], "relation": "visibility", "ref": None,
                                  "error": visibility_error} for item in items if item["key"] in alert_keys]
            if from_store and visibility != "public":
                out["pending"] = [entry["key"] for entry in out["incomplete"]]
            if not from_store and len(alert_keys) == len(items):
                raise QueueError(visibility_error)
        items = [item for item in items if item["key"] not in withheld]
    res: dict = {"created": [], "incomplete": [], "done": set(), "refused": set()}
    reason = out.get("error", f"Queue limits: {NO_QUEUE_WRITE}")
    if items and limits != NO_QUEUE_WRITE:
        try:
            res = _post_items(owner, name, items, runner, from_store, frozenset(withheld))
            reason = "incomplete relation"
        except GhUnavailable as e:
            res = e.partial or res
            reason = str(e)
            out["error"] = reason
        out["created"] = res["created"]
        out["incomplete"].extend(res["incomplete"])
    left = [i for i in items if i["key"] not in res["done"] | res["refused"]]
    retired = res["done"] | res["refused"]
    if from_store:
        if visibility == "public":
            retired |= withheld
        left_to_store = []
    else:
        left_to_store = left
    path = pending_path(repo)
    if left_to_store or (retired and os.path.exists(path)):
        stored = {(i.get("target"), i["key"]): i for i in read_pending(repo)}
        for key in retired:
            stored.pop((target, key), None)
        for item in left_to_store:
            stored[target, item["key"]] = dict(_draft(item), target=target, pending_reason=reason)
        write_pending(repo, list(stored.values()))
    out["pending"].extend(i["key"] for i in left)
    if path and out["pending"]:
        out["pending_path"] = path
    return out


def github_publish(req: dict, runner=gh_runner) -> dict:
    """Post the pending store's drafts bound to this repo's current `origin`; a draft stored for
    another target stays pending and is reported, never posted elsewhere."""
    with _queue_write_lock(req["repo"]):
        return _github_publish(req, runner)


def _github_publish(req: dict, runner) -> dict:
    stored = read_pending(req["repo"])
    if not stored:
        return {"created": [], "incomplete": [], "pending": []}
    owner, name = github_slug(req["repo"])
    target = f"{owner}/{name}".lower()
    mine = [_draft(i) for i in stored if i.get("target") == target]
    other = [i for i in stored if i.get("target") != target]
    foreign = [{"key": i["key"], "relation": "target", "ref": i.get("target"),
                "error": f"stored for {i.get('target')}, origin is now {target}; not posted"} for i in other]
    if not mine:
        return {"created": [], "incomplete": foreign, "pending": [i["key"] for i in other],
                "pending_path": pending_path(req["repo"])}
    out = _github_create(req, runner, (owner, name), mine)
    out["incomplete"] = out["incomplete"] + foreign
    out["pending"] = out["pending"] + [i["key"] for i in other]
    if out["pending"]:
        out["pending_path"] = pending_path(req["repo"])
    return out


def _parse_rejection(comments: list[dict]) -> tuple[str, str]:
    for c in reversed(comments):
        body = c.get("body") or ""
        if _REJECT_MARKER in body and c.get("authorAssociation") in TRUSTED_AUTHORS:
            reason = re.search(r"^Reason:\s*(.*?)\s*$", body, re.MULTILINE)
            bar = re.search(r"^Re-file only with:\s*(.*?)\s*$", body, re.MULTILINE)
            return (reason.group(1) if reason else ""), (bar.group(1) if bar else "")
    return "", ""


def github_rejected(req: dict, runner=gh_runner) -> dict:
    """Closed-not-planned trusted `task-queue` issues, with the reason from the reject comment."""
    owner, name = github_slug(req["repo"])
    rejected = [
        issue for page in _issue_pages(runner, REJECTED_QUERY, owner, name) for issue in page
        if issue.get("stateReason") == "NOT_PLANNED" and issue.get("authorAssociation") in TRUSTED_AUTHORS
    ]
    details = _issue_details(runner, REJECTION_COMMENTS_QUERY, [issue["id"] for issue in rejected])
    entries = []
    for issue in rejected:
        reason, bar = _parse_rejection(details[issue["id"]]["comments"]["nodes"])
        entries.append({"ref": f"#{issue['number']}", "title": issue["title"], "reason": reason,
                        "refile_bar": bar, "url": issue["url"]})
    return {"entries": entries}


def _queue_issue(req: dict, runner) -> tuple[str, str, dict]:
    owner, name = github_slug(req["repo"])
    number = _parse_issue_ref(req.get("ref"))
    issue = _repository(_graphql(runner, NODE_QUERY, {"owner": owner, "name": name, "number": number}),
                        owner, name).get("issue")
    if issue is None or issue.get("authorAssociation") not in TRUSTED_AUTHORS or \
            QUEUE_LABEL not in [n["name"] for n in issue["labels"]["nodes"]]:
        raise QueueError(f"#{number} is not a trusted {QUEUE_LABEL} issue in {owner}/{name}")
    return owner, name, issue


def _one_line(req: dict, field: str, required: bool = True) -> str:
    value = req.get(field)
    if value is None and not required:
        return ""
    if not (isinstance(value, str) and value.strip()):
        raise QueueError(f"{field} must be a non-empty string")
    return " ".join(value.split())


def github_reject(req: dict, runner=gh_runner) -> dict:
    reason, bar = _one_line(req, "reason"), _one_line(req, "refile_bar", required=False)
    owner, name, issue = _queue_issue(req, runner)
    body = f"{_REJECT_MARKER}\n**Rejected — do not re-file.**\nReason: {reason}\n"
    if bar:
        body += f"Re-file only with: {bar}\n"
    _rest(runner, "POST", f"repos/{owner}/{name}/issues/{issue['number']}/comments", {"body": body})
    _rest(runner, "PATCH", f"repos/{owner}/{name}/issues/{issue['number']}",
          {"state": "closed", "state_reason": "not_planned"})
    return {"ref": f"#{issue['number']}"}


def github_defer(req: dict, runner=gh_runner) -> dict:
    reason = _one_line(req, "reason")
    owner, name, issue = _queue_issue(req, runner)
    body = issue.get("body") or ""
    keys = _KEY_RE.findall(body)
    if keys and keys[-1].startswith(MIGRATION_KEY_PREFIX):
        body, _ = _migration_body_and_deferral(body)
    else:
        body = _DEFERRED_LINE_RE.sub("", body).rstrip()
    body = (body + "\n\n" if body else "") + f"Deferred: {reason}\n"
    ensure_labels(runner, owner, name, ["deferred"])
    _rest(runner, "PATCH", f"repos/{owner}/{name}/issues/{issue['number']}", {"body": body})
    _rest(runner, "POST", f"repos/{owner}/{name}/issues/{issue['number']}/labels", arrays={"labels": ["deferred"]})
    return {"ref": f"#{issue['number']}"}


def github_visibility(repo: str, runner) -> str:
    owner, name = github_slug(repo)
    return _github_visibility(owner, name, runner)


def _github_visibility(owner: str, name: str, runner) -> str:
    data = _graphql(runner, DESCRIBE_QUERY, {"owner": owner, "name": name})
    visibility = _repository(data, owner, name).get("visibility")
    if visibility not in ("PRIVATE", "PUBLIC"):
        return "unknown"
    return visibility.lower()


def github_op(op: str, req: dict, runner=gh_runner) -> tuple[int, dict | None]:
    if op == "describe":
        # Local harness checks need the backend itself, not a GitHub visibility query.
        visibility = "unknown" if req.get("verify_visibility") is False else github_visibility(req["repo"], runner)
        if req.get("verify_visibility") is True and visibility == "unknown":
            raise QueueError("GitHub did not confirm public or private repository visibility")
        return EXIT_OK, {
            "backend": "github", "contract": CONTRACT, "visibility": visibility,
            "ops": list(GITHUB_OPS), "close_ref_template": "Closes {ref}",
        }
    if op == "list":
        return EXIT_OK, github_list(req, runner)
    if op == "inventory":
        return EXIT_OK, github_inventory(req, runner)
    if op == "show":
        return EXIT_OK, github_show(req, runner)
    if op == "create":
        return EXIT_OK, github_create(req, runner)
    if op == "publish":
        return EXIT_OK, github_publish(req, runner)
    if op == "rejected":
        return EXIT_OK, github_rejected(req, runner)
    if op == "reject":
        return EXIT_OK, github_reject(req, runner)
    if op == "defer":
        return EXIT_OK, github_defer(req, runner)
    return EXIT_UNSUPPORTED, None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _run_adapter(cmd: list[str], op: str, req: dict) -> tuple[int, dict | None]:
    try:
        out = subprocess.run([*cmd, op], input=json.dumps(req), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", check=False)
    except OSError as e:
        raise QueueError(f"queue adapter {cmd[0]!r} could not start: {e}") from e
    if out.stderr:
        sys.stderr.write(out.stderr)
    if out.returncode != EXIT_OK:
        return (out.returncode if out.returncode == EXIT_UNSUPPORTED else EXIT_ERROR), None
    try:
        data = json.loads(out.stdout)
    except ValueError as e:
        raise QueueError(f"queue adapter {cmd[0]!r} printed no JSON object for {op}: {e}") from e
    if not isinstance(data, dict):
        raise QueueError(f"queue adapter {cmd[0]!r} printed a non-object for {op}")
    return EXIT_OK, data


def handle(op: str, req: object, env: dict[str, str] | None = None, runner=gh_runner) -> tuple[int, dict | None]:
    if op not in OPS:
        raise QueueError(f"unknown op {op!r}; expected one of {', '.join(OPS)}")
    if not isinstance(req, dict):
        raise QueueError("request must be a JSON object")
    if req.get("contract") != CONTRACT:
        raise QueueError(f"request contract must be {CONTRACT}, got {req.get('contract')!r}")
    repo = req.get("repo")
    if not (isinstance(repo, str) and os.path.isabs(repo) and os.path.isdir(repo)):
        raise QueueError(f"request repo must be an existing absolute path, got {repo!r}")
    item_ref = req.get("ref")
    historical_file_read = bool(req.get("rev")) and (
        op == "rejected" or (op == "show" and isinstance(item_ref, str) and _FILE_REF_RE.fullmatch(item_ref))
    )
    revision = req.get("ref") if op in ("list", "describe", "inventory") else req.get("rev") if historical_file_read else None
    backend = resolve(repo, env, revision)
    if historical_file_read and backend["source"] == "github-host":
        backend = {"backend": "backlog", "source": "historical-file"}
    if backend["backend"] == "backlog":
        code, data = backlog_op(op, req)
        if (
            op == "describe" and req.get("verify_visibility") is True
            and origin_host(_git(repo, "remote", "get-url", "origin")) == "github.com"
        ):
            data["visibility"] = github_visibility(repo, runner)
            if data["visibility"] == "unknown":
                raise QueueError("GitHub did not confirm public or private repository visibility")
        if code == EXIT_UNSUPPORTED:
            sys.stderr.write(f"queue_backend: the backlog backend does not support {op!r}\n")
        elif op in ("describe", "list") and backend["source"] == "github-open-backlog" and data is not None:
            warnings = data.setdefault("warnings", [])
            if backend["open_items"]:
                warnings.append(LEGACY_BACKLOG_WARNING.format(n=backend["open_items"]))
            if backend["active_items"]:
                warnings.append(
                    f"backlog.md has {backend['active_items']} legacy [>] item(s); finish the sprint or run "
                    "reconcile-harness.py before migrating with migrate_backlog.py"
                )
        return code, data
    if backend["backend"] == "github":
        code, data = github_op(op, req, runner)
        if code == EXIT_UNSUPPORTED:
            sys.stderr.write(f"queue_backend: the github backend does not support {op!r}\n")
        elif op in ("describe", "list") and data is not None and backend.get("active_items"):
            data.setdefault("warnings", []).append(
                f"backlog.md has {backend['active_items']} unclaimed legacy [>] item(s); the issues queue stays "
                "active. To recover confirmed file work, run reconcile-harness.py with AGENT_QUEUE_BACKEND=backlog"
            )
        return code, data
    return _run_adapter(backend["command"], op, req)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--test"]:
        return run_tests()
    if len(argv) != 1:
        sys.stderr.write("usage: queue_backend.py <op> < request.json | --test\n")
        return EXIT_ERROR
    try:
        req = json.loads(sys.stdin.buffer.read().decode("utf-8") or "null")
    except ValueError as e:
        sys.stderr.write(f"queue_backend: request is not JSON: {e}\n")
        return EXIT_ERROR
    try:
        code, data = handle(argv[0], req)
    except QueueError as e:
        sys.stderr.write(f"queue_backend: {e}\n")
        return EXIT_ERROR
    if data is not None:
        print(json.dumps(data))
    return code


# ---------------------------------------------------------------------------
# Self-check (--test) — temp repos only
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


FIXTURE_BACKLOG = """# Backlog

<!--
## Template
- [ ] not real
-->

## Alpha group

- [ ] [FEAT] first alpha item
  wrapped tail
- [ ] [FEAT] second alpha item
- [ ] [FEAT] parked alpha *(deferred: waits on vendor)*

### Beta child

- [ ] [FIX] beta only item

## Gamma

- [ ] [DOCS] gamma doc *(blocked by: 1-alpha-group)*
- [ ] [TEST] gamma test

## Delta

- [ ] [FEAT] delta one

## Rejected — do not re-file

- **Drop the widget** (PR #9 follow-up) — rejected by the user; no failure seen. Re-file only with
  a recorded widget crash.
- **Plain entry** — out of scope.
"""

FIXTURE_TASKS = "# Running sprint\n\nstatus: open\n\n- [ ] sprint item\n"


def run_tests() -> int:
    import shutil
    import tempfile
    from unittest.mock import patch

    print("=== queue_backend.py --test ===\n")
    with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
        gh_runner(["api", "graphql"])
        _assert(run.call_args.args[0] == ["gh", "api", "--hostname", "github.com", "graphql"],
                "GitHub queue requests explicitly target github.com")
    selectors = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", ENV_VAR, "XDG_CONFIG_HOME"}
    env = {k: v for k, v in os.environ.items() if k not in selectors}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    })
    saved_env = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)  # subprocesses (git, backlog_candidates.py) inherit the neutralized env

    def git(cwd: str, *args: str) -> None:
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull,
                        "-C", cwd, *args], check=True, capture_output=True)

    def write(path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def cli(op: str, req: object, extra_env: dict[str, str] | None = None) -> tuple[int, Any, str]:
        run_env = dict(os.environ, **(extra_env or {}))
        out = subprocess.run([sys.executable, os.path.abspath(__file__), op], input=json.dumps(req),
                             capture_output=True, text=True, encoding="utf-8", env=run_env, check=False)
        try:
            data = json.loads(out.stdout) if out.stdout.strip() else None
        except ValueError:
            data = out.stdout
        return out.returncode, data, out.stderr

    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.realpath(os.path.join(tmp, "repo"))
            os.makedirs(repo)
            git(repo, "init", "-q", "-b", "main")
            write(os.path.join(repo, "backlog.md"), FIXTURE_BACKLOG)
            git(repo, "add", "backlog.md")
            git(repo, "commit", "-q", "--no-verify", "-m", "seed")
            cfg = os.path.join(tmp, "cfg")
            base_env = {"XDG_CONFIG_HOME": cfg}

            print("Test 1: resolver order")
            _assert(resolve(repo, dict(base_env)) == {"backend": "backlog", "source": "fallback"},
                    "no origin → backlog fallback")
            _assert(resolve(repo, dict(base_env, **{ENV_VAR: "github"}))["backend"] == "github",
                    "env names github")
            r = resolve(repo, dict(base_env, **{ENV_VAR: "python3 /x/adapter.py --flag"}))
            _assert(r == {"backend": "adapter", "source": "env", "command": ["python3", "/x/adapter.py", "--flag"]},
                    "env adapter command is shell-split")
            _assert(split_command('py "C:\\my tools\\a.py" -x', posix=False) == ["py", "C:\\my tools\\a.py", "-x"],
                    "Windows split keeps backslashes and drops quotes")
            try:
                split_command('py "C:/x', posix=True)
                _assert(False, "unbalanced quote → QueueError")
            except QueueError:
                _assert(True, "unbalanced quote → QueueError")
            git(repo, "remote", "add", "origin", "git@github.com:owner/repo.git")
            _assert(resolve(repo, dict(base_env))["source"] == "github-open-backlog",
                    "github.com origin with open backlog.md items keeps backlog")
            git(repo, "rm", "-q", "--cached", "backlog.md")
            git(repo, "commit", "-q", "--no-verify", "-m", "migrated")
            _assert(resolve(repo, dict(base_env), "HEAD")["backend"] == "github",
                    "with a list ref, the open-items guard reads backlog.md at that ref")
            _assert(resolve(repo, dict(base_env), "HEAD~1")["backend"] == "backlog",
                    "a ref still holding open items keeps backlog")
            git(repo, "reset", "-q", "HEAD~1")
            _assert(resolve(repo, dict(base_env, **{ENV_VAR: "backlog"}))["source"] == "env",
                    "env beats the host rule")
            empty = os.path.realpath(os.path.join(tmp, "empty"))
            os.makedirs(empty)
            git(empty, "init", "-q", "-b", "main")
            git(empty, "remote", "add", "origin", "https://github.com/owner/empty.git")
            standalone = os.path.join(tmp, "installed-queue")
            os.mkdir(standalone)
            for filename in ("queue_backend.py", "backlog_candidates.py"):
                shutil.copyfile(os.path.join(HERE, filename), os.path.join(standalone, filename))
            described = subprocess.run(
                [sys.executable, os.path.join(standalone, "queue_backend.py"), "describe"],
                input=json.dumps({"contract": 1, "repo": empty, "verify_visibility": False}),
                capture_output=True, text=True,
            )
            _assert(described.returncode == 0 and json.loads(described.stdout)["backend"] == "github",
                    "the installed two-file queue works without cycle_state.py")
            write(os.path.join(empty, "backlog.md"), "# Backlog\n\n## Done\n\n- [x] closed\n")
            _assert(resolve(empty, dict(base_env)) == {"backend": "github", "source": "github-host"},
                    "github.com origin without open items → github")
            write(os.path.join(empty, "backlog.md"), "# Backlog\n\n## Sprint\n\n- [>] last active item\n")
            _assert(resolve(empty, dict(base_env))["backend"] == "github",
                    "unclaimed legacy marker does not switch a migrated GitHub repo back to backlog")
            os.mkdir(os.path.join(empty, "tasks.md"))
            try:
                resolve(empty, dict(base_env))
                _assert(False, "unreadable claims must not switch the queue")
            except QueueError as e:
                _assert("tasks.md" in str(e), "unreadable claims fail backend resolution")
            os.rmdir(os.path.join(empty, "tasks.md"))
            write(os.path.join(empty, "tasks.md"), "# Sprint\nstatus: failed\n\n## Covers\n\n- #17 issue claim\n")
            _assert(resolve(empty, dict(base_env))["backend"] == "github",
                    "an issues sprint does not claim an old file item")
            write(os.path.join(empty, "tasks.md"), "# Sprint\nstatus: failed\n\n## Covers\n\n- [ ] different file item\n")
            _assert(resolve(empty, dict(base_env))["backend"] == "github",
                    "an unrelated file claim does not switch the queue")
            write(os.path.join(empty, "tasks.md"), "# Sprint\nstatus: failed\n\n## Covers\n\n- [ ] last active item\n")
            git(empty, "add", "backlog.md", "tasks.md")
            git(empty, "commit", "-q", "--no-verify", "-m", "in flight")
            active = resolve(empty, dict(base_env))
            _assert(active["backend"] == "backlog" and active["open_items"] == 0 and active["active_items"] == 1,
                    "claimed legacy in-flight item keeps the file queue even without open items")
            os.remove(os.path.join(empty, "backlog.md"))
            _assert(resolve(empty, dict(base_env))["backend"] == "github", "github.com origin, no backlog.md → github")
            _assert(resolve(empty, dict(base_env), "HEAD") == active,
                    "pinned ref retains legacy in-flight file items")
            forge = os.path.realpath(os.path.join(tmp, "forge"))
            os.makedirs(forge)
            git(forge, "init", "-q", "-b", "main")
            git(forge, "remote", "add", "origin", "https://git.example.org/team/forge.git")
            _assert(resolve(forge, dict(base_env))["source"] == "fallback", "unregistered host → fallback")
            adapter = os.path.join(tmp, "adapter.py")
            write(adapter, ADAPTER_SOURCE)
            os.makedirs(os.path.join(cfg, "agent-toolkit"))
            write(registry_path(base_env), json.dumps({"hosts": {"git.example.org": [sys.executable, adapter]}}))
            _assert(resolve(forge, dict(base_env)) == {"backend": "adapter", "source": "registry",
                                                      "command": [sys.executable, adapter]},
                    "registry host → adapter command")
            _assert(resolve(repo, dict(base_env))["backend"] == "backlog",
                    "github host rule precedes the registry")
            for url, host in (("ssh://git@git.example.org:2222/a/b.git", "git.example.org"),
                              ("https://user@GitHub.com/a/b", "github.com"),
                              ("C:\\repos\\x", None), ("/srv/x.git", None)):
                _assert(origin_host(url) == host, f"origin_host({url!r}) == {host!r}")

            locked = os.path.realpath(os.path.join(tmp, "locked"))
            os.makedirs(os.path.join(locked, "backlog.md"))  # a directory: unreadable, not absent
            git(locked, "init", "-q", "-b", "main")
            git(locked, "remote", "add", "origin", "https://github.com/owner/locked.git")
            try:
                resolve(locked, dict(base_env))
                _assert(False, "unreadable backlog.md on github.com → QueueError, not github")
            except QueueError:
                _assert(True, "unreadable backlog.md on github.com → QueueError, not github")

            print("\nTest 2: contract framing and exit codes")
            req = {"contract": 1, "repo": repo}
            code, data, _ = cli("describe", req, base_env)
            _assert(code == 0 and data["backend"] == "backlog" and data["contract"] == 1
                    and "rejected" in data["ops"], "describe → 0 with backend/contract/ops")
            code, data, _ = cli("create", dict(req, items=[{"key": "k", "title": "t"}]), base_env)
            _assert(code == 0 and data == {"edit_file": "backlog.md"}, "create on backlog → edit_file")
            code, data, _ = cli("reject", dict(req, ref="backlog.md:9"), base_env)
            _assert(code == 2 and data is None, "reject on backlog → exit 2")
            code, _, err = cli("list", {"contract": 2, "repo": repo}, base_env)
            _assert(code == 1 and "contract" in err, "wrong contract version → exit 1")
            code, _, _ = cli("list", {"contract": 1}, base_env)
            _assert(code == 1, "missing repo → exit 1")
            code, _, _ = cli("bogus", req, base_env)
            _assert(code == 1, "unknown op → exit 1")
            code, data, _ = cli("publish", req, base_env)
            _assert(code == 2 and data is None, "publish on backlog → exit 2")
            code, _, err = cli("create", dict(req, items=[]), dict(base_env, **{ENV_VAR: "github"}))
            _assert(code == 1 and "items" in err, "github create with no items → exit 1 before any gh call")

            print("\nTest 3: backlog list parity with backlog_candidates.py --json --counts")
            script = os.path.join(HERE, "backlog_candidates.py")
            tasks = os.path.join(repo, "tasks.md")
            write(tasks, FIXTURE_TASKS)
            for full in (False, True):
                flags = ["--json", "--counts"] + (["--full-scan"] if full else [])
                ref_out = subprocess.run([sys.executable, script, "--tasks", tasks, "--backlog",
                                          os.path.join(repo, "backlog.md"), *flags],
                                         capture_output=True, text=True, check=True)
                expected = json.loads(ref_out.stdout)
                code, data, _ = cli("list", dict(req, full_scan=full), base_env)
                got = data["candidates"] if code == 0 else []
                mode = "full scan" if full else "fast path"
                _assert([c["title"] for c in got] == [c["title"] for c in expected],
                        f"{mode}: same titles in the same order ({len(expected)})")
                _assert([c["counts"] for c in got]
                        == [{k: c[k] for k in ("open", "deferred", "blocked")} for c in expected],
                        f"{mode}: counts open/deferred/blocked match")
                _assert([c["ref"] for c in got] == [f"{c['source']}:{c['line']}" for c in expected],
                        f"{mode}: ref = <source>:<line>")
            alpha = next(c for c in data["candidates"] if c["title"] == "Alpha group")
            _assert(alpha["items"] == ["[FEAT] first alpha item wrapped tail", "[FEAT] second alpha item"],
                    "items[] = open unparked texts in document order, wrapped lines folded")
            _assert(alpha["tag"] == "FEAT", "shared [type] becomes tag")
            gamma = next(c for c in data["candidates"] if c["title"] == "Gamma")
            _assert(gamma["tag"] == "TEST" and gamma["counts"]["blocked"] == 1, "tag ignores parked items; blocked counted")
            h1 = data["candidates"][0]
            _assert(h1["ref"] == "tasks.md:1" and h1["items"] == [], "tasks.md h1 block carries no items")
            _assert(data["parked"] == [] and data["claimed"] == [], "parked/claimed empty unless asked/claimed")

            code, data, _ = cli("list", dict(req, full_scan=True, parked=True), base_env)
            _assert(data["parked"] == [
                {"ref": "backlog.md:13", "kind": "deferred", "payload": "waits on vendor"},
                {"ref": "backlog.md:21", "kind": "blocked", "payload": "1-alpha-group"},
            ], "parked[] maps --parked --json markers")

            print("\nTest 4: list honors ref and tasks")
            write(os.path.join(repo, "backlog.md"), FIXTURE_BACKLOG.replace("## Delta", "## Delta edited"))
            code, data, _ = cli("list", dict(req, full_scan=True, ref="HEAD"), base_env)
            _assert("Delta" in [c["title"] for c in data["candidates"]], "ref reads the committed queue")
            head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            _assert(data["rev"] == head, "list echoes the resolved rev")
            write(os.path.join(repo, "backlog.md"), "# Moved\n\n\n\n" + FIXTURE_BACKLOG)
            code, shown, _ = cli("show", dict(req, ref="backlog.md:10", rev=data["rev"]), base_env)
            _assert(code == 0 and shown["title"] == "[FEAT] first alpha item wrapped tail",
                    "show with rev reads the listed commit, not the shifted working tree")
            code, rej, _ = cli("rejected", dict(req, rev=data["rev"]), base_env)
            _assert(code == 0 and rej["entries"][0]["ref"] == "backlog.md:30", "rejected with rev reads the commit")
            write(os.path.join(repo, "backlog.md"), FIXTURE_BACKLOG.replace("## Delta", "## Delta edited"))
            code, data, _ = cli("list", dict(req, full_scan=True), base_env)
            _assert("Delta edited" in [c["title"] for c in data["candidates"]], "no ref reads the working tree")
            git(repo, "checkout", "-q", "--", "backlog.md")
            alt = os.path.join(tmp, "alt-tasks.md")
            write(alt, "# Other sprint\nstatus: open\n")
            code, data, _ = cli("list", dict(req, tasks=alt), base_env)
            _assert(data["candidates"][0]["title"] == "Other sprint", "tasks path overrides <repo>/tasks.md")
            code, _, err = cli("list", dict(req, ref="no-such-rev"), base_env)
            _assert(code == 1 and "no-such-rev" in err, "unresolvable ref → exit 1")

            print("\nTest 5: claimed items")
            wt = os.path.join(repo, ".worktrees", "wt1")
            git(repo, "worktree", "add", "-q", "-b", "b1", wt)
            write(os.path.join(wt, "backlog.md"), FIXTURE_BACKLOG.replace("- [ ] [FEAT] delta one\n", ""))
            code, data, _ = cli("list", dict(req, full_scan=True), base_env)
            _assert([c["ref"] for c in data["claimed"]] == ["backlog.md:26"], "claimed[] names the claimed line")
            _assert("Delta" not in [c["title"] for c in data["candidates"]], "a fully claimed group is not listed")
            _assert(any("claimed" in w for w in data["warnings"]), "claim note lands in warnings[]")
            git(repo, "worktree", "remove", "--force", wt)

            global _run_candidates
            real_run = _run_candidates
            stale = [{"source": "backlog.md", "kind": "h2", "title": "Renamed since", "line": 8, "items": 2,
                      "open": 3, "deferred": 1, "blocked": 0}]
            _run_candidates = lambda args: (stale, [])  # noqa: E731 — the queue moved between reads
            try:
                backlog_list(dict(req))
                _assert(False, "a queue changed between the two reads → QueueError")
            except QueueError:
                _assert(True, "a queue changed between the two reads → QueueError")
            finally:
                _run_candidates = real_run

            print("\nTest 6: show and rejected")
            code, data, _ = cli("show", dict(req, ref="backlog.md:10"), base_env)
            _assert(code == 0 and data["title"] == "[FEAT] first alpha item wrapped tail"
                    and data["body"] == "- [ ] [FEAT] first alpha item\n  wrapped tail"
                    and data["parent"] == "backlog.md:8", "show item: folded title, raw body, heading parent")
            code, data, _ = cli("show", dict(req, ref="backlog.md:21"), base_env)
            _assert(data["blocked_by"] == ["1-alpha-group"] and data["title"] == "[DOCS] gamma doc",
                    "show item: blocked_by payload, marker dropped from title")
            code, data, _ = cli("show", dict(req, ref="backlog.md:13"), base_env)
            _assert(data["blocked_by"] == [], "show item: a deferred marker is not a blocker")
            write(tasks, "# Sprint A\nstatus: open\n\n## Scope\n\n- x\n\n## Covers\n\n- [ ] item\n\n# Sprint B\n")
            code, data, _ = cli("show", dict(req, ref="tasks.md:1"), base_env)
            _assert(code == 0 and "## Covers" in data["body"] and "Sprint B" not in data["body"],
                    "show on a tasks.md h1 spans its ## sections up to the next h1")
            write(tasks, FIXTURE_TASKS)
            _assert(" ".join(bc._BLOCK_MARKER_RE.sub(_strip_marker, "Doc *(blocked by: <n>-<slug>)* and *(deferred: x)* tail").split())
                    == "Doc *(blocked by: <n>-<slug>)* and tail", "title keeps placeholder markers, collapses gaps")
            code, data, _ = cli("show", dict(req, ref="backlog.md:15"), base_env)
            _assert(data["title"] == "Beta child" and data["parent"] == "backlog.md:8"
                    and data["body"] == "- [ ] [FIX] beta only item", "show heading: region body, outer parent")
            code, _, _ = cli("show", dict(req, ref="backlog.md:2"), base_env)
            _assert(code == 1, "show on a non-item line → exit 1")
            code, _, _ = cli("show", dict(req, ref="README.md:1"), base_env)
            _assert(code == 1, "show on a foreign file → exit 1")
            code, data, _ = cli("rejected", req, base_env)
            _assert(data == {"entries": [
                {"ref": "backlog.md:30", "title": "Drop the widget",
                 "reason": "rejected by the user; no failure seen.", "refile_bar": "a recorded widget crash"},
                {"ref": "backlog.md:32", "title": "Plain entry", "reason": "out of scope.", "refile_bar": ""},
            ]}, "rejected splits title / reason / re-file bar")

            print("\nTest 7: adapter through the registry")
            forge_req = {"contract": 1, "repo": forge}
            code, data, _ = cli("describe", forge_req, base_env)
            _assert(code == 0 and data.get("backend") == "fixture-adapter", "registry adapter answers describe")
            code, data, _ = cli("list", forge_req, base_env)
            _assert(code == 0 and data["candidates"][0]["ref"] == "#1", "adapter list passes through")
            code, data, _ = cli("defer", dict(forge_req, ref="#1", reason="r"), base_env)
            _assert(code == 2 and data is None, "adapter exit 2 passes through")
            code, _, err = cli("show", forge_req, base_env)
            _assert(code == 1 and "boom" in err, "adapter error → exit 1, stderr forwarded")
            registry = registry_path(base_env)
            write(registry, json.dumps({"hosts": ["invalid"]}))
            code, _, err = cli("describe", forge_req, base_env)
            _assert(code == 1 and registry in err and "hosts must be an object" in err and "Traceback" not in err,
                    "a malformed hosts registry reports its path without a traceback")

            run_github_tests(tmp, git, write)
            run_github_write_tests(tmp, git)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


# Fixtures follow the envelope `gh api graphql` printed for LIST_QUERY against a live repo
# (`{"data": {"repository": {"isPrivate": ..., "issues": {"pageInfo": ..., "nodes": [...]}}}}`).

def _fx_conn(nodes: list[dict], cursor: str | None = None) -> dict:
    return {"pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}, "nodes": nodes}


def _fx_issue(n: int, title: str, assoc: str = "OWNER", labels: tuple = (QUEUE_LABEL,), body: str = "",
              parent: tuple | None = None, blocked: tuple = (), subs: tuple = (), prs: tuple = (),
              sub_cursor: str | None = None) -> dict:
    def node(num: int, state: str = "OPEN", repo: str = "owner/repo", title_: str = "") -> dict:
        return {"number": num, "state": state, "title": title_, "repository": {"nameWithOwner": repo}}
    return {
        "number": n, "title": title, "body": body, "url": f"https://github.com/owner/repo/issues/{n}",
        "state": "OPEN", "authorAssociation": assoc, "repository": {"nameWithOwner": "owner/repo"},
        "parent": None if parent is None else {"number": parent[1], "repository": {"nameWithOwner": parent[0]}},
        "labels": _fx_conn([{"name": label} for label in labels]),
        "blockedBy": _fx_conn([{k: v for k, v in node(*b).items() if k != "title"} for b in blocked]),
        "subIssues": _fx_conn([node(*s) for s in subs], sub_cursor),
        "closedByPullRequestsReferences": _fx_conn(
            [{"number": p, "url": f"https://github.com/owner/repo/pull/{p}", "state": state, "authorAssociation": assoc}
             for p, state, assoc in ((pr if isinstance(pr, tuple) else (pr, "OPEN", "MEMBER")) for pr in prs)]),
    }


def _fx_queue() -> tuple[list[dict], list[dict]]:
    """Two pages of open task-queue issues covering every mapping rule."""
    page1 = [
        _fx_issue(1, "[FEAT] lone feature"),
        _fx_issue(2, "[FEAT] stranger's issue", assoc="NONE"),
        _fx_issue(3, "Group A", assoc="MEMBER",
                  subs=((4, "OPEN", "owner/repo", "[FIX] a1"), (5, "OPEN", "owner/repo", "[FIX] a2"),
                        (6, "CLOSED", "owner/repo", "[FIX] done"), (7, "OPEN", "owner/repo", "[FIX] a4")),
                  sub_cursor="s1"),
        _fx_issue(4, "[FIX] a1", parent=("owner/repo", 3)),
        _fx_issue(5, "[FIX] a2", parent=("owner/repo", 3), blocked=((9, "OPEN"),)),
        _fx_issue(7, "[FIX] a4", assoc="CONTRIBUTOR", parent=("owner/repo", 3)),
        _fx_issue(8, "[FIX] a5", parent=("owner/repo", 3), labels=(QUEUE_LABEL, "deferred")),
        _fx_issue(9, "[FIX] blocker"),
        _fx_issue(10, "[DOCS] blocked one", blocked=((1, "OPEN"), (11, "CLOSED"))),
        _fx_issue(24, "[FIX] child read before its parent", parent=("owner/repo", 25)),
    ]
    page2 = [
        _fx_issue(12, "[TEST] closed blocker only", blocked=((11, "CLOSED"),)),
        _fx_issue(13, "[FEAT] someday idea", labels=(QUEUE_LABEL, "someday")),
        _fx_issue(14, "[FEAT] has open PR", prs=(40,)),
        _fx_issue(15, "[FEAT] covered in a worktree"),
        _fx_issue(16, "[FEAT] closed by an unpushed commit"),
        _fx_issue(17, "Group B", subs=((18, "OPEN", "owner/repo", "[FIX] b1"),)),
        _fx_issue(18, "[FIX] b1", parent=("owner/repo", 17), labels=(QUEUE_LABEL, "deferred"),
                  body="Context.\nDeferred: waits on vendor\n"),
        _fx_issue(19, "[FIX] child of a foreign parent", parent=("other/repo", 5)),
        _fx_issue(20, "[FEAT] unlabelled in labels connection", labels=("bug",)),
        _fx_issue(21, "Group C", subs=((22, "OPEN", "owner/repo", "[FIX] c1"),)),
        _fx_issue(22, "[FIX] c1", parent=("owner/repo", 21), prs=(41,)),
        _fx_issue(23, "[FEAT] merged PR and a stranger's PR", prs=((42, "MERGED", "MEMBER"), (43, "OPEN", "NONE"))),
        _fx_issue(25, "Group D", subs=((24, "OPEN", "owner/repo", "[FIX] child read before its parent"),)),
    ]
    return page1, page2


def _fake_gh(pages: dict, conn_pages: dict | None = None, issues: dict | None = None, private: bool = False,
             calls: list | None = None, child_details: dict | None = None):
    import copy

    def run(args: list[str]) -> tuple[int, str, str]:
        query, variables = "", {}
        for i, a in enumerate(args):
            if a in ("-f", "-F"):
                k, v = args[i + 1].split("=", 1)
                if k == "query":
                    query = v
                elif k.endswith("[]"):
                    variables.setdefault(k[:-2], []).append(v)
                else:
                    variables[k] = int(v) if a == "-F" else v
        if calls is not None:
            calls.append((query, variables))
        if query in (LIST_QUERY, INVENTORY_QUERY):
            repo = {"isPrivate": private, "issues": copy.deepcopy(pages[variables.get("after")])}
            if query == INVENTORY_QUERY:
                repo["issues"]["nodes"] = [n for n in repo["issues"]["nodes"] if QUEUE_LABEL in _labels(n)]
        elif query == DESCRIBE_QUERY:
            repo = {"visibility": "PRIVATE" if private else "PUBLIC"}
        elif query == SHOW_QUERY:
            repo = {"issue": copy.deepcopy((issues or {}).get(variables["number"]))}
        elif query == UNREAD_CHILDREN_QUERY:
            nodes = [(child_details or {})[issue_id] for issue_id in variables["ids"]]
            return 0, json.dumps({"data": {"nodes": nodes}}), ""
        else:
            conn = next(c for c in _NODE_SEL if query == _conn_query(c))
            repo = {"issue": {conn: copy.deepcopy((conn_pages or {})[(variables["number"], conn, variables["after"])])}}
        return 0, json.dumps({"data": {"repository": repo}}), ""
    return run


def run_github_tests(tmp: str, git, write) -> None:
    import copy

    print("\nTest 8: github backend — trust gate, groups, parking, order")
    repo = os.path.realpath(os.path.join(tmp, "gh"))
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", "base")
    git(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    base = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    git(repo, "update-ref", "refs/remotes/origin/main", base)
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", "[FEAT] local work\n\nCloses #16\nFixes other/repo#15")
    wt = os.path.join(repo, ".worktrees", "cov")
    git(repo, "worktree", "add", "-q", "-b", "cov", wt)
    write(os.path.join(wt, "tasks.md"), "# Sprint\nstatus: active\n\n## Covers\n\n- #15 [FEAT] covered, follow-up to #12\n\n## Notes\n\n- #1\n")

    page1, page2 = _fx_queue()
    pages = {None: _fx_conn(page1, "p1"), "p1": _fx_conn(page2)}
    conn_pages = {(3, "subIssues", "s1"): _fx_conn([{"number": 8, "state": "OPEN", "title": "[FIX] a5",
                                                     "repository": {"nameWithOwner": "owner/repo"}}])}
    calls: list = []
    runner = _fake_gh(pages, conn_pages, calls=calls)
    req = {"contract": 1, "repo": repo}
    for private, visibility in ((False, "public"), (True, "private")):
        _, described = handle(
            "describe", dict(req, verify_visibility=True), {ENV_VAR: "backlog"}, _fake_gh({}, private=private),
        )
        _assert(described["backend"] == "backlog" and described["visibility"] == visibility,
                f"findings can verify {visibility} visibility without switching off the file queue")
    _, described = handle("describe", req, {ENV_VAR: "backlog"}, runner)
    _assert(described["visibility"] == "unknown" and not calls,
            "ordinary file queue descriptions leave visibility unknown without contacting GitHub")
    _, described = handle("describe", dict(req, verify_visibility=False), {ENV_VAR: "github"}, runner)
    _assert(described["backend"] == "github" and described["visibility"] == "unknown" and not calls,
            "harness checks can describe the github backend without contacting GitHub")
    data = github_list(dict(req, full_scan=True, parked=True), runner)
    refs = [c["ref"] for c in data["candidates"]]
    _assert(refs == ["#1", "#3", "#9", "#12", "#19", "#23", "#25", "#13"],
            f"full scan: trusted, unparked, unclaimed issues by number with someday last ({refs})")
    _assert("#2" not in refs and any("#2" in w and "NONE" in w for w in data["warnings"]),
            "trust gate: a non-member author is skipped with a warning")
    _assert("#20" not in refs, "trust gate: an issue without the task-queue label is not a candidate")
    _assert(not {"#4", "#5", "#7", "#8"} & set(refs), "sub-issues of a listed parent are never standalone")
    _assert("#19" in refs, "a sub-issue of a parent in another repo stands alone")
    group = data["candidates"][1]
    _assert(group["items"] == ["[FIX] a1"] and group["item_refs"] == ["#4"] and group["tag"] == "FIX",
            "parent takes only its eligible open sub-issues as items")
    _assert(group["excluded"] == [{"ref": "#5", "reason": "blocked"},
                                  {"ref": "#7", "reason": "not a trusted task-queue issue"},
                                  {"ref": "#8", "reason": "deferred"}],
            "ineligible sub-issues are named with their reason (sub-issue page 2 read)")
    _assert(group["counts"] == {"open": 4, "deferred": 1, "blocked": 1}, "group counts cover all open sub-issues")
    _assert(any(q == _conn_query("subIssues") for q, _ in calls), "a nested connection with a next page is paged")
    lone = data["candidates"][0]
    _assert(lone["items"] == ["[FEAT] lone feature"] and lone["item_refs"] == ["#1"]
            and lone["tag"] == "FEAT" and lone["url"].endswith("/issues/1"), "a lone issue is its own single item")
    _assert({"ref": "#10", "kind": "blocked", "payload": "#1"} in data["parked"],
            "an open blocker parks the issue; a closed one is ignored")
    _assert("#12" in refs, "only closed blockers → not blocked")
    _assert({"ref": "#18", "kind": "deferred", "payload": "waits on vendor"} in data["parked"],
            "deferred label parks with the `Deferred:` body line as payload")
    _assert({"ref": "#17", "kind": "deferred", "payload": "no eligible sub-issue: #18 deferred"} in data["parked"],
            "a parent whose open sub-issues are all ineligible is parked")
    _assert("#21" not in refs and not any(p["ref"] == "#21" for p in data["parked"]),
            "a parent whose open sub-issues are all claimed is neither listed nor parked")
    claimed = {c["ref"]: c["by"] for c in data["claimed"]}
    _assert(claimed.get("#14", "").endswith("/pull/40"), "claim (b): an open closing PR")
    _assert("#23" not in claimed and any("pull/43" in w for w in data["warnings"]),
            "claim (b) ignores a merged PR and an untrusted author's PR (with a warning)")
    _assert(os.path.realpath(claimed.get("#15", "")) == os.path.realpath(wt), "claim (a): a .worktrees `## Covers` ref")
    _assert("#1" not in claimed, "a ref outside `## Covers` claims nothing")
    _assert("#12" not in claimed, "a `#N` quoted in a Covers title is not a claim")
    _assert(claimed.get("#16") == "main (unpushed commit)", "claim (c): an unpushed closing commit on the default branch")
    calls.clear()
    code, inventory = handle("inventory", dict(req, ref=base), {}, runner)
    entries = {i["ref"]: i for i in inventory["entries"]}
    _assert(code == EXIT_OK and {"#4", "#5", "#8", "#14", "#15", "#18", "#22", "#25"} <= entries.keys()
            and not {"#2", "#20"} & entries.keys() and "Deferred:" in entries["#18"]["body"],
            "inventory includes eligible, blocked, deferred and claimed children and roots, excluding non-queue issues")
    _assert(calls == [(INVENTORY_QUERY, {"owner": "owner", "name": "repo"}),
                      (INVENTORY_QUERY, {"owner": "owner", "name": "repo", "after": "p1"})],
            "inventory reads later pages without requesting selection-only connections")
    broken_pages = _fake_gh({None: pages[None], "p1": _fx_conn(page2, "p1")})
    try:
        handle("inventory", req, {}, broken_pages)
    except QueueError as exc:
        _assert("pagination did not advance" in str(exc), "inventory rejects an incomplete scan")
    else:
        _assert(False, "inventory rejects an incomplete scan")

    tasks_path = os.path.join(wt, "tasks.md")
    key = "a" * 64
    git_dir = _git(wt, "rev-parse", "--git-dir")
    archive_dir = os.path.join(repo, ".git", "task-cycle", key)
    os.makedirs(archive_dir)
    write(os.path.join(archive_dir, "contract.md"), bc._read_optional(tasks_path) or "")
    write(os.path.join(wt, git_dir, "task-cycle-contract"), f"cov\n{key}\n")
    os.remove(tasks_path)
    data = github_list(dict(req, full_scan=True), runner)

    def archive_claimed(result):
        return any(c["ref"] == "#15" and os.path.realpath(c["by"]) == os.path.realpath(wt)
                   for c in result["claimed"])

    _assert(archive_claimed(data) and "#15" not in {
        c["ref"] for c in data["candidates"]
    }, "an archived Covers claim survives removal of tasks.md before a PR exists")
    _assert(not any(c["ref"] == "#15" for c in github_list(dict(req, repo=wt), runner)["claimed"])
            and archive_claimed(github_list(dict(req, repo=wt, ref=base), runner)),
            "a worktree counts its archived claims only on pinned scans")
    _assert(data["incomplete"] is False and not github_list(dict(req), runner)["parked"], "parked[] only when asked")
    fast = github_list(dict(req), runner)["candidates"]
    _assert([c["ref"] for c in fast] == ["#1", "#3", "#9"], "fast path caps at 3, oldest first")

    print("\nTest 9: github backend — default branch, page limit, errors, show, describe")
    git(repo, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
    _assert(default_branch(repo) == "main", "unset origin/HEAD falls back to an existing origin/main")
    data = github_list(dict(req), runner)
    _assert({"ref": "#16", "by": "main (unpushed commit)"} in data["claimed"], "claim (c) still read without origin/HEAD")
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    _assert(default_branch(repo) is None, "no origin/HEAD, origin/main or origin/master → unresolvable")
    data = github_list(dict(req), runner)
    _assert(any("default branch" in w for w in data["warnings"]) and data["candidates"],
            "unresolvable default branch → warning, list still answers")

    data = github_list(dict(req, full_scan=True), runner, max_pages=1)
    _assert(data["incomplete"] is True and any(w.startswith("incomplete") for w in data["warnings"]),
            "page limit → incomplete flag and warning")
    _assert("#3" not in [c["ref"] for c in data["candidates"]] and data["candidates"],
            "an issue whose connection hit the limit is left out, not half-read")
    _assert("#24" not in [c["ref"] for c in data["candidates"]] and any("#24" in w for w in data["warnings"]),
            "a truncated read never offers a sub-issue whose parent was not read")
    children = [{"id": f"I_{n}", "number": n, "state": "OPEN", "title": "[FIX] item",
                 "repository": {"nameWithOwner": "owner/repo"}} for n in (4, 8)]
    group_parent = dict(next(issue for issue in page1 if issue["number"] == 3), subIssues=_fx_conn(children))
    group_child = next(issue for issue in page1 if issue["number"] == 4)
    group_pages = {None: _fx_conn([page1[0], group_parent, group_child], "p1")}
    child_details = {"I_8": {"id": "I_8", "authorAssociation": "OWNER",
                             "labels": _fx_conn([{"name": QUEUE_LABEL}])}}
    group_runner = _fake_gh(group_pages, child_details=child_details)
    truncated_group = github_list(dict(req, full_scan=True), group_runner, max_pages=1)
    _assert(truncated_group["incomplete"] and [c["ref"] for c in truncated_group["candidates"]] == ["#1"]
            and "incomplete: #3 left out; incomplete read of sub-issues #8" in truncated_group["warnings"],
            "a parent with one eligible and one unread child is withheld while unrelated work remains eligible")
    child_details["I_8"]["labels"] = _fx_conn([])
    truncated_group = github_list(dict(req, full_scan=True), group_runner, max_pages=1)
    _assert([c["ref"] for c in truncated_group["candidates"]] == ["#1", "#3"]
            and truncated_group["candidates"][1]["excluded"] == [
                {"ref": "#8", "reason": "not a trusted task-queue issue"},
            ], "truncation does not withhold a parent solely because a child lacks the queue label")
    stranger = {None: _fx_conn([_fx_issue(2, "x", assoc="NONE")], "p1")}
    try:
        github_list(dict(req), _fake_gh(stranger), max_pages=1)
        _assert(False, "incomplete read with zero candidates → QueueError, never an empty queue")
    except QueueError:
        _assert(True, "incomplete read with zero candidates → QueueError, never an empty queue")

    def failing(code: int, err: str):
        return lambda args: (code, "", err)
    for code, err, label in ((4, "To get started with GitHub CLI, please run:  gh auth login", "unauthenticated"),
                             (1, "HTTP 502", "server error")):
        try:
            github_list(dict(req), failing(code, err))
            _assert(False, f"gh {label} → QueueError")
        except QueueError as e:
            _assert(("gh auth login" in str(e)) == (code == 4), f"gh {label} → QueueError naming the fix")
    errs = lambda args: (0, json.dumps({"errors": [{"message": "Field 'x' doesn't exist"}]}), "")  # noqa: E731
    try:
        github_list(dict(req), errs)
        _assert(False, "GraphQL errors → QueueError")
    except QueueError:
        _assert(True, "GraphQL errors → QueueError")
    saved_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.path.join(tmp, "no-bin")
    try:
        try:
            gh_runner(["--version"])
            _assert(False, "gh missing → QueueError, never a backlog.md fallback")
        except QueueError as e:
            _assert("gh" in str(e) and "backlog.md" in str(e), "gh missing → QueueError, never a backlog.md fallback")
    finally:
        os.environ["PATH"] = saved_path
    write(os.path.join(repo, "backlog.md"), "# Backlog\n\n## A\n\n- [ ] open\n")
    code, data = handle("list", dict(req), {}, failing(4, "gh auth login"))
    _assert(code == 0 and "rev" in data and data["candidates"][0]["title"] == "A",
            "resolver stays on backlog while backlog.md has open items (gh never called)")
    code, data = handle("describe", dict(req, ref="HEAD"), {}, _fake_gh(pages))
    _assert(code == 0 and data["backend"] == "github",
            "describe with ref reads the open-items guard at that ref, not the working tree")
    try:
        handle("list", dict(req), {ENV_VAR: "github"}, failing(4, "gh auth login"))
        _assert(False, "github with gh unauthenticated → QueueError even with backlog.md present")
    except QueueError:
        _assert(True, "github with gh unauthenticated → QueueError even with backlog.md present")
    os.remove(os.path.join(repo, "backlog.md"))

    write(os.path.join(repo, "backlog.md"), "# Backlog\n\n## A\n\n- [ ] historic\n\n"
          "## Rejected — do not re-file\n\n- **Old idea** — no demand.\n")
    git(repo, "add", "backlog.md")
    git(repo, "commit", "-q", "--no-verify", "-m", "file queue")
    git(repo, "rm", "-q", "backlog.md")
    git(repo, "commit", "-q", "--no-verify", "-m", "archive the file queue")
    _, historic = handle("list", dict(req, ref="HEAD^"), {}, failing(4, "gh auth login"))
    historic_req = dict(req, rev=historic["rev"])
    try:
        _, shown = handle("show", dict(historic_req, ref="backlog.md:5"), {}, failing(4, "gh auth login"))
        _, rejected = handle("rejected", historic_req, {}, failing(4, "gh auth login"))
        _assert(shown["title"] == "historic" and rejected["entries"][0]["title"] == "Old idea",
                "historical show and rejected both use the file queue from list's revision")
    except QueueError as e:
        _assert(False, f"historical show and rejected both use the file queue from list's revision: {e}")

    backlog_path = os.path.join(repo, "backlog.md")
    write(backlog_path, "# Backlog\n\n## Rejected — do not re-file\n\n- **Old idea** — no demand.\n")
    git(repo, "add", "backlog.md")
    git(repo, "commit", "-q", "--no-verify", "-m", "rejections only")
    try:
        _, rejected = handle("rejected", dict(req, rev="HEAD"), {}, failing(4, "gh auth login"))
        _assert(rejected["entries"][0]["title"] == "Old idea",
                "historical rejected reads a file snapshot with no open items")
    except QueueError as e:
        _assert(False, f"historical rejected reads a file snapshot with no open items: {e}")
    os.remove(backlog_path)

    for url in ("ssh://git@github.com:22/owner/repo.git", "git@github.com:owner/repo", "https://github.com/owner/repo/"):
        git(repo, "remote", "set-url", "origin", url)
        _assert(github_slug(repo) == ("owner", "repo"), f"github_slug({url!r})")
    git(repo, "remote", "set-url", "origin", "https://github.com/owner/repo.git")

    issues = {n["number"]: n for n in copy.deepcopy(page1 + page2)}
    show_runner = _fake_gh(pages, conn_pages, issues)
    shown = github_show(dict(req, ref="#5"), show_runner)
    _assert(shown == {"ref": "#5", "title": "[FIX] a2", "body": "", "labels": [QUEUE_LABEL], "blocked_by": ["#9"],
                      "parent": "#3", "url": "https://github.com/owner/repo/issues/5", "state": "OPEN"},
            "show: title, labels, open blockers, parent ref, url")
    _assert(github_show(dict(req, ref="#19"), show_runner)["parent"] == "other/repo#5",
            "show: a foreign parent keeps its owner/name")
    for bad, label in (("#2", "untrusted author"), ("#20", "no task-queue label"), ("#99", "missing issue"),
                       ("backlog.md:3", "non-issue ref")):
        try:
            github_show(dict(req, ref=bad), show_runner)
            _assert(False, f"show {label} → QueueError")
        except QueueError:
            _assert(True, f"show {label} → QueueError")

    code, data = handle("describe", dict(req), {ENV_VAR: "github"}, _fake_gh(pages, private=True))
    _assert(code == 0 and data == {"backend": "github", "contract": 1, "visibility": "private",
                                   "ops": list(GITHUB_OPS), "close_ref_template": "Closes {ref}"},
            "describe: private repo, every op, closing template")
    code, data = handle("describe", dict(req), {}, _fake_gh(pages))
    _assert(code == 0 and data["visibility"] == "public", "resolver picks github for a github.com origin without backlog items")
    git(repo, "worktree", "remove", wt)
    _assert(any(c["ref"] == "#15" for c in github_list(dict(req, full_scan=True), runner)["candidates"]),
            "an archive without a registered worktree does not claim an issue")
    git(repo, "worktree", "add", "-q", wt, "cov")
    _assert(any(c["ref"] == "#15" for c in github_list(dict(req, full_scan=True), runner)["candidates"]),
            "recreating the worktree on the same branch does not revive the old registration")
    git(repo, "worktree", "remove", wt)


class _FakeGitHub:
    """A stateful stand-in for `gh` covering the write path: issues, labels, relations, comments.

    `fail_after` = number of runner calls that succeed before every later call fails like an
    unreachable gh; `lose_create` = how many issue creations succeed at GitHub but report failure."""

    def __init__(self, labels=(QUEUE_LABEL,), private: bool = False):
        self.labels = set(labels)
        self.issues: dict[int, dict] = {}
        self.calls: list[list[str]] = []
        self.fail_after: int | None = None
        self.lose_create = 0
        self.reject_relation: set[tuple[str, int]] = set()  # (kind, child number) answered with a GraphQL error
        self.visibility = "PRIVATE" if private else "PUBLIC"
        self.page_size = 100

    def add(self, title: str, body: str = "", labels=(QUEUE_LABEL,), assoc: str = "OWNER", state: str = "OPEN",
            reason: str | None = None, comments=()) -> int:
        n = len(self.issues) + 1
        self.issues[n] = {"number": n, "id": f"I_{n}", "title": title, "body": body, "labels": set(labels),
                          "assoc": assoc, "state": state, "stateReason": reason, "parent": None,
                          "blockedBy": [], "comments": list(comments)}
        return n

    def writes(self) -> list[list[str]]:
        return [c for c in self.calls if ("--method" in c and c[c.index("--method") + 1] != "GET")
                or any(a.startswith("query=mutation") for a in c)]

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(args)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            return 1, "", "error connecting to api.github.com"
        fields: dict = {}
        for i, a in enumerate(args):
            if a in ("-f", "-F"):
                k, v = args[i + 1].split("=", 1)
                if k.endswith("[]"):
                    fields.setdefault(k[:-2], []).append(v)
                else:
                    fields[k] = int(v) if a == "-F" else v
        if args[:2] == ["api", "graphql"]:
            return self._graphql(fields.pop("query"), fields)
        method, path = args[args.index("--method") + 1], args[args.index("--method") + 2]
        return self._rest(method, path.split("/")[3:], fields)

    def _ok(self, data: dict) -> tuple[int, str, str]:
        return 0, json.dumps(data), ""

    def _node(self, n: int) -> dict:
        return {"number": n, "repository": {"nameWithOwner": "owner/repo"}}

    def _issue_page(self, nodes: list[dict], after: str | None) -> tuple[int, str, str]:
        start = int(after or 0)
        end = start + self.page_size
        return self._ok({"data": {"repository": {
            "issues": _fx_conn(nodes[start:end], str(end) if len(nodes) > end else None),
        }}})

    def _graphql(self, query: str, v: dict) -> tuple[int, str, str]:
        if query == DESCRIBE_QUERY:
            return self._ok({"data": {"repository": {"visibility": self.visibility}}})
        if query == KEYS_QUERY:
            nodes = [{"id": i["id"], "number": n, "url": f"https://github.com/owner/repo/issues/{n}",
                      "title": i["title"], "body": i["body"], "authorAssociation": i["assoc"],
                      "state": i["state"], "stateReason": i["stateReason"]}
                     for n, i in sorted(self.issues.items())]
            return self._issue_page(nodes, v.get("after"))
        if query == NODE_QUERY:
            i = self.issues.get(v["number"]) if v["owner"] == "owner" else None
            node = i and {"id": i["id"], "number": i["number"], "body": i["body"], "authorAssociation": i["assoc"],
                          "labels": _fx_conn([{"name": x} for x in sorted(i["labels"])])}
            return self._ok({"data": {"repository": {"issue": node}}})
        if query == REJECTED_QUERY:
            nodes = [{"id": i["id"], "number": n, "title": i["title"], "url": f"https://github.com/owner/repo/issues/{n}",
                      "stateReason": i["stateReason"], "authorAssociation": i["assoc"]}
                     for n, i in sorted(self.issues.items()) if i["state"] == "CLOSED" and QUEUE_LABEL in i["labels"]]
            return self._issue_page(nodes, v.get("after"))
        by_id = {i["id"]: i for i in self.issues.values()}
        if query == KEY_RELATIONS_QUERY:
            nodes = [{"id": i["id"], "labels": _fx_conn([{"name": x} for x in sorted(i["labels"])]),
                      "parent": self._node(i["parent"]) if i["parent"] else None,
                      "blockedBy": {"nodes": [self._node(b) for b in i["blockedBy"]]}}
                     for i in (by_id[issue_id] for issue_id in v["ids"])]
            return self._ok({"data": {"nodes": nodes}})
        if query == REJECTION_COMMENTS_QUERY:
            nodes = [{"id": issue_id, "comments": {"nodes": by_id[issue_id]["comments"]}} for issue_id in v["ids"]]
            return self._ok({"data": {"nodes": nodes}})
        if query == ADD_SUB_ISSUE:
            child = by_id[v["child"]]
            if ("parent", child["number"]) in self.reject_relation or child["parent"]:
                return self._ok({"data": None, "errors": [{"message": "sub-issue already has a parent"}]})
            child["parent"] = by_id[v["parent"]]["number"]
            return self._ok({"data": {"addSubIssue": {"issue": {"number": by_id[v["parent"]]["number"]}}}})
        if query == ADD_BLOCKED_BY:
            issue = by_id[v["issue"]]
            if ("blocked_by", issue["number"]) in self.reject_relation:
                return self._ok({"data": None, "errors": [{"message": "dependency limit reached"}]})
            issue["blockedBy"].append(by_id[v["blocker"]]["number"])
            return self._ok({"data": {"addBlockedBy": {"issue": {"number": issue["number"]}}}})
        raise AssertionError(f"unexpected query {query[:60]}")

    def _rest(self, method: str, parts: list[str], f: dict) -> tuple[int, str, str]:
        from urllib.parse import unquote
        if parts[0] == "labels":
            if method == "GET":
                return (0, "{}", "") if unquote(parts[1]) in self.labels else (1, "", "gh: Not Found (HTTP 404)")
            self.labels.add(f["name"])
            return self._ok({"name": f["name"]})
        if parts == ["issues"] and method == "POST":
            missing = set(f.get("labels", [])) - self.labels
            if missing or len(f["title"]) > 256:
                return 1, "", f"gh: Validation Failed (HTTP 422) labels {missing}"
            n = self.add(f["title"], f["body"], f.get("labels", []))
            if self.lose_create:
                self.lose_create -= 1
                return 1, "", "net/http: timeout awaiting response headers"
            return self._ok({"number": n, "node_id": f"I_{n}", "html_url": f"https://github.com/owner/repo/issues/{n}"})
        issue = self.issues[int(parts[1])]
        if parts[2:] == ["comments"]:
            issue["comments"].append({"body": f["body"], "authorAssociation": "OWNER"})
        elif parts[2:] == ["labels"]:
            issue["labels"].update(f["labels"])
        elif method == "PATCH":
            if "body" in f:
                issue["body"] = f["body"]
            if f.get("state") == "closed":
                issue["state"], issue["stateReason"] = "CLOSED", f["state_reason"].upper()
        return self._ok({"number": issue["number"]})


def _test_concurrent_writers(repo: str, linked: str) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    for op, kind in (("create", "code-scanning"), ("publish", "dependabot")):
        gh = _FakeGitHub(private=True)
        item = {"key": f"gh-alert/{kind}/17", "title": "Remediate fixture alert", "labels": ["security"]}
        req = {"contract": 1, "repo": repo, "items": [item]}
        other_req = dict(req, repo=linked)
        if op == "publish":
            github_create(dict(req, queue_limits=NO_QUEUE_WRITE), gh)
        first_lookup = Event()
        second_started = Event()
        second_done = Event()

        def first_runner(args):
            result = gh(args)
            if f"query={KEYS_QUERY}" in args:
                first_lookup.set()
                if not second_started.wait(5):
                    raise AssertionError("competing writer did not start")
                second_done.wait(0.5)
            return result

        def second_writer():
            second_started.set()
            try:
                return (github_create if op == "create" else github_publish)(other_req, gh)
            finally:
                second_done.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(github_create, req, first_runner)
            if not first_lookup.wait(5):
                raise AssertionError("first writer did not reach the queue lookup")
            second = pool.submit(second_writer)
            first_result, second_result = first.result(timeout=5), second.result(timeout=5)
        _assert(len(gh.issues) == 1 and first_result["created"] and not second_result["pending"]
                and all(issue["reused"] for issue in second_result["created"]),
                f"a concurrent create and {op} from different worktrees file the same alert once")


def run_github_write_tests(tmp: str, git) -> None:
    print("\nTest 10: github create — batch dependencies, labels, retry safety, pending store")
    repo = os.path.realpath(os.path.join(tmp, "ghw"))
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", "base")
    git(repo, "remote", "add", "origin", "git@github.com:owner/repo.git")
    common = subprocess.run(["git", "-C", repo, "rev-parse", "--git-common-dir"], capture_output=True,
                            text=True).stdout.strip()
    store = os.path.join(os.path.normpath(os.path.join(repo, common)), "agent-queue", "pending.json")
    req = {"contract": 1, "repo": repo}
    linked = os.path.join(tmp, "ghw-linked")
    git(repo, "worktree", "add", "-q", "--detach", linked, "HEAD")
    _test_concurrent_writers(repo, linked)

    def status() -> str:
        return subprocess.run(["git", "-C", repo, "status", "--porcelain", "--ignored"], capture_output=True,
                              text=True).stdout

    alerts = [
        {"key": f"gh-alert/{kind}/7", "title": f"Review {kind} alert #7", "labels": ["security"]}
        for kind in ("dependabot", "code-scanning", "secret-scanning")
    ]
    alert_req = dict(req, items=alerts)
    gh = _FakeGitHub()
    _, desc = handle("describe", req, {ENV_VAR: "github"}, gh)
    _assert(desc["visibility"] == "public", "a public scan is report-only")
    try:
        handle("create", alert_req, {ENV_VAR: "github"}, gh)
    except QueueError as e:
        _assert("confirmed private" in str(e) and not gh.writes() and not os.path.exists(store) and status() == "",
                "even a direct create cannot write security alerts to a public repository")
    else:
        raise AssertionError("a public GitHub security alert create was accepted")

    gh.visibility = "INTERNAL"
    _, desc = handle("describe", req, {ENV_VAR: "github"}, gh)
    _assert(desc["visibility"] == "unknown", "internal is not confirmed private under the queue contract")
    try:
        handle("create", alert_req, {ENV_VAR: "github"}, gh)
    except QueueError as e:
        _assert("confirmed private" in str(e) and not gh.writes() and not os.path.exists(store),
                "an internal repository cannot receive security alert issues")
    else:
        raise AssertionError("an internal GitHub security alert create was accepted")

    gh.visibility = "PUBLIC"
    ordinary = {"key": "ordinary", "title": "Publish this ordinary draft"}
    _, out = handle("create", dict(req, items=[alerts[0], ordinary]), {ENV_VAR: "github"}, gh)
    _assert([i["key"] for i in out["created"]] == ["ordinary"]
            and out["incomplete"][0]["relation"] == "visibility" and not os.path.exists(store),
            "a mixed create files ordinary items without posting or storing the public alert")
    dependent = {"key": "dependent", "title": "Follow up", "blocked_by": [alerts[0]["key"]]}
    independent = {"key": "independent", "title": "Independent follow-up"}
    _, out = handle("create", dict(req, items=[alerts[0], dependent, independent]), {ENV_VAR: "github"}, gh)
    _assert([i["key"] for i in out["created"]] == ["independent"] and out["pending"] == ["dependent"]
            and {entry["relation"] for entry in out["incomplete"]} == {"visibility", "target"},
            "a withheld alert only defers its dependent item, not independent queue items")
    write_pending(repo, [])

    gh = _FakeGitHub(private=True)

    def visibility_unavailable(args):
        if f"query={DESCRIBE_QUERY}" in args:
            return 1, "", "temporarily unable to read repository visibility"
        return gh(args)

    _, out = handle("create", dict(req, items=[alerts[0], ordinary]), {ENV_VAR: "github"}, visibility_unavailable)
    _assert(not gh.calls and set(out["pending"]) == {alerts[0]["key"], ordinary["key"]}
            and "temporarily unable" in out["error"],
            "a failed visibility request leaves both alert and ordinary drafts recoverable")
    _, out = handle("publish", req, {ENV_VAR: "github"}, gh)
    _assert({i["key"] for i in out["created"]} == {alerts[0]["key"], ordinary["key"]} and not os.path.exists(store),
            "publish can send drafts stored after a visibility lookup failed")

    gh = _FakeGitHub(private=True)
    gh.add("An already filed alert", "<!-- gh-alert: code-scanning/7 -->\nReference above.\n"
           "<!-- gh-alert: dependabot/7 -->", labels=["security"], state="CLOSED")
    _, out = handle("create", alert_req, {ENV_VAR: "github"}, gh)
    _assert([i["reused"] for i in out["created"]] == [True, False, False]
            and gh.issues[1]["labels"] == {"security"} and len(gh.issues) == 3,
            "private filing reuses a closed issue by its final marker and ignores an earlier quoted marker")
    _assert(all(gh.issues[n]["labels"] == {QUEUE_LABEL, "security"}
                and gh.issues[n]["body"].endswith(f"<!-- gh-alert: {kind}/7 -->")
                for n, kind in ((2, "code-scanning"), (3, "secret-scanning"))),
            "new issues carry the security label and the kind/number marker")
    gh.calls.clear()
    _, out = handle("create", alert_req, {ENV_VAR: "github"}, gh)
    _assert(all(i["reused"] for i in out["created"]) and len(out["created"]) == 3
            and not gh.writes() and not os.path.exists(store),
            "a private rescan reuses every marker without updating issues or creating labels")
    _, out = handle("create", dict(req, items=[alerts[0], dependent]), {ENV_VAR: "github"}, gh)
    _assert(not out["incomplete"] and gh.issues[4]["blockedBy"] == [1],
            "an ordinary issue can reference a reused alert in the same batch")

    gh = _FakeGitHub(private=True)
    handle("create", dict(req, queue_limits=NO_QUEUE_WRITE, items=[alerts[0], ordinary]),
           {ENV_VAR: "github"}, gh)
    _assert(not gh.calls and set(i["key"] for i in read_pending(repo)) == {alerts[0]["key"], ordinary["key"]},
            "create under no-queue-write stores drafts without any GitHub calls")
    gh.calls.clear()
    _, out = handle("publish", dict(req, queue_limits=NO_QUEUE_WRITE), {ENV_VAR: "github"}, gh)
    _assert(not gh.calls and set(out["pending"]) == {alerts[0]["key"], ordinary["key"]},
            "publish under no-queue-write performs no visibility lookup or writes")
    gh.visibility = "PUBLIC"
    _, out = handle("publish", req, {ENV_VAR: "github"}, gh)
    _assert([i["key"] for i in out["created"]] == ["ordinary"]
            and not out["pending"] and out["incomplete"][0]["relation"] == "visibility"
            and not os.path.exists(store),
            "publish files ordinary drafts and clears alert drafts when the repository becomes public")

    gh = _FakeGitHub()
    existing = gh.add("[FEAT] earlier ticket", "<!-- queue-key: old -->")
    items = [
        {"key": "t1", "title": "[FEAT] schema", "body": "Source: docs/design/x.md", "labels": []},
        {"key": "t2", "title": "[FEAT] reader", "body": "", "labels": ["someday"], "blocked_by": ["t1"]},
        {"key": "t3", "title": "[FIX] both", "blocked_by": ["t1", "t2", f"#{existing}", "old"]},
    ]
    code, out = handle("create", dict(req, items=items), {ENV_VAR: "github"}, gh)
    refs = {c["key"]: c["ref"] for c in out["created"]}
    _assert(code == 0 and refs == {"t1": "#2", "t2": "#3", "t3": "#4"}
            and not any(c["reused"] for c in out["created"]), f"create files one issue per item in order ({refs})")
    _assert(gh.issues[3]["blockedBy"] == [2], "a batch-key dependency becomes addBlockedBy on the new issue")
    _assert(sorted(gh.issues[4]["blockedBy"]) == [1, 2, 3],
            "batch keys, an existing ref and a known queue-key resolve; a blocker named twice is added once")
    _assert(gh.issues[2]["body"].endswith("<!-- queue-key: t1 -->") and gh.issues[2]["body"].startswith("Source:"),
            "the queue-key marker is appended to the body")
    _assert(gh.issues[3]["labels"] == {QUEUE_LABEL, "someday"} and "someday" in gh.labels,
            "label bootstrap: a missing label is created before filing")
    _assert(not any(c[:4] == ["api", "--method", "POST", "repos/owner/repo/labels"]
                    and "name=task-queue" in c for c in gh.calls), "an existing label is never re-created")
    _assert(out["incomplete"] == [] and out["pending"] == [] and not os.path.exists(store),
            "a clean create writes no pending store")
    _assert(status() == "", "a github create leaves no working-tree change")

    for concurrent in (True, False):
        label = "race" if concurrent else "invalid"
        label_runner = _FakeGitHub()
        label_runner.labels.add(QUEUE_LABEL)
        draft = {"key": label, "title": f"Test {label} label", "labels": [label]}

        def label_post(args):
            if args[:4] == ["api", "--method", "POST", "repos/owner/repo/labels"]:
                if concurrent:
                    label_runner.labels.add(label)
                return 1, "", "gh: Validation Failed (HTTP 422)"
            return label_runner(args)

        try:
            result = github_create(dict(req, items=[draft]), label_post)
        except GhRejected as exc:
            _assert(not concurrent and "HTTP 422" in str(exc) and not label_runner.issues,
                    f"label creation rejection is propagated only if the label is absent ({label})")
        else:
            _assert(concurrent and len(result["created"]) == 1 and not result["pending"],
                    f"a label created by another writer between GET and POST lets filing continue ({label})")

    n_before = len(gh.issues)
    code, out = handle("create", dict(req, items=items), {ENV_VAR: "github"}, gh)
    _assert(len(gh.issues) == n_before and all(c["reused"] for c in out["created"])
            and not gh.issues[4]["blockedBy"].count(1) > 1, "a re-sent create reuses every issue by queue-key")

    print("\nTest 11: github create — lost response, missing relations, failure path, publish")
    gh = _FakeGitHub()
    gh.lose_create = 1
    pair = [{"key": "p", "title": "Parent"}, {"key": "c", "title": "[FIX] child", "parent_key": "p"}]
    code, out = handle("create", dict(req, items=pair), {ENV_VAR: "github"}, gh)
    _assert(code == 0 and out["pending"] == ["p", "c"] and "timeout" in out.get("error", "")
            and out["pending_path"] == store and os.path.exists(store),
            "gh failing mid-write → exit 0, unfiled drafts kept in the git-common-dir pending store")
    _assert(status() == "", "the pending store is outside the working tree")
    _assert(len(gh.issues) == 1, "the lost-response issue exists at GitHub")
    code, out = handle("publish", dict(req), {ENV_VAR: "github"}, gh)
    _assert(code == 0 and [c["reused"] for c in out["created"]] == [True, False] and len(gh.issues) == 2,
            "publish reuses the lost-response issue by queue-key instead of duplicating it")
    _assert(gh.issues[2]["parent"] == 1 and out["pending"] == [] and not os.path.exists(store),
            "publish completes the parent relation and empties the store")

    gh = _FakeGitHub()
    first = {"key": "review:17:first", "title": "[DEBT] First review finding"}
    _, out = handle("create", dict(req, items=[first]), {ENV_VAR: "github"}, gh)
    _assert(out["created"][0]["ref"] == "#1" and gh.issues[1]["parent"] is None,
            "a single review finding starts as a standalone issue")
    group = [
        {"key": "review:17:group", "title": "Review follow-ups — PR #17"},
        dict(first, parent_key="review:17:group"),
        {"key": "review:17:late", "title": "[DEBT] Late finding", "parent_key": "review:17:group"},
    ]
    _, out = handle("create", dict(req, items=group), {ENV_VAR: "github"}, gh)
    _assert(gh.issues[1]["parent"] == gh.issues[3]["parent"] == 2 and len(gh.issues) == 3
            and out["created"][1]["reused"] and not os.path.exists(store),
            "a late finding groups the earlier issue without duplication")

    gh = _FakeGitHub()
    sweep = {"key": "sweep:fixture", "title": "[HARNESS] Fixture", "refile_completed": True}
    gh.add(sweep["title"], "<!-- queue-key: sweep:fixture -->", state="CLOSED", reason="COMPLETED")
    gh.lose_create = 1
    _, out = handle("create", dict(req, items=[sweep]), {ENV_VAR: "github"}, gh)
    _assert(out["pending"] == [sweep["key"]] and len(gh.issues) == 2,
            "a recurring finding creates a new issue when its previous issue was completed")
    _, out = handle("publish", req, {ENV_VAR: "github"}, gh)
    _assert(out["created"][0]["reused"] and out["created"][0]["ref"] == "#2" and not os.path.exists(store),
            "publish reuses a recurring finding whose first response was lost")
    gh.issues[2].update(state="CLOSED", stateReason="NOT_PLANNED")
    _, out = handle("create", dict(req, items=[sweep]), {ENV_VAR: "github"}, gh)
    _assert(not out["created"] and not out["pending"] and out["incomplete"][0]["relation"] == "rejected",
            "a recurring finding closed without completion stays closed")

    gh = _FakeGitHub()
    migrated = dict(sweep, key=MIGRATION_KEY_PREFIX + "completed", title="Revised title", body="New details")
    gh.add("Original title", _issue_body("Old details", _KEY_MARKER.format(migrated["key"])),
           state="CLOSED", reason="COMPLETED")
    _, out = handle("create", dict(req, items=[migrated]), {ENV_VAR: "github"}, gh)
    _assert(not out["incomplete"] and [c["ref"] for c in out["created"]] == ["#2"],
            "refiling an edited draft compares against the selected migrated recurrence")
    _, out = handle("create", dict(req, items=[migrated]), {ENV_VAR: "github"}, gh)
    _assert(not out["incomplete"] and len(out["created"]) == 1 and out["created"][0]["reused"],
            "a retry checks the existing recurrence body against its own marker")
    write_pending(repo, [])

    gh = _FakeGitHub()
    gh.add(sweep["title"], _KEY_MARKER.format(sweep["key"]), state="CLOSED", reason="COMPLETED")
    recurrence = {"key": f"{sweep['key']}:after:1", "title": "Explicit recurrence"}
    _, out = handle("create", dict(req, items=[sweep, recurrence]), {ENV_VAR: "github"}, gh)
    _assert(len(gh.issues) == 2 and [issue["ref"] for issue in out["created"]] == ["#2", "#2"]
            and out["created"][1]["reused"], "a later item reuses a recurrence created earlier in the same batch")

    gh = _FakeGitHub()
    gh.reject_relation.add(("blocked_by", 2))
    code, out = handle("create", dict(req, items=[{"key": "a", "title": "A"},
                                                  {"key": "b", "title": "B", "blocked_by": ["a"]}]),
                       {ENV_VAR: "github"}, gh)
    _assert(out["incomplete"] == [{"key": "b", "relation": "blocked_by", "ref": "#1", "error": "dependency limit reached"}]
            and out["pending"] == ["b"], "a failed relation → incomplete[] and that item stays pending")
    _assert(QUEUE_LABEL in gh.issues[1]["labels"] and QUEUE_LABEL not in gh.issues[2]["labels"],
            "an issue whose relation failed carries no task-queue label, so selection never offers it half-linked")
    gh.reject_relation.clear()
    code, out = handle("publish", dict(req), {ENV_VAR: "github"}, gh)
    _assert(gh.issues[2]["blockedBy"] == [1] and out["created"][0]["reused"] and out["pending"] == []
            and len(gh.issues) == 2, "publish completes the missing relation on the reused issue")
    _assert(QUEUE_LABEL in gh.issues[2]["labels"], "the task-queue label lands once every relation is filed")

    gh = _FakeGitHub()
    code, out = handle("create", dict(req, items=[{"key": "long", "title": "x" * 300},
                                                  {"key": "ok", "title": "fine"}]), {ENV_VAR: "github"}, gh)
    _assert(out["incomplete"][0]["key"] == "long" and out["incomplete"][0]["relation"] == "create"
            and out["pending"] == [] and not os.path.exists(store) and [c["key"] for c in out["created"]] == ["ok"],
            "an HTTP 422 refusal is reported, never stored for an endless retry, and the rest still files")

    def no_gh(args):
        raise GhUnavailable("the github queue backend needs the GitHub CLI: install `gh`")
    code, out = handle("create", dict(req, items=pair), {ENV_VAR: "github"}, no_gh)
    _assert(out["pending"] == ["p", "c"] and "GitHub CLI" in out["error"] and os.path.exists(store),
            "gh not installed → drafts stored, not dropped")
    git(repo, "remote", "set-url", "origin", "git@github.com:someone/fork.git")
    gh = _FakeGitHub()
    code, out = handle("publish", dict(req), {ENV_VAR: "github"}, gh)
    _assert(gh.calls == [] and out["pending"] == ["p", "c"] and out["incomplete"][0]["relation"] == "target",
            "a draft stored for another origin is never posted to the current one")
    git(repo, "remote", "set-url", "origin", "git@github.com:owner/repo.git")
    handle("create", dict(req, queue_limits=NO_QUEUE_WRITE,
                          items=[{"key": "bad", "title": "B", "blocked_by": ["typo"]}]), {ENV_VAR: "github"}, gh)
    code, out = handle("publish", dict(req), {ENV_VAR: "github"}, gh)
    _assert(code == 0 and {c["key"] for c in out["created"]} == {"p", "c"} and out["pending"] == ["bad"]
            and out["incomplete"] == [{"key": "bad", "relation": "target", "ref": "typo",
                                       "error": "not a batch key, a known queue-key or an issue ref"}],
            "one stored draft with an unknown target does not block the rest of the store")
    write_pending(repo, [])
    draft = {"key": "shared", "title": "First origin draft"}
    handle("create", dict(req, queue_limits=NO_QUEUE_WRITE, items=[draft]), {ENV_VAR: "github"}, gh)
    git(repo, "remote", "set-url", "origin", "git@github.com:someone/fork.git")
    fork_draft = dict(draft, title="Second origin draft")
    handle("create", dict(req, queue_limits=NO_QUEUE_WRITE, items=[fork_draft]), {ENV_VAR: "github"}, gh)
    _assert({(i["target"], i["title"]) for i in read_pending(repo)}
            == {("owner/repo", draft["title"]), ("someone/fork", fork_draft["title"])},
            "pending drafts with the same key coexist across origins")
    gh = _FakeGitHub()
    handle("create", dict(req, items=[fork_draft]), {ENV_VAR: "github"}, gh)
    remaining = read_pending(repo)
    _assert([(i["target"], i["title"]) for i in remaining] == [("owner/repo", draft["title"])],
            "a direct create only retires its own origin's draft")
    git(repo, "remote", "set-url", "origin", "git@github.com:owner/repo.git")
    gh = _FakeGitHub()
    _, out = handle("publish", req, {ENV_VAR: "github"}, gh)
    _assert(gh.issues.get(1, {}).get("title") == draft["title"] and not out["pending"],
            "switching back restores access to the original draft")

    gh = _FakeGitHub()
    gh.add("[DOCS] marker docs", "Write `<!-- queue-key: quoted -->` like this:\n<!-- queue-key: quoted -->\n"
           "trailing prose\r\n<!-- queue-key: real -->")
    marker_items = _validate_items([{"key": key, "title": key} for key in ("quoted", "real")])
    _assert(set(key_index(gh, "owner", "repo", marker_items)) == {"real"},
            "key_index takes the last own-line marker, never a quoted one earlier in the body")
    gh = _FakeGitHub()
    gh.page_size = 1
    for n in range(100):
        gh.add(f"Unrelated {n}", _KEY_MARKER.format(f"other:{n}"))
    blocker = gh.add("Existing blocker", _KEY_MARKER.format("late-blocker"))
    late_draft = {"key": "late-draft", "title": "Late draft", "blocked_by": ["late-blocker"]}
    gh.lose_create = 1
    _, out = handle("create", dict(req, items=[late_draft]), {ENV_VAR: "github"}, gh)
    _assert(out["pending"] == ["late-draft"] and len(gh.issues) == blocker + 1,
            "an absent key beyond 100 pages can be filed even when the response is lost")
    gh.add("Unread tail", _KEY_MARKER.format("tail"))
    gh.calls.clear()
    _, out = handle("publish", req, {ENV_VAR: "github"}, gh)
    _assert(not out["pending"] and len(out["created"]) == 1 and out["created"][0]["reused"]
            and gh.issues[blocker + 1]["blockedBy"] == [blocker],
            "publish reuses the late issue and completes its relation to a key outside the batch")
    _assert(not any(f"after={blocker + 1}" in call for call in gh.calls)
            and [arg for call in gh.calls if f"query={KEY_RELATIONS_QUERY}" in call
                 for arg in call if arg.startswith("ids[]=")] == [f"ids[]=I_{blocker + 1}"],
            "lookup stops after the last needed key and reads relations only for the reused issue")
    code, out = handle("create", dict(req, items=pair, queue_limits=NO_QUEUE_WRITE), {ENV_VAR: "github"}, gh)
    code, out = handle("create", dict(req, items=pair), {ENV_VAR: "github"}, gh)
    _assert(out["pending"] == [] and not os.path.exists(store),
            "a direct create that files a stored key retires its stale pending draft")
    from concurrent.futures import ThreadPoolExecutor

    drafts = [{"key": f"k{n}", "title": "T"} for n in range(8)]
    requests = [dict(req, items=[d], queue_limits=NO_QUEUE_WRITE) for d in drafts]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda request: github_create(request, gh), requests))
    _assert(sorted(i["key"] for i in read_pending(repo)) == [d["key"] for d in drafts],
            "concurrent pending writes keep every draft (queue writer lock)")
    write_pending(repo, [])

    from threading import Event
    from unittest.mock import patch

    held = Event()
    release = Event()

    def hold_writer():
        with _queue_write_lock(repo):
            held.set()
            release.wait(2)

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(hold_writer)
        _assert(held.wait(2), "the other writer holds the lock before publish")
        with patch(f"{__name__}.QUEUE_LOCK_TIMEOUT", 0.05, create=True):
            try:
                github_publish(req, gh)
            except QueueError as exc:
                _assert("timed out" in str(exc) and "retry" in str(exc), "writer lock timeout is retryable")
            else:
                _assert(False, "publish times out before the other writer releases its lock")
            finally:
                release.set()
        holder.result()
    _assert(not github_publish(req, gh)["pending"], "publish can retry after the writer releases the lock")

    gh = _FakeGitHub()
    code, out = handle("create", dict(req, items=pair, queue_limits=NO_QUEUE_WRITE), {ENV_VAR: "github"}, gh)
    _assert(code == 0 and out["pending"] == ["p", "c"] and gh.calls == [] and os.path.exists(store),
            "no-queue-write → drafts go pending and gh is never called")
    code, out = handle("publish", dict(req, queue_limits=NO_QUEUE_WRITE), {ENV_VAR: "github"}, gh)
    _assert(gh.calls == [] and out["pending"] == ["p", "c"], "publish under no-queue-write posts nothing")
    code, out = handle("publish", dict(req), {ENV_VAR: "github"}, gh)
    _assert(out["pending"] == [] and len(gh.issues) == 2 and not os.path.exists(store), "a later publish files them")

    secret = {"key": "security-fixture", "title": "Security fixture", "labels": ["Security"]}
    gh = _FakeGitHub()
    for limits in ("none", NO_QUEUE_WRITE):
        _, out = handle("create", dict(req, items=[secret], queue_limits=limits), {ENV_VAR: "github"}, gh)
        _assert(out["withheld_security"] == 1 and not gh.writes() and not os.path.exists(store),
                f"a public security draft never posts or goes pending ({limits})")
    gh.visibility = "PRIVATE"
    _, out = handle("create", dict(req, items=[secret], queue_limits=NO_QUEUE_WRITE), {ENV_VAR: "github"}, gh)
    _assert(out["pending"] == [secret["key"]] and not gh.writes() and os.path.exists(store),
            "a verified private security draft can wait without making a remote write")
    gh.fail_after = len(gh.calls)
    _, out = handle("publish", req, {ENV_VAR: "github"}, gh)
    _assert(out["withheld_security"] == 1 and not out["pending"] and os.path.exists(store),
            "publish with unavailable visibility keeps a previously private draft without reporting its key")
    gh.fail_after = None
    gh.visibility = "PUBLIC"
    _, out = handle("publish", req, {ENV_VAR: "github"}, gh)
    _assert(out["withheld_security"] == 1 and not gh.writes() and not os.path.exists(store),
            "publish suppresses and clears a private draft if the repository has become public")

    gh = _FakeGitHub()
    gh.fail_after = 0
    code, out = handle("create", dict(req, items=pair[:1]), {ENV_VAR: "github"}, gh)
    _assert(out["pending"] == ["p"] and out["created"] == [], "gh unreachable before any write → all drafts pending")
    write_pending(repo, [])
    for bad, label in (([{"key": "x", "title": "X", "blocked_by": ["nope"]}], "unknown key"),
                       ([{"key": "x", "title": "X"}, {"key": "x", "title": "Y"}], "duplicate key"),
                       ([{"key": "x -->", "title": "X"}], "marker-breaking key"),
                       ([{"key": "x", "title": "X", "blocked_by": ["x"]}], "self-blocking item"),
                       ([{"key": "x", "title": "X", "body": ["b"]}], "non-string body")):
        try:
            handle("create", dict(req, items=bad), {ENV_VAR: "github"}, _FakeGitHub())
            _assert(False, f"create with {label} → QueueError")
        except QueueError:
            _assert(not os.path.exists(store), f"create with {label} → QueueError, nothing stored")

    print("\nTest 12: github rejected, reject, defer")
    gh = _FakeGitHub(labels=(QUEUE_LABEL,))
    gh.page_size = 1
    keep = gh.add("[FEAT] keep")
    gh.add("[FEAT] done", state="CLOSED", reason="COMPLETED")
    gh.add("[FEAT] stranger's", assoc="NONE", state="CLOSED", reason="NOT_PLANNED")
    for _ in range(100):
        gh.add("Completed", state="CLOSED", reason="COMPLETED")
    last = gh.add("Late rejection", state="CLOSED", reason="NOT_PLANNED")
    code, out = handle("reject", dict(req, ref=f"#{keep}", reason="no failure seen",
                                      refile_bar="a recorded crash"), {ENV_VAR: "github"}, gh)
    _assert(code == 0 and out == {"ref": "#1"} and gh.issues[1]["stateReason"] == "NOT_PLANNED",
            "reject comments and closes as not planned")
    code, out = handle("rejected", dict(req), {ENV_VAR: "github"}, gh)
    _assert(out == {"entries": [
        {"ref": "#1", "title": "[FEAT] keep", "reason": "no failure seen",
         "refile_bar": "a recorded crash", "url": "https://github.com/owner/repo/issues/1"},
        {"ref": f"#{last}", "title": "Late rejection", "reason": "", "refile_bar": "",
         "url": f"https://github.com/owner/repo/issues/{last}"},
    ]}, "rejected reads past 100 pages and returns only trusted closed-not-planned issues")
    comment_requests = [[arg for arg in call if arg.startswith("ids[]=")]
                        for call in gh.calls if f"query={REJECTION_COMMENTS_QUERY}" in call]
    _assert(comment_requests == [["ids[]=I_1", f"ids[]=I_{last}"]],
            "rejected batches comments across pages only for trusted issues with matching state reason")
    target = gh.add("[FIX] later", "Context.\nDeferred: old reason\n")
    code, out = handle("defer", dict(req, ref=f"#{target}", reason="waits on vendor"), {ENV_VAR: "github"}, gh)
    _assert(code == 0 and "deferred" in gh.issues[target]["labels"] and "deferred" in gh.labels
            and gh.issues[target]["body"].count("Deferred:") == 1
            and gh.issues[target]["body"].rstrip().endswith("Deferred: waits on vendor"),
            "defer bootstraps the label, labels the issue and replaces the Deferred: line")
    stranger = gh.add("[FEAT] stranger", assoc="NONE")
    try:
        handle("defer", dict(req, ref=f"#{stranger}", reason="r"), {ENV_VAR: "github"}, gh)
        _assert(False, "defer on an untrusted issue → QueueError")
    except QueueError:
        _assert(not gh.issues[stranger]["labels"] - {QUEUE_LABEL}, "defer on an untrusted issue → QueueError")
    _assert(status() == "", "no write op leaves a working-tree change")


ADAPTER_SOURCE = """import json, sys
op = sys.argv[-1]
req = json.load(sys.stdin)
assert req["contract"] == 1
if op == "describe":
    print(json.dumps({"backend": "fixture-adapter", "contract": 1, "visibility": "private",
                      "ops": ["describe", "list"], "close_ref_template": "Closes {ref}"}))
elif op == "list":
    print(json.dumps({"candidates": [{"id": "1", "ref": "#1", "title": "t", "tag": "", "labels": [],
                      "items": [], "url": "", "counts": {"open": 1, "deferred": 0, "blocked": 0}}],
                      "parked": [], "claimed": [], "warnings": []}))
elif op == "show":
    sys.stderr.write("boom\\n")
    sys.exit(1)
else:
    sys.exit(2)
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
