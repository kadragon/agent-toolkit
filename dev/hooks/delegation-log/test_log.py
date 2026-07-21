#!/usr/bin/env python3
"""Tests for delegation-log hook. Run: python3 test_log.py --test"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("log", os.path.join(HERE, "log.py"))
log = importlib.util.module_from_spec(spec)
spec.loader.exec_module(log)

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f" — {name}")
    if not cond:
        fails.append(name)


# --- normalize + description_hash ---------------------------------------------
check("normalize collapses whitespace", log.normalize("Foo  Bar") == "foo bar")
check("normalize lowercases", log.normalize("ABC") == "abc")
check("normalize strips", log.normalize("  x  ") == "x")
check("normalize empty", log.normalize("") == "")
check("normalize None-safe", log.normalize(None) == "")

h1 = log.description_hash("Foo  Bar")
h2 = log.description_hash("foo bar")
check("hash deterministic: 'Foo  Bar' == 'foo bar'", h1 == h2)
check("hash length 16", len(h1) == 16)
check("hash hex string", all(c in "0123456789abcdef" for c in h1))
check("different descriptions → different hashes", log.description_hash("abc") != log.description_hash("xyz"))

# --- build_record -------------------------------------------------------------
rec = log.build_record({
    "tool_input": {"subagent_type": "general-purpose", "description": "Investigate the codebase"},
    "cwd": "/repo",
    "session_id": "s1",
}, 9999)
check("record ts", rec["ts"] == 9999)
check("record subagent_type", rec["subagent_type"] == "general-purpose")
check("record description_hash length", len(rec["description_hash"]) == 16)
check("record cwd", rec["cwd"] == "/repo")
check("record session", rec["session"] == "s1")

# missing subagent_type → empty string
rec2 = log.build_record({"tool_input": {"description": "x"}, "cwd": "/x", "session_id": ""}, 1)
check("missing subagent_type → empty string", rec2["subagent_type"] == "")

# missing description → hash of empty string
rec3 = log.build_record({"tool_input": {}, "cwd": "/x", "session_id": ""}, 1)
check("missing description → hash of empty", rec3["description_hash"] == log.description_hash(""))

# --- append_capped trims to MAX_LINES ----------------------------------------
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "sub", "log.jsonl")
    for i in range(log.MAX_LINES + 50):
        log.append_capped(p, json.dumps({"i": i}))
    with open(p) as f:
        lines = f.readlines()
    check("log capped at MAX_LINES", len(lines) == log.MAX_LINES)
    check("log keeps newest", json.loads(lines[-1])["i"] == log.MAX_LINES + 49)

# --- symlink guard (Unix only) ------------------------------------------------
if log._IS_WIN:
    print("SKIP — symlink protection test (O_NOFOLLOW unavailable on Windows)")
else:
    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "target.txt")
        with open(target, "w") as fh:
            fh.write("original\n")
        link = os.path.join(td, "link.jsonl")
        os.symlink(target, link)
        log.append_capped(link, '{"test":1}')
        with open(target) as fh:
            content = fh.read()
        check("symlink write skipped — target unmodified", content == "original\n")
        check("symlink still a symlink", os.path.islink(link))

# --- .gitignore boundary ------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "test.jsonl")
    gi_path = os.path.join(td, ".gitignore")
    with open(gi_path, "w", encoding="utf-8") as gh:
        gh.write("keep")  # no trailing newline
    log.append_capped(lp, '{"test":1}')
    with open(gi_path, encoding="utf-8") as gh:
        gi_content = gh.read()
    check(".gitignore line boundary preserved", gi_content == "keep\n*\n")

# delegations.jsonl already in .gitignore → no duplicate
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "test.jsonl")
    gi_path = os.path.join(td, ".gitignore")
    with open(gi_path, "w", encoding="utf-8") as gh:
        gh.write("delegations.jsonl\n")
    log.append_capped(lp, '{"test":1}')
    with open(gi_path, encoding="utf-8") as gh:
        gi_content = gh.read()
    check(".gitignore no duplicate when delegations.jsonl present", gi_content == "delegations.jsonl\n")

# wildcard already in .gitignore → no duplicate
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "test.jsonl")
    gi_path = os.path.join(td, ".gitignore")
    with open(gi_path, "w", encoding="utf-8") as gh:
        gh.write("*\n")
    log.append_capped(lp, '{"test":1}')
    with open(gi_path, encoding="utf-8") as gh:
        gi_content = gh.read()
    check(".gitignore no duplicate when * present", gi_content == "*\n")

# --- invalid-UTF-8 .gitignore -------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "test.jsonl")
    gi_path = os.path.join(td, ".gitignore")
    with open(gi_path, "wb") as gh:
        gh.write(b"\xff\xfe not valid utf-8\n")
    raised = False
    try:
        log.append_capped(lp, '{"test":1}')
    except UnicodeDecodeError:
        raised = True
    check("invalid-utf8 .gitignore does not raise", not raised)
    wrote = os.path.exists(lp) and '{"test":1}' in open(lp, encoding="utf-8").read()
    check("log entry written despite undecodable .gitignore", wrote)

# --- end-to-end: Task call → exactly 1 line with all expected keys -----------
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init", "-q", d], check=True)
    payload = {
        "tool_name": "Task",
        "cwd": d,
        "session_id": "s42",
        "tool_input": {
            "subagent_type": "general-purpose",
            "description": "Investigate the codebase",
        },
    }
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True)
    target = os.path.join(d, ".claude", "logs", "delegations.jsonl")
    check("e2e exit 0", r.returncode == 0)
    check("e2e log written", os.path.exists(target))
    with open(target) as f:
        lines = f.readlines()
    check("e2e exactly 1 line", len(lines) == 1)
    row = json.loads(lines[0])
    check("e2e has ts", "ts" in row and isinstance(row["ts"], int))
    check("e2e subagent_type", row.get("subagent_type") == "general-purpose")
    check("e2e description_hash length", len(row.get("description_hash", "")) == 16)
    check("e2e has cwd", "cwd" in row)
    check("e2e session", row.get("session") == "s42")
    gi = os.path.join(d, ".claude", "logs", ".gitignore")
    check("e2e gitignore created", os.path.exists(gi) and open(gi).read().strip() == "*")

# --- end-to-end: malformed stdin → exit 0, no write --------------------------
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init", "-q", d], check=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input="not json", text=True, capture_output=True)
    target = os.path.join(d, ".claude", "logs", "delegations.jsonl")
    check("malformed stdin exit 0", r.returncode == 0)
    check("malformed stdin no write", not os.path.exists(target))

# --- end-to-end: non-Task tool → no write ------------------------------------
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init", "-q", d], check=True)
    payload = {
        "tool_name": "Bash", "cwd": d, "session_id": "s",
        "tool_input": {"command": "echo hi"},
    }
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True)
    target = os.path.join(d, ".claude", "logs", "delegations.jsonl")
    check("non-Task tool exit 0", r.returncode == 0)
    check("non-Task tool no write", not os.path.exists(target))

# --- hash deterministic across calls (same desc → same hash) -----------------
desc = "Investigate the codebase"
expected_hash = log.description_hash(desc)
check("hash deterministic same call", log.description_hash(desc) == expected_hash)
check("hash deterministic normalized", log.description_hash("INVESTIGATE  THE  CODEBASE") == expected_hash)

# --- end-to-end: non-git cwd falls back to CLAUDE_PROJECT_DIR ---------------
with tempfile.TemporaryDirectory() as nogit, tempfile.TemporaryDirectory() as proj:
    subprocess.run(["git", "init", "-q", proj], check=True)
    payload = {
        "tool_name": "Task",
        "cwd": nogit,
        "session_id": "s",
        "tool_input": {"subagent_type": "agent", "description": "do something"},
    }
    env = dict(os.environ, CLAUDE_PROJECT_DIR=proj)
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True, env=env)
    target = os.path.join(proj, ".claude", "logs", "delegations.jsonl")
    check("CLAUDE_PROJECT_DIR fallback", os.path.exists(target))

# --- end-to-end: non-git cwd, no CLAUDE_PROJECT_DIR → skip ------------------
with tempfile.TemporaryDirectory() as nogit:
    payload = {
        "tool_name": "Task",
        "cwd": nogit,
        "session_id": "s",
        "tool_input": {"subagent_type": "agent", "description": "do something"},
    }
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    r = subprocess.run([sys.executable, os.path.join(HERE, "log.py")],
                       input=json.dumps(payload), text=True, capture_output=True, env=env)
    target = os.path.join(nogit, ".claude", "logs", "delegations.jsonl")
    check("no git root no proj dir: exit 0", r.returncode == 0)
    check("no git root no proj dir: no write", not os.path.exists(target))

# ============================================================================
# REGRESSION TESTS — finding #10 (delegation-log)
# ============================================================================

# Finding #10: .gitignore idempotency — existing pattern that already MATCHES
#   delegations.jsonl via fnmatch (e.g. *.jsonl, *) must suppress appending *.
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "test.jsonl")
    gi_path = os.path.join(td, ".gitignore")
    with open(gi_path, "w", encoding="utf-8") as gh:
        gh.write("*.jsonl\n")
    log.append_capped(lp, '{"test":1}')
    with open(gi_path, encoding="utf-8") as gh:
        gi_content = gh.read()
    check(
        "regression #10: *.jsonl already matches delegations.jsonl → no * appended",
        gi_content == "*.jsonl\n",
    )

# Also verify an arbitrary glob that matches (e.g. 'delegations.*') suppresses append
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "test.jsonl")
    gi_path = os.path.join(td, ".gitignore")
    with open(gi_path, "w", encoding="utf-8") as gh:
        gh.write("delegations.*\n")
    log.append_capped(lp, '{"test":1}')
    with open(gi_path, encoding="utf-8") as gh:
        gi_content = gh.read()
    check(
        "regression #10: delegations.* already matches → no * appended",
        gi_content == "delegations.*\n",
    )

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("all passed")
