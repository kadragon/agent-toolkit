"""Weekly and 5-hour quota pace for dispatch: which CLI has room for the next wave.

Uses server-reported limits and locally tracked reset passes.
- Claude: read the snapshot written by the home repo's status line. See
  references/quota-snapshot.md for the file contract.
- Codex: the latest token_count.rate_limits event in recent session JSONL files
  under $CODEX_HOME (default ~/.codex), plus reset-passes.json in that directory.

Without arguments it prints one JSON object:
  {"claude": {...}, "codex": {...}, "bias": "none|codex|claude|both-hot",
   "effective_bias": "none|codex|claude", "prefer_expiring_passes": true|false}
Each CLI gets used (weekly percent), elapsed (percent of its 7-day window),
ahead (used - elapsed), reset_in_h, runway_h (hours to 100% at the weekly pace,
null when there is no estimate), age_h (snapshot age), five_hour_used when
reported, and state ok|hot|critical|unknown.
Each CLI also gets reset_passes and reset_passes_before_weekly_reset.
"""
import datetime as dt
import json
import math
import os
import time
from pathlib import Path

WEEK = 7 * 24 * 3600
CLAUDE_CACHE = Path(os.environ.get(
    "QUOTA_CLAUDE_CACHE", str(Path.home() / ".claude" / "state" / "quota-claude.json")))
HOT_USED = 75
CRITICAL_USED = 90
HOT_5H = 80
CRITICAL_5H = 90
MIN_PACE_HOURS = 24
HOT_AHEAD = 15
HOT_PROJECTED = 120
RANK = {"ok": 0, "hot": 1, "critical": 2}


def finite(value):
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) \
            and math.isfinite(value)
    except OverflowError:
        return False


def window(value, percent_key, observed, reset_key="resets_at"):
    if not isinstance(value, dict):
        return None
    percent, reset = value.get(percent_key), value.get(reset_key)
    if not finite(percent) or not 0 <= percent <= 100 or not finite(reset):
        return None
    return {"used": percent, "reset": reset, "observed": observed}


def claude_snapshot(path=CLAUDE_CACHE):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    observed = data.get("observed")
    if not finite(observed):
        return None
    snap = window(data, "used", observed, "reset")
    if snap and isinstance(data.get("five_hour"), dict):
        short = window(data["five_hour"], "used", observed, "reset")
        if short:
            snap["five_hour"] = short
    return snap


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_snapshot(home=None):
    home = Path(home) if home else codex_home()
    today = dt.datetime.now(dt.timezone.utc).date()
    files = []
    for days in range(9):
        day = today - dt.timedelta(days=days)
        for path in (home / "sessions" / day.strftime("%Y/%m/%d")).glob("*.jsonl"):
            try:
                files.append((path.stat().st_mtime, path))
            except OSError:
                continue
    latest = None
    for _, path in sorted(files, key=lambda entry: entry[0], reverse=True)[:40]:
        try:
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 512 * 1024))
                lines = stream.read().splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if b'"rate_limits"' not in line:
                continue
            try:
                event = json.loads(line)
                payload = event.get("payload") or {}
                rate = payload.get("rate_limits") or {}
                if event.get("type") != "event_msg" or payload.get("type") != "token_count" \
                        or rate.get("limit_id") not in (None, "codex"):
                    continue
                observed = dt.datetime.fromisoformat(
                    event["timestamp"].replace("Z", "+00:00")).timestamp()
                windows = {v.get("window_minutes"): v for k in ("primary", "secondary")
                           if isinstance((v := rate.get(k)), dict)}
                if 10080 not in windows:
                    continue
                snap = window(windows[10080], "used_percent", observed)
                if snap and 300 in windows:
                    short = window(windows[300], "used_percent", observed)
                    if short:
                        snap["five_hour"] = short
                if snap and (latest is None or snap["observed"] > latest["observed"]):
                    latest = snap
                break
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
    return latest


def reset_passes(home, now):
    try:
        values = json.loads((home / "reset-passes.json").read_text(encoding="utf-8-sig"))
        if not isinstance(values, list):
            return []
        unexpired = []
        for value in values:
            if not isinstance(value, str) or "T" not in value:
                return []
            expiry = dt.datetime.fromisoformat(value)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=dt.timezone.utc)
            timestamp = expiry.timestamp()
            if timestamp > now:
                unexpired.append((timestamp, value))
        return sorted(unexpired, key=lambda item: item[0])
    except (OSError, ValueError, OverflowError, RecursionError):
        return []


def assess(snapshot, now):
    if not snapshot:
        return {"state": "unknown"}
    used, reset, observed = snapshot["used"], snapshot["reset"], snapshot["observed"]
    reset_in_h = max(0.0, reset - now) / 3600
    if reset <= now:
        used, elapsed_h = 0.0, 0.0
    else:
        elapsed_h = max(0.0, WEEK - (reset - now)) / 3600
    elapsed = 100.0 * elapsed_h / (WEEK / 3600)
    ahead = used - elapsed
    runway_h = None
    if used == 100:
        runway_h = 0.0
    elif used > 0 and elapsed_h > 0:
        runway_h = elapsed_h * (100 - used) / used
    pace_hot = elapsed_h >= MIN_PACE_HOURS and (
        ahead >= HOT_AHEAD or used > HOT_PROJECTED * elapsed_h / (WEEK / 3600)
    )
    if used >= CRITICAL_USED:
        state = "critical"
    elif used >= HOT_USED or pace_hot:
        state = "hot"
    else:
        state = "ok"
    result = {"used": round(used, 1)}
    short = snapshot.get("five_hour")
    if isinstance(short, dict) and short.get("reset", 0) > now:
        short_used = short["used"]
        short_state = "critical" if short_used >= CRITICAL_5H else "hot" if short_used >= HOT_5H else "ok"
        if RANK[short_state] > RANK[state]:
            state = short_state
        result["five_hour_used"] = round(short_used, 1)
        result["five_hour_reset_in_h"] = round((short["reset"] - now) / 3600, 1)
    return {
        "state": state,
        **result,
        "elapsed": round(elapsed, 1),
        "ahead": round(ahead, 1),
        "reset_in_h": round(reset_in_h, 1),
        "runway_h": round(runway_h, 1) if runway_h is not None and math.isfinite(runway_h) else None,
        "age_h": round((now - observed) / 3600, 1),
    }


def bias(claude, codex):
    tight = {"hot", "critical"}
    c, x = claude["state"] in tight, codex["state"] in tight
    if c and x:
        return "both-hot"
    if c:
        return "codex"
    if x:
        return "claude"
    c = bool(claude["reset_passes_before_weekly_reset"])
    x = bool(codex["reset_passes_before_weekly_reset"])
    if c != x:
        return "claude" if c else "codex"
    return "none"


def assess_with_passes(snapshot, home, now):
    result = assess(snapshot, now)
    passes = reset_passes(home, now)
    result["reset_passes"] = len(passes)
    result["reset_passes_before_weekly_reset"] = [
        value for expiry, value in passes if snapshot and expiry < snapshot["reset"]
    ]
    lowered = {"critical": "hot", "hot": "ok"}
    if passes and result["state"] in lowered:
        result["raw_state"] = result["state"]
        result["state"] = lowered[result["state"]]
    return result


def main():
    now = time.time()
    home = codex_home()
    clis = {"claude": assess_with_passes(claude_snapshot(), claude_home(), now),
            "codex": assess_with_passes(codex_snapshot(home), home, now)}
    routing = bias(**clis)
    effective = routing
    if routing == "both-hot":
        effective = "none"
        eligible = [cli for cli, quota in clis.items() if quota.get("raw_state", quota["state"]) != "critical"]
        claude_runway, codex_runway = (clis[cli]["runway_h"] for cli in ("claude", "codex"))
        if len(eligible) == 1:
            effective = eligible[0]
        elif eligible and claude_runway is not None and codex_runway is not None and claude_runway != codex_runway:
            effective = "claude" if claude_runway > codex_runway else "codex"
    preferred = clis.get(effective, {})
    print(json.dumps({**clis, "bias": routing, "effective_bias": effective,
                      "prefer_expiring_passes": bool(preferred.get("state") == "ok"
                                                     and preferred["reset_passes_before_weekly_reset"])}))


if __name__ == "__main__":
    main()
