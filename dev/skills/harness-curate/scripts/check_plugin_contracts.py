#!/usr/bin/env python3
"""check_plugin_contracts.py — find repo-side rules that contradict a shipped `dev` plugin contract.

A repo can write its own rule over a plugin contract — a convention doc, a lint gate, a habit of
hand-editing after a bundled script runs. The plugin script then keeps doing what its contract
says, the repo rule keeps undoing it, and the agent pays the difference by hand every cycle. This
check makes the conflict visible to `harness-curate`, which proposes the repo-side fix.

Contracts checked:

  backlog-history   On the file backend, closed items leave `backlog.md`: `task_nodes.py prune-backlog` deletes them at
                    cleanup, and the closure record is the `CHANGELOG.md` entry. A repo that keeps
                    `- [x]` lines in `backlog.md`, or documents a rule to keep them, conflicts.
  legacy-backlog    GitHub repos with an old file queue or steering that still points at it.

Usage:
  python3 check_plugin_contracts.py [--project PATH | --all]
  python3 check_plugin_contracts.py --test

  --project PATH  repo root to check (default: cwd).
  --all           check the current repo and repos with local session metadata.

Scanned: `backlog.md`, `AGENTS.md`, `CLAUDE.md`, and `docs/*.md` (top level only — `docs/design/`
holds past specs, not live rules). A change-record doc (`docs/log.md`, `docs/*-log.md`,
`docs/changelog.md`, `docs/*-history.md`, `-`/`_`/`.` separators alike) is skipped too: it quotes the rule it retired, so the quote is not a rule. Fenced code blocks and HTML comments are masked, so a template
sample is not a rule. The masking is imported from `task-next/scripts/backlog_candidates.py` (same
`dev` plugin, always co-installed) so both scripts agree on what markup is.

Exit: 0 no conflict · 1 conflict reported on stdout · 2 usage error. Read-only; writes nothing.
Self-check (--test): exits 0 on PASS, 1 on FAIL. All fixtures live in a tempdir.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from session_paths import _codex_session_meta_cwd, codex_home

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "task-next" / "scripts"))
from backlog_candidates import (  # noqa: E402
    _strip_fenced_blocks,
    _strip_html_comments,
    tokenize,
    unclosed_fence_line,
)
from migrate_backlog import build_plan  # noqa: E402
from queue_backend import ENV_VAR, QueueError, _git, origin_host, resolve  # noqa: E402

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_DONE_RE = re.compile(r"^\s*[-*+]\s+\[[xX]\]\s")
# A doc line that states a keep-`[x]`-as-history rule. Both halves must sit on one line.
_KEEP_RULE_RE = re.compile(r"\[x\].*\bhistory\b|\bhistory\b.*\[x\]", re.IGNORECASE)
# A line that forbids keeping them states the plugin contract, not a conflict with it.
_NEGATION_RE = re.compile(r"\b(?:do not|don't|never|no longer|must not)\b", re.IGNORECASE)
_PRUNE_RE = re.compile(r"prune-backlog")
# A dated change record (`harness-log.md`, `changelog.md`) names a rule to say it was removed.
_RECORD_DOC_RE = re.compile(r"(?:^|[-_.])(?:log|changelog|history)\.md$", re.IGNORECASE)
_ARCHIVE_DOC_RE = re.compile(r"(?:^|[-_.])archives?\.md$|^archives?[-_.]", re.IGNORECASE)
_BACKLOG_FILE = r"(?<![\w./-])(?:`backlog\.md`|backlog\.md(?![\w/-]|\.[\w./-]))"
_CLAUSE_BREAK_RE = re.compile(r";\s*|[.!?]\s+")
_QUEUE_RULE_RE = re.compile(
    rf"(?:\b(?:queue(?: truth| source)?|source of truth|system of record|canonical queue)"
    rf"\s*(?:is\s+|(?:lives )?in\s+|[:=—-]\s*)?{_BACKLOG_FILE}"
    rf"|{_BACKLOG_FILE}\s*(?:is|as)\s+(?:the\s+)?(?:canonical\s+|work\s+|task\s+)?queue\b"
    rf"|{_BACKLOG_FILE}\s+is\s+(?:the\s+)?(?:single\s+)?source of truth\b"
    rf"|\b(?:add|file|record|track|queue|log|put|capture)\b[^.]*?"
    rf"\b(?:tasks?|items?|work|follow-ups?|bugs?|findings?|issues?)\b[^.]*?"
    rf"\b(?:in|to|under)\s+{_BACKLOG_FILE}"
    rf"|\b(?:use|update|check|read|consult)\s+{_BACKLOG_FILE}\s+(?:for|as|before)\b"
    rf"|\b(?:file|add|create|open)\s+(?:an?\s+)?{_BACKLOG_FILE}\s+(?:entry|item)\b)",
    re.IGNORECASE,
)
_ISSUES_RULE = "Use GitHub issues labeled `task-queue` as the work queue."
MAX_SHOWN = 10


def masked_lines(text: str) -> list[str]:
    """Source lines with HTML comments and fenced blocks blanked; line count preserved."""
    return _strip_fenced_blocks(_strip_html_comments(text)).splitlines()


def is_keep_rule(line: str) -> bool:
    return bool(_KEEP_RULE_RE.search(line)) and not _NEGATION_RE.search(line)


def done_items(text: str) -> list[tuple[int, str, str]]:
    """`(line number, owning heading, item line)` for every `- [x]` item outside markup."""
    heading = "(no heading)"
    found = []
    for n, line in enumerate(masked_lines(text), start=1):
        m = _HEADING_RE.match(line)
        if m:
            heading = line.strip()
        elif _DONE_RE.match(line):
            found.append((n, heading, line.strip()))
    return found


def rule_docs(root: Path) -> list[Path]:
    docs = [root / "AGENTS.md", root / "CLAUDE.md"]
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        docs.extend(p for p in sorted(docs_dir.glob("*.md")) if not _RECORD_DOC_RE.search(p.name))
    return [p for p in docs if p.is_file()]


def grep_docs(root: Path, match, *, skip_archives: bool = False) -> list[str]:
    hits = []
    for path in rule_docs(root):
        if skip_archives and _ARCHIVE_DOC_RE.search(path.name):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(masked_lines(text), start=1):
            if match(line):
                hits.append(f"{path.relative_to(root).as_posix()}:{n}: {line.strip()}")
    return hits


def check_backlog_history(root: Path, env: dict[str, str] | None = None) -> list[str]:
    """Report lines for the backlog-history contract; empty when the repo conforms."""
    if resolve(str(root.resolve()), env)["backend"] != "backlog":
        return []
    backlog = root / "backlog.md"
    items = done_items(backlog.read_text(encoding="utf-8", errors="replace")) if backlog.is_file() else []
    rules = grep_docs(root, is_keep_rule)
    if not items and not rules:
        return []
    out = [
        "CONFLICT backlog-history: the plugin deletes a closed item's `- [ ]` line (`prune-backlog`) "
        "and records the closure in the file queue's CHANGELOG.md; this repo keeps closed items as `[x]`.",
    ]
    if items:
        headings = sorted({h for _, h, _ in items})
        out.append(f"  backlog.md holds {len(items)} `[x]` item(s) under {len(headings)} heading(s):")
        out.extend(f"    backlog.md:{n}: {line}" for n, _, line in items[:MAX_SHOWN])
        if len(items) > MAX_SHOWN:
            out.append(f"    … {len(items) - MAX_SHOWN} more")
    if rules:
        out.append("  Repo rule(s) that keep `[x]` as history:")
        out.extend(f"    {hit}" for hit in rules)
    related = [h for h in grep_docs(root, _PRUNE_RE.search) if h not in rules]
    if related:
        out.append("  Repo doc lines naming `prune-backlog` (workarounds or gates to re-check):")
        out.extend(f"    {hit}" for hit in related)
    out.append(
        "  Proposed repo-side fix: rewrite each listed rule to 'closed items are deleted; the "
        "CHANGELOG.md entry is the record'; retire any gate that counts `[x]` items; delete the "
        "existing `[x]` lines once their closure is in CHANGELOG.md or git history."
    )
    return out


def is_legacy_queue_rule(line: str) -> bool:
    return any(_QUEUE_RULE_RE.search(clause) and not _NEGATION_RE.search(clause)
               for clause in _CLAUSE_BREAK_RE.split(line))


def backlog_migration_proposal(backlog: Path) -> str:
    try:
        text = backlog.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"backlog.md: fix the read error before planning migration or deletion ({exc})."

    if fence := unclosed_fence_line(text):
        return f"backlog.md:{fence}: fix the unclosed code fence before planning migration or deletion."
    states = [token["state"] for token in tokenize(text) if token["type"] == "checkbox"]
    if open_count := states.count(" "):
        return f"backlog.md: {open_count} open item(s); run the migration dry run."
    if ">" in states:
        return "backlog.md: resolve in-flight [>] items before proposing deletion."
    plan = build_plan(text, "unknown")
    if plan["issues"] or plan["refused"]:
        return "backlog.md: rejected entries remain; run the migration dry run."
    return "backlog.md: no open or in-flight items; propose deleting the file after showing its diff."


def check_legacy_backlog(root: Path, env: dict[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    if (env.get(ENV_VAR, "").strip() not in ("", "github")
            or origin_host(_git(str(root), "remote", "get-url", "origin")) != "github.com"):
        return []

    hits = []
    backlog = root / "backlog.md"
    if backlog.is_file():
        hits.append(f"  {backlog_migration_proposal(backlog)}")

    for hit in grep_docs(root, is_legacy_queue_rule, skip_archives=True):
        hits.append(f"  {hit}")
        hits.append(f"    Proposed replacement: {_ISSUES_RULE}")

    return ["CONFLICT legacy-backlog: migrate the GitHub file queue and its steering.", *hits] if hits else []


CHECKS = (check_backlog_history, check_legacy_backlog)


def run(root: Path, env: dict[str, str] | None = None) -> tuple[int, list[str]]:
    lines: list[str] = []
    failed = False
    for check in CHECKS:
        try:
            lines.extend(check(root, env))
        except (QueueError, OSError, ValueError) as exc:
            lines.append(f"Error: {exc}")
            failed = True
    return (2 if failed else int(bool(lines))), lines


def main(argv: list[str]) -> int:
    if "--test" in argv:
        return run_tests()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--project", type=Path)
    scope.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    root = args.project or Path.cwd()
    return report(project_roots(session_project_paths()) if args.all else [git_root(root) or root],
                  show_root=args.all)


def git_root(path: Path) -> Path | None:
    if path.is_dir() and (root := _git(str(path), "rev-parse", "--show-toplevel")):
        return Path(root).resolve()
    return None


def project_roots(paths) -> list[Path]:
    candidates = {Path.cwd(), *(Path(path) for path in paths if Path(path).is_absolute())}
    return sorted({root for path in candidates if (root := git_root(path)) is not None})


def session_project_paths():
    """Yield local session working directories without decoding transcript directory names."""
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    for transcript in (claude / "projects").glob("*/*.jsonl"):
        try:
            with transcript.open(encoding="utf-8", errors="replace") as stream:
                for _, line in zip(range(32), stream):
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict) and isinstance(cwd := record.get("cwd"), str) and cwd:
                        yield cwd
                        break
        except OSError:
            continue
    for transcript in (Path(codex_home()) / "sessions").rglob("*.jsonl"):
        try:
            cwd = _codex_session_meta_cwd(transcript)
        except (AttributeError, UnicodeError):
            continue
        if isinstance(cwd, str) and cwd:
            yield cwd


def report(roots: list[Path], show_root: bool = False) -> int:
    status = 0
    for root in roots:
        if show_root:
            print(f"Project: {root}")
        if not root.is_dir():
            print(f"Error: not a directory: {root}", file=sys.stderr)
            status = 2
            continue
        code, lines = run(root)
        print("\n".join(lines) if lines else "OK: no plugin-contract conflicts")
        status = max(status, code)
    if not roots:
        print("No local Git repositories found.")
    return status


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


def _repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="plugin-contracts-"))
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def run_tests() -> int:
    print("=== check_plugin_contracts.py --test ===\n")

    def check(root):
        return run(root, env={})

    code, lines = check(_repo({"backlog.md": "# Backlog\n\n## Now\n\n- [ ] open item\n"}))
    _assert(code == 0 and not lines, "open items only, no rule → no conflict")

    code, _ = check(_repo({}))
    _assert(code == 0, "no backlog.md, no docs → no conflict")

    code, lines = check(_repo({
        "backlog.md": "## Review Backlog\n\n### PR #100 — x\n\n- [x] done — verdict\n- [ ] open\n",
    }))
    text = "\n".join(lines)
    _assert(code == 1, "`[x]` item in backlog.md → conflict")
    _assert("backlog.md:5: - [x] done — verdict" in text, "conflict names the `[x]` line and number")

    github = _repo({
        "backlog.md": "## Old queue\n- [x] closed\n",
        "docs/conventions.md": "Keep `[x]` items as history.\n",
    })
    subprocess.run(["git", "init", "-q", str(github)], check=True)
    subprocess.run(
        ["git", "-C", str(github), "config", "remote.origin.url", "https://github.com/fixture/repo.git"],
        check=True,
    )
    code, lines = check(github)
    text = "\n".join(lines)
    _assert(code == 1 and "propose deleting" in text and "CONFLICT backlog-history" not in text,
            "history-only GitHub backlog proposes retirement under the issues backend")
    with (github / "backlog.md").open("a", encoding="utf-8") as backlog:
        backlog.write("- [ ] still queued\n")
    code, lines = check(github)
    text = "\n".join(lines)
    _assert(code == 1 and "backlog.md holds 1" in text and "1 open item(s); run the migration dry run" in text,
            "open GitHub backlog prompts migration and retains its history check")
    _assert("propose deleting" not in text, "open items prevent deletion")
    _legacy_tests(github)

    code, lines = check(_repo({
        "backlog.md": "## Now\n\n- [ ] open\n",
        "docs/conventions.md": "- Thematic bucket — keep `[x]` items as history.\n"
                               "- After a run, re-add what `prune-backlog` removed.\n",
    }))
    text = "\n".join(lines)
    _assert(code == 1, "doc rule keeping `[x]` history → conflict without any `[x]` line")
    _assert("docs/conventions.md:1:" in text, "conflict names the rule line")
    _assert("docs/conventions.md:2:" in text, "related `prune-backlog` doc line is listed")

    code, _ = check(_repo({
        "backlog.md": "## Now\n\n<!--\n- [x] template sample\n-->\n```\n- [x] fenced sample\n```\n",
        "docs/x.md": "```\nkeep [x] as history\n```\n",
    }))
    _assert(code == 0, "`[x]` and rule text inside comments/fences are ignored")

    code, _ = check(_repo({
        "backlog.md": "## Now\n\n- [ ] open\n",
        "docs/architecture.md": "line deletion is owned by `task_nodes.py prune-backlog`\n",
        "docs/design/old.md": "keep [x] as history\n",
    }))
    _assert(code == 0, "a doc naming `prune-backlog` alone, or a rule under docs/design/, is not a conflict")

    code, _ = check(_repo({
        "backlog.md": "## Now\n\n- [ ] open\n",
        "docs/harness-log.md": "- The thematic-bucket \"keep `[x]` as history\" rule and\n"
                               "  the \"re-add after `prune-backlog`\" workaround are gone.\n",
        "docs/conventions.md": "- The `prune-backlog` step deletes every line it covers.\n",
    }))
    _assert(code == 0, "a change-record doc quoting the retired rule is not a conflict")

    code, _ = check(_repo({"docs/catalog.md": "- Thematic bucket — keep `[x]` items as history.\n"}))
    _assert(code == 1, "a doc whose name only ends in the letters `log` (`catalog.md`) is still scanned")

    code, _ = check(_repo({"AGENTS.md": "- Done items: do not keep `[x]` lines as history.\n"}))
    _assert(code == 0, "a rule that forbids `[x]` history states the contract → no conflict")

    code, _ = check(_repo({"backlog.md": "## Now\n\n````md\n```\n- [x] template only\n```\n````\n"}))
    _assert(code == 0, "a shorter fence inside a longer one does not close it")

    print(f"\n{PASS_COUNT} passed, {FAIL_COUNT} failed")
    return 0 if FAIL_COUNT == 0 else 1


def _legacy_tests(github: Path) -> None:
    backlog = github / "backlog.md"
    agents = github / "AGENTS.md"
    agents.write_text("## Workflow\n- Queue truth `backlog.md`\n- File a `backlog.md` entry instead.\n"
                      "- Do not edit generated files; record follow-ups in backlog.md.\n"
                      "- Track tasks in backlog.md; never commit credentials.\n"
                      "- Put the file in backlog.md format.\n"
                      "- Do not file tasks in backlog.md.\n"
                      "- Track tasks in backlog.md.bak.\n",
                      encoding="utf-8")
    (github / "CLAUDE.md").write_text("<!-- Use backlog.md as the queue. -->\n"
                                     "```md\nQueue: backlog.md\n```\n"
                                     "Historical notes are in `backlog.md`.\n", encoding="utf-8")
    docs = github / "docs"
    (docs / "design").mkdir()
    for path in [docs / "design" / "queue.md", docs / "archive-2024.md", docs / "queue-history.md"]:
        path.write_text("Queue: backlog.md\n", encoding="utf-8")
    (docs / "workflow.md").write_text("Record new work in `backlog.md`.\n", encoding="utf-8")
    original = {p: p.read_bytes() for p in github.rglob("*.md")}
    text = "\n".join(check_legacy_backlog(github, env={}))
    _assert(all(f"AGENTS.md:{n}:" in text for n in (2, 3, 4, 5)) and "docs/workflow.md:1:" in text
            and text.count(_ISSUES_RULE) == 5, "steering proposals name each live line and its replacement")
    _assert(all(p.read_bytes() == data for p, data in original.items()), "the check leaves every source intact")
    _assert(not check_legacy_backlog(github, {ENV_VAR: "backlog"}), "explicit file backend opts out")
    _assert(not check_legacy_backlog(github, {ENV_VAR: "python3 /fixture/adapter.py"}), "explicit adapter opts out")

    for content, expected in [
        ("", "propose deleting"),
        ("<!--\n- [ ] example\n-->\n", "propose deleting"),
        ("## Now\n- [>] in flight\n", "resolve in-flight"),
        ("```\n- [ ] ambiguous\n", "unclosed code fence"),
        ("## Rejected — do not re-file\n- Build a dashboard — defer until needed.\n", "rejected entries remain"),
    ]:
        backlog.write_text(content, encoding="utf-8")
        _assert(expected in "\n".join(check_legacy_backlog(github, env={})), f"backlog reports {expected}")
    backlog.write_bytes(b"# Backlog\n\xff\n")
    code, lines = run(github, env={})
    text = "\n".join(lines)
    _assert(code == 2 and "fix the read error" in text and "AGENTS.md:2:" in text and "propose deleting" not in text,
            "a malformed backlog still reports steering and cannot be retired")
    backlog.unlink()
    text = "\n".join(check_legacy_backlog(github, env={}))
    _assert("AGENTS.md:2:" in text and "propose deleting" not in text, "steering-only GitHub repos are reported")
    with patch.dict(os.environ, {ENV_VAR: ""}), contextlib.redirect_stdout(io.StringIO()) as out:
        code = main(["--project", str(docs)])
    _assert(code == 1 and "AGENTS.md:2:" in out.getvalue(), "a nested project argument resolves the repository root")
    _assert(check_backlog_history(_repo({"docs/archive-policy.md": "Keep [x] items as history.\n"}), env={}),
            "the archive-name exclusion is limited to the migration steering check")

    other = _repo({"backlog.md": "- [ ] open\n", "AGENTS.md": "Queue: backlog.md\n"})
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    subprocess.run(["git", "-C", str(other), "remote", "add", "origin", "git@gitlab.com:fixture/other.git"], check=True)
    _assert(not check_legacy_backlog(other, env={}), "non-GitHub remotes are skipped")
    with tempfile.TemporaryDirectory(prefix="curate-sessions-") as tmp:
        claude = Path(tmp) / "claude"
        codex = Path(tmp) / "codex"
        transcript = claude / "projects" / "opaque-token" / "session.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"cwd": str(github / "docs")}) + "\n", encoding="utf-8")
        rollout = codex / "sessions" / "day" / "rollout.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": str(other)}}) + "\n",
                           encoding="utf-8")
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(claude), "CODEX_HOME": str(codex), ENV_VAR: ""}):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = main(["--all"])
        report_text = out.getvalue()
        _assert(code == 1 and f"Project: {github.resolve()}" in report_text
                and f"Project: {other.resolve()}" in report_text and "CONFLICT legacy-backlog" in report_text,
                "all scope resolves Claude and Codex project roots and reports by repository")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
