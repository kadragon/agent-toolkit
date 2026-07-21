# Out-of-Scope Review Findings

Deferred items surfaced during dev-review-cycle. Not blocking; triage later.

## capture-learnings / task-audit-nudge

The self-improve-nudge hook was retired in favor of the manual `capture-learnings`
skill; its transcript-scan logic (`detect_signals`, `encode_project`, `config_dir`)
now lives in `dev-tools/skills/capture-learnings/scripts/scan_session.py`. The
pending-file, session-marker, and SessionStart-surface items from PR #157 are moot
(no auto hook, no pending file). Residual pre-existing items below.

- [ ] **[P3] `encode_project` key collision** — `/tmp/foo.bar` and `/tmp/foo-bar` both encode to `-tmp-foo-bar` (codex C2). The verbatim `encode_project` now appears in both `task-audit-nudge` and `capture-learnings/scan_session.py`; extremely unlikely in practice. If fixed, fix both together (append a short path hash) to keep them consistent.
- [ ] **[pre-existing] `task-audit-nudge.config_dir` has the Codex/CLAUDE_PLUGIN_ROOT precedence bug** — under Codex, `CLAUDE_PLUGIN_ROOT` is set as a compat alias, so its `config_dir()` returns `~/.claude` instead of `~/.codex`. Port the CODEX_HOME-first ordering already used in `capture-learnings/scan_session.py::config_dir`.
- [ ] **[pre-existing] `detect_signals` never resets `saw_error`** — after one tool error, every later success sets `recovered=True` (agy F1). Carried verbatim into `scan_session.py`. Assess whether error→recovery should require adjacency.
