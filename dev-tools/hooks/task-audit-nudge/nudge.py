#!/usr/bin/env python3
"""task-audit-nudge — Claude Code SessionStart staleness reminder.

Honest B-tier automation: does NOT detect "X done 5x" (that needs per-session
LLM clustering, which the on-demand /dev-tools:task-audit deliberately avoids).
Instead it tracks how long since the audit last ran and emits a one-line nudge
when stale. The audit itself still does all analysis on demand.

State: $CLAUDE_CONFIG_DIR/.task-audit-state.json  { lastRunMs, lastNudgeMs }
  lastRunMs   - written by the /dev-tools:task-audit command's final step
  lastNudgeMs - written here, throttles the nudge to once per THROTTLE window

Never raises - a reminder must never block session start.
"""

import json
import os
import sys
import time

DAY_MS = 86_400_000
STALE_DAYS = 7         # nudge once audit is older than this
THROTTLE_MS = DAY_MS   # at most one nudge per 24h, even while stale


def main():
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    state_path = os.path.join(config_dir, ".task-audit-state.json")
    now = int(time.time() * 1000)

    state = {"lastRunMs": 0, "lastNudgeMs": 0}
    try:
        with open(state_path, encoding="utf-8") as f:
            state.update(json.load(f))
    except Exception:
        pass

    stale_ms = now - (state.get("lastRunMs") or 0)
    since_nudge = now - (state.get("lastNudgeMs") or 0)

    if stale_ms <= STALE_DAYS * DAY_MS or since_nudge <= THROTTLE_MS:
        sys.stdout.write("OK")   # fresh enough, or already nudged recently
        return

    never = not state.get("lastRunMs")
    days = stale_ms // DAY_MS
    age = "has never run" if never else f"last ran {days}d ago"

    # Persist throttle stamp.
    try:
        state["lastNudgeMs"] = now
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

    sys.stdout.write(
        f"TASK-AUDIT REMINDER: /dev-tools:task-audit {age} (>{STALE_DAYS}d stale). "
        "Recurring inline work accumulates in ~/.claude/history.jsonl across sessions but is only "
        "surfaced when the audit runs. If a natural pause comes up, suggest the user run "
        "`/dev-tools:task-audit` (current project) or `/dev-tools:task-audit all` to catch work that "
        "should become an agent/skill/hook. Do not interrupt active work to do this."
    )


try:
    main()
except Exception:
    sys.stdout.write("OK")   # any failure -> silent, never block startup
sys.exit(0)
