## Review Backlog

### PR #84 — agent-teams task store separation (out-of-scope findings)

- [ ] `agent-teams-onboarding.md` — native store path written as `~/.claude/tasks/{team-name}/`, but Claude Code honors `CLAUDE_CONFIG_DIR` when set. File uses the `~/.claude/` convention throughout; reconcile the whole file's path display (e.g. `$CLAUDE_CONFIG_DIR/...`) in one pass rather than spot-editing. P3. (source: agy)

---

### PR #81 — consolidate-deps PR #80 fixes review cycle (out-of-scope findings)

Pre-existing items surfaced during PR #81's review; the regex/version class predates this PR (introduced in PR #80), so they were left out of scope.

- [x] `consolidate-deps.py:_replace_pinned_versions` (and `parse_group_pr_body`) — version-replace class `[\w.!+-]+` uses Unicode `\w`; a non-ASCII version token (e.g. `1.0.0α`) would match. Scope to ASCII via `re.ASCII` flag or an explicit `[A-Za-z0-9_.!+-]` class. Pre-existing (PR #80). conf ~70%, P3. (source: review)
- [x] `consolidate-deps.py:--selftest` — no assertion covers a PEP 440 epoch version (`foo==1!1.0.0` → `foo==2.0.0`) even though `!` is in the version class. Add an epoch case to `_replace_pinned_versions` and/or `parse_group_pr_body` selftest. Pre-existing behavior. conf ~60%, P3. (source: review)

---

# Sprint: consolidate-deps ASCII version-class + epoch test (bundle of 2)

status: done

**Scope**
- `dev-tools/skills/dependabot-manager/scripts/consolidate-deps.py` — `parse_group_pr_body` regex (line 86), `_replace_pinned_versions` regex (line 144), `cmd_selftest`.

**Acceptance criteria**
- [x] #1: both version-token regexes ASCII-scoped so `\w` cannot match non-ASCII characters — `_replace_pinned_versions` (`[\w.!+-]+`) and `parse_group_pr_body` (`[\w.+-]*\w` ×2). Use `re.ASCII` flag on `re.subn`/`re.finditer`. A non-ASCII trailing token (e.g. `1.0.0α`) no longer absorbs the non-ASCII char into the matched version.
- [x] #2: `--selftest` adds a PEP 440 epoch case proving `!` survives in `_replace_pinned_versions`: `foo==1!1.0.0` with update `foo→2!2.0.0` rewrites cleanly to `foo==2!2.0.0` (no stale suffix). Plus an ASCII-boundary assertion locking in the `re.ASCII` flag.

**Out of scope**
- `.cjs` parser (no `\w` Unicode concern raised there).
- Widening/narrowing which characters are *allowed* in a version (only the ASCII scoping of `\w`).
- title-regex / `parse_package_update`.

**Lint/test command**
- `python dev-tools/skills/dependabot-manager/scripts/consolidate-deps.py --selftest`
- `node dev-tools/skills/dependabot-manager/scripts/consolidate-deps.cjs --selftest`
