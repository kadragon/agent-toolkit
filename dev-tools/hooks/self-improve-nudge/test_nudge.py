#!/usr/bin/env python3
"""Tests for self-improve-nudge Stop writer + SessionStart reader.
Run: python3 test_nudge.py --test"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


common = _load("_common", "_common.py")
nudge = _load("nudge", "nudge.py")

fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f" — {name}")
    if not cond:
        fails.append(name)


def run(script, payload, config_dir, cwd_for_run=None):
    """Invoke a hook script as a subprocess with CLAUDE_CONFIG_DIR pinned."""
    env = dict(os.environ, CLAUDE_CONFIG_DIR=config_dir)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    env.pop("CODEX_HOME", None)
    return subprocess.run(
        [sys.executable, os.path.join(HERE, script)],
        input=json.dumps(payload), text=True, capture_output=True,
        env=env, cwd=cwd_for_run or HERE,
    )


# --- _common: symmetric key derivation ---------------------------------------
check("encode_project deterministic",
      common.encode_project("/a/b") == common.encode_project("/a/b"))
check("encode_project replaces separators",
      "/" not in common.encode_project("/a/b") and "." not in common.encode_project("/a/b.c"))
p1 = common.pending_path("/repo/x", "/cfg")
p2 = common.pending_path("/repo/x", "/cfg")
check("pending_path stable for same cwd", p1 == p2)
check("pending_path differs by cwd",
      common.pending_path("/repo/x", "/cfg") != common.pending_path("/repo/y", "/cfg"))
check("pending_path under projects/", os.sep + "projects" + os.sep in p1)

# --- detect_signals: complex-task threshold ----------------------------------
recs = []
for _ in range(nudge.ACTION_THRESHOLD):
    recs.append({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit"}]}})
signals, parts = nudge.detect_signals(recs)
check("complex-task fires at threshold", "complex-task" in signals)
check("complex-task part present", any("complex task" in p for p in parts))

signals2, _ = nudge.detect_signals(recs[:-1])  # one below threshold
check("complex-task below threshold silent", "complex-task" not in signals2)

# error-recovery
rr = [
    {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
]
sig_r, _ = nudge.detect_signals(rr)
check("error-recovery fires on error->success", "error-recovery" in sig_r)

# user-correction
rc = [
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
    {"type": "user", "message": {"content": "no, that's wrong"}},
]
sig_c, _ = nudge.detect_signals(rc)
check("user-correction fires on pushback", "user-correction" in sig_c)

# ============================================================================
# END-TO-END: Stop writer
# ============================================================================

def transcript_with_signals(dir_):
    """Write a transcript that trips the complex-task signal."""
    tp = os.path.join(dir_, "t.jsonl")
    with open(tp, "w", encoding="utf-8") as f:
        for _ in range(nudge.ACTION_THRESHOLD):
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash"}]}}) + "\n")
    return tp


# Stop writes a pending file and does NOT block (empty stdout, exit 0).
with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as proj:
    tp = transcript_with_signals(cfg)
    payload = {"session_id": "s1", "transcript_path": tp, "cwd": proj}
    r = run("nudge.py", payload, cfg)
    check("stop exit 0", r.returncode == 0)
    check("stop does NOT block (no stdout json)", r.stdout.strip() == "")
    pend = common.pending_path(proj, cfg)
    check("stop wrote pending file", os.path.exists(pend))
    if os.path.exists(pend):
        data = json.load(open(pend, encoding="utf-8"))
        check("pending has complex-task signal", "complex-task" in data.get("signals", []))
        check("pending has written_ms", isinstance(data.get("written_ms"), int))

# No signals -> no pending file.
with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as proj:
    tp = os.path.join(cfg, "empty.jsonl")
    with open(tp, "w") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": []}}) + "\n")
    r = run("nudge.py", {"session_id": "s2", "transcript_path": tp, "cwd": proj}, cfg)
    check("no-signal exit 0", r.returncode == 0)
    check("no-signal no pending file", not os.path.exists(common.pending_path(proj, cfg)))

# stop_hook_active guard -> no write.
with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as proj:
    tp = transcript_with_signals(cfg)
    r = run("nudge.py", {"session_id": "s3", "transcript_path": tp,
                         "cwd": proj, "stop_hook_active": True}, cfg)
    check("stop_hook_active no pending", not os.path.exists(common.pending_path(proj, cfg)))

# session-once marker -> second Stop in same session does not rewrite.
with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as proj:
    tp = transcript_with_signals(cfg)
    payload = {"session_id": "sX", "transcript_path": tp, "cwd": proj}
    run("nudge.py", payload, cfg)
    pend = common.pending_path(proj, cfg)
    os.remove(pend)  # simulate consumption
    run("nudge.py", payload, cfg)  # same session again
    check("session-once marker blocks rewrite", not os.path.exists(pend))

# ============================================================================
# END-TO-END: SessionStart reader (surface.py)
# ============================================================================

# Writer then reader in the SAME project -> reader surfaces and deletes.
with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as proj:
    tp = transcript_with_signals(cfg)
    run("nudge.py", {"session_id": "w1", "transcript_path": tp, "cwd": proj}, cfg)
    pend = common.pending_path(proj, cfg)
    check("handoff: pending exists before surface", os.path.exists(pend))
    r = run("surface.py", {"session_id": "next", "cwd": proj, "source": "startup"}, cfg)
    check("surface exit 0", r.returncode == 0)
    check("surface emits nudge text", "[self-improve-nudge]" in r.stdout)
    check("surface names the signal", "complex-task" in r.stdout)
    check("surface consumed pending file", not os.path.exists(pend))

# Second SessionStart -> nothing to surface (fired exactly once).
    r2 = run("surface.py", {"session_id": "next2", "cwd": proj, "source": "startup"}, cfg)
    check("surface silent when no pending", r2.stdout.strip() == "")

# No pending file at all -> silent.
with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as proj:
    r = run("surface.py", {"session_id": "s", "cwd": proj, "source": "startup"}, cfg)
    check("surface silent with no pending file", r.stdout.strip() == "" and r.returncode == 0)

# Stale pending (older than MAX_AGE_MS) -> deleted, not surfaced.
with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as proj:
    pend = common.pending_path(proj, cfg)
    os.makedirs(os.path.dirname(pend), exist_ok=True)
    with open(pend, "w", encoding="utf-8") as f:
        json.dump({"signals": ["complex-task"], "parts": ["[A] old"],
                   "written_ms": 1}, f)  # ancient
    r = run("surface.py", {"session_id": "s", "cwd": proj, "source": "startup"}, cfg)
    check("stale pending not surfaced", r.stdout.strip() == "")
    check("stale pending deleted", not os.path.exists(pend))

# Cross-project isolation: pending in project A not surfaced when opening B.
with tempfile.TemporaryDirectory() as cfg, \
     tempfile.TemporaryDirectory() as projA, tempfile.TemporaryDirectory() as projB:
    tp = transcript_with_signals(cfg)
    run("nudge.py", {"session_id": "a", "transcript_path": tp, "cwd": projA}, cfg)
    r = run("surface.py", {"session_id": "b", "cwd": projB, "source": "startup"}, cfg)
    check("cross-project: opening B does not surface A's nudge", r.stdout.strip() == "")
    check("cross-project: A's pending still intact",
          os.path.exists(common.pending_path(projA, cfg)))

# malformed stdin -> exit 0, silent (both scripts).
with tempfile.TemporaryDirectory() as cfg:
    for script in ("nudge.py", "surface.py"):
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, script)],
            input="not json", text=True, capture_output=True,
            env=dict(os.environ, CLAUDE_CONFIG_DIR=cfg),
        )
        check(f"{script} malformed stdin exit 0", r.returncode == 0)

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("all passed")
