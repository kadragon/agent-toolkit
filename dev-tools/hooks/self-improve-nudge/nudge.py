#!/usr/bin/env python3
"""self-improve-nudge — Stop hook: per-session learning-capture gate.

Purpose: fires ONCE at session end when capture signals are present.
         Blocks Stop so Claude captures lessons before they evaporate.

Distinct from harness-curator (cold-path cross-session retrospective):
this is hot-path — single session, fired automatically, captures the delta
while context is still live.

Signals:
  A  complex-task     >= 10 action tool calls (Edit/Write/Bash/Agent etc.)
  B  error-recovery   is_error true -> success in tool_result sequence
  C  user-correction  pushback phrases after an assistant turn
"""

import json
import os
import re
import sys

ACTION_TOOLS = re.compile(
    r"^(Edit|Write|Bash|Agent|Task|Workflow|NotebookEdit|WebSearch|mcp__)"
)

# Mirrors scan_transcripts.py CORRECTION_RE for consistency.
CORRECTION_RE = re.compile(
    r"^(no|nope|nah)\b(?![ ]\w)"
    r"|\b(wrong|undo|revert|incorrect|not what|that'?s not|don'?t)\b"
    r"|(아니|그게 아니|아닌데|다시|틀렸|잘못|되돌려)",
    re.IGNORECASE,
)
CORRECTION_MAXLEN = 80
ACTION_THRESHOLD = 10
THROTTLE_HOURS = 4          # cross-session cooldown; prevents every-session noise


def load_state(state_path):
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state_path, state):
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


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
        parts = []
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return " ".join(parts)
    return ""


def detect_signals(records):
    signals = []
    parts = []

    # Signal A: action tool calls across the full session
    action_count = 0
    for r in records:
        if r.get("type") != "assistant":
            continue
        msg = r.get("message") or {}
        content = msg.get("content") or []
        if not isinstance(content, list):
            continue
        for b in content:
            if (isinstance(b, dict)
                    and b.get("type") == "tool_use"
                    and ACTION_TOOLS.match(b.get("name", ""))):
                action_count += 1

    if action_count >= ACTION_THRESHOLD:
        signals.append("complex-task")
        parts.append(
            f"[A] complex task ({action_count} action calls). "
            "Reusable workflow -> `skill-creator`; one-off -> pass."
        )

    # Signal B: error->recovery in tool_result sequence
    error_flags = []
    for r in records:
        if r.get("type") != "user":
            continue
        content = (r.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                error_flags.append(bool(b.get("is_error")))

    recovered = any(
        error_flags[i] and any(not e for e in error_flags[i + 1:])
        for i in range(len(error_flags) - 1)
    )
    if recovered:
        signals.append("error-recovery")
        parts.append(
            "[B] error->recovery. "
            "Setup/infra fix -> `docs/<topic>.md`; "
            "approach correction -> auto-memory or CLAUDE.md delta; "
            "one-off -> pass."
        )

    # Signal C: correction phrase in user turn immediately after assistant turn
    prev_was_assistant = False
    for r in records:
        typ = r.get("type")
        if typ == "assistant":
            prev_was_assistant = True
            continue
        if typ == "user":
            if prev_was_assistant:
                txt = text_of(r.get("message", {})).replace("\n", " ").strip()
                if txt and len(txt) <= CORRECTION_MAXLEN and CORRECTION_RE.search(txt):
                    signals.append("user-correction")
                    parts.append(
                        "[C] user corrected approach. "
                        "Preference/style -> auto-memory; "
                        "workflow misunderstanding -> `skill-creator` improvement; "
                        "else -> pass."
                    )
                    break
            prev_was_assistant = False

    return signals, parts


def main():
    inp = read_input()

    # Guard 1: prevent infinite re-invocation
    if inp.get("stop_hook_active"):
        sys.exit(0)

    # Guard 2: session-once marker
    session_id = inp.get("session_id", "")
    if not session_id:
        sys.exit(0)

    config_dir = (
        os.environ.get("CLAUDE_CONFIG_DIR")
        or os.path.expanduser("~/.claude")
    )
    marker_dir = os.path.join(config_dir, "tmp", "nudge-markers")
    os.makedirs(marker_dir, exist_ok=True)

    # Guard 2a: session-once marker
    marker = os.path.join(marker_dir, f"{session_id}.nudged")
    if os.path.exists(marker):
        sys.exit(0)

    # Guard 2b: cross-session throttle — don't fire more than once per THROTTLE_HOURS
    import time
    state_path = os.path.join(marker_dir, ".state.json")
    state = load_state(state_path)
    now = time.time()
    last_fired = state.get("lastFiredTs", 0)
    if now - last_fired < THROTTLE_HOURS * 3600:
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

    # Mark fired before output so a crash in print doesn't re-fire
    try:
        open(marker, "w").close()
    except Exception:
        pass
    state["lastFiredTs"] = now
    save_state(state_path, state)

    signal_list = ", ".join(signals)
    lines = [
        f"[self-improve-nudge] Signals: {signal_list}.",
        "Apply §Harness ratchet §Write-back gate — capture what passed an objective check, then stop normally.",
        "",
    ] + parts + ["", "Then stop normally."]

    print(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


try:
    main()
except Exception:
    sys.exit(0)
