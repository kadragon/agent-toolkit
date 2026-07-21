#!/usr/bin/env python3
"""scan_transcripts.py — bounded per-project transcript scan for harness-curate.

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
  --full             also re-include prompts already covered by a prior run (see below)

Caps are enforced and dropped counts printed — never silently truncate.
Never raises on a malformed line; a bad record is skipped.

Also folds in Codex CLI sessions (~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl) for
the SAME project, so work done via either tool feeds one report. Codex's storage is
fundamentally different from Claude's — date-partitioned, not project-partitioned, with
the project path only recoverable by reading each file's session_meta.cwd — so:
  - Codex matching only runs for `current`/`--project` scope, where a real absolute path
    is known. `all` scope can't reverse Claude's encode_project() dir names back into a
    path to match Codex's cwd against, so it skips Codex entirely (documented, not silent).
  - `~/.codex/archived_sessions/` is excluded by design (retention overflow, not the
    working set) — only `~/.codex/sessions/` is scanned.
  - Codex has no dedicated attributionSkill-style field. Instead, when a skill loads it
    injects a synthetic role=user turn shaped like "<skill>\n<name>foo</name>\n<path>..."
    (confirmed by reading real session files before writing this) — parsed by
    _codex_turn_signal() to build CODEX-SKILLS-ACTIVE.
  - Codex's closest analog to Agent/Task delegation is `event_msg` records with
    payload.type == "sub_agent_activity" (payload.agent_path identifies the sub-task,
    payload.kind == "started" marks invocation) — used to build CODEX-AGENTS-USED.
  - Several other kinds of harness-injected content also arrive as synthetic role=user
    turns (environment context, review-request scaffolding, plugin recommendations, hook
    output, repeated AGENTS.md reinjection, subagent-completion notices) — filtered out of
    PROMPTS/CORRECTIONS/FRICTIONS by _CODEX_NOISE_RE, mirroring how keep_prompt() already
    filters Claude's <command-message>/<system-reminder>/etc.
"""

import collections
import datetime
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


def _iso_to_ms(ts):
    """Parse a transcript record's ISO-8601 timestamp (e.g. '2026-07-01T00:20:59.502Z')
    into epoch ms, to compare against lastRunMs (already epoch ms). 0 on parse failure
    so a malformed timestamp sorts as "very old" rather than crashing the scan."""
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000
    except Exception:
        return 0


def read_last_run_ms(tdir):
    """Read lastRunMs from this project's own .harness-curator-state.json (Step 6
    writes it there). 0 if absent/unreadable — treated as "never run", i.e. scan
    everything."""
    p = os.path.join(tdir, ".harness-curator-state.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("lastRunMs") or 0
    except Exception:
        return 0


def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def codex_state_dir(codex_root, real_path):
    """Codex has no project-keyed directory to hold this skill's own bookkeeping (session
    files are date-partitioned, not project-partitioned — see module docstring), so mint one
    under the SAME encode_project() scheme Claude's side already uses, purely for
    .harness-curator-state.json. This does not hold real Codex session data."""
    return os.path.join(codex_root, "projects", encode_project(real_path))


def _codex_session_meta_cwd(fp):
    """Read just the leading records of a Codex rollout file to find session_meta.payload.cwd.
    session_meta is normally the first line, but a few extra lines are tolerated in case a
    future format prepends something. None if not found/unreadable — never raises."""
    try:
        with open(fp, encoding="utf-8") as fh:
            for _, line in zip(range(5), fh):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("type") == "session_meta":
                    payload = r.get("payload")
                    return payload.get("cwd") if isinstance(payload, dict) else None
    except OSError:
        pass
    return None


def find_codex_session_files(codex_root, real_path):
    """*.jsonl under <codex_root>/sessions (archived_sessions excluded — see module
    docstring) whose session_meta.cwd matches real_path. Cheap because only the leading
    lines of each file are read (benchmarked at ~0.1s for 1400+ files), not the whole file."""
    root = os.path.join(codex_root, "sessions")
    if not os.path.isdir(root):
        return []
    target = os.path.normcase(os.path.abspath(real_path))
    matches = []
    for fp in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        cwd = _codex_session_meta_cwd(fp)
        if cwd and os.path.normcase(os.path.abspath(cwd)) == target:
            matches.append(fp)
    return matches


def _codex_message_text(payload):
    """Join a Codex response_item message's text blocks. User turns use 'input_text',
    assistant turns use 'output_text' — both are read the same way here."""
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    parts = [b.get("text", "") for b in content
             if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")]
    return " ".join(parts)


# Codex has no dedicated attributionSkill-style field. Instead, when a skill loads it
# injects a synthetic role=user turn shaped like "<skill>\n<name>foo</name>\n<path>...".
# Confirmed by reading real session files (found in ~/.codex/sessions, e.g. a `caveman`
# and a `dev:task-next` load) before writing this — do not assume this format is
# stable across Codex CLI versions; re-verify against real files if this stops matching.
_CODEX_SKILL_LOAD_RE = re.compile(r"^<skill>\s*<name>([^<]+)</name>", re.IGNORECASE)

# Several other kinds of harness-injected content also arrive as role=user turns rather
# than a separate field (unlike Claude, where this lives on the assistant side). None of
# these are free-text human intent, so they must not enter PROMPTS/CORRECTIONS/FRICTIONS —
# mirrors keep_prompt()'s Claude-side filtering of <command-message>/<system-reminder>/etc.
# Found by sampling ~400 real Codex session files; re-verify if new tag names appear.
_CODEX_NOISE_RE = re.compile(
    r"^<(environment_context|user_action|turn_aborted|recommended_plugins|image|"
    r"user_shell_command|hook_prompt|subagent_notification)\b"
    r"|^# AGENTS\.md instructions",
    re.IGNORECASE,
)


def _codex_turn_signal(txt):
    """Classify a Codex role=user turn's leading marker.

    Returns (kind, value):
      ("skill", name) — synthetic skill-load marker, Codex's analog of Claude's
          attributionSkill. Does NOT reset the correction-detection window (like Claude's
          attributionSkill, which lives on the assistant side and never resets it).
      ("noise", None) — harness-injected template (environment context, review-request
          scaffolding, plugin recommendations, hook output, repeated AGENTS.md reinjection,
          subagent-completion notices). DOES reset the window — a real user action (or
          Codex lifecycle event) occurred — but isn't itself prompt content, and isn't run
          through CORRECTION_RE/FRICTION_RE (it's templated, not human free text).
      (None, None) — an ordinary free-text user turn; caller applies the normal logic.
    """
    stripped = txt.lstrip()
    m = _CODEX_SKILL_LOAD_RE.match(stripped)
    if m:
        return "skill", m.group(1).strip()
    if _CODEX_NOISE_RE.match(stripped):
        return "noise", None
    return None, None


def scan_codex_files(files):
    """Parse matched Codex rollout files into a summary shaped like scan_dir()'s.
    skill_sessions comes from the synthetic <skill> turn marker (see _codex_turn_signal);
    agent_sessions comes from sub_agent_activity events instead of Claude's Agent/Task
    tool_use — Codex's agent_path is a task-thread id, not a named subagent_type."""
    prompts = []                                    # (ts, text)
    corrections = []                                # (skill, text)
    agent_corrections = []                          # (agent_path, text)
    frictions = []
    skill_sessions = collections.defaultdict(set)   # skill name -> {session files}
    agent_sessions = collections.defaultdict(set)   # agent_path -> {session files}
    sessions = 0

    for fp in files:
        last_skill = None
        last_agents = set()
        frictions_seen = set()
        try:
            fh = open(fp, encoding="utf-8")
        except OSError:
            continue
        sessions += 1
        with fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                typ = r.get("type")
                payload = r.get("payload")
                if not isinstance(payload, dict):
                    continue

                if typ == "event_msg" and payload.get("type") == "sub_agent_activity":
                    if payload.get("kind") == "started":
                        path = payload.get("agent_path")
                        if path:
                            agent_sessions[path].add(fp)
                            last_agents.add(path)
                    continue

                if typ != "response_item" or payload.get("type") != "message":
                    continue
                if payload.get("role") != "user":
                    continue     # assistant turns carry no attribution signal to key off
                txt = _codex_message_text(payload).replace("\n", " ").strip()
                if not txt:
                    continue

                kind, value = _codex_turn_signal(txt)
                if kind == "skill":
                    if value:
                        skill_sessions[value].add(fp)
                        last_skill = value
                    continue
                if kind == "noise":
                    last_skill = None
                    last_agents = set()
                    continue

                if len(txt) < CORRECTION_MAXLEN and CORRECTION_RE.search(txt):
                    if last_skill:
                        corrections.append((last_skill, txt[:160]))
                    for a in last_agents:
                        agent_corrections.append((a, txt[:160]))
                if len(txt) <= FRICTION_MAXLEN and FRICTION_RE.search(txt) and txt not in frictions_seen:
                    frictions_seen.add(txt)
                    frictions.append(txt)
                last_skill = None
                last_agents = set()
                if keep_prompt(txt):
                    prompts.append((r.get("timestamp", 0), txt[:200]))

    prompts.sort(key=lambda x: x[0])
    return {
        "sessions": sessions,
        "prompts": prompts,
        "skill_sessions": {k: len(v) for k, v in skill_sessions.items()},
        "agent_sessions": {k: len(v) for k, v in agent_sessions.items()},
        "corrections": corrections,
        "agent_corrections": agent_corrections,
        "frictions": frictions,
    }


def build_codex_summary(real_path, full):
    """None if no Codex sessions match this project (nothing to report)."""
    root = codex_home()
    files = find_codex_session_files(root, real_path)
    if not files:
        return None
    summary = scan_codex_files(files)
    summary["last_run_ms"] = 0 if full else read_last_run_ms(codex_state_dir(root, real_path))
    return summary


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
    """Scan one transcript dir. Return a summary dict, or None if it has no .jsonl.

    Scans every session file — SKILLS-ACTIVE / AGENTS-USED / CORRECTION-SIGNALS /
    HARNESS-FRICTION all need cumulative lifetime counts (a demote candidate is
    "~0 across all history", not "~0 since last run"), so file-level skipping
    would silently corrupt those signals. The PROMPTS section is filtered
    separately in main()/emit() to new-since-last-run — that's the part that
    otherwise makes the model re-cluster the same already-reported prompts run
    after run.
    """
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


def _split_new(prompts, last_run_ms):
    """(new_prompts, stale_count) — new_prompts is everything if last_run_ms is 0 (never
    run / --full), else only prompts newer than that checkpoint. Shared by the Claude and
    Codex emitters so both apply the same incremental-PROMPTS rule (see module docstring)."""
    if not last_run_ms:
        return prompts, 0
    new_prompts = [p for p in prompts if _iso_to_ms(p[0]) > last_run_ms]
    return new_prompts, len(prompts) - len(new_prompts)


def emit(summary):
    prompts = summary["prompts"]
    total = len(prompts)
    last_run_ms = summary.get("last_run_ms", 0)
    new_prompts, stale_count = _split_new(prompts, last_run_ms)
    shown = new_prompts[-PROMPT_CAP:]
    dropped = len(new_prompts) - len(shown)
    print(f"\n### PROJECT {summary['label']}")
    header = f"sessions={summary['sessions']}  prompts_total={total}"
    if last_run_ms:
        header += (f"  new_since_last_run={len(new_prompts)}"
                   f"  already_analyzed_suppressed={stale_count} (pass --full to include)")
    if dropped:
        header += f"  showing_latest={PROMPT_CAP}  dropped_older={dropped}"
    print(header)

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

    print("\nPROMPTS (cluster these by intent):" + (" [new since last run]" if last_run_ms else ""))
    if last_run_ms and not shown:
        print("  (none — nothing new since last curator run; pass --full to re-review full history)")
    for _, txt in shown:
        print("- " + txt)

    if summary.get("codex"):
        emit_codex(summary["codex"])


def emit_codex(codex):
    """Codex-sourced data for the same project, appended after the Claude-sourced report.
    Kept in clearly-prefixed CODEX-* sections rather than merged into the sections above —
    the two platforms' signals aren't directly comparable (see module docstring: skill
    detection relies on a synthetic turn marker instead of a field, agent_path isn't a
    named role like Claude's subagent_type)."""
    prompts = codex["prompts"]
    total = len(prompts)
    last_run_ms = codex.get("last_run_ms", 0)
    new_prompts, stale_count = _split_new(prompts, last_run_ms)
    shown = new_prompts[-PROMPT_CAP:]
    dropped = len(new_prompts) - len(shown)

    print("\n--- CODEX-SOURCED (~/.codex/sessions, matched by session_meta.cwd; "
          "archived_sessions excluded) ---")
    header = f"codex_sessions={codex['sessions']}  codex_prompts_total={total}"
    if last_run_ms:
        header += (f"  new_since_last_run={len(new_prompts)}"
                   f"  already_analyzed_suppressed={stale_count} (pass --full to include)")
    if dropped:
        header += f"  showing_latest={PROMPT_CAP}  dropped_older={dropped}"
    print(header)

    sk = codex["skill_sessions"]
    if sk:
        print("\nCODEX-SKILLS-ACTIVE (skill: sessions-used — from the synthetic <skill> "
              "load marker, Codex's analog of attributionSkill; low count near asset = "
              "demote candidate):")
        for name, n in sorted(sk.items(), key=lambda x: -x[1]):
            print(f"  {name}: {n}")
    else:
        print("\nCODEX-SKILLS-ACTIVE: (none recorded)")

    ag = codex["agent_sessions"]
    if ag:
        print("\nCODEX-AGENTS-USED (agent_path: sessions-invoked — agent_path is Codex's "
              "sub_agent_activity task identifier, not necessarily a named role):")
        for name, n in sorted(ag.items(), key=lambda x: -x[1]):
            print(f"  {name}: {n}")
    else:
        print("\nCODEX-AGENTS-USED: (none recorded)")

    corr = codex["corrections"]
    if corr:
        show = corr[:CORRECTION_CAP]
        cdropped = len(corr) - len(show)
        print("\nCODEX-CORRECTION-SIGNALS (skill-active then user pushed back — underperform candidate):"
              + (f"  [dropped {cdropped}]" if cdropped else ""))
        for skill, txt in show:
            print(f"  [{skill}] {txt}")

    acorr = codex["agent_corrections"]
    if acorr:
        show = acorr[:CORRECTION_CAP]
        adropped = len(acorr) - len(show)
        print("\nCODEX-AGENT-CORRECTION-SIGNALS:" + (f"  [dropped {adropped}]" if adropped else ""))
        for agent, txt in show:
            print(f"  [{agent}] {txt}")

    fric = codex["frictions"]
    if fric:
        show = fric[:FRICTION_CAP]
        fdropped = len(fric) - len(show)
        print("\nCODEX-HARNESS-FRICTION:" + (f"  [dropped {fdropped}]" if fdropped else ""))
        for txt in show:
            print(f"  {txt}")

    print("\nCODEX-PROMPTS (cluster together with PROMPTS above by intent):"
          + (" [new since last run]" if last_run_ms else ""))
    if last_run_ms and not shown:
        print("  (none — nothing new since last curator run; pass --full to re-review full history)")
    for _, txt in shown:
        print("- " + txt)


def main():
    args = sys.argv[1:]    # caller passes scope tokens directly; quote paths with spaces
    full = "--full" in args   # force full historical PROMPTS window, ignoring last-run state
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    proj_root = os.path.join(config_dir, "projects")

    # dirs entries: (claude_transcript_dir, label, real_path). real_path is the actual
    # absolute project path when known (current/--project scope) — used to match Codex
    # sessions by session_meta.cwd. None for `all` scope: Claude's encode_project() dir
    # names can't be reversed back into a real path, so Codex matching is skipped there
    # (see module docstring) rather than guessed.
    if "--project" in args:
        i = args.index("--project")
        if i + 1 >= len(args):
            print("--project requires an absolute path")
            sys.exit(2)
        path = args[i + 1]
        scope, dirs = "named", [(resolve_project_dir(path, proj_root), path, path)]
    elif "all" in args:
        if not os.path.isdir(proj_root):
            print(f"No projects dir at {proj_root} — nothing to scan.")
            sys.exit(0)
        scope = "all"
        dirs = [(os.path.join(proj_root, n), n, None)
                for n in sorted(os.listdir(proj_root))
                if os.path.isdir(os.path.join(proj_root, n))]
    else:
        cwd = os.getcwd()
        scope, dirs = "current", [(resolve_project_dir(cwd, proj_root), cwd, cwd)]

    def build(d, label, real_path):
        s = scan_dir(d, label)
        if s is not None:
            s["last_run_ms"] = 0 if full else read_last_run_ms(d)
        if real_path is not None:
            codex_summary = build_codex_summary(real_path, full)
            if codex_summary is not None:
                if s is None:
                    s = {"label": label, "sessions": 0, "prompts": [], "skill_sessions": {},
                         "agent_sessions": {}, "corrections": [], "agent_corrections": [],
                         "frictions": [], "last_run_ms": 0}
                s["codex"] = codex_summary
        return s

    def has_data(s):
        if s["prompts"] or s["frictions"] or s["corrections"]:
            return True
        codex = s.get("codex")
        return bool(codex and (codex["prompts"] or codex["frictions"]
                                or codex["corrections"] or codex["agent_corrections"]))

    summaries = [s for s in (build(d, label, real_path) for d, label, real_path in dirs)
                 if s is not None and has_data(s)]
    if not summaries:
        print(f"NO TRANSCRIPT DATA for scope={scope} (looked in {proj_root}"
              f"{' and Codex sessions' if scope != 'all' else ''}).")
        if scope != "all":
            print("Try scanning all projects: scope 'all'")
        sys.exit(0)

    summaries.sort(key=lambda s: -(len(s["prompts"]) + len(s.get("codex", {}).get("prompts", []))))
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
