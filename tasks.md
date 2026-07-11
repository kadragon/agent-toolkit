# Tasks

## Review Backlog

### PR #133 — [HARNESS] make skill paths cross-platform (2026-07-11)

- [ ] [harness] `check_plugin_root_portability` scans full markdown text, so a prose-only mention of `CLAUDE_PLUGIN_ROOT`/`PLUGIN_ROOT` (e.g. migration notes) hard-fails CI; if a legitimate prose mention is ever needed, scope the scan to fenced blocks + inline code spans instead of loosening to fences only (source: agy) — scripts/ci/check_harness_drift.py:191
