#!/usr/bin/env python3
"""
quiz_state.py — deterministic state manager for the repo-quiz skill.

Owns everything that must be exact so the model never has to do date math,
scheduler arithmetic, or XP bookkeeping in its head: spaced-repetition
scheduling (FSRS when available, SM-2 fallback otherwise), XP/level, streak
(with streak-freeze), achievements, persona/goal config, the append-only
question log, and the human-readable mistakes note.

All state lives under <repo>/.repo-quiz/ :
  progress.json   xp, level, streak, freezes, achievements, config, and
                  per-concept schedule (FSRS or SM-2, whichever produced it)
  history.jsonl   one line per question asked (append-only audit trail)
  mistakes.md     human-readable wrong-answer notes, newest first

Concepts are keyed by a stable slug the model assigns (e.g. "auth-token-verify").
The model generates a fresh question for a concept each time; this script only
tracks *when* a concept is due and how the learner is doing on it.

Scheduler (design borrowed from open-spaced-repetition/py-fsrs):
  Each `record` call uses FSRS (`from fsrs import Scheduler, Card, Rating`)
  when the `fsrs` package is importable and REPO_QUIZ_NO_FSRS is unset;
  otherwise (or if the FSRS call raises for any reason — API drift, bad
  state, etc.) it falls back to the original SM-2 math so the skill keeps
  working with zero extra deps installed. `concept["sched"]` records which
  scheduler produced the current state ("fsrs" or "sm2"); a concept can
  switch schedulers across reviews without crashing — it just re-initializes
  cleanly under whichever scheduler is active.

Subcommands:
  init                                  create .repo-quiz/, add it to .gitignore
  status                                print dashboard JSON (xp, level, streak,
                                         due, config, achievements)
  due --count N                         list concepts due for review, most-overdue first
  record --concept S --correct B        apply an answer: schedule + XP + streak +
                                         achievements + logs
      [--grade again|hard|good|easy] [--type SLUG] [--title T] [--note N]
      [--session ID] [--today YYYY-MM-DD]
  config [--get] [--set-persona P] [--set-daily-goal N]
                                         read or update persona/daily_goal
  --test                                self-check on a throwaway temp dir; no real state

Grade mapping (SM-2 quality 0-5):
  --grade given:  again -> 2, hard -> 3, good -> 4, easy -> 5
  --grade absent: correct -> 5, wrong -> 2  (back-compat with --correct-only calls)
FSRS rating: again -> Rating.Again ... easy -> Rating.Easy. When --grade is not
given, effective grade defaults to "good" (correct) / "again" (wrong).

XP: type-weighted so grinding easy question types yields little (design
borrowed from the Duolingo gamification case study — weighted XP, streak
freeze, tiered achievements). Weight table (correct answers only):
  mc=1.0  fill-blank=1.2  code-trace=1.5  bug-hunt=1.5  why=1.5  free-recall=2.0
XP_correct = round(10 * weight); wrong = flat 3 (participation).
Level = 1 + xp // 100.
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

XP_WRONG = 3
XP_PER_LEVEL = 100

TYPE_XP_WEIGHTS = {
    "mc": 1.0,
    "fill-blank": 1.2,
    "code-trace": 1.5,
    "bug-hunt": 1.5,
    "why": 1.5,
    "free-recall": 2.0,
}

GRADE_TO_SM2_QUALITY = {"again": 2, "hard": 3, "good": 4, "easy": 5}
STREAK_ACHIEVEMENT_TIERS = (3, 7, 30)

DEFAULT_CONFIG = {"persona": "mid", "daily_goal": 5}


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
    """Bump the consecutive-day streak on the first activity of a new day.

    Streak-freeze (Duolingo-style): if exactly one day was missed (gap == 2)
    and a freeze token is available, consume it and preserve the streak
    instead of resetting. A gap > 2 always resets, freeze or not.
    """
    last = state.get("last_active")
    if last == today:
        return
    if last:
        gap = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(last)).days
        if gap == 1:
            state["streak"] = state.get("streak", 0) + 1
        elif gap == 2 and state.get("freezes", 1) > 0:
            state["freezes"] = state.get("freezes", 1) - 1
            # streak preserved as-is; a frozen day doesn't grow it either
        else:
            state["streak"] = 1
    else:
        state["streak"] = 1
    state["last_active"] = today


def current_streak(state, today):
    """Return the active streak without mutating persisted progress."""
    last = state.get("last_active")
    if not last:
        return 0
    gap = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(last)).days
    # A pending freeze keeps the streak alive on the first missed day (gap==2),
    # matching update_streak(), so status doesn't read as broken before today's round.
    alive = gap in (0, 1) or (gap == 2 and state.get("freezes", 1) > 0)
    return state.get("streak", 0) if alive else 0


def unlock_achievements(state, correct, qtype):
    """Unlock modest, difficulty-tiered milestones. Returns newly unlocked slugs."""
    achievements = state.setdefault("achievements", [])
    newly = []

    def unlock(slug):
        if slug not in achievements:
            achievements.append(slug)
            newly.append(slug)

    if correct:
        state["correct_total"] = state.get("correct_total", 0) + 1
        if state["correct_total"] == 1:
            unlock("first-correct")
        if qtype == "bug-hunt":
            unlock("first-bug-hunt")

    streak = state.get("streak", 0)
    for tier in STREAK_ACHIEVEMENT_TIERS:
        if streak >= tier:
            unlock(f"streak-{tier}")

    return newly


def resolve_grade(grade, correct):
    """Effective grade name: explicit --grade wins, else derived from --correct."""
    return grade if grade else ("good" if correct else "again")


def sm2_quality_for(grade, correct):
    """SM-2 quality 0-5. Explicit grade uses the finer scale; otherwise the
    original boolean back-compat mapping (correct=5, wrong=2)."""
    if grade:
        return GRADE_TO_SM2_QUALITY[grade]
    return 5 if correct else 2


def type_weight(qtype):
    return TYPE_XP_WEIGHTS.get(qtype, 1.0)


def xp_for_answer(correct, qtype):
    if not correct:
        return XP_WRONG
    return round(10 * type_weight(qtype))


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


def _fsrs_available():
    """True only if `import fsrs` succeeds AND REPO_QUIZ_NO_FSRS is unset/falsey.

    The env override lets --test exercise the SM-2 fallback deterministically
    regardless of whether py-fsrs happens to be installed.
    """
    if os.environ.get("REPO_QUIZ_NO_FSRS"):
        return False
    try:
        import fsrs  # noqa: F401  # type: ignore[import-not-found]
        return True
    except Exception:
        return False


def _fsrs_review(concept, grade, today):
    """Run one FSRS review. Returns (due_iso, fsrs_dict). Raises on ANY problem
    so the caller can fall back to SM-2 without ever corrupting stdout."""
    import fsrs  # type: ignore[import-not-found]

    rating_map = {
        "again": fsrs.Rating.Again,
        "hard": fsrs.Rating.Hard,
        "good": fsrs.Rating.Good,
        "easy": fsrs.Rating.Easy,
    }
    rating = rating_map[grade]

    if concept.get("sched") == "fsrs" and concept.get("fsrs"):
        card = fsrs.Card.from_dict(concept["fsrs"])
    else:
        card = fsrs.Card()

    # This quiz schedules at whole-day granularity (one review round per day), so
    # drop FSRS's sub-day learning/relearning steps — otherwise a freshly-answered
    # card is due again in minutes (same calendar date) and re-surfaces the same day.
    # With empty steps the first "good" schedules days out, matching the SM-2 fallback.
    scheduler = fsrs.Scheduler(learning_steps=(), relearning_steps=())
    y, m, d = (int(part) for part in today.split("-"))
    review_dt = datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc)
    card, _review_log = scheduler.review_card(card, rating, review_datetime=review_dt)

    due_val = card.due
    if isinstance(due_val, datetime.datetime):
        due_val = due_val.astimezone(datetime.timezone.utc).date()
    elif not isinstance(due_val, datetime.date):
        due_val = datetime.date.fromisoformat(str(due_val)[:10])

    return due_val.isoformat(), card.to_dict()


def apply_schedule(concept, sm2_quality, grade, today):
    """Schedule one review: FSRS when available, else (or on any FSRS error)
    the SM-2 fallback. Always leaves concept["sched"]/["due"]/["interval"] set."""
    if _fsrs_available():
        try:
            due_iso, fsrs_dict = _fsrs_review(concept, grade, today)
            concept["sched"] = "fsrs"
            concept["fsrs"] = fsrs_dict
            concept["due"] = due_iso
            concept["interval"] = (
                datetime.date.fromisoformat(due_iso) - datetime.date.fromisoformat(today)
            ).days
            return
        except Exception:
            pass  # fall through to SM-2; never let a scheduler error reach stdout
    concept["sched"] = "sm2"
    concept.pop("fsrs", None)  # drop stale FSRS card so a later FSRS review starts fresh
    sm2(concept, sm2_quality, today)


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
    config = dict(DEFAULT_CONFIG)
    config.update(state.get("config", {}))
    print(json.dumps({
        "xp": xp,
        "level": level_for(xp),
        "xp_to_next": XP_PER_LEVEL - (xp % XP_PER_LEVEL),
        "streak": current_streak(state, today),
        "freezes": state.get("freezes", 1),
        "last_active": state.get("last_active"),
        "total_concepts": len(state.get("concepts", {})),
        "due_count": len(due),
        "due": due,
        "config": config,
        "achievements": state.get("achievements", []),
        "scheduler": "fsrs" if _fsrs_available() else "sm2",
        "fsrs_available": _fsrs_available(),
        "fsrs_notice_seen": bool(state.get("config", {}).get("fsrs_notice_seen", False)),
    }, ensure_ascii=False))


def cmd_due(repo, today, count):
    state = load_progress(repo)
    print(json.dumps(due_concepts(state, today, count), ensure_ascii=False))


def cmd_config(repo, args):
    state = load_progress(repo)
    config = state.setdefault("config", {})
    config.setdefault("persona", DEFAULT_CONFIG["persona"])
    config.setdefault("daily_goal", DEFAULT_CONFIG["daily_goal"])

    changed = False
    if getattr(args, "set_persona", None):
        config["persona"] = args.set_persona
        changed = True
    if getattr(args, "set_daily_goal", None) is not None:
        config["daily_goal"] = args.set_daily_goal
        changed = True
    if getattr(args, "seen_fsrs_notice", False):
        config["fsrs_notice_seen"] = True
        changed = True

    if changed:
        save_progress(repo, state)
    print(json.dumps(config, ensure_ascii=False))


def cmd_record(repo, args, today):
    state = load_progress(repo)
    concepts = state.setdefault("concepts", {})
    concept = concepts.setdefault(args.concept, {})
    if args.title:
        concept["title"] = args.title
    concept.setdefault("title", args.concept)

    correct = args.correct == "true"  # argparse choices already restrict to true|false
    qtype = getattr(args, "type", None) or "mc"
    grade_arg = getattr(args, "grade", None)
    grade = resolve_grade(grade_arg, correct)
    sm2_quality = sm2_quality_for(grade_arg, correct)

    prev_last_correct = concept.get("last_correct")
    recovering = correct and prev_last_correct is False

    concept["seen"] = concept.get("seen", 0) + 1
    if not correct:
        concept["wrong"] = concept.get("wrong", 0) + 1
    concept["last_correct"] = correct

    apply_schedule(concept, sm2_quality, grade, today)

    update_streak(state, today)
    xp_gain = xp_for_answer(correct, qtype)
    state["xp"] = state.get("xp", 0) + xp_gain
    state["level"] = level_for(state["xp"])
    newly_unlocked = unlock_achievements(state, correct, qtype)

    session = args.session or today
    append_line(repo, HISTORY, json.dumps({
        "ts": today,
        "session": session,
        "concept": args.concept,
        "title": concept["title"],
        "type": qtype,
        "grade": grade,
        "correct": correct,
        "sched": concept["sched"],
        "next_due": concept["due"],
    }, ensure_ascii=False))

    if not correct:
        block = [f"## {today} — {concept['title']} (`{args.concept}`)"]
        if args.note:
            block.append("")
            block.append(args.note.strip())
        block.append("")
        prepend_line(repo, MISTAKES, "\n".join(block))
    elif recovering:
        prepend_line(repo, MISTAKES,
                    f"> ✓ {today}: got `{args.concept}` right after a previous miss.\n")

    save_progress(repo, state)
    print(json.dumps({
        "concept": args.concept,
        "correct": correct,
        "grade": grade,
        "type": qtype,
        "sched": concept["sched"],
        "next_due": concept["due"],
        "interval_days": concept["interval"],
        "xp": state["xp"],
        "xp_gained": xp_gain,
        "level": state["level"],
        "streak": state.get("streak", 0),
        "freezes": state.get("freezes", 1),
        "achievements_unlocked": newly_unlocked,
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

        # streak-freeze: gap==2 with a token consumes it and preserves streak
        stf = {"streak": 5, "last_active": "2026-07-01", "freezes": 1}
        update_streak(stf, "2026-07-03")
        check("freeze consumed on gap==2", stf["freezes"] == 0)
        check("streak preserved when freeze consumed", stf["streak"] == 5)

        stf_none = {"streak": 5, "last_active": "2026-07-01", "freezes": 0}
        update_streak(stf_none, "2026-07-03")
        check("streak resets on gap==2 with no freeze", stf_none["streak"] == 1)

        stf_big_gap = {"streak": 5, "last_active": "2026-07-01", "freezes": 1}
        update_streak(stf_big_gap, "2026-07-05")
        check("streak resets on gap>2 even with a freeze available",
              stf_big_gap["streak"] == 1)
        check("freeze not consumed on gap>2", stf_big_gap["freezes"] == 1)

        # current_streak (read-only display): a pending freeze keeps gap==2 alive
        check("display keeps streak alive at gap==2 with a freeze",
              current_streak({"streak": 4, "last_active": "2026-07-14", "freezes": 1},
                             "2026-07-16") == 4)
        check("display drops streak at gap==2 without a freeze",
              current_streak({"streak": 4, "last_active": "2026-07-14", "freezes": 0},
                             "2026-07-16") == 0)
        check("display drops streak at gap>2 even with a freeze",
              current_streak({"streak": 4, "last_active": "2026-07-12", "freezes": 1},
                             "2026-07-16") == 0)

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
        check("status includes config", status.get("config", {}).get("persona") == "mid")
        check("status includes achievements", status.get("achievements") == [])
        check("status exposes fsrs_available bool",
              isinstance(status.get("fsrs_available"), bool))
        check("status scheduler matches availability",
              status.get("scheduler") == ("fsrs" if status.get("fsrs_available") else "sm2"))
        check("status fsrs_notice_seen defaults false",
              status.get("fsrs_notice_seen") is False)

        # config: the one-time FSRS install notice can be marked seen, and it persists
        seen_args = argparse.Namespace(get=False, set_persona=None,
                                       set_daily_goal=None, seen_fsrs_notice=True)
        cmd_config(repo, seen_args)
        seen_status = io.StringIO()
        with contextlib.redirect_stdout(seen_status):
            cmd_status(repo, "2026-07-16")
        check("fsrs notice persists as seen",
              json.loads(seen_status.getvalue()).get("fsrs_notice_seen") is True)

        # level thresholds
        check("level 1 at 0 xp", level_for(0) == 1)
        check("level 2 at 100 xp", level_for(100) == 2)

        # grade mapping: explicit --grade uses the finer SM-2 quality scale
        check("grade again -> sm2 quality 2", sm2_quality_for("again", True) == 2)
        check("grade hard -> sm2 quality 3", sm2_quality_for("hard", True) == 3)
        check("grade good -> sm2 quality 4", sm2_quality_for("good", True) == 4)
        check("grade easy -> sm2 quality 5", sm2_quality_for("easy", True) == 5)
        check("no grade, correct -> sm2 quality 5 (back-compat)",
              sm2_quality_for(None, True) == 5)
        check("no grade, wrong -> sm2 quality 2 (back-compat)",
              sm2_quality_for(None, False) == 2)
        check("resolve_grade defaults to good on correct", resolve_grade(None, True) == "good")
        check("resolve_grade defaults to again on wrong", resolve_grade(None, False) == "again")
        check("resolve_grade honors explicit grade", resolve_grade("hard", True) == "hard")

        # type-weighted XP: higher-demand question types pay more on a correct answer
        check("mc correct xp == 10", xp_for_answer(True, "mc") == 10)
        check("free-recall correct xp > mc correct xp",
              xp_for_answer(True, "free-recall") > xp_for_answer(True, "mc"))
        check("bug-hunt correct xp > mc correct xp",
              xp_for_answer(True, "bug-hunt") > xp_for_answer(True, "mc"))
        check("wrong xp is flat regardless of type",
              xp_for_answer(False, "free-recall") == XP_WRONG == xp_for_answer(False, "mc"))

        # achievements: at least one unlock path, including a streak tier
        ach_state = {"achievements": [], "streak": 0, "correct_total": 0}
        unlock_achievements(ach_state, True, "mc")
        check("first-correct achievement unlocks", "first-correct" in ach_state["achievements"])
        unlock_achievements(ach_state, True, "bug-hunt")
        check("first-bug-hunt achievement unlocks",
              "first-bug-hunt" in ach_state["achievements"])
        ach_state["streak"] = 7
        unlock_achievements(ach_state, True, "mc")
        check("streak-7 achievement unlocks", "streak-7" in ach_state["achievements"])
        before = list(ach_state["achievements"])
        unlock_achievements(ach_state, True, "bug-hunt")
        check("achievements don't duplicate on repeat unlock",
              ach_state["achievements"] == before)

        # FSRS live path: only when py-fsrs is actually importable (and not
        # forced off) — otherwise this is a SKIP, not a failure.
        if _fsrs_available():
            fc = {}
            apply_schedule(fc, sm2_quality_for(None, True), resolve_grade(None, True),
                           "2026-07-16")
            check("fsrs path marks concept sched=fsrs", fc.get("sched") == "fsrs")
            check("fsrs path sets a due date", "due" in fc and "fsrs" in fc)
            apply_schedule(fc, sm2_quality_for("again", False), "again", "2026-07-17")
            check("fsrs path survives an 'again' review without crashing",
                  "due" in fc)
        else:
            print("  SKIP  fsrs live path (py-fsrs not installed / REPO_QUIZ_NO_FSRS set) "
                  "— verified by code review only, not executed in this environment")

        # SM-2 fallback: forced deterministically regardless of outer env,
        # so this always runs. Interval grows on good, resets on again.
        forced_backup = os.environ.get("REPO_QUIZ_NO_FSRS")
        os.environ["REPO_QUIZ_NO_FSRS"] = "1"
        try:
            fb = {}
            apply_schedule(fb, sm2_quality_for(None, True), resolve_grade(None, True),
                           "2026-07-16")
            check("forced fallback uses sm2", fb.get("sched") == "sm2")
            check("forced fallback first good -> interval 1", fb.get("interval") == 1)
            apply_schedule(fb, sm2_quality_for(None, True), resolve_grade(None, True),
                           "2026-07-17")
            check("forced fallback second good -> interval 6", fb.get("interval") == 6)
            apply_schedule(fb, sm2_quality_for("again", False), "again", "2026-07-23")
            check("forced fallback again -> interval resets to 1", fb.get("interval") == 1)
            check("forced fallback again -> sched stays sm2", fb.get("sched") == "sm2")
            # a fallback review must discard a stale FSRS payload so a later FSRS
            # review can't restore pre-fallback state and drop the SM-2 answer
            stale = {"sched": "fsrs", "fsrs": {"card_id": 1, "due": "2026-07-10T00:00:00+00:00"}}
            apply_schedule(stale, sm2_quality_for(None, True), resolve_grade(None, True),
                           "2026-07-16")
            check("fallback drops stale fsrs payload", "fsrs" not in stale)
            check("fallback retags concept sm2", stale.get("sched") == "sm2")
        finally:
            if forced_backup is None:
                os.environ.pop("REPO_QUIZ_NO_FSRS", None)
            else:
                os.environ["REPO_QUIZ_NO_FSRS"] = forced_backup

        # record: wrong answer writes a mistakes.md block and schedules review
        args = argparse.Namespace(concept="auth-flow", correct="false",
                                  title="Auth token verification",
                                  note="Verified in middleware/auth.ts, not routes.",
                                  session="s1", grade=None, type=None)
        cmd_record(repo, args, "2026-07-16")
        with open(os.path.join(repo, STATE_DIR, MISTAKES), encoding="utf-8") as f:
            mistakes = f.read()
        check("mistakes.md records wrong answer", "auth-flow" in mistakes)
        check("mistakes.md keeps the note", "middleware/auth.ts" in mistakes)

        args_newer = argparse.Namespace(concept="routing", correct="false",
                                        title="Request routing", note="Newer miss.",
                                        session="s1", grade=None, type=None)
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

            bad_type = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--repo", invalid_repo,
                 "record", "--concept", "x", "--correct", "true", "--type", "code_trace"],
                capture_output=True, text=True, check=False,
            )
            check("unknown --type exits nonzero", bad_type.returncode != 0)

            bad_goal = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--repo", invalid_repo,
                 "config", "--set-daily-goal", "0"],
                capture_output=True, text=True, check=False,
            )
            check("non-positive --set-daily-goal exits nonzero", bad_goal.returncode != 0)
        finally:
            shutil.rmtree(invalid_repo, ignore_errors=True)

        due = due_concepts(load_progress(repo), "2026-07-17", 5)
        check("wrong concept becomes due next day", any(d["concept"] == "auth-flow" for d in due))

        # record: correct answer awards more XP than a wrong one
        args2 = argparse.Namespace(concept="build-system", correct="true",
                                   title="Build pipeline", note=None, session="s1",
                                   grade=None, type=None)
        cmd_record(repo, args2, "2026-07-16")
        state = load_progress(repo)
        check("xp accrues (6 wrong + 10 correct)",
              state["xp"] == 2 * XP_WRONG + xp_for_answer(True, "mc"))

        # record: --type and --grade land in history.jsonl
        args3 = argparse.Namespace(concept="free-recall-demo", correct="true",
                                   title="Free recall demo", note=None, session="s1",
                                   grade="easy", type="free-recall")
        cmd_record(repo, args3, "2026-07-17")
        with open(os.path.join(repo, STATE_DIR, HISTORY), encoding="utf-8") as f:
            history_lines = [json.loads(line) for line in f if line.strip()]
        last_entry = history_lines[-1]
        check("history records --type", last_entry["type"] == "free-recall")
        check("history records --grade", last_entry["grade"] == "easy")

        # a concept answered correctly today is not due today
        due_today = due_concepts(state, "2026-07-16", 5)
        check("correct concept not due same day",
              all(d["concept"] != "build-system" for d in due_today))

        # config: get defaults, set, and round-trip persistence
        cfg_get_args = argparse.Namespace(get=True, set_persona=None, set_daily_goal=None)
        cfg_out = io.StringIO()
        with contextlib.redirect_stdout(cfg_out):
            cmd_config(repo, cfg_get_args)
        cfg = json.loads(cfg_out.getvalue())
        check("config defaults persona=mid", cfg.get("persona") == "mid")
        check("config defaults daily_goal=5", cfg.get("daily_goal") == 5)

        cfg_set_args = argparse.Namespace(get=False, set_persona="senior", set_daily_goal=10)
        cfg_out2 = io.StringIO()
        with contextlib.redirect_stdout(cfg_out2):
            cmd_config(repo, cfg_set_args)
        cfg2 = json.loads(cfg_out2.getvalue())
        check("config set persona", cfg2.get("persona") == "senior")
        check("config set daily_goal", cfg2.get("daily_goal") == 10)

        cfg_out3 = io.StringIO()
        with contextlib.redirect_stdout(cfg_out3):
            cmd_config(repo, cfg_get_args)
        cfg3 = json.loads(cfg_out3.getvalue())
        check("config round-trips persona across calls", cfg3.get("persona") == "senior")
        check("config round-trips daily_goal across calls", cfg3.get("daily_goal") == 10)

        # backward compatibility: a pre-existing progress.json with none of the
        # new keys (sched/config/freezes/fsrs/achievements) must load cleanly
        legacy_repo = tempfile.mkdtemp(prefix="quiz-legacy-")
        try:
            os.makedirs(os.path.join(legacy_repo, STATE_DIR), exist_ok=True)
            legacy_state = {
                "xp": 20, "level": 1, "streak": 2, "last_active": "2026-07-15",
                "concepts": {
                    "old-concept": {
                        "title": "Old", "ef": 2.5, "interval": 6, "reps": 2,
                        "due": "2026-07-20",
                    },
                },
            }
            with open(os.path.join(legacy_repo, STATE_DIR, PROGRESS), "w",
                      encoding="utf-8") as f:
                json.dump(legacy_state, f)

            legacy_status_out = io.StringIO()
            with contextlib.redirect_stdout(legacy_status_out):
                cmd_status(legacy_repo, "2026-07-16")
            legacy_status = json.loads(legacy_status_out.getvalue())
            check("legacy progress.json loads without KeyError", legacy_status.get("xp") == 20)
            check("legacy status gets a default config",
                  legacy_status.get("config", {}).get("persona") == "mid")
            check("legacy status gets empty achievements",
                  legacy_status.get("achievements") == [])

            legacy_record_args = argparse.Namespace(
                concept="old-concept", correct="true", title=None, note=None,
                session=None, grade=None, type=None,
            )
            cmd_record(legacy_repo, legacy_record_args, "2026-07-21")
            check("legacy concept records without KeyError", True)
        finally:
            shutil.rmtree(legacy_repo, ignore_errors=True)
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


# ---------- entry ----------

def _positive_int(value):
    """argparse type: a daily goal must be a positive integer (>= 1)."""
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError("must be a positive integer (>= 1)")
    return ivalue


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
    pr.add_argument("--grade", default=None, choices=("again", "hard", "good", "easy"))
    pr.add_argument("--type", default=None, choices=tuple(TYPE_XP_WEIGHTS),
                    help="question type slug, e.g. mc/fill-blank/code-trace/"
                         "bug-hunt/why/free-recall (default: mc)")
    pr.add_argument("--title", default=None)
    pr.add_argument("--note", default=None)
    pr.add_argument("--session", default=None)

    pc = sub.add_parser("config")
    pc.add_argument("--get", action="store_true", help="print current config (default action)")
    pc.add_argument("--set-persona", default=None, choices=("junior", "mid", "senior"))
    pc.add_argument("--set-daily-goal", type=_positive_int, default=None)
    pc.add_argument("--seen-fsrs-notice", action="store_true",
                    help="mark the one-time FSRS install notice as shown")

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
    elif args.cmd == "config":
        cmd_config(args.repo, args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
