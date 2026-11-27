"""Read-only SessionStart nudge for projects with enough new transcripts."""

import json
import os
import time

from session_paths import (
    codex_home,
    codex_state_dir,
    find_codex_session_files,
    resolve_project_dir,
)

STATE_FILE = ".harness-curator-state.json"
DAY_MS = 86_400_000
DUE_DAYS = 14
DUE_SESSIONS = 10


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def state_path(project):
    proj_root = os.path.join(config_dir(), "projects")
    return os.path.join(resolve_project_dir(project, proj_root), STATE_FILE)


def read_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def count_newer(paths, since_ms):
    count = 0
    for fp in paths:
        try:
            if os.path.getmtime(fp) * 1000 > since_ms:
                count += 1
        except OSError:
            pass
    return count


def new_sessions(state_dir, since_ms):
    """Transcripts in the resolved project dir modified after `since_ms`."""
    try:
        names = [n for n in os.listdir(state_dir) if n.endswith(".jsonl")]
    except OSError:
        return 0
    return count_newer((os.path.join(state_dir, n) for n in names), since_ms)


def new_codex_sessions(project, since_ms):
    """The project's Codex rollouts (matched by session_meta cwd) modified after `since_ms`."""
    return len(find_codex_session_files(codex_home(), project, since_ms))


def last_run_ms(path):
    last = read_state(path).get("lastRunMs") or 0
    return last if isinstance(last, (int, float)) else 0


def due_message(project, now_ms=None):
    """Return the nudge line, or None when a curate run is not due."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    path = state_path(project)
    last = max(last_run_ms(path),
               last_run_ms(os.path.join(codex_state_dir(codex_home(), project), STATE_FILE)))
    if last and now_ms - last <= DUE_DAYS * DAY_MS:
        return None
    sessions = new_sessions(os.path.dirname(path), last)
    if sessions < DUE_SESSIONS:  # the Codex scan reads every rollout's head; skip it when unneeded
        sessions += new_codex_sessions(project, last)
    if sessions < DUE_SESSIONS:
        return None
    age = f"{int((now_ms - last) // DAY_MS)}d ago" if last else "never"
    return (
        f"HARNESS-CURATE DUE: last run {age}, {sessions} sessions since. "
        "At the start of your next reply, suggest in one sentence that the user run "
        "`/dev:harness-curate` (Claude Code) or `$harness-curate` (Codex), then continue their task."
    )


if __name__ == "__main__":
    if message := due_message(os.getcwd()):
        print(message)
