#!/usr/bin/env python3
"""check_plugin_contracts.py — find repo-side rules that contradict a shipped `dev` plugin contract.

A repo can write its own rule over a plugin contract — a convention doc, a lint gate, a habit of
hand-editing after a bundled script runs. The plugin script then keeps doing what its contract
says, the repo rule keeps undoing it, and the agent pays the difference by hand every cycle. This
check makes the conflict visible to `harness-curate`, which proposes the repo-side fix.

Contracts checked:

  backlog-history   Closed items leave `backlog.md`: `task_nodes.py prune-backlog` deletes them at
                    cleanup, and the closure record is the `CHANGELOG.md` entry. A repo that keeps
                    `- [x]` lines in `backlog.md`, or documents a rule to keep them, conflicts.

Usage:
  python3 check_plugin_contracts.py [--project PATH]
  python3 check_plugin_contracts.py --test

  --project PATH  repo root to check (default: cwd).

Scanned: `backlog.md`, `AGENTS.md`, `CLAUDE.md`, and `docs/*.md` (top level only — `docs/design/`
holds past specs, not live rules). Fenced code blocks and HTML comments are masked, so a template
sample is not a rule.

Exit: 0 no conflict · 1 conflict reported on stdout · 2 usage error. Read-only; writes nothing.
Self-check (--test): exits 0 on PASS, 1 on FAIL. All fixtures live in a tempdir.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_DONE_RE = re.compile(r"^\s*[-*+]\s+\[[xX]\]\s")
# A doc line that states a keep-`[x]`-as-history rule. Both halves must sit on one line.
_KEEP_RULE_RE = re.compile(r"\[x\].*\bhistory\b|\bhistory\b.*\[x\]", re.IGNORECASE)
_PRUNE_RE = re.compile(r"prune-backlog")
MAX_SHOWN = 10


def masked_lines(text: str) -> list[str]:
    """Source lines with HTML comments and fenced blocks blanked; line count preserved."""
    text = _COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return out


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
        docs.extend(sorted(docs_dir.glob("*.md")))
    return [p for p in docs if p.is_file()]


def grep_docs(root: Path, pattern: re.Pattern[str]) -> list[str]:
    hits = []
    for path in rule_docs(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(masked_lines(text), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(root).as_posix()}:{n}: {line.strip()}")
    return hits


def check_backlog_history(root: Path) -> list[str]:
    """Report lines for the backlog-history contract; empty when the repo conforms."""
    backlog = root / "backlog.md"
    items = done_items(backlog.read_text(encoding="utf-8", errors="replace")) if backlog.is_file() else []
    rules = grep_docs(root, _KEEP_RULE_RE)
    if not items and not rules:
        return []
    out = [
        "CONFLICT backlog-history: the plugin deletes closed backlog items (`prune-backlog`) and "
        "records the closure in CHANGELOG.md; this repo keeps them in backlog.md.",
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
    related = [h for h in grep_docs(root, _PRUNE_RE) if h not in rules]
    if related:
        out.append("  Repo doc lines naming `prune-backlog` (workarounds or gates to re-check):")
        out.extend(f"    {hit}" for hit in related)
    out.append(
        "  Proposed repo-side fix: rewrite each listed rule to 'closed items are deleted; the "
        "CHANGELOG.md entry is the record'; retire any gate that counts `[x]` items; delete the "
        "existing `[x]` lines once their closure is in CHANGELOG.md or git history."
    )
    return out


CHECKS = (check_backlog_history,)


def run(root: Path) -> tuple[int, list[str]]:
    lines: list[str] = []
    for check in CHECKS:
        lines.extend(check(root))
    return (1 if lines else 0), lines


def main(argv: list[str]) -> int:
    if "--test" in argv:
        return run_tests()
    root = Path.cwd()
    if "--project" in argv:
        i = argv.index("--project")
        if i + 1 >= len(argv):
            print("Error: --project requires a path", file=sys.stderr)
            return 2
        root = Path(argv[i + 1])
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        return 2
    code, lines = run(root)
    print("\n".join(lines) if lines else "OK: no plugin-contract conflicts")
    return code


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

    code, lines = run(_repo({"backlog.md": "# Backlog\n\n## Now\n\n- [ ] open item\n"}))
    _assert(code == 0 and not lines, "open items only, no rule → no conflict")

    code, _ = run(_repo({}))
    _assert(code == 0, "no backlog.md, no docs → no conflict")

    code, lines = run(_repo({
        "backlog.md": "## Review Backlog\n\n### PR #100 — x\n\n- [x] done — verdict\n- [ ] open\n",
    }))
    text = "\n".join(lines)
    _assert(code == 1, "`[x]` item in backlog.md → conflict")
    _assert("backlog.md:5: - [x] done — verdict" in text, "conflict names the `[x]` line and number")

    code, lines = run(_repo({
        "backlog.md": "## Now\n\n- [ ] open\n",
        "docs/conventions.md": "- Thematic bucket — keep `[x]` items as history.\n"
                               "- After a run, re-add what `prune-backlog` removed.\n",
    }))
    text = "\n".join(lines)
    _assert(code == 1, "doc rule keeping `[x]` history → conflict without any `[x]` line")
    _assert("docs/conventions.md:1:" in text, "conflict names the rule line")
    _assert("docs/conventions.md:2:" in text, "related `prune-backlog` doc line is listed")

    code, _ = run(_repo({
        "backlog.md": "## Now\n\n<!--\n- [x] template sample\n-->\n```\n- [x] fenced sample\n```\n",
        "docs/x.md": "```\nkeep [x] as history\n```\n",
    }))
    _assert(code == 0, "`[x]` and rule text inside comments/fences are ignored")

    code, _ = run(_repo({
        "backlog.md": "## Now\n\n- [ ] open\n",
        "docs/architecture.md": "line deletion is owned by `task_nodes.py prune-backlog`\n",
        "docs/design/old.md": "keep [x] as history\n",
    }))
    _assert(code == 0, "a doc naming `prune-backlog` alone, or a rule under docs/design/, is not a conflict")

    print(f"\n{PASS_COUNT} passed, {FAIL_COUNT} failed")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
