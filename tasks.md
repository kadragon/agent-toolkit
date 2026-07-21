# Out-of-Scope Review Findings

Deferred items surfaced during task-review. Not blocking; triage later.

## Plugin validation

- [ ] **[P2] `dev/skills/task-review/SKILL.md` frontmatter fails Claude plugin validation** — `claude plugin validate ./dev` reports a YAML parse error and drops all metadata. Quote or fold the `description:` scalar, then add validator coverage.

## task-audit-nudge

The self-improve-nudge hook was retired for the manual `harness-capture` skill,
which is now scriptless (reflects on the live conversation — no transcript parse).
So the `detect_signals` / `encode_project` / `config_dir` items that were carried
into its old `scan_session.py` are moot for this skill. `task-audit-nudge` still
has its own copies; residual items below.

- [ ] **[P3] `encode_project` key collision** — `/tmp/foo.bar` and `/tmp/foo-bar` both encode to `-tmp-foo-bar` (codex C2). The verbatim `encode_project` lives in `task-audit-nudge` and `harness-curate/scan_transcripts.py`; extremely unlikely in practice. If fixed, fix both together (append a short path hash) to keep them consistent.
- [ ] **[pre-existing] `task-audit-nudge.config_dir` has the Codex/CLAUDE_PLUGIN_ROOT precedence bug** — under Codex, `CLAUDE_PLUGIN_ROOT` is set as a compat alias, so its `config_dir()` returns `~/.claude` instead of `~/.codex`. Fix: check `CODEX_HOME` (and a `/.codex/` script path) before falling back to the Claude default.
