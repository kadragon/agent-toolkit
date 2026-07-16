#!/usr/bin/env python3
"""
quiz_state.py — deterministic state manager for the repo-quiz skill.

Owns everything that must be exact so the model never has to do date math or
SM-2 arithmetic in its head: spaced-repetition scheduling, XP/level, streak,
the append-only question log, and the human-readable mistakes note.

All state lives under <repo>/.repo-quiz/ :
  progress.json   XP, level, streak, and per-concept SM-2 schedule
  history.jsonl   one line per question asked (append-only audit trail)
  mistakes.md     human-readable wrong-answer notes, newest first

Concepts are keyed by a stable slug the model assigns (e.g. "auth-token-verify").
The model generates a fresh question for a concept each time; this script only
tracks *when* a concept is due and how the learner is doing on it.

Subcommands:
  init                              create .repo-quiz/, add it to .gitignore
  status                            print dashboard JSON (xp, level, streak, due)
  due --count N                     list concepts due for review, most-overdue first
  record --concept S --correct B    apply an answer: SM-2 + XP + streak + logs
      [--title T] [--note N] [--session ID] [--today YYYY-MM-DD]
  --test                            self-check on a throwaay temp dir; no real state

Grade mapping (SM-2 quality 0-5): correct -> 5, wrong -> 2.
XP: +10 correct, +3 wrong (participation). Level = 1 + xp // 100.
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import subprocess
import sys

STATE_DIR = ".repo-quiz"
PROGRESS = "progress.json"
HISTORY = "history.jsonl"
MISTAKES = "mistakes.md"

XP_CORRECT = 10
XP_WRONG = 3
XP_PER_LEVEL = 100


# ---------- paths & io ----------

def state_dir(repo):
    return os.path.join(repo, STATE_DIR)


def load_progress(repo):
    path = os.path.join(state_dir(repo), PROGRESS)
    if not os.path.exists(path):
        return {"xp": 0, "level": 1, "streak": 0, "last_active": None, "concepts": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_progress(repo, state):
    os.makedirs(state_dir(repo), exist_ok=True)
    path = os.path.join(state_dir(repo), PROGRESS)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def append_line(repo, filename, line):
    os.makedirs(state_dir(repo), exist_ok=True)
    path = os.path.join(state_dir(repo), filename)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def prepend_line(repo, filename, line):
    os.makedirs(state_dir(repo), exist_ok=True)
    path = os.path.join(state_dir(repo), filename)
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
        f.write(existing)


# ---------- core logic ----------

def today_str(override=None):
    if override:
        return override
    return datetime.date.today().isoformat()


def level_for(xp):
    return 1 + xp // XP_PER_LEVEL


def update_streak(state, today):
    """Bump the consecutive-day streak on the first activity of a new day."""
    last = state.get("last_active")
    if last == today:
        return
    if last:
        gap = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(last)).days
        state["streak"] = state.get("streak", 0) + 1 if gap == 1 else 1
    else:
        state["streak"] = 1
    state["last_active"] = today


def current_streak(state, today):
    """Return the active streak without mutating persisted progress."""
    last = state.get("last_active")
    if not last:
        return 0
    gap = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(last)).days
    return state.get("streak", 0) if gap in (0, 1) else 0


def sm2(concept, quality, today):
    """Apply the SM-2 update in place. concept holds ef/interval/reps/due."""
    ef = concept.get("ef", 2.5)
    interval = concept.get("interval", 0)
    reps = concept.get("reps", 0)

    if quality < 3:
        reps = 0
        interval = 1
    else:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = round(interval * ef)
        reps += 1

    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(1.3, round(ef, 2))

    due = datetime.date.fromisoformat(today) + datetime.timedelta(days=interval)
    concept["ef"] = ef
    concept["interval"] = interval
    concept["reps"] = reps
    concept["due"] = due.isoformat()


def due_concepts(state, today, count):
    due = [
        {"concept": slug, "title": c.get("title", slug), "due": c.get("due", today)}
        for slug, c in state.get("concepts", {}).items()
        if c.get("due", today) <= today
    ]
    due.sort(key=lambda x: x["due"])
    return due[:count] if count else due


# ---------- commands ----------

def cmd_init(repo):
    os.makedirs(state_dir(repo), exist_ok=True)
    gi = os.path.join(repo, ".gitignore")
    entry = f"{STATE_DIR}/"
    lines = []
    if os.path.exists(gi):
        with open(gi, encoding="utf-8") as f:
            lines = f.read().splitlines()
    if entry not in lines and STATE_DIR not in lines:
        with open(gi, "a", encoding="utf-8", newline="\n") as f:
            if lines and lines[-1].strip():
                f.write("\n")
            f.write(f"# repo-quiz local progress (personal, not shared)\n{entry}\n")
        added = True
    else:
        added = False
    print(json.dumps({"state_dir": state_dir(repo), "gitignore_added": added}))


def cmd_status(repo, today):
    state = load_progress(repo)
    due = due_concepts(state, today, 0)
    xp = state.get("xp", 0)
    print(json.dumps({
        "xp": xp,
        "level": level_for(xp),
        "xp_to_next": XP_PER_LEVEL - (xp % XP_PER_LEVEL),
        "streak": current_streak(state, today),
        "last_active": state.get("last_active"),
        "total_concepts": len(state.get("concepts", {})),
        "due_count": len(due),
        "due": due,
    }, ensure_ascii=False))


def cmd_due(repo, today, count):
    state = load_progress(repo)
    print(json.dumps(due_concepts(state, today, count), ensure_ascii=False))


def cmd_record(repo, args, today):
    state = load_progress(repo)
    concepts = state.setdefault("concepts", {})
    concept = concepts.setdefault(args.concept, {})
    if args.title:
        concept["title"] = args.title
    concept.setdefault("title", args.concept)
    was_wrong = concept.get("wrong", 0) > 0 and concept.get("reps", 0) == 0

    correct = args.correct.lower() in ("true", "1", "yes", "y")
    quality = 5 if correct else 2

    concept["seen"] = concept.get("seen", 0) + 1
    if not correct:
        concept["wrong"] = concept.get("wrong", 0) + 1

    sm2(concept, quality, today)
    update_streak(state, today)
    state["xp"] = state.get("xp", 0) + (XP_CORRECT if correct else XP_WRONG)
    state["level"] = level_for(state["xp"])

    session = args.session or today
    append_line(repo, HISTORY, json.dumps({
        "ts": today,
        "session": session,
        "concept": args.concept,
        "title": concept["title"],
        "correct": correct,
        "next_due": concept["due"],
    }, ensure_ascii=False))

    if not correct:
        block = [f"## {today} — {concept['title']} (`{args.concept}`)"]
        if args.note:
            block.append("")
            block.append(args.note.strip())
        block.append("")
        prepend_line(repo, MISTAKES, "\n".join(block))
    elif was_wrong:
        prepend_line(repo, MISTAKES,
                    f"> ✓ {today}: got `{args.concept}` right after a previous miss.\n")

    save_progress(repo, state)
    print(json.dumps({
        "concept": args.concept,
        "correct": correct,
        "next_due": concept["due"],
        "interval_days": concept["interval"],
        "xp": state["xp"],
        "level": state["level"],
        "streak": state["streak"],
    }, ensure_ascii=False))


# ---------- self-check ----------

def run_tests():
    import tempfile
    import shutil

    failures = []

    def check(name, cond):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failures.append(name)

    repo = tempfile.mkdtemp(prefix="quiz-test-")
    try:
        # init adds gitignore entry
        with open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("node_modules/\n")
        cmd_init(repo)
        with open(os.path.join(repo, ".gitignore"), encoding="utf-8") as f:
            gi = f.read()
        check("gitignore gets .repo-quiz/", ".repo-quiz/" in gi)
        check("gitignore preserves prior entries", "node_modules/" in gi)

        # init is idempotent — no duplicate entry
        cmd_init(repo)
        with open(os.path.join(repo, ".gitignore"), encoding="utf-8") as f:
            check("init idempotent", f.read().count(".repo-quiz/") == 1)

        # SM-2: correct answers grow the interval 0 -> 1 -> 6
        c = {}
        sm2(c, 5, "2026-07-16")
        check("first correct -> interval 1", c["interval"] == 1)
        check("first correct due +1d", c["due"] == "2026-07-17")
        sm2(c, 5, "2026-07-17")
        check("second correct -> interval 6", c["interval"] == 6)
        sm2(c, 5, "2026-07-23")
        check("third correct -> interval > 6", c["interval"] > 6)

        # SM-2: a wrong answer resets reps and schedules tomorrow
        sm2(c, 2, "2026-07-30")
        check("wrong resets interval to 1", c["interval"] == 1)
        check("wrong keeps ef >= 1.3", c["ef"] >= 1.3)

        # streak: consecutive day increments, gap resets
        st = {"streak": 0, "last_active": None}
        update_streak(st, "2026-07-16")
        check("first day streak 1", st["streak"] == 1)
        update_streak(st, "2026-07-16")
        check("same day no double count", st["streak"] == 1)
        update_streak(st, "2026-07-17")
        check("next day streak 2", st["streak"] == 2)
        update_streak(st, "2026-07-20")
        check("gap resets streak", st["streak"] == 1)

        # status: a streak expires when no activity occurred yesterday or today
        expired = {
            "xp": 0, "streak": 3, "last_active": "2026-07-10", "concepts": {}
        }
        save_progress(repo, expired)
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            cmd_status(repo, "2026-07-16")
        status = json.loads(status_output.getvalue())
        check("status expires stale streak", status["streak"] == 0)

        # level thresholds
        check("level 1 at 0 xp", level_for(0) == 1)
        check("level 2 at 100 xp", level_for(100) == 2)

        # record: wrong answer writes a mistakes.md block and schedules review
        args = argparse.Namespace(concept="auth-flow", correct="false",
                                  title="Auth token verification",
                                  note="Verified in middleware/auth.ts, not routes.",
                                  session="s1")
        cmd_record(repo, args, "2026-07-16")
        with open(os.path.join(repo, STATE_DIR, MISTAKES), encoding="utf-8") as f:
            mistakes = f.read()
        check("mistakes.md records wrong answer", "auth-flow" in mistakes)
        check("mistakes.md keeps the note", "middleware/auth.ts" in mistakes)

        args_newer = argparse.Namespace(concept="routing", correct="false",
                                        title="Request routing", note="Newer miss.",
                                        session="s1")
        cmd_record(repo, args_newer, "2026-07-17")
        with open(os.path.join(repo, STATE_DIR, MISTAKES), encoding="utf-8") as f:
            mistakes = f.read()
        check("mistakes.md stores newest miss first",
              mistakes.index("routing") < mistakes.index("auth-flow"))

        # CLI: malformed boolean input must fail before state is changed
        invalid_repo = tempfile.mkdtemp(prefix="quiz-invalid-")
        try:
            result = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--repo", invalid_repo,
                 "record", "--concept", "typo", "--correct", "ture"],
                capture_output=True, text=True, check=False,
            )
            check("invalid --correct exits nonzero", result.returncode != 0)
            check("invalid --correct leaves progress unchanged",
                  not os.path.exists(os.path.join(invalid_repo, STATE_DIR, PROGRESS)))
        finally:
            shutil.rmtree(invalid_repo, ignore_errors=True)

        due = due_concepts(load_progress(repo), "2026-07-17", 5)
        check("wrong concept becomes due next day", any(d["concept"] == "auth-flow" for d in due))

        # record: correct answer awards more XP than a wrong one
        args2 = argparse.Namespace(concept="build-system", correct="true",
                                   title="Build pipeline", note=None, session="s1")
        cmd_record(repo, args2, "2026-07-16")
        state = load_progress(repo)
        check("xp accrues (6 wrong + 10 correct)",
              state["xp"] == 2 * XP_WRONG + XP_CORRECT)

        # a concept answered correctly today is not due today
        due_today = due_concepts(state, "2026-07-16", 5)
        check("correct concept not due same day",
              all(d["concept"] != "build-system" for d in due_today))
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


# ---------- entry ----------

def main(argv):
    if "--test" in argv:
        print("=== quiz_state.py --test ===\n")
        return run_tests()

    p = argparse.ArgumentParser(description="repo-quiz state manager")
    p.add_argument("--repo", default=".", help="repo root (default: cwd)")
    p.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    sub.add_parser("status")

    pd = sub.add_parser("due")
    pd.add_argument("--count", type=int, default=0)

    pr = sub.add_parser("record")
    pr.add_argument("--concept", required=True)
    pr.add_argument("--correct", required=True, choices=("true", "false"))
    pr.add_argument("--title", default=None)
    pr.add_argument("--note", default=None)
    pr.add_argument("--session", default=None)

    args = p.parse_args(argv)
    today = today_str(args.today)

    if args.cmd == "init":
        cmd_init(args.repo)
    elif args.cmd == "status":
        cmd_status(args.repo, today)
    elif args.cmd == "due":
        cmd_due(args.repo, today, args.count)
    elif args.cmd == "record":
        cmd_record(args.repo, args, today)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
