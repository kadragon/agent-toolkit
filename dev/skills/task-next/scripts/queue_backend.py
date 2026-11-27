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
  2. `origin` host `github.com` → `github`, unless `backlog.md` still has an open `- [ ]` item
     (parked ones included), which keeps the repo on `backlog`.
  3. `${XDG_CONFIG_HOME:-~/.config}/agent-toolkit/queue-backends.json`
     (`{"hosts": {"<origin host>": ["cmd", "arg", ...]}}`) → that adapter command.
  4. `backlog`.

`backlog` is built in: `list` runs `backlog_candidates.py` and maps its JSON onto the contract,
`show` and `rejected` read `backlog.md` directly, and `create` answers `{"edit_file":
"backlog.md"}` so the caller keeps its hand-edit path. `github` resolves but answers exit 2 for
every op until its read path lands. An adapter command receives `<op>` as its last argument and
the request on stdin; its stdout and exit code pass through.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backlog_candidates as bc  # noqa: E402

CONTRACT = 1
OPS = ("describe", "list", "show", "create", "rejected", "reject", "defer")
BACKLOG_OPS = ("describe", "list", "show", "create", "rejected")
EXIT_OK, EXIT_ERROR, EXIT_UNSUPPORTED = 0, 1, 2
ENV_VAR = "AGENT_QUEUE_BACKEND"
_TAG_RE = re.compile(r"^\[([^\[\]\s]+)\]")
_REFILE_RE = re.compile(r"\s*re-file\s+only\s*(?:with|if|when)?\s*", re.IGNORECASE)


class QueueError(Exception):
    """An error the CLI reports on stderr with exit 1."""


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
    cmd = (data.get("hosts") or {}).get(host) if isinstance(data, dict) else None
    if cmd is None:
        return None
    if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
        raise QueueError(f"{path}: hosts[{host!r}] must be a non-empty list of strings")
    return cmd


def backlog_open_items(repo: str, rev: str | None = None) -> int:
    """Unchecked `- [ ]` items in `<repo>/backlog.md` (as committed at `rev` when given), parked
    ones included; 0 when absent."""
    if rev:
        sha = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
        if not sha:
            raise QueueError(f"ref {rev!r} does not resolve to a commit in {repo}")
        text = _git(repo, "show", f"{sha}:backlog.md") or ""
        return sum(1 for t in bc.tokenize(text) if t["type"] == "checkbox" and t["state"] == " ")
    try:
        with open(os.path.join(repo, "backlog.md"), encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return 0
    except (OSError, ValueError) as e:  # unreadable is not "empty": never flip to github on it
        raise QueueError(f"cannot read {os.path.join(repo, 'backlog.md')}: {e}") from e
    return sum(1 for t in bc.tokenize(text) if t["type"] == "checkbox" and t["state"] == " ")


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
        if backlog_open_items(repo, rev):  # the queue `list` will read, not this checkout's
            return {"backend": "backlog", "source": "github-open-backlog"}
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


def _parse_ref(ref: object) -> tuple[str, int]:
    m = re.fullmatch(r"(backlog\.md|tasks\.md):(\d+)", ref) if isinstance(ref, str) else None
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


def handle(op: str, req: object, env: dict[str, str] | None = None) -> tuple[int, dict | None]:
    if op not in OPS:
        raise QueueError(f"unknown op {op!r}; expected one of {', '.join(OPS)}")
    if not isinstance(req, dict):
        raise QueueError("request must be a JSON object")
    if req.get("contract") != CONTRACT:
        raise QueueError(f"request contract must be {CONTRACT}, got {req.get('contract')!r}")
    repo = req.get("repo")
    if not (isinstance(repo, str) and os.path.isabs(repo) and os.path.isdir(repo)):
        raise QueueError(f"request repo must be an existing absolute path, got {repo!r}")
    backend = resolve(repo, env, req.get("ref") if op == "list" else None)
    if backend["backend"] == "backlog":
        code, data = backlog_op(op, req)
        if code == EXIT_UNSUPPORTED:
            sys.stderr.write(f"queue_backend: the backlog backend does not support {op!r}\n")
        return code, data
    if backend["backend"] == "github":
        sys.stderr.write(f"queue_backend: the github backend does not implement {op!r} yet\n")
        return EXIT_UNSUPPORTED, None
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
    import tempfile

    print("=== queue_backend.py --test ===\n")
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
            write(os.path.join(empty, "backlog.md"), "# Backlog\n\n## Done\n\n- [x] closed\n")
            _assert(resolve(empty, dict(base_env)) == {"backend": "github", "source": "github-host"},
                    "github.com origin without open items → github")
            os.remove(os.path.join(empty, "backlog.md"))
            _assert(resolve(empty, dict(base_env))["backend"] == "github", "github.com origin, no backlog.md → github")
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
            code, _, err = cli("list", req, dict(base_env, **{ENV_VAR: "github"}))
            _assert(code == 2 and "github" in err, "github backend → exit 2 for list")
            code, _, _ = cli("describe", req, dict(base_env, **{ENV_VAR: "github"}))
            _assert(code == 2, "github backend → exit 2 for describe")

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
    finally:
        os.environ.clear()
        os.environ.update(saved_env)

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


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
