# Dispatch quota inputs

## Claude quota snapshot

Each home repo's Claude status line runs its own local `quota.py --capture` with the
status-line JSON on stdin. Keep the status-line command pointed at that local script so
plugin updates and versioned cache paths do not affect it. Dispatch runs the bundled
`scripts/quota.py` to read the snapshot.

The writer and reader use `~/.claude/state/quota-claude.json` by default. To use a different
file, set `QUOTA_CLAUDE_CACHE` to the same path in both the status-line and dispatch
environments. The writer atomically replaces the snapshot after receiving a valid
`rate_limits.seven_day` window. It includes `rate_limits.five_hour` when valid.

```json
{
  "used": 42,
  "reset": 1795843200,
  "observed": 1795224000,
  "five_hour": {
    "used": 17,
    "reset": 1795242000,
    "observed": 1795224000
  }
}
```

`used` is a numeric percentage from 0 to 100. `reset` and `observed` are Unix timestamps
in seconds. The top-level fields describe the weekly window; `five_hour` is optional and
uses the same fields. If the file is missing, unreadable, or invalid JSON, the reader emits
`"claude": {"state": "unknown"}` and evaluates Codex independently.

## Quota states

Dispatch classifies either CLI as `critical` when actual usage in an active weekly or
five-hour window reaches 90%. Actual weekly usage from 75% and five-hour usage from 80%
are `hot` below the critical threshold. From 24 hours into the weekly window, pace also
qualifies as `hot` if `ahead` (usage minus elapsed percentage) is at least 15 percentage
points or the straight-line projection at reset exceeds 120%. The reader still reports
`runway_h` whenever it can estimate hours to 100%, including during the first 24 hours.

## Codex reset passes

Maintain `$CODEX_HOME/reset-passes.json` by hand. When `CODEX_HOME` is unset, use
`~/.codex/reset-passes.json`. Store one ISO-8601 expiry timestamp per pass in a JSON array,
with `T` between the date and time. Use explicit offsets such as `Z` or `+09:00`. The reader
interprets timestamps without an offset as UTC.

```json
["2026-12-01T09:00:00+09:00", "2026-12-14T00:00:00Z"]
```

Missing, unreadable, or malformed files count as zero passes. An invalid entry makes the
whole file malformed. Remove a pass from the file after redeeming it.

The Codex output includes `reset_passes`, the number of expiries strictly after the current
time. Any positive count lowers Codex's assessed state one step before bias is computed
(`critical` to `hot`, `hot` to `ok`). The `ok` and `unknown` states and reported usage and runway
stay as assessed.

`reset_passes_before_weekly_reset` lists the original expiry strings for unexpired passes
that expire strictly before the weekly window's `resets_at`, earliest expiry first. Prefer
these passes when redeeming one. The list is empty if the upcoming reset is unknown.
