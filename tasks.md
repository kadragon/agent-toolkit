## Review Backlog

### PR #84 — agent-teams task store separation (out-of-scope findings)

- [x] `agent-teams-onboarding.md` — native store path written as `~/.claude/tasks/{team-name}/`, but Claude Code honors `CLAUDE_CONFIG_DIR` when set. File uses the `~/.claude/` convention throughout; reconcile the whole file's path display (e.g. `$CLAUDE_CONFIG_DIR/...`) in one pass rather than spot-editing. P3. (source: agy)

---

### PR #81 — consolidate-deps PR #80 fixes review cycle (out-of-scope findings)

Pre-existing items surfaced during PR #81's review; the regex/version class predates this PR (introduced in PR #80), so they were left out of scope.

- [x] `consolidate-deps.py:_replace_pinned_versions` (and `parse_group_pr_body`) — version-replace class `[\w.!+-]+` uses Unicode `\w`; a non-ASCII version token (e.g. `1.0.0α`) would match. Scope to ASCII via `re.ASCII` flag or an explicit `[A-Za-z0-9_.!+-]` class. Pre-existing (PR #80). conf ~70%, P3. (source: review)
- [x] `consolidate-deps.py:--selftest` — no assertion covers a PEP 440 epoch version (`foo==1!1.0.0` → `foo==2.0.0`) even though `!` is in the version class. Add an epoch case to `_replace_pinned_versions` and/or `parse_group_pr_body` selftest. Pre-existing behavior. conf ~60%, P3. (source: review)
