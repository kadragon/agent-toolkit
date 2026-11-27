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
import argparse
import datetime as dt
import errno
import json
import math
import os
import sys
import tempfile
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
RESET_PASS_REFRESH_AGE = 24 * 3600
RESET_PASS_LOOKUP_TIMEOUT = 15


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


def read_codex_reset_passes(home):
    # The launcher runs this script in isolated mode, which omits the script directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from codex_app_server import request

    result = request("codex", home, "account/rateLimits/read", {"excludeResetCreditDetails": False},
                     timeout=RESET_PASS_LOOKUP_TIMEOUT)
    summary = result.get("rateLimitResetCredits") if isinstance(result, dict) else None
    count = summary.get("availableCount") if isinstance(summary, dict) else None
    if type(count) is not int or count < 0:
        raise ValueError("Codex response has no valid available reset-credit count")
    if count == 0:
        return []
    rows = summary.get("credits")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Codex response has no reset-credit details")
    expiries = {}
    for row in rows:
        if row.get("status") != "available" or row.get("resetType") != "codexRateLimits":
            continue
        credit_id, expiry = row.get("id"), row.get("expiresAt")
        if not isinstance(credit_id, str) or not credit_id or credit_id in expiries:
            raise ValueError("Codex response has an invalid or duplicate reset-credit ID")
        if type(expiry) is not int or expiry <= 0:
            raise ValueError("Codex response has a reset credit without a valid expiry")
        expiries[credit_id] = expiry
    if len(expiries) != count:
        raise ValueError("Codex reset-credit details do not match the available count")
    return [dt.datetime.fromtimestamp(expiry, dt.timezone.utc).isoformat().replace("+00:00", "Z")
            for expiry in sorted(expiries.values())]


def lock_reset_pass_cache(lock):
    if os.name == "nt":
        import msvcrt

        # LK_LOCK retries for up to ten seconds and the handle releases it on close.
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    deadline = time.monotonic() + RESET_PASS_LOOKUP_TIMEOUT
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for the Codex reset-pass cache lock") from None
            time.sleep(0.05)


def file_mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def refresh_codex_reset_passes(home, *, force=False):
    cache = home / "reset-passes.json"
    refreshed = home / "reset-passes.refreshed"
    try:
        home.mkdir(parents=True, exist_ok=True)
        with (home / "reset-passes.lock").open("a+b") as lock:
            lock_reset_pass_cache(lock)
            last_success = file_mtime(refreshed)
            if (not force and last_success is not None and cache.is_file()
                    and 0 <= time.time() - last_success < RESET_PASS_REFRESH_AGE):
                return True
            expiries = read_codex_reset_passes(home)
            temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=home, delete=False)
            temporary_path = Path(temporary.name)
            try:
                with temporary:
                    json.dump(expiries, temporary)
                    temporary.write("\n")
                temporary_path.replace(cache)
            finally:
                temporary_path.unlink(missing_ok=True)
            try:
                refreshed.touch()
            except OSError as error:
                print(f"warning: Codex reset-pass cache updated but could not record refresh time ({error})",
                      file=sys.stderr)
    except (OSError, ValueError, OverflowError, RuntimeError) as error:
        last_success = file_mtime(refreshed)
        cache_time = file_mtime(cache)
        now = time.time()
        if last_success is not None:
            age = f"last successful refresh {max(0, now - last_success) / 3600:.1f}h ago"
        elif cache_time is not None:
            age = f"cache file age {max(0, now - cache_time) / 3600:.1f}h"
        else:
            age = "cache age unknown"
        print(f"warning: Codex reset-pass refresh failed ({error}); using cached passes ({age})", file=sys.stderr)
        return False
    return True


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


def main(argv=()):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh-if-stale", action="store_true", help="refresh stale Codex passes before wave planning")
    mode.add_argument("--refresh-codex-reset-passes", action="store_true", help="force an immediate Codex pass refresh")
    args = parser.parse_args(argv)
    home = codex_home()
    if args.refresh_codex_reset_passes:
        return 0 if refresh_codex_reset_passes(home, force=True) else 1
    if args.refresh_if_stale:
        refresh_codex_reset_passes(home)
    now = time.time()
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
    if effective in clis and clis[effective]["state"] == "unknown":
        effective = "none"
    preferred = clis.get(effective, {})
    print(json.dumps({**clis, "bias": routing, "effective_bias": effective,
                      "prefer_expiring_passes": bool(preferred.get("state") == "ok"
                                                     and preferred["reset_passes_before_weekly_reset"])}))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
