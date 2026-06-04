#!/usr/bin/env python3
"""scan_transcripts.py — bounded per-project transcript scan for harness-curator.

Reads Claude Code session transcripts (~/.claude/projects/<encoded>/*.jsonl) and
emits a COMPACT, BOUNDED summary the model then clusters and routes. Deterministic
extraction here; clustering / judgment stays with the model (same split as the old
task-audit command).

Unlike history.jsonl (prompts only), transcripts also carry:
  - attributionSkill : which skill was active on each assistant record (skill-load signal)
  - Agent/Task tool_use : which subagent_type the main thread invoked (agent-use signal)
  - user corrections : short negative follow-ups right after a skill- or agent-active turn
These power the triggering-miss / underperforming-asset / demote signals for BOTH
skills and agents — an installed agent with ~0 invocations is a demote candidate just
like an unused skill.

Scope (mirrors the old command):
  (empty)            current cwd project
  all                every project
  --project <path>   one named project (absolute path, pre-encoding)

Caps are enforced and dropped counts printed — never silently truncate.
Never raises on a malformed line; a bad record is skipped.
"""

import collections
import glob
import json
import os
import re
import sys

# ---- caps (bounded output) ----
PROMPT_CAP = 250        # prompts shown per project (most recent kept)
CORRECTION_CAP = 40     # correction samples per project
PROJECT_CAP = 25        # projects shown in `all` scope (busiest kept)

NOISE = {"hi", "ok", "okay", "yes", "no", "go", "go on", "continue", "next",
         "thanks", "ty", "y", "n", "do it", "yep", "nope", "sure", "stop",
         "wait", "done", "more", "again", "yeah", "k"}

# short user follow-up matching this right after a skill-active turn = correction.
# English: anchor weak words (no/stop) to message start and avoid bare \bactually\b —
# "no worries", "actually perfect" are positive follow-ups, not corrections.
# Korean: substring match (no \b) — \b does not fire between Hangul syllable + 조사
# ("아니야", "틀렸어"), so word-boundary anchoring would miss real corrections.
CORRECTION_RE = re.compile(
    r"^(no|nope|nah)\b(?![ ]\w)"                       # leading "no" — not "no worries"/"no problem"
    r"|\b(wrong|undo|revert|incorrect|not what|that'?s not|don'?t)\b"
    r"|(아니|그게 아니|아닌데|다시|틀렸|잘못|되돌려)",
    re.IGNORECASE,
)
CORRECTION_MAXLEN = 50   # a real correction is short; longer text is usually a new task


def encode_project(path):
    """Map an absolute project path to its transcript dir name: '/' and '.' -> '-'."""
    return re.sub(r"[/.]", "-", path)


def keep_prompt(d):
    d = (d or "").strip()
    if not d:
        return False
    if d.startswith("/") or d.startswith("!"):   # slash command / shell passthrough
        return False
    # harness-injected blocks rendered into the user turn (not real prompts)
    if re.match(r"<(command-message|command-name|task-notification|local-command|"
                r"system-reminder|user-prompt-submit-hook)", d):
        return False
    low = d.lower()
    if low in NOISE:
        return False
    # Korean is dense — "스킬 만들어줘" (7 chars, 2 words) is a real request. Exempt
    # Hangul-bearing text from the English short-prompt filter; drop only ultra-short.
    if any(0xAC00 <= ord(c) <= 0xD7A3 for c in d):
        return len(d) >= 5
    if len(d) < 12 and len(d.split()) < 3:
        return False
    return True


def text_of(message):
    """Extract plain user text from a message; '' if it is a tool_result / non-text."""
    if not isinstance(message, dict):
        return ""
    c = message.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict):
                if b.get("type") == "tool_result":
                    return ""            # tool output echoed as user role — not a prompt
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
        return " ".join(parts)
    return ""


def scan_dir(tdir, label):
    """Scan one transcript dir. Return a summary dict, or None if it has no .jsonl."""
    files = sorted(glob.glob(os.path.join(tdir, "*.jsonl")))
    if not files:
        return None

    prompts = []                                    # (ts, text)
    corrections = []                                # (skill_active, text)
    agent_corrections = []                          # (agent_active, text)
    skill_sessions = collections.defaultdict(set)   # skill -> {session files}
    agent_sessions = collections.defaultdict(set)   # subagent_type -> {session files}
    sessions = 0

    for fp in files:
        last_skill = None                # skill active on the most recent assistant turn
        last_agent = None                # subagent_type invoked on the most recent assistant turn
        try:
            fh = open(fp, encoding="utf-8")
        except OSError:
            continue                     # unreadable file is not a counted session
        sessions += 1
        with fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("isMeta") or r.get("isSidechain"):
                    continue
                typ, ts = r.get("type"), r.get("timestamp", 0)

                if typ == "assistant":
                    a = r.get("attributionSkill")
                    if a:
                        skill_sessions[a].add(fp)
                        last_skill = a
                    # Agent/Task tool_use carries the subagent_type the main thread
                    # delegated to. The subagent's own turns are isSidechain (skipped
                    # above), so this main-chain tool_use is the only agent-use record.
                    msg = r.get("message")
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if isinstance(content, list):
                        for b in content:
                            if (isinstance(b, dict) and b.get("type") == "tool_use"
                                    and b.get("name") in ("Agent", "Task")):
                                st = (b.get("input") or {}).get("subagent_type")
                                if st:
                                    agent_sessions[st].add(fp)
                                    last_agent = st
                    continue

                if typ == "user":
                    txt = text_of(r.get("message")).replace("\n", " ").strip()
                    if not txt:
                        continue
                    if len(txt) < CORRECTION_MAXLEN and CORRECTION_RE.search(txt):
                        if last_skill:
                            corrections.append((last_skill, txt[:160]))
                        if last_agent:
                            agent_corrections.append((last_agent, txt[:160]))
                    last_skill = None    # reset after any real user turn
                    last_agent = None
                    if keep_prompt(txt):
                        prompts.append((ts, txt[:200]))

    prompts.sort(key=lambda x: x[0])
    return {
        "label": label,
        "sessions": sessions,
        "prompts": prompts,
        "skill_sessions": {k: len(v) for k, v in skill_sessions.items()},
        "agent_sessions": {k: len(v) for k, v in agent_sessions.items()},
        "corrections": corrections,
        "agent_corrections": agent_corrections,
    }


def emit(summary):
    prompts = summary["prompts"]
    total = len(prompts)
    shown = prompts[-PROMPT_CAP:]
    dropped = total - len(shown)
    print(f"\n### PROJECT {summary['label']}")
    print(f"sessions={summary['sessions']}  prompts_kept={total}"
          + (f"  showing_latest={PROMPT_CAP}  dropped_older={dropped}" if dropped else ""))

    sk = summary["skill_sessions"]
    if sk:
        print("\nSKILLS-ACTIVE (skill: sessions-used — low count near asset = demote candidate):")
        for name, n in sorted(sk.items(), key=lambda x: -x[1]):
            print(f"  {name}: {n}")
    else:
        print("\nSKILLS-ACTIVE: (none recorded)")

    ag = summary["agent_sessions"]
    if ag:
        print("\nAGENTS-USED (subagent_type: sessions-invoked — installed agent near 0 = demote candidate):")
        for name, n in sorted(ag.items(), key=lambda x: -x[1]):
            print(f"  {name}: {n}")
    else:
        print("\nAGENTS-USED: (none recorded)")

    corr = summary["corrections"]
    if corr:
        show = corr[:CORRECTION_CAP]
        cdropped = len(corr) - len(show)
        print("\nCORRECTION-SIGNALS (skill-active then user pushed back — underperform candidate):"
              + (f"  [dropped {cdropped}]" if cdropped else ""))
        for skill, txt in show:
            print(f"  [{skill}] {txt}")

    acorr = summary["agent_corrections"]
    if acorr:
        show = acorr[:CORRECTION_CAP]
        adropped = len(acorr) - len(show)
        print("\nAGENT-CORRECTION-SIGNALS (agent invoked then user pushed back — underperform candidate):"
              + (f"  [dropped {adropped}]" if adropped else ""))
        for agent, txt in show:
            print(f"  [{agent}] {txt}")

    print("\nPROMPTS (cluster these by intent):")
    for _, txt in shown:
        print("- " + txt)


def main():
    args = sys.argv[1:]    # caller passes scope tokens directly; quote paths with spaces
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    proj_root = os.path.join(config_dir, "projects")

    if "--project" in args:
        i = args.index("--project")
        if i + 1 >= len(args):
            print("--project requires an absolute path")
            sys.exit(2)
        path = args[i + 1]
        scope, dirs = "named", [(os.path.join(proj_root, encode_project(path)), path)]
    elif "all" in args:
        if not os.path.isdir(proj_root):
            print(f"No projects dir at {proj_root} — nothing to scan.")
            sys.exit(0)
        scope = "all"
        dirs = [(os.path.join(proj_root, n), n)
                for n in sorted(os.listdir(proj_root))
                if os.path.isdir(os.path.join(proj_root, n))]
    else:
        cwd = os.getcwd()
        scope, dirs = "current", [(os.path.join(proj_root, encode_project(cwd)), cwd)]

    summaries = [s for s in (scan_dir(d, label) for d, label in dirs) if s and s["prompts"]]
    if not summaries:
        print(f"NO TRANSCRIPT DATA for scope={scope} (looked in {proj_root}).")
        if scope != "all":
            print("Try scanning all projects: scope 'all'")
        sys.exit(0)

    summaries.sort(key=lambda s: -len(s["prompts"]))
    total_p = len(summaries)
    shown = summaries[:PROJECT_CAP] if scope == "all" else summaries
    header = f"SCOPE={scope}  projects_with_data={total_p}"
    if scope == "all" and total_p > len(shown):
        header += f"  showing_busiest={PROJECT_CAP}  dropped={total_p - len(shown)}"
    print(header)
    for s in shown:
        emit(s)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"scan failed: {e}")
        sys.exit(1)
