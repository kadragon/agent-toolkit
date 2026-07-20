# Out-of-Scope Review Findings

Deferred items surfaced during dev-review-cycle. Not blocking; triage later.

## self-improve-nudge defer (PR #157)

- [ ] **[P3] Concurrent same-cwd sessions overwrite the pending nudge** — `nudge.py` writes `open(path, "w")`; if two sessions on the same project both Stop before either restarts, the second clobbers the first's signals (flagged independently by agy + codex). Accepted as a best-effort tradeoff for now (once-per-project nudge; loss collapses two nudges into one, no user-visible harm). Fix if it ever matters: merge/union signals with an existing fresh pending file before writing, or key per-session and drain all on surface.
- [ ] **[P3] `encode_project` key collision** — `/tmp/foo.bar` and `/tmp/foo-bar` both encode to `-tmp-foo-bar` (codex C2). Mirrors the verbatim `encode_project` in `task-audit-nudge`; extremely unlikely in practice. If fixed, fix both hooks together (append a short path hash) to keep them consistent.
- [ ] **[pre-existing] `task-audit-nudge.config_dir` has the same Codex/CLAUDE_PLUGIN_ROOT precedence bug** fixed in `self-improve-nudge/_common.py` (PR #157) — under Codex, `CLAUDE_PLUGIN_ROOT` is set as a compat alias, so its `config_dir()` returns `~/.claude` instead of `~/.codex`. Port the CODEX_HOME-first fix there.
- [ ] **[pre-existing] `detect_signals` never resets `saw_error`** — after one tool error, every later success sets `recovered=True` (agy F1). Pre-existing in `nudge.py`, not touched by PR #157. Assess whether error→recovery should require adjacency.
- [ ] **[pre-existing] `nudge-markers/` never cleaned up** — `~/.claude/tmp/nudge-markers/<session_id>.nudged` accumulates one empty file per session (agy F2). `surface.py` (SessionStart) is a natural place to opportunistically prune markers older than N days.
