# Claude quota snapshot

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
