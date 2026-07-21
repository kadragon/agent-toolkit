#!/usr/bin/env python3
"""summarize.py — cluster the per-repo failed-commands.jsonl for harness-curate.

Reads `<root>/.claude/logs/failed-commands.jsonl` (root = cwd / given path, walks
up to the git root), groups failures by (command-signature, exitCode), and prints
a BOUNDED, ranked summary. The model then judges: a command failing the same way
≥N times is a harness gap (missing guard / doc / alias / skill).

Signature = first two tokens of the command (basename of the head), so
`git psh origin main` and `git psh origin dev` cluster together as `git psh`.

Usage:
  python3 summarize.py [root]      # default root = cwd
  python3 summarize.py --test

Output (stdout), deterministic, never raises:
  FAILED-COMMANDS (<repo>): <total> records, <unique> signatures
  <count>x  exit <code>  <signature>
            e.g. <one sample command>
            err: <stderr first line>
"""

import json
import os
import shlex
import subprocess
import sys

LOG_REL = os.path.join(".claude", "logs", "failed-commands.jsonl")
TOP = 15            # cap printed signatures
MIN_COUNT = 1       # print signatures seen at least this many times


def git_root(path):
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return path


def signature(command):
    try:
        toks = shlex.split(command) if command else []
    except ValueError:
        toks = command.split() if command else []
    toks = [t for t in toks if "=" not in t.split("/")[0] and t != "sudo"]
    head = [os.path.basename(t) for t in toks[:2]]
    return " ".join(head) or "(empty)"


def load(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except OSError:
        pass
    return rows


def summarize(rows):
    groups = {}
    for r in rows:
        key = (signature(r.get("command", "")), r.get("exitCode"))
        g = groups.setdefault(key, {"count": 0, "sample": "", "err": ""})
        g["count"] += 1
        if not g["sample"]:
            g["sample"] = r.get("command", "")
            err = (r.get("stderr") or "").strip().splitlines()
            g["err"] = err[0] if err else ""
    ranked = sorted(groups.items(), key=lambda kv: -kv[1]["count"])
    return ranked


def render(root, rows):
    ranked = summarize(rows)
    lines = [f"FAILED-COMMANDS ({os.path.basename(root) or root}): "
             f"{len(rows)} records, {len(ranked)} signatures"]
    shown = 0
    for (sig, code), g in ranked:
        if g["count"] < MIN_COUNT:
            continue
        if shown >= TOP:
            lines.append(f"  ... {len(ranked) - shown} more signatures (capped)")
            break
        lines.append(f"  {g['count']}x  exit {code}  {sig}")
        lines.append(f"        e.g. {g['sample'][:100]}")
        if g["err"]:
            lines.append(f"        err: {g['err'][:120]}")
        shown += 1
    return "\n".join(lines)


_USAGE = """\
Usage:
  python3 summarize.py [root]      # default root = cwd
  python3 summarize.py --test
"""


def main(argv):
    if argv and argv[0] in {"--help", "-h"}:
        print(_USAGE, end="")
        return
    root = git_root(os.path.abspath(argv[0])) if argv else git_root(os.getcwd())
    rows = load(os.path.join(root, LOG_REL))
    print(render(root, rows))


def _test():
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL") + f" — {name}")
        if not cond:
            fails.append(name)

    check("signature strips args", signature("git psh origin main") == "git psh")
    check("signature env+sudo", signature("A=1 sudo git psh") == "git psh")
    check("signature single", signature("gti") == "gti")
    check("signature empty", signature("") == "(empty)")

    rows = [
        {"command": "git psh origin main", "exitCode": 1, "stderr": "unknown cmd psh"},
        {"command": "git psh origin dev", "exitCode": 1, "stderr": "unknown cmd psh"},
        {"command": "gti status", "exitCode": 127, "stderr": "not found"},
    ]
    ranked = summarize(rows)
    check("clusters psh together", ranked[0][1]["count"] == 2)
    check("two signatures", len(ranked) == 2)
    out = render("/tmp/myrepo", rows)
    check("render header", "3 records, 2 signatures" in out)
    check("render top first", "2x  exit 1  git psh" in out)
    check("render empty ok", "0 records" in render("/tmp/r", []))

    # --help must print usage text, not treat flag as a path
    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        main(["--help"])
    finally:
        sys.stdout = old_stdout
    out = buf.getvalue()
    check("--help prints usage (not FAILED-COMMANDS)", "FAILED-COMMANDS" not in out and len(out) > 0)

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        main(sys.argv[1:])
