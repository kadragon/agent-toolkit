#!/usr/bin/env python3
"""Preserve a branch's contract and check evidence across sessions; report clues, never completion.

save [--file PATH] reads the approved contract from PATH or stdin. Existing different
contracts are refused; --replace is for an explicitly approved scope revision. Every
**Acceptance criteria:** checkbox must name its check after an arrow (`- [ ] X → pytest -k x`),
so "done" is decided by a runnable signal rather than by how the diff looks. save is
refused on main/master: the archive is keyed by branch name, so a contract written from
the base branch (a --tree run whose Bash CWD reset to the main checkout) would be keyed
where the next cycle looks for its own and would block it.
evidence --command TEXT --exit N [--log PATH] [--env TEXT] records a validation run beside
the contract, with HEAD and the index tree, so a later session can judge reuse.
note reads text from stdin and appends it to the branch's notes, so a stuck or interrupted
run hands its failed approaches to a fresh session instead of re-trying them.
inspect reports the current branch, HEAD, all dirty state, the saved contract, the saved
evidence, the notes, and whether the recorded tree still matches the working index.
retire [--branch NAME] deletes a branch's archive after a confirmed merge, so a reused
branch name cannot resurrect a completed cycle's contract. --branch names the merged
branch when the caller has already switched back to the base or deleted it.
Archives live in the common Git directory so removing a worktree cannot erase them.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_BRANCHES = ("main", "master")
CRITERIA_HEADING = "**Acceptance criteria:**"
CHECKBOX = re.compile(r"^\s*- \[[ xX]\]\s*(.*)$")
FIELD = re.compile(r"^\*\*[^*]+:\*\*")
# The inline template form, or the `## Acceptance criteria` heading a tasks.md sprint block uses.
CRITERIA_START = re.compile(r"^(?:\*\*Acceptance criteria:\*\*|#{1,6}\s+Acceptance criteria\s*$)", re.I)
ARROW = re.compile(r"(?:→|->)\s*\S")


def check_criteria(text):
    """Refuse a contract whose acceptance criteria do not each name a check."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if CRITERIA_START.match(line.strip())]
    if not starts:
        raise ValueError(f"Contract has no {CRITERIA_HEADING} section")
    for start in starts:
        items = []
        for line in lines[start + 1:]:
            if FIELD.match(line.strip()) or line.startswith("#"):
                break
            match = CHECKBOX.match(line)
            if match:
                items.append(match.group(1))
        if not items:
            raise ValueError(f"{CRITERIA_HEADING} section at line {start + 1} lists no criteria")
        for item in items:
            if not ARROW.search(item):
                raise ValueError(
                    f"Criterion names no check: '{item}' — append '→ <test, command, or "
                    "observation that proves it>'"
                )


def git(*args):
    return subprocess.check_output(["git", *args], text=True).rstrip("\n")


def index_tree():
    """The tree the checks actually ran against. None when the index cannot be written."""
    try:
        return git("write-tree")
    except subprocess.CalledProcessError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand", required=True)
    save = sub.add_parser("save")
    save.add_argument("--file", type=Path)
    save.add_argument("--replace", action="store_true")
    evidence = sub.add_parser("evidence")
    evidence.add_argument("--command", dest="check_command", required=True)
    evidence.add_argument("--exit", dest="exit_code", type=int, required=True)
    evidence.add_argument("--log")
    evidence.add_argument("--env")
    sub.add_parser("note")
    sub.add_parser("inspect")
    retire = sub.add_parser("retire")
    retire.add_argument("--branch")
    args = parser.parse_args()
    try:
        branch = getattr(args, "branch", None) or git("symbolic-ref", "--quiet", "--short", "HEAD")
        common = Path(git("rev-parse", "--git-common-dir")).resolve()
        key = hashlib.sha256(branch.encode()).hexdigest()
        slot = common / "task-cycle" / key
        path = slot / "contract.md"
        evidence_path = slot / "evidence.json"
        notes_path = slot / "notes.md"
        if args.subcommand == "save":
            if branch in BASE_BRANCHES:
                raise ValueError(
                    f"Refusing to archive from base branch '{branch}' — run this from the "
                    "feature branch or worktree that owns the cycle"
                )
            text = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
            if not text.strip():
                raise ValueError("Empty contract refused")
            check_criteria(text)
            if path.exists() and path.read_text(encoding="utf-8") != text and not args.replace:
                raise ValueError("Saved contract differs; inspect before an approved --replace")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
            result = {"branch": branch, "contract_path": str(path)}
        elif args.subcommand == "evidence":
            if not path.exists():
                raise ValueError(f"No archived contract for '{branch}'; save it before evidence")
            record = {
                "head": git("rev-parse", "HEAD"),
                "tree": index_tree(),
                "command": args.check_command,
                "exit_code": args.exit_code,
                "log": args.log,
                "environment": args.env,
            }
            slot.mkdir(parents=True, exist_ok=True)
            temporary = evidence_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(evidence_path)
            result = {"branch": branch, "evidence_path": str(evidence_path), **record}
        elif args.subcommand == "note":
            if not path.exists():
                raise ValueError(f"No archived contract for '{branch}'; save it before a note")
            text = sys.stdin.read().strip()
            if not text:
                raise ValueError("Empty note refused")
            with notes_path.open("a", encoding="utf-8") as notes:
                notes.write(text + "\n\n")
            result = {"branch": branch, "notes_path": str(notes_path)}
        elif args.subcommand == "retire":
            existed = slot.is_dir()
            if existed:
                shutil.rmtree(slot)
            result = {"branch": branch, "retired": existed, "contract_path": str(path)}
        else:
            record = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else None
            result = {
                "branch": branch,
                "head": git("rev-parse", "HEAD"),
                "changes": git("status", "--porcelain=v1", "--untracked-files=all"),
                "contract_path": str(path),
                "contract": path.read_text(encoding="utf-8") if path.exists() else None,
                "evidence_path": str(evidence_path),
                "evidence": record,
                "notes": notes_path.read_text(encoding="utf-8") if notes_path.exists() else None,
                "tree_matches_current": bool(record) and record.get("tree") == index_tree(),
            }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
