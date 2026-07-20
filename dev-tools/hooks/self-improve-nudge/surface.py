#!/usr/bin/env python3
"""self-improve-nudge — SessionStart reader: replay a deferred capture nudge.

nudge.py (Stop) records capture signals to a per-project pending file instead of
blocking Stop. This hook, at the next SessionStart in the same project, replays
that nudge as a one-line reminder (via stdout -> session context) and deletes the
file so it fires exactly once. There is no work summary to bury at session start.

Never raises — a reminder must never block session start.
"""

import json
import os
import sys
import time

from _common import config_dir, pending_path

MAX_AGE_MS = 7 * 86_400_000  # drop a pending nudge older than this, unsurfaced


def read_input():
    try:
        return json.loads(sys.stdin.read())
    except Exception:
        return {}


def main():
    inp = read_input()
    cwd = inp.get("cwd") or os.getcwd()
    cdir = config_dir()
    path = pending_path(cwd, cdir)

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return  # no pending nudge (the common case) — stay silent

    # Consume exactly once: delete before emitting so a crash can't re-surface.
    try:
        os.remove(path)
    except OSError:
        pass

    written_ms = payload.get("written_ms") or 0
    if written_ms and int(time.time() * 1000) - written_ms > MAX_AGE_MS:
        return  # stale — the session it described is long gone

    signals = payload.get("signals") or []
    parts = payload.get("parts") or []
    if not signals:
        return

    signal_list = ", ".join(signals)
    lines = [
        f"[self-improve-nudge] Your previous session in this project showed capture "
        f"signals: {signal_list}.",
        "Apply §Harness ratchet §Write-back gate — if a reusable lesson passed an "
        "objective check (test/exit-0/verifier), capture it now; else disregard.",
        "",
    ] + parts + [
        "",
        "Mention this in one line at the start of your next reply, then continue "
        "the user's task.",
    ]
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # any failure -> silent, never block startup
    sys.exit(0)
