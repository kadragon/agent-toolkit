#!/usr/bin/env python3
"""
Read the skill-run telemetry sink and judge each skill's success-rate trend.

This is the read half of the sink `record_skill_run.py` writes. Signal 3
("Underperforming asset") otherwise detects only from `CORRECTION-SIGNALS` — a skill
loaded, then the user pushed back — which is anecdotal and cannot be trended: it can say
a skill produced a wrong result once, never that the skill *got worse*. This script turns
the sink's rows into that trend: a recent-window success rate against a baseline-window
one, per `skill_id`.

Three verdicts, and the third is the point. `declining` is a finding. `ok` is not.
`insufficient-data` means the windows hold too few runs to support either — the sink is
young, or the skill barely ran — and it must never be reported as health, because a skill
with two recorded runs is not passing a check, it is failing to be measured. Signal 3
routes on `declining` only; see `references/signal-taxonomy.md` Section 3.

Success is `outcome == "success"`; `partial` and `failure` are both non-success. That
single numeric definition is what makes the delta interpretable — `user_feedback` is
reported alongside as context for the delegate brief, never folded into the rate.

The baseline window CONTAINS the recent one (last 30 days vs last 7, not 30-to-7 vs
last 7). The overlap damps the delta, which is deliberate: a non-overlapping baseline
swings hard on a handful of rows, and a false `declining` costs a real skill-rewrite
delegation. The cost of that choice is that a skill whose whole history sits inside the
recent window compares against itself, so the baseline must additionally hold
`min_recent` runs OLDER than the recent window before either verdict is allowed.

The sink is located through `record_skill_run.resolve_sink_dir()`, never by re-deriving
the encoded project dir — the pin it honours is the only thing keeping reader and writer
on the same file (see that module's docstring).

Usage:
  skill_run_health.py [--project PATH] [--window-days N] [--baseline-days N]
      [--threshold F] [--min-recent N] [--min-baseline N] [--json]
  skill_run_health.py --test

Exits 0 with a stderr note when the sink is absent or empty: a harness-curate run must
never break because a repo has no telemetry yet.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from record_skill_run import (  # noqa: E402
    FEEDBACK,
    SINK_FILE,
    UNKNOWN_VERSION,
    resolve_sink_dir,
)

DAY_MS = 86400000
WINDOW_DAYS = 7           # recent window
BASELINE_DAYS = 30        # baseline window, containing the recent one
THRESHOLD = 0.20          # rate drop (baseline - recent) that makes a skill `declining`
MIN_RECENT = 3            # fewer recent rows than this -> insufficient-data
MIN_BASELINE = 10         # fewer baseline rows than this -> insufficient-data
SUCCESS = "success"

DECLINING = "declining"
OK = "ok"
INSUFFICIENT = "insufficient-data"
# Report order: findings first, then the skills that could not be judged, then the
# healthy ones. A reader scanning the top of the list must not have to page past `ok`
# rows to reach the finding.
VERDICT_ORDER = {DECLINING: 0, INSUFFICIENT: 1, OK: 2}


def read_rows(path):
    """Every parseable row in the sink, plus the count of lines that were not.

    Same tolerance as `record_skill_run._trim`: one corrupt line must not blind the
    reader to the rest of the history. The count is surfaced, never swallowed — a sink
    that is mostly unparseable is a broken writer, not a healthy skill.
    """
    rows, corrupt = [], 0
    if not os.path.exists(path):
        return rows, corrupt
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                corrupt += 1
                continue
            if not isinstance(row, dict) or not isinstance(row.get("skill_id"), str):
                corrupt += 1
                continue
            if not isinstance(row.get("recorded_at"), (int, float)):
                corrupt += 1
                continue
            rows.append(row)
    return rows, corrupt


def _tally(rows):
    """(runs, successes, feedback counts) over `rows`."""
    runs = len(rows)
    successes = sum(1 for r in rows if r.get("outcome") == SUCCESS)
    feedback = {k: 0 for k in FEEDBACK}
    for r in rows:
        fb = r.get("user_feedback")
        if fb in feedback:
            feedback[fb] += 1
    return runs, successes, feedback


def judge(rows, now_ms, window_days=WINDOW_DAYS, baseline_days=BASELINE_DAYS,
          threshold=THRESHOLD, min_recent=MIN_RECENT, min_baseline=MIN_BASELINE):
    """One verdict record per `skill_id`, sorted findings-first then by id.

    Window membership is `recorded_at > now - days*DAY_MS`: a row exactly on the boundary
    is outside the window. Rows dated in the future are kept — a clock skew is not
    something to silently discard telemetry over — and land in both windows.
    """
    recent_from = now_ms - window_days * DAY_MS
    baseline_from = now_ms - baseline_days * DAY_MS

    by_skill = {}
    for row in rows:
        by_skill.setdefault(row["skill_id"], []).append(row)

    out = []
    for skill_id in sorted(by_skill):
        skill_rows = by_skill[skill_id]
        recent = [r for r in skill_rows if r["recorded_at"] > recent_from]
        baseline = [r for r in skill_rows if r["recorded_at"] > baseline_from]
        r_runs, r_ok, r_fb = _tally(recent)
        b_runs, b_ok, b_fb = _tally(baseline)

        rec = {
            "skill_id": skill_id,
            "recent_runs": r_runs,
            "recent_successes": r_ok,
            "recent_rate": (r_ok / r_runs) if r_runs else None,
            "baseline_runs": b_runs,
            "baseline_successes": b_ok,
            "baseline_rate": (b_ok / b_runs) if b_runs else None,
            "delta": None,
            "verdict": INSUFFICIENT,
            "reason": "",
            "recent_feedback": r_fb,
            "baseline_feedback": b_fb,
            # str(): the sink is a file, and a hand-edited or foreign row can carry a
            # numeric version. Sorting str against int raises, which would cost the whole
            # report over a field nothing judges.
            "versions": sorted({str(r["skill_version"]) if r.get("skill_version")
                                else UNKNOWN_VERSION for r in baseline}),
        }
        # The tail is the baseline minus the recent window. Without it there is nothing to
        # compare against: the two windows hold the same rows, the delta is structurally
        # 0.00, and a skill failing 11 of 12 recent runs would read `ok` — the measured-and-
        # fine verdict — because it is too young to have a past. That is the mislabel
        # `insufficient-data` exists to prevent, so the tail carries the same run floor as
        # the recent window.
        tail_runs = b_runs - r_runs
        if r_runs < min_recent or b_runs < min_baseline:
            rec["reason"] = (f"needs >={min_recent} runs in {window_days}d "
                             f"(has {r_runs}) and >={min_baseline} in {baseline_days}d "
                             f"(has {b_runs})")
        elif tail_runs < min_recent:
            rec["reason"] = (f"needs >={min_recent} runs older than {window_days}d to "
                             f"compare against (has {tail_runs})")
        else:
            delta = rec["recent_rate"] - rec["baseline_rate"]
            rec["delta"] = delta
            if -delta >= threshold:
                rec["verdict"] = DECLINING
                rec["reason"] = (f"{window_days}d rate is {-delta:.2f} below the "
                                 f"{baseline_days}d rate (threshold {threshold:.2f})")
            else:
                rec["verdict"] = OK
        out.append(rec)

    out.sort(key=lambda r: (VERDICT_ORDER[r["verdict"]], r["skill_id"]))
    return out


def _rate(n_ok, n):
    return f"{n_ok}/{n}" + (f" ({n_ok / n:.2f})" if n else "")


def format_rows(records, window_days, baseline_days):
    lines = []
    for r in records:
        parts = [r["skill_id"], r["verdict"],
                 f"{window_days}d={_rate(r['recent_successes'], r['recent_runs'])}",
                 f"{baseline_days}d={_rate(r['baseline_successes'], r['baseline_runs'])}"]
        if r["delta"] is not None:
            parts.append(f"delta={r['delta']:+.2f}")
        # The route brief is required to quote the feedback mix (signal-taxonomy Section 3),
        # so the default output has to carry it — not only `--json`.
        fb = ",".join(f"{k}:{v}" for k, v in sorted(r["recent_feedback"].items())
                      if v and k != "accepted")
        if fb:
            parts.append(f"fb={fb}")
        if r["reason"]:
            parts.append(f"— {r['reason']}")
        lines.append("  ".join(parts))
    return lines


def run_tests():
    import shutil
    import tempfile

    results = []

    def check(name, cond):
        results.append((name, bool(cond)))
        print(("PASS  " if cond else "FAIL  ") + name)

    now = 100 * DAY_MS

    def row(skill, days_ago, outcome, feedback="accepted", version="1.0.0"):
        return {"skill_id": skill, "skill_version": version, "outcome": outcome,
                "user_feedback": feedback, "recorded_at": now - int(days_ago * DAY_MS)}

    # a skill that was healthy for a month and fell over this week
    rows = ([row("a", 20, "success") for _ in range(20)]
            + [row("a", 2, "failure") for _ in range(5)])
    got = {r["skill_id"]: r for r in judge(rows, now)}
    check("a fallen skill reads declining", got["a"]["verdict"] == DECLINING)
    check("declining carries both window rates",
          got["a"]["recent_runs"] == 5 and got["a"]["baseline_runs"] == 25
          and got["a"]["recent_successes"] == 0 and got["a"]["baseline_successes"] == 20)
    check("delta is signed negative", got["a"]["delta"] < 0)

    # steady skill
    rows = [row("b", d, "success") for d in (1, 2, 3, 4, 5, 10, 12, 14, 20, 25, 28)]
    got = {r["skill_id"]: r for r in judge(rows, now)}
    check("a steady skill reads ok", got["b"]["verdict"] == OK)

    # too few recent rows, plenty of baseline
    rows = ([row("c", 20, "success") for _ in range(15)] + [row("c", 1, "failure")])
    got = {r["skill_id"]: r for r in judge(rows, now)}
    check("thin recent window is insufficient-data",
          got["c"]["verdict"] == INSUFFICIENT)
    check("insufficient-data states both counts in its reason",
          "has 1" in got["c"]["reason"] and "has 16" in got["c"]["reason"])

    # plenty recent, thin baseline (young sink): still not judgeable
    rows = [row("d", 1, "failure") for _ in range(5)]
    got = {r["skill_id"]: r for r in judge(rows, now)}
    check("thin baseline is insufficient-data, never a verdict",
          got["d"]["verdict"] == INSUFFICIENT)

    # `partial` is not success
    rows = ([row("e", 20, "success") for _ in range(20)]
            + [row("e", 2, "partial") for _ in range(5)])
    got = {r["skill_id"]: r for r in judge(rows, now)}
    check("partial counts as non-success", got["e"]["verdict"] == DECLINING)

    # window boundary: exactly `window_days` old is OUTSIDE the recent window
    rows = ([row("f", 7, "success") for _ in range(12)]
            + [row("f", 6.9, "success") for _ in range(3)])
    got = {r["skill_id"]: r for r in judge(rows, now)}
    check("row exactly at the window edge is excluded from recent",
          got["f"]["recent_runs"] == 3 and got["f"]["baseline_runs"] == 15)

    # rows older than the baseline window drop out of both
    rows = ([row("g", 40, "failure") for _ in range(50)]
            + [row("g", 20, "success") for _ in range(12)]
            + [row("g", 1, "success") for _ in range(4)])
    got = {r["skill_id"]: r for r in judge(rows, now)}
    check("rows past the baseline window are excluded",
          got["g"]["baseline_runs"] == 16 and got["g"]["verdict"] == OK)

    # threshold and minimums are overridable
    rows = ([row("h", 20, "success") for _ in range(18)]
            + [row("h", 2, "success") for _ in range(4)]
            + [row("h", 2, "failure") for _ in range(1)])
    check("a sub-threshold drop is ok at the default",
          judge(rows, now)[0]["verdict"] == OK)
    check("the same drop is declining at a lower threshold",
          judge(rows, now, threshold=0.05)[0]["verdict"] == DECLINING)
    check("raising min-recent forces insufficient-data",
          judge(rows, now, min_recent=99)[0]["verdict"] == INSUFFICIENT)
    check("raising min-baseline forces insufficient-data",
          judge(rows, now, min_baseline=999)[0]["verdict"] == INSUFFICIENT)

    # a skill whose whole history sits inside the recent window has nothing to compare
    # against: the windows are identical, so the delta is structurally 0.00
    rows = [row("young", 5, "failure") for _ in range(11)] + [row("young", 5, "success")]
    got = judge(rows, now)[0]
    check("an all-recent skill is insufficient-data, not ok",
          got["verdict"] == INSUFFICIENT)
    check("the all-recent reason names the missing tail",
          "older than 7d" in got["reason"] and "has 0" in got["reason"])
    check("an all-recent skill still reports its rates",
          got["recent_runs"] == 12 and got["baseline_runs"] == 12)

    # a tail at exactly the floor is judgeable
    rows = ([row("edge", 20, "success") for _ in range(3)]
            + [row("edge", 2, "success") for _ in range(9)])
    check("a tail at exactly min_recent is judged", judge(rows, now)[0]["verdict"] == OK)
    rows = ([row("edge2", 20, "success") for _ in range(2)]
            + [row("edge2", 2, "success") for _ in range(10)])
    check("a tail one under min_recent is insufficient-data",
          judge(rows, now)[0]["verdict"] == INSUFFICIENT)

    # per-skill isolation and report ordering
    rows = ([row("z-ok", d, "success") for d in range(1, 15)]
            + [row("a-bad", 20, "success") for _ in range(20)]
            + [row("a-bad", 2, "failure") for _ in range(5)]
            + [row("m-thin", 1, "success")])
    ordered = judge(rows, now)
    check("findings sort ahead of insufficient-data and ok",
          [r["verdict"] for r in ordered] == [DECLINING, INSUFFICIENT, OK])
    check("skills are tallied independently",
          {r["skill_id"] for r in ordered} == {"a-bad", "m-thin", "z-ok"})

    # feedback context is carried, not folded into the rate
    rows = ([row("i", 20, "success", "corrected") for _ in range(20)]
            + [row("i", 2, "success", "rejected") for _ in range(5)])
    got = judge(rows, now)[0]
    check("feedback is reported as context", got["recent_feedback"]["rejected"] == 5)
    check("feedback does not move the rate", got["verdict"] == OK)

    # the unknown version sentinel survives the read
    rows = ([row("j", 20, "success", version=None) for _ in range(12)]
            + [row("j", 2, "success") for _ in range(3)])
    check("missing skill_version reads as the unknown sentinel",
          judge(rows, now)[0]["versions"] == ["1.0.0", UNKNOWN_VERSION])

    tmpdir = tempfile.mkdtemp(prefix="skill-run-health-")
    try:
        # absent sink: no rows, no crash
        missing = os.path.join(tmpdir, "nope", SINK_FILE)
        got_rows, corrupt = read_rows(missing)
        check("absent sink reads as zero rows", got_rows == [] and corrupt == 0)

        # corrupt-line tolerance
        path = os.path.join(tmpdir, SINK_FILE)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(row("k", 1, "success")) + "\n")
            f.write("{not json\n")
            f.write("\n")  # blank lines are not corruption
            f.write(json.dumps({"skill_id": "k"}) + "\n")  # no recorded_at
            f.write(json.dumps(["not", "a", "dict"]) + "\n")
            f.write(json.dumps(row("k", 2, "failure")) + "\n")
        got_rows, corrupt = read_rows(path)
        check("parseable rows survive corrupt neighbours", len(got_rows) == 2)
        check("unparseable and malformed lines are counted", corrupt == 3)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(
        description="Trend skill success rates from the run-telemetry sink (Signal 3).")
    ap.add_argument("--project", default=None, help="repo path (default: cwd)")
    ap.add_argument("--window-days", type=int, default=WINDOW_DAYS,
                    help=f"recent window (default {WINDOW_DAYS})")
    ap.add_argument("--baseline-days", type=int, default=BASELINE_DAYS,
                    help=f"baseline window, contains the recent one "
                         f"(default {BASELINE_DAYS})")
    ap.add_argument("--threshold", type=float, default=THRESHOLD,
                    help=f"rate drop that makes a skill declining "
                         f"(default {THRESHOLD})")
    ap.add_argument("--min-recent", type=int, default=MIN_RECENT,
                    help=f"minimum recent-window runs (default {MIN_RECENT})")
    ap.add_argument("--min-baseline", type=int, default=MIN_BASELINE,
                    help=f"minimum baseline-window runs (default {MIN_BASELINE})")
    ap.add_argument("--json", action="store_true", help="emit the records as JSON")
    ap.add_argument("--test", action="store_true", help="run self-tests")
    a = ap.parse_args()

    if a.test:
        return run_tests()
    if a.window_days < 1 or a.baseline_days < a.window_days:
        ap.error("--baseline-days must be >= --window-days >= 1")
    if not 0 < a.threshold <= 1:
        ap.error("--threshold must be in (0, 1]")
    if a.min_recent < 1 or a.min_baseline < 1:
        # A zero or negative floor does not "disable the gate" — it lets a skill with no
        # rows in a window reach the delta arithmetic with no rate to subtract.
        ap.error("--min-recent and --min-baseline must be >= 1")

    project = os.path.abspath(a.project or os.getcwd())
    sink_dir, warning, _ = resolve_sink_dir(project)
    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    path = os.path.join(sink_dir, SINK_FILE)

    rows, corrupt = read_rows(path)
    if corrupt:
        print(f"warning: skipped {corrupt} unparseable line(s) in {path}", file=sys.stderr)
    if not rows:
        # Not an error: a repo whose cycle tails have not run yet has no telemetry, and a
        # harness-curate run must not break on that.
        print(f"no skill-run telemetry recorded yet ({path})", file=sys.stderr)
        if a.json:
            print("[]")
        return 0

    records = judge(rows, int(time.time() * 1000),
                    window_days=a.window_days, baseline_days=a.baseline_days,
                    threshold=a.threshold, min_recent=a.min_recent,
                    min_baseline=a.min_baseline)
    if a.json:
        print(json.dumps(records, indent=2, sort_keys=True))
    else:
        print(f"sink: {path}  rows: {len(rows)}")
        for line in format_rows(records, a.window_days, a.baseline_days):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
