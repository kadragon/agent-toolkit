#!/usr/bin/env python3
"""scan_transcripts.py — bounded per-project transcript scan for harness-curator.

Reads Claude Code session transcripts (~/.claude/projects/<encoded>/*.jsonl) and
emits a COMPACT, BOUNDED summary the model then clusters and routes. Deterministic
extraction here; clustering / judgment stays with the model (same split as the old
task-audit command).

Unlike history.jsonl (prompts only), transcripts also carry:
  - attributionSkill : which skill was active on each assistant record (skill-load signal)
  - user corrections : short negative follow-ups right after a skill-active turn
These power the triggering-miss / underperforming-asset / demote signals.

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
import shlex
import sys

# ---- caps (bounded output) ----
PROMPT_CAP = 250        # prompts shown per project (most recent kept)
CORRECTION_CAP = 40     # correction samples per project
PROJECT_CAP = 25        # projects shown in `all` scope (busiest kept)

NOISE = {"hi", "ok", "okay", "yes", "no", "go", "go on", "continue", "next",
         "thanks", "ty", "y", "n", "do it", "yep", "nope", "sure", "stop",
         "wait", "done", "more", "again", "yeah", "k"}

# short user follow-up matching these right after a skill-active turn = correction
CORRECTION_RE = re.compile(
    r"\b(no|wrong|not what|actually|undo|revert|that'?s not|don'?t|nope|incorrect|"
    r"아니|그게 아니|다시|틀렸|잘못|되돌려|아닌데|왜)\b",
    re.IGNORECASE,
)


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
    skill_sessions = collections.defaultdict(set)   # skill -> {session files}
    sessions = 0

    for fp in files:
        sessions += 1
        last_skill = None                # skill active on the most recent assistant turn
        try:
            fh = open(fp, encoding="utf-8")
        except OSError:
            continue
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
                    continue

                if typ == "user":
                    txt = text_of(r.get("message")).replace("\n", " ").strip()
                    if not txt:
                        continue
                    if last_skill and len(txt) < 80 and CORRECTION_RE.search(txt):
                        corrections.append((last_skill, txt[:160]))
                    last_skill = None    # reset after any real user turn
                    if keep_prompt(txt):
                        prompts.append((ts, txt[:200]))

    prompts.sort(key=lambda x: x[0])
    return {
        "label": label,
        "sessions": sessions,
        "prompts": prompts,
        "skill_sessions": {k: len(v) for k, v in skill_sessions.items()},
        "corrections": corrections,
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

    corr = summary["corrections"]
    if corr:
        show = corr[:CORRECTION_CAP]
        cdropped = len(corr) - len(show)
        print("\nCORRECTION-SIGNALS (skill-active then user pushed back — underperform candidate):"
              + (f"  [dropped {cdropped}]" if cdropped else ""))
        for skill, txt in show:
            print(f"  [{skill}] {txt}")

    print("\nPROMPTS (cluster these by intent):")
    for _, txt in shown:
        print("- " + txt)


def main():
    args = shlex.split(sys.argv[1]) if len(sys.argv) > 1 else []   # robust to paths with spaces
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
