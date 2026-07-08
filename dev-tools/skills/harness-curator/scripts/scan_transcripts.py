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
  - harness-friction : recurring-behavior complaints (FRICTION_RE) — over-protection signal
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
FRICTION_CAP = 30       # harness-friction samples per project
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

# Harness-friction (over-protection) signal: the user complaining about a RECURRING
# imposed behavior — typically a hook or a CLAUDE.md rule that fires too often or
# blocks them. Distinct from a task correction: it targets the harness itself, not
# the answer. Anchored to recurrence-complaint phrasing ("you keep", "every time",
# "자꾸", "매번") so it does not fire on a one-off "stop". These have no
# attributionSkill (hooks/rules don't carry one), so they're collected standalone;
# the model judges which rule/hook each maps to and routes to loosen/demote.
# Over-collects: "every time it crashes" (task complaint) also passes — the model
# MUST read samples before routing (see signal-taxonomy.md §5). Korean alternation
# assumes txt has been newline-stripped upstream (text_of → .replace("\n", " ")).
FRICTION_RE = re.compile(
    r"\b(you keep|you always|every ?time|each time|"
    r"stop (doing|asking|adding|using|inserting|reminding)|"
    r"turn (this|that|it) off|disable (this|that|it|the)|"
    r"why do you (keep|always))\b"
    r"|(자꾸|매번|왜.{0,4}자꾸|비활성|끄(자|고|는|자고|다|기)|꺼(줘|라)?)"
    r"|(역치|임계값|threshold).{0,6}(높|낮|조정)"
    r"|너무.{0,4}민감",
    re.IGNORECASE,
)
FRICTION_MAXLEN = 120    # complaints run a little longer than bare corrections


def encode_project(path):
    """Map a project path to its transcript dir name: '/', '.', '\\', ':' -> '-'.

    Normalizes to an absolute, case-folded path first so Windows drive-letter
    case differences (`C:` vs `c:`) don't fragment state across sessions.
    """
    path = os.path.normcase(os.path.abspath(path))
    return re.sub(r"[/.:\\]", "-", path)


def _loose_key(name):
    """Case/underscore/hyphen-insensitive key for fuzzy-matching an encoded dir name.

    Claude Code's own project-dir naming has drifted across versions (e.g. some
    transcripts landed under 'C--Dev-workspace-knue-patis', others under
    'c--dev-workspace_knue-patis' for the SAME repo) — different case and different
    treatment of '_' vs '-'. encode_project() only produces one exact candidate, so
    an exact-match lookup silently misses real data sitting under a sibling encoding.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _jsonl_count(d):
    try:
        return len(glob.glob(os.path.join(d, "*.jsonl")))
    except OSError:
        return 0


def resolve_project_dir(path, proj_root):
    """Find the transcript dir for `path`, tolerating the case/separator drift above.

    Prefers an exact encode_project() match, but only when it actually holds
    transcripts — a directory can exist with zero *.jsonl files (e.g. created solely
    by this skill's own Step 6 state-file write, which uses a raw, non-normcased
    substitution that can diverge from encode_project() and spuriously "claim" the
    exact-match slot). When the exact dir has no jsonl data, scan proj_root for
    directories whose loose key matches and pick whichever (exact or fuzzy sibling)
    has the most *.jsonl files. Falls back to the exact (possibly nonexistent) path
    so downstream 'no data' reporting is unchanged when truly nothing matches.
    """
    exact = os.path.join(proj_root, encode_project(path))
    exact_count = _jsonl_count(exact) if os.path.isdir(exact) else -1
    if exact_count > 0:
        return exact
    if not os.path.isdir(proj_root):
        return exact
    target_key = _loose_key(encode_project(path))
    best, best_count = None, exact_count
    for n in os.listdir(proj_root):
        d = os.path.join(proj_root, n)
        if not os.path.isdir(d) or _loose_key(n) != target_key:
            continue
        count = _jsonl_count(d)
        if count > best_count:
            best, best_count = d, count
    return best if best is not None else exact


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
    frictions = []                                  # (text) — harness over-protection complaints
    skill_sessions = collections.defaultdict(set)   # skill -> {session files}
    agent_sessions = collections.defaultdict(set)   # subagent_type -> {session files}
    sessions = 0

    for fp in files:
        last_skill = None                # skill active on the most recent assistant turn
        last_agents = set()              # subagent_types invoked since the last user turn
        frictions_seen = set()           # deduplicate friction phrases within a session
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
                                    last_agents.add(st)
                    continue

                if typ == "user":
                    txt = text_of(r.get("message")).replace("\n", " ").strip()
                    if not txt:
                        continue
                    if len(txt) < CORRECTION_MAXLEN and CORRECTION_RE.search(txt):
                        if last_skill:
                            corrections.append((last_skill, txt[:160]))
                        # Credit every distinct subagent type invoked since the last
                        # user turn — one turn can spawn many (the set dedups repeats
                        # of the same type), so a scalar would misattribute to whichever
                        # block happened to be last.
                        for st in last_agents:
                            agent_corrections.append((st, txt[:160]))
                    # Harness-friction is orthogonal to skill/agent attribution — a
                    # complaint about a hook or rule, captured wherever it appears.
                    if len(txt) <= FRICTION_MAXLEN and FRICTION_RE.search(txt) and txt not in frictions_seen:
                        frictions_seen.add(txt)
                        frictions.append(txt)
                    last_skill = None    # reset after any real user turn
                    last_agents = set()
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
        "frictions": frictions,
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

    fric = summary["frictions"]
    if fric:
        show = fric[:FRICTION_CAP]
        fdropped = len(fric) - len(show)
        print("\nHARNESS-FRICTION (recurring-behavior complaint — inspect: a hook/rule firing"
              " too often = over-protection/demote candidate; ≥2 = signal. May also be a task"
              " complaint — read before routing):"
              + (f"  [dropped {fdropped}]" if fdropped else ""))
        for txt in show:
            print(f"  {txt}")

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
        scope, dirs = "named", [(resolve_project_dir(path, proj_root), path)]
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
        scope, dirs = "current", [(resolve_project_dir(cwd, proj_root), cwd)]

    summaries = [s for s in (scan_dir(d, label) for d, label in dirs) if s and (s["prompts"] or s["frictions"] or s["corrections"])]
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
