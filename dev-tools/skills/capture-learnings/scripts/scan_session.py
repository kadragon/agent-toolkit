#!/usr/bin/env python3
"""capture-learnings — on-demand capture-signal scan of the CURRENT session.

Manual counterpart to the retired self-improve-nudge hook: instead of surfacing
automatically (which interrupted mid-task and polluted context), this runs only
when the user invokes the capture-learnings skill. It reads the current project's
newest Claude Code transcript, detects the same three objective capture signals,
and prints them so the caller can apply the §Harness ratchet write-back gate.

Signals (identical to the old hook):
  A  complex-task     >= 10 action tool calls (Edit/Write/Bash/Agent etc.)
  B  error-recovery   is_error true -> success in tool_result sequence
  C  user-correction  short pushback phrase right after an assistant turn

Usage:
  python3 scan_session.py [--cwd PATH]   scan the project at PATH (default: cwd)
  python3 scan_session.py --test         run self-tests

Claude Code only. It reads Claude's project-partitioned transcript tree
(<config>/projects/<encoded>/*.jsonl, honoring CLAUDE_CONFIG_DIR). Codex stores
sessions in a different, date-partitioned layout with a different record format,
so under Codex this prints a clear notice and does nothing — use harness-curator
for Codex sessions. Never raises for a missing transcript — prints a plain
message and exits 0.
"""

import glob
import json
import os
import re
import sys

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


# --- transcript location (tolerates Claude's project-dir case/separator drift) --

def _under_codex():
    """True when running under Codex rather than Claude Code. Codex sets
    CODEX_HOME and installs the plugin under a /.codex/ path. Used to bail with a
    clear notice instead of silently scanning a Claude tree that Codex never
    populates (its sessions live in a date-partitioned rollout layout)."""
    if os.environ.get("CODEX_HOME"):
        return True
    return "/.codex/" in os.path.realpath(__file__).replace("\\", "/")


def config_dir():
    """Claude Code config root (~/.claude), honoring CLAUDE_CONFIG_DIR."""
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def encode_project(path):
    """Map a project path to its transcript dir name: '/', '.', '\\', ':' -> '-'.
    Normalizes to an absolute, case-folded path first (mirrors
    harness-curator/scan_transcripts.py)."""
    path = os.path.normcase(os.path.abspath(path))
    return re.sub(r"[/.:\\]", "-", path)


def _loose_key(name):
    """Case/underscore/hyphen-insensitive key for fuzzy-matching an encoded dir
    name — Claude's own naming has drifted across versions (case, '_' vs '-'),
    so an exact encode_project() match can miss real data under a sibling dir."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _jsonl_count(d):
    try:
        return len(glob.glob(os.path.join(d, "*.jsonl")))
    except OSError:
        return 0


def resolve_project_dir(path, proj_root):
    """Find the transcript dir for `path`, tolerating case/separator drift.
    Prefers an exact encode_project() match that actually holds transcripts;
    otherwise scans proj_root for a loose-key sibling with the most *.jsonl."""
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


def newest_transcript(cwd):
    """Absolute path of the current project's most-recently-written transcript,
    or None. The active session's file is being appended, so it sorts newest."""
    proj_root = os.path.join(config_dir(), "projects")
    tdir = resolve_project_dir(cwd, proj_root)
    files = glob.glob(os.path.join(tdir, "*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda f: os.path.getmtime(f))


# --- signal detection (copied verbatim from the retired nudge.py) ---------------

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
        # tool_result-bearing messages are not user text.
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


def report(signals, parts):
    if not signals:
        return (
            "No objective capture signals (complex-task / error-recovery / "
            "user-correction) in this session. Nothing to capture."
        )
    lines = [
        "Capture signals in this session: " + ", ".join(signals) + ".",
        "",
    ] + parts + [
        "",
        "Apply the §Harness ratchet write-back gate: capture a lesson ONLY if it "
        "is reusable AND passed an objective check (test / exit-0 / verifier); "
        "otherwise disregard.",
    ]
    return "\n".join(lines)


def main(argv):
    if _under_codex():
        sys.stdout.write(
            "capture-learnings scans Claude Code transcripts only. Under Codex, "
            "use the harness-curator skill — it handles Codex session rollouts."
        )
        return

    cwd = os.getcwd()
    if "--cwd" in argv:
        cwd = argv[argv.index("--cwd") + 1]

    tp = newest_transcript(cwd)
    if not tp:
        sys.stdout.write(
            "No Claude Code transcript found for this project — nothing to scan."
        )
        return

    records = load_transcript(tp)
    if not records:
        sys.stdout.write("Current transcript is empty — nothing to scan.")
        return

    signals, parts = detect_signals(records)
    sys.stdout.write(report(signals, parts))


# --- self-tests ----------------------------------------------------------------

def _test():
    import tempfile

    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL") + f" — {name}")
        if not cond:
            fails.append(name)

    # detect_signals: complex-task threshold
    recs = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit"}]}} for _ in range(ACTION_THRESHOLD)]
    sig, parts = detect_signals(recs)
    check("complex-task fires at threshold", "complex-task" in sig)
    check("complex-task part present", any("complex task" in p for p in parts))
    check("complex-task below threshold silent",
          "complex-task" not in detect_signals(recs[:-1])[0])

    # error-recovery
    rr = [
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
    ]
    check("error-recovery fires on error->success",
          "error-recovery" in detect_signals(rr)[0])

    # user-correction
    rc = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
        {"type": "user", "message": {"content": "no, that's wrong"}},
    ]
    check("user-correction fires on pushback",
          "user-correction" in detect_signals(rc)[0])

    # report text
    check("report: no-signal message", "Nothing to capture" in report([], []))
    check("report: signal names + gate",
          "write-back gate" in report(["complex-task"], ["[A] x"]))

    # end-to-end: newest_transcript resolves the project dir and main() scans it.
    with tempfile.TemporaryDirectory() as cfg:
        os.environ["CLAUDE_CONFIG_DIR"] = cfg
        os.environ.pop("CODEX_HOME", None)
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        with tempfile.TemporaryDirectory() as proj:
            tdir = os.path.join(cfg, "projects", encode_project(proj))
            os.makedirs(tdir, exist_ok=True)
            tp = os.path.join(tdir, "sess.jsonl")
            with open(tp, "w", encoding="utf-8") as f:
                for _ in range(ACTION_THRESHOLD):
                    f.write(json.dumps({"type": "assistant", "message": {"content": [
                        {"type": "tool_use", "name": "Bash"}]}}) + "\n")
            check("newest_transcript finds the session file",
                  newest_transcript(proj) == tp)

            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["--cwd", proj])
            out = buf.getvalue()
            check("main reports complex-task", "complex-task" in out)

            # Codex platform -> loud Claude-only notice, never a silent scan.
            os.environ["CODEX_HOME"] = os.path.join(cfg, "codex-home")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["--cwd", proj])
            check("main bails with a notice under Codex",
                  "Claude Code transcripts only" in buf.getvalue())
            os.environ.pop("CODEX_HOME", None)

        # No transcript dir at all -> graceful message.
        with tempfile.TemporaryDirectory() as empty_proj:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["--cwd", empty_proj])
            check("main graceful when no transcript",
                  "nothing to scan" in buf.getvalue())

    print()
    if fails:
        print(f"{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    if "--test" in sys.argv:
        # Test mode must NOT swallow: a crashed fixture has to surface as a
        # non-zero exit so CI / verification can't read it as a pass.
        _test()
    else:
        try:
            main(sys.argv[1:])
        except Exception as e:
            # Runtime only: never hard-fail the invoking skill — surface and move on.
            sys.stdout.write(f"capture-learnings scan error: {e}")
        sys.exit(0)
