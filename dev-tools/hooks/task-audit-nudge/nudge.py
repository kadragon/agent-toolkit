#!/usr/bin/env python3
"""task-audit-nudge — SessionStart staleness reminder.

Honest B-tier automation: does NOT detect "X done 5x" (that needs per-session
LLM clustering, which the on-demand harness-curator skill deliberately avoids).
Instead it tracks two staleness signals and emits a one-line nudge when either fires:
  1. Analysis-stale: curator hasn't run in >STALE_DAYS
  2. Candidates-pending: curator ran and produced recommendations that haven't been
     acted on or refreshed in >STALE_DAYS (lastCandidateMs is set by the skill's
     Step 6 when HARNESS_PENDING=1, cleared when HARNESS_PENDING=0/unset)

False-positive accepted: if the user acts on candidates without re-running, lastCandidateMs
stays set — the message instructs them to "act on them OR re-run to refresh," which
self-corrects on next curator run.

State:
  Claude: $CLAUDE_CONFIG_DIR/projects/<encoded-cwd>/.harness-curator-state.json
  Codex:  $CODEX_HOME/projects/<encoded-cwd>/.harness-curator-state.json
  Per-project isolation: running the audit in project A no longer suppresses
  nudges for project B. Encoded path mirrors the transcript directory layout.
  lastRunMs       - written by the harness-curator skill's Step 6
  lastCandidateMs - written by Step 6 when HARNESS_PENDING=1, cleared when 0
  lastNudgeMs     - written here, throttles the nudge to once per THROTTLE window

Never raises - a reminder must never block session start.
"""

import json
import os
import re
import sys
import time

DAY_MS = 86_400_000
STALE_DAYS = 7         # nudge once audit is older than this
THROTTLE_MS = DAY_MS   # at most one nudge per 24h, even while stale


def encode_project(path):
    path = os.path.normcase(os.path.abspath(path))
    return re.sub(r"[/.:\\]", "-", path)


def config_dir():
    if os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    if os.environ.get("CODEX_HOME"):
        return os.environ["CODEX_HOME"]

    script_path = os.path.realpath(__file__)
    if "/.codex/" in script_path:
        return os.path.expanduser("~/.codex")
    return os.path.expanduser("~/.claude")


def main():
    cwd = os.getcwd()
    state_dir = os.path.join(config_dir(), "projects", encode_project(cwd))
    state_path = os.path.join(state_dir, ".harness-curator-state.json")
    now = int(time.time() * 1000)

    state = {"lastRunMs": 0, "lastNudgeMs": 0}
    try:
        with open(state_path, encoding="utf-8") as f:
            state.update(json.load(f))
    except Exception:
        pass

    stale_ms = now - (state.get("lastRunMs") or 0)
    since_nudge = now - (state.get("lastNudgeMs") or 0)
    last_candidate_ms = state.get("lastCandidateMs") or 0
    candidate_age_ms = (now - last_candidate_ms) if last_candidate_ms else None

    analysis_stale = stale_ms > STALE_DAYS * DAY_MS
    candidates_pending = candidate_age_ms is not None and candidate_age_ms >= STALE_DAYS * DAY_MS

    if (not analysis_stale and not candidates_pending) or since_nudge <= THROTTLE_MS:
        return

    if candidates_pending and candidate_age_ms is not None:
        days = candidate_age_ms // DAY_MS
        msg = (
            f"HARNESS-CURATOR REMINDER: harness candidates were surfaced {days}d ago "
            "and have not been acted on or refreshed. "
            "At the start of your next reply, mention this to the user in one sentence — "
            "suggest they act on the top recommendation or re-run `harness-curator` to "
            "refresh — then continue their task."
        )
    else:
        never = not state.get("lastRunMs")
        days = stale_ms // DAY_MS
        age = "has never run" if never else f"last ran {days}d ago"
        msg = (
            f"HARNESS-CURATOR REMINDER: harness analysis {age} (>{STALE_DAYS}d stale). "
            "Recurring inline work and skill misfires accumulate across sessions but are only "
            "surfaced when the analysis runs. Surface this once, briefly, at the start of your "
            "next reply, then continue the user's task: suggest invoking the `harness-curator` "
            "skill (current project, or 'all' scope) to catch work that should become an "
            "agent/skill/hook, skills that aren't triggering, or assets to retire."
        )

    # Persist throttle stamp.
    try:
        os.makedirs(state_dir, exist_ok=True)
        state["lastNudgeMs"] = now
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

    sys.stdout.write(msg)


try:
    main()
except Exception:
    pass   # any failure -> silent, never block startup
sys.exit(0)
