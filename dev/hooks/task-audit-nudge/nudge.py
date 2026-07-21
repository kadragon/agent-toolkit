#!/usr/bin/env python3
"""task-audit-nudge — SessionStart staleness reminder.

Honest B-tier automation: does NOT detect "X done 5x" (that needs per-session
LLM clustering, which the on-demand harness-curate skill deliberately avoids).
Instead it tracks two staleness signals and emits a one-line nudge when either fires:
  1. Analysis-stale: curator hasn't run in >STALE_DAYS AND at least MIN_NEW_SESSIONS
     sessions have accumulated since the last run (or ever, if never run). Elapsed
     time alone does not fire this — a project reopened after a long dormant
     stretch with few/no new sessions has nothing new worth analyzing, so it must
     not nag just because the clock ran out.
  2. Candidates-pending: curator ran and produced recommendations that haven't been
     acted on or refreshed in >STALE_DAYS (lastCandidateMs is set by the skill's
     Step 6 when HARNESS_PENDING=1, cleared when HARNESS_PENDING=0/unset). This one
     is time-only by design — unactioned recommendations don't need fresh sessions
     to still be worth a reminder.

False-positive accepted: if the user acts on candidates without re-running, lastCandidateMs
stays set — the message instructs them to "act on them OR re-run to refresh," which
self-corrects on next curator run.

State:
  Claude: $CLAUDE_CONFIG_DIR/projects/<resolved-cwd-dir>/.harness-curator-state.json
  Codex:  $CODEX_HOME/projects/<resolved-cwd-dir>/.harness-curator-state.json
  Per-project isolation: running the audit in project A no longer suppresses
  nudges for project B. resolve_state_dir() mirrors scan_transcripts.py's
  resolve_project_dir() (exact-match dir if it holds *.jsonl, else the fuzzy
  case/underscore-drift sibling with the most jsonl files) so this always reads
  the SAME dir harness-curate's Step 6 wrote lastRunMs/lastCandidateMs into.
  lastRunMs       - written by the harness-curate skill's Step 6
  lastCandidateMs - written by Step 6 when HARNESS_PENDING=1, cleared when 0
  lastNudgeMs     - written here, throttles the nudge to once per THROTTLE window

  New-session counting differs by platform: for Claude, the resolved state_dir IS the
  project's real transcript directory, so counting *.jsonl there directly works
  (_new_session_count). For Codex, state_dir is ONLY this hook's own bookkeeping
  location — real sessions live under $CODEX_HOME/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl
  (date-partitioned, matched by each file's session_meta.cwd), so a separate counter
  (_codex_new_session_count) is required. Using the Claude-side counter under Codex
  would always return 0 and permanently suppress analysis_stale regardless of real
  activity — caught by review before shipping; see config_dir()'s is_codex flag.

Never raises - a reminder must never block session start.
"""

import glob
import json
import os
import re
import sys
import time

DAY_MS = 86_400_000
STALE_DAYS = 7         # nudge once audit is older than this
THROTTLE_MS = DAY_MS   # at most one nudge per 24h, even while stale
MIN_NEW_SESSIONS = 3   # need this many sessions since lastRunMs before "stale" fires —
                       # a dormant project reopened after a long break has 0 new sessions;
                       # elapsed time alone must not nag when there's nothing new to analyze


def encode_project(path):
    path = os.path.normcase(os.path.abspath(path))
    return re.sub(r"[/.:\\]", "-", path)


def _loose_key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _jsonl_count(d):
    try:
        return len(glob.glob(os.path.join(d, "*.jsonl")))
    except OSError:
        return 0


def _new_session_count(d, since_ms):
    """Count *.jsonl files modified after since_ms (0 = count all, i.e. never run).

    Only valid when real session transcripts live directly in `d` — true for Claude
    (`d` IS the project's transcript dir) but NOT for Codex, where `d` is purely this
    hook's own state-bookkeeping directory and real sessions live elsewhere entirely
    (date-partitioned under <codex_home>/sessions/, matched by session_meta.cwd — see
    _codex_new_session_count). Calling this on a Codex state dir always returns 0 and
    permanently suppresses the nudge, regardless of real activity — use the Codex
    variant when running under Codex.
    """
    try:
        files = glob.glob(os.path.join(d, "*.jsonl"))
    except OSError:
        return 0
    count = 0
    for f in files:
        try:
            if os.path.getmtime(f) * 1000 > since_ms:
                count += 1
        except OSError:
            continue
    return count


def _codex_new_session_count(codex_home, since_ms, cwd):
    """Codex equivalent of _new_session_count. Real session files live under
    <codex_home>/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl (date-partitioned, not
    project-partitioned), so a file only counts if BOTH its mtime is newer than
    since_ms AND its leading session_meta.payload.cwd matches this project — mirrors
    scan_transcripts.py's find_codex_session_files(). The mtime check runs first (cheap
    stat, filters out the vast majority) before opening/reading any file's content."""
    root = os.path.join(codex_home, "sessions")
    if not os.path.isdir(root):
        return 0
    target = os.path.normcase(os.path.abspath(cwd))
    count = 0
    for fp in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(fp) * 1000 <= since_ms:
                continue
        except OSError:
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                for _, line in zip(range(5), fh):
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if r.get("type") == "session_meta":
                        payload = r.get("payload")
                        session_cwd = payload.get("cwd") if isinstance(payload, dict) else None
                        if session_cwd and os.path.normcase(os.path.abspath(session_cwd)) == target:
                            count += 1
                        break
        except OSError:
            continue
    return count


def resolve_state_dir(cwd, proj_root):
    """Mirror scan_transcripts.py's resolve_project_dir so this nudge reads/writes
    state at the SAME dir harness-curate's Step 6 uses — otherwise a curator run
    that resolves to a fuzzy sibling (exact dir empty of *.jsonl) leaves this nudge
    reading a stale/empty exact dir forever, nagging even right after a real run."""
    exact = os.path.join(proj_root, encode_project(cwd))
    exact_count = _jsonl_count(exact) if os.path.isdir(exact) else -1
    if exact_count > 0:
        return exact
    if not os.path.isdir(proj_root):
        return exact
    target_key = _loose_key(encode_project(cwd))
    best, best_count = None, exact_count
    for n in os.listdir(proj_root):
        d = os.path.join(proj_root, n)
        if not os.path.isdir(d) or _loose_key(n) != target_key:
            continue
        count = _jsonl_count(d)
        if count > best_count:
            best, best_count = d, count
    return best if best is not None else exact


def config_dir():
    """(dir, is_codex). is_codex tells the caller which session-counting strategy applies
    — Claude's real sessions live in `dir`'s own projects tree, Codex's don't (see
    _codex_new_session_count)."""
    if os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), False
    if os.environ.get("CODEX_HOME"):
        return os.environ["CODEX_HOME"], True

    script_path = os.path.realpath(__file__)
    if "/.codex/" in script_path:
        return os.path.expanduser("~/.codex"), True
    return os.path.expanduser("~/.claude"), False


def main():
    cwd = os.getcwd()
    cdir, is_codex = config_dir()
    proj_root = os.path.join(cdir, "projects")
    state_dir = resolve_state_dir(cwd, proj_root)
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

    last_run_ms = state.get("lastRunMs") or 0
    new_sessions = (_codex_new_session_count(cdir, last_run_ms, cwd) if is_codex
                    else _new_session_count(state_dir, last_run_ms))
    analysis_stale = stale_ms > STALE_DAYS * DAY_MS and new_sessions >= MIN_NEW_SESSIONS
    candidates_pending = candidate_age_ms is not None and candidate_age_ms >= STALE_DAYS * DAY_MS

    if (not analysis_stale and not candidates_pending) or since_nudge <= THROTTLE_MS:
        return

    if candidates_pending and candidate_age_ms is not None:
        days = candidate_age_ms // DAY_MS
        msg = (
            f"HARNESS-CURATOR REMINDER: harness candidates were surfaced {days}d ago "
            "and have not been acted on or refreshed. "
            "At the start of your next reply, mention this to the user in one sentence — "
            "suggest they act on the top recommendation or re-run `harness-curate` to "
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
            "next reply, then continue the user's task: suggest invoking the `harness-curate` "
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
