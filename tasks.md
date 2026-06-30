## Review Backlog

### PR #102 — next-tasks --tree mode + size-gate lite path (out-of-scope findings)

- [ ] [debt] `next-tasks/SKILL.md:447` — Batch mode A7 cleanup: uses `git branch -D` on ALL units (merged, dropped, conflicted). Conflicted units that completed QA but failed merge lose their implementation. Fix: use `git branch -d` for merged units; preserve conflicted branches for manual resolution. Pre-existing batch mode code, not introduced by this PR. P1 (source: agy)

---

### PR #96 — commit-guard bare switch-back review cycle (out-of-scope findings)

- [ ] `commit-guard/guard.py:_bare_switch_target` — option-value args desync the positional count: `git switch --conflict merge main` treats `merge` (the value of `--conflict`) as a positional, so `len(positionals) == 2` → returns `None` → a real switch-back to main is missed → commit on main allowed (bypass). Fail-open-consistent (matches the never-block-on-uncertainty contract) and contrived, so not a regression of this PR's new detection. Fix needs a known value-option skip-set (`--conflict`, `-t`/`--track`, …) or a more complete checkout/switch option model. P3, conf ~70. (source: agy)
- [ ] `commit-guard/guard.py:_bare_switch_target` — previous-branch / reflog ref spellings are not modeled: `git checkout -b X && git checkout - && git commit` (or `@{-1}`) switches back to the prior branch (possibly main) but `-`/`@{-1}` are skipped as flags / left untrusted, so the commit can land on main while attributed to X (bypass). Pre-existing-class gap (the whole unmodeled-switch-back family), not introduced or worsened by this PR; both filtered at 2/10 new-finding confidence by the security pass. A future hardening could reset `running_branch = None` on statically-unknown switch targets. P3. (source: codex/security)

---

### PR #93 — commit-guard static-analysis review cycle (deferred findings)

- [x] `commit-guard/guard.py` — bare switch-back is not modeled: `git checkout -b X && git checkout main && git commit` keeps `running_branch=X` across the bare `git checkout main` (only `-b/-c`/long-create flags update attribution), so a commit that lands on main is mis-attributed to X and allowed. Deferred because the fix needs bare-`checkout <ref>` handling, which is statically ambiguous (branch switch vs `checkout <pathspec>` vs `checkout -- file`) and risks false-positives that block legit commits. Contrived multi-checkout chain; dominant accidental cases stay guarded. P3, conf 95. (source: agy/codex) — **fixed v3.6.7: `_bare_switch_target` re-attributes only main/master targets (fail-toward-block), `--`/multi-positional restores excluded.**
- [x] `commit-guard/guard.py:type-guard` — single-quoted literal command substitution is treated as undecidable: `git commit -m 'wip $(date)'` passes the literal text `wip $(date)` to git (no expansion), but the `$(`/backtick substring skip fires and the type guard is bypassed, allowing a malformed subject on a feature branch. Fix needs quote-context parsing of the raw `-m` arg to distinguish single-quoted (literal → enforce type) from double/unquoted (expandable → fail-open). Branch guard still applies. P2, conf 90. (source: codex/review)

---

### PR #92 — hwpx table.py append-para/toggle-check review cycle (out-of-scope findings)

- [x] `table.py:_append_para_match` — re-runs `_locate_cell_sublist` twice (once to read the sibling style, then again inside `_append_para_cell`); a full `find_table`+`top_cells` scan repeats on the same unchanged XML. Micro-perf only on small cell strings; a fix would thread pre-resolved coords into an `_append_para_at` helper, adding complexity for negligible gain. P3, conf 100. (source: review) — **won't-fix 2026-06-22: negligible gain, adds complexity.**

---

### PR #90 — reconcile-harness strip_sprint_block review cycle (out-of-scope findings)

- [x] `reconcile-harness.py:strip_sprint_block` (and `tasks_title`) — both locate the sprint block via the first `^#\s+` heading. A fenced code block under `## Review Backlog` containing a `# comment` line above the sprint would be misparsed as the sprint heading, truncating content. Pre-existing convention (mirrors `tasks_title`); agy's narrowing fix (`# (Sprint|Bundle):`) is wrong — single-item sprint headings are the raw backlog item text, not `# Sprint:`. A correct fix would gate on the `status:`-owning section. conf ~50%, P3. (source: agy)

---

### PR #84 — agent-teams task store separation (out-of-scope findings)

- [x] `agent-teams-onboarding.md` — native store path written as `~/.claude/tasks/{team-name}/`, but Claude Code honors `CLAUDE_CONFIG_DIR` when set. File uses the `~/.claude/` convention throughout; reconcile the whole file's path display (e.g. `$CLAUDE_CONFIG_DIR/...`) in one pass rather than spot-editing. P3. (source: agy)

---

### PR #81 — consolidate-deps PR #80 fixes review cycle (out-of-scope findings)

Pre-existing items surfaced during PR #81's review; the regex/version class predates this PR (introduced in PR #80), so they were left out of scope.

- [x] `consolidate-deps.py:_replace_pinned_versions` (and `parse_group_pr_body`) — version-replace class `[\w.!+-]+` uses Unicode `\w`; a non-ASCII version token (e.g. `1.0.0α`) would match. Scope to ASCII via `re.ASCII` flag or an explicit `[A-Za-z0-9_.!+-]` class. Pre-existing (PR #80). conf ~70%, P3. (source: review)
- [x] `consolidate-deps.py:--selftest` — no assertion covers a PEP 440 epoch version (`foo==1!1.0.0` → `foo==2.0.0`) even though `!` is in the version class. Add an epoch case to `_replace_pinned_versions` and/or `parse_group_pr_body` selftest. Pre-existing behavior. conf ~60%, P3. (source: review)
