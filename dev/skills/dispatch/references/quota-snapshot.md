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
uses the same fields. If the file is missing, unreadable, invalid JSON, or lacks a valid weekly
`used`, `reset`, or `observed`, the reader emits Claude `state: unknown` and evaluates Codex
independently. An invalid `five_hour` object is ignored. A Claude status-line draw refreshes
its snapshot. Codex updates its snapshot during a session and may report only the weekly window.

## Quota states

Dispatch classifies either CLI as `critical` when actual usage in an active weekly or
five-hour window reaches 90%. Actual weekly usage from 75% and five-hour usage from 80%
are `hot` below the critical threshold. From 24 hours into the weekly window, pace also
qualifies as `hot` if `ahead` (usage minus elapsed percentage) is at least 15 percentage
points or the straight-line projection at reset exceeds 120%. The reader still reports
`runway_h` whenever it can estimate hours to 100%, including during the first 24 hours.

## Reset passes

Each CLI uses a `reset-passes.json` array with one ISO-8601 expiry per pass. Use `T` and an
explicit offset such as `Z` or `+09:00`. The reader interprets timestamps without an offset
as UTC.

```json
["2026-12-01T09:00:00+09:00", "2026-12-14T00:00:00Z"]
```

Missing, unreadable, or malformed files count as zero passes. An invalid entry makes the whole
file malformed.

Maintain Claude's file in `$CLAUDE_CONFIG_DIR` or `~/.claude` by hand. Remove a pass from it after
redemption.

Codex stores its file in `$CODEX_HOME` or `~/.codex`. Wave planning calls
`quota.py --refresh-if-stale` before calculating routing. It checks the recorded success time and
refreshes when it is missing or at least 24 hours old, or when the cache file is missing. Launch
and ordinary quota reads use the local cache. After redeeming a Codex pass, force a refresh with
`python3 -I "<dispatch>/scripts/quota.py" --refresh-codex-reset-passes`.

Refreshes are serialized and use the Codex app server's read-only `account/rateLimits/read`
with a 15-second request deadline. Valid details replace the array atomically. An explicit zero
writes an empty array. If Codex is unavailable or the response is unsupported or incomplete,
the existing file is retained. The warning reports the last successful refresh age, or the file
age for a manually maintained cache when available. Planning still prints the routing snapshot.
The manual refresh command exits with status 1 on failure.

Each CLI reports `reset_passes`, the number of expiries strictly after the current time.
Any positive count lowers the assessed state one step for routing (`critical` to `hot`,
`hot` to `ok`). When this happens, `raw_state` retains the original assessment for the critical
approval gate. Usage and runway are the values from the snapshot.

`reset_passes_before_weekly_reset` lists the original expiry strings for unexpired passes
that expire strictly before the weekly window's `resets_at`, earliest expiry first. Prefer
these passes when redeeming one. The list is empty if the upcoming reset is unknown or has passed.

When neither CLI is hot, passes expiring before the reset favor their CLI if only one CLI
has them. A quota-driven preference takes precedence. For `both-hot`, `effective_bias`
favors the only CLI that can run without critical approval. If both can run, it favors the
longer weekly runway when both estimates are available and differ. If both require approval,
it leaves the choice to the user. If the favored CLI is `ok` and has expiring passes,
`prefer_expiring_passes` tightens the routing exceptions.
The launcher warns when a snapshot is unknown. It skips the routing gate for that CLI and
when the preferred CLI's snapshot is unknown. A known critical state still requires approval.
If the quota helper fails or returns invalid output, the launcher warns and proceeds without
a quota decision.
