#!/usr/bin/env python3
"""self-improve-nudge — Stop hook: per-session learning-capture nudge.

Purpose: fires ONCE at session end when capture signals are present. Instead of
         blocking Stop (which forced an extra Claude turn that buried the work
         summary), it records the signals to a per-project pending file and exits
         cleanly. surface.py replays it at the NEXT SessionStart in the same
         project, where there is no summary to bury.

Distinct from harness-curator (cold-path cross-session retrospective):
this is warm-path — fired automatically per session, surfaced at the very next
session start rather than mid-transcript.

Signals:
  A  complex-task     >= 10 action tool calls (Edit/Write/Bash/Agent etc.)
  B  error-recovery   is_error true -> success in tool_result sequence
  C  user-correction  pushback phrases after an assistant turn
"""

import json
import os
import re
import sys
import time

from _common import config_dir, pending_path

ACTION_TOOLS = re.compile(
    r"^(Edit|Write|Bash|Agent|Task|Workflow|NotebookEdit|WebSearch)"
)

# Mirrors scan_transcripts.py CORRECTION_RE for consistency.
CORRECTION_RE = re.compile(
    r"^(no|nope|nah)\b(?![ ]\w)"
    r"|\b(wrong|undo|revert|incorrect|not what|that'?s not|don'?t)\b"
    r"|(아니|그게 아니|아닌데|다시|틀렸|잘못|되돌려)",
    re.IGNORECASE,
)
CORRECTION_MAXLEN = 50
ACTION_THRESHOLD = 10


def read_input():
    try:
        return json.loads(sys.stdin.read())
    except Exception:
        return {}


def load_transcript(path):
    records = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if not r.get("isMeta") and not r.get("isSidechain"):
                        records.append(r)
                except Exception:
                    continue
    except Exception:
        pass
    return records


def text_of(message):
    if not isinstance(message, dict):
        return ""
    c = message.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        # Mirrors scan_transcripts.py: tool_result-bearing messages are not user text.
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return ""
        parts = []
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return " ".join(parts)
    return ""


def detect_signals(records):
    """Single pass over records to detect all three signals."""
    action_count = 0
    saw_error = False
    recovered = False
    correction_found = False
    prev_was_assistant = False

    for r in records:
        typ = r.get("type")

        if typ == "assistant":
            prev_was_assistant = True
            msg = r.get("message") or {}
            content = msg.get("content") or []
            if isinstance(content, list):
                for b in content:
                    if (isinstance(b, dict)
                            and b.get("type") == "tool_use"
                            and ACTION_TOOLS.match(b.get("name", ""))):
                        action_count += 1

        elif typ == "user":
            content = (r.get("message") or {}).get("content") or []
            is_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )

            if is_tool_result:
                # Signal B: O(n) linear error->recovery detection.
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        if b.get("is_error"):
                            saw_error = True
                        elif saw_error:
                            recovered = True
                # tool_result is not a human turn — don't break assistant adjacency.
            else:
                # Human message: check Signal C.
                if not correction_found and prev_was_assistant:
                    txt = text_of(r.get("message", {})).replace("\n", " ").strip()
                    if txt and len(txt) < CORRECTION_MAXLEN and CORRECTION_RE.search(txt):
                        correction_found = True
                prev_was_assistant = False

    signals = []
    parts = []

    if action_count >= ACTION_THRESHOLD:
        signals.append("complex-task")
        parts.append(
            f"[A] complex task ({action_count} action calls). "
            "Reusable workflow -> `skill-creator`; one-off -> pass."
        )

    if recovered:
        signals.append("error-recovery")
        parts.append(
            "[B] error->recovery. "
            "Setup/infra fix -> `docs/<topic>.md`; "
            "approach correction -> auto-memory or CLAUDE.md delta; "
            "one-off -> pass."
        )

    if correction_found:
        signals.append("user-correction")
        parts.append(
            "[C] user corrected approach. "
            "Preference/style -> auto-memory; "
            "workflow misunderstanding -> `skill-creator` improvement; "
            "else -> pass."
        )

    return signals, parts


def main():
    inp = read_input()

    # Guard 1: prevent infinite re-invocation
    if inp.get("stop_hook_active"):
        sys.exit(0)

    session_id = inp.get("session_id", "")
    if not session_id:
        sys.exit(0)

    cdir = config_dir()
    marker_dir = os.path.join(cdir, "tmp", "nudge-markers")
    os.makedirs(marker_dir, exist_ok=True)

    # Guard 2: session-once marker (sufficient — per-session warm-path needs no cross-session throttle)
    marker = os.path.join(marker_dir, f"{session_id}.nudged")
    if os.path.exists(marker):
        sys.exit(0)

    # Guard 3: transcript must exist and be readable
    transcript = inp.get("transcript_path", "")
    if not transcript or not os.path.isfile(transcript):
        sys.exit(0)

    records = load_transcript(transcript)
    if not records:
        sys.exit(0)

    signals, parts = detect_signals(records)
    if not signals:
        sys.exit(0)

    # Mark fired before writing so a crash below doesn't re-fire this session.
    try:
        open(marker, "a").close()
    except Exception:
        pass

    # Record the signals for surface.py to replay at the next SessionStart in
    # this project. Do NOT block Stop — blocking forced an extra Claude turn that
    # buried the session's work summary. cwd keys the file; the reader derives the
    # same path from its own cwd next session.
    cwd = inp.get("cwd") or os.getcwd()
    payload = {
        "signals": signals,
        "parts": parts,
        "written_ms": int(time.time() * 1000),
        "session_id": session_id,
    }
    try:
        path = pending_path(cwd, cdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
