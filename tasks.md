# Tasks

## Review Backlog

### PR #45 — dev-review-cycle: hub adapter (GitHub/Forgejo) + review-quality upgrades (2026-06-11)

- [ ] [debt] `hub.sh` callers — `2>/dev/null` on hub.sh invocations (preflight.sh, commit-and-push.sh, ci-wait.sh) discards stderr diagnostics; on failure callers see only `{}` and lose the cause. Fix: capture stderr to a var/file and surface it in error JSON. (source: agy) — P2
- [ ] [debt] `hub.sh:30` — scp-style remotes with non-`git` ssh users (`forgejo@host:owner/repo`) miss the `git@*` pattern → HUB_TYPE=none. Fix: order url patterns http(s) → ssh:// → `*@*:*`. (source: agy) — P2
- [ ] [debt] `hub.sh:47` — GitHub Enterprise hosts (`github.company.com`) classified as forgejo; regresses gh-authenticated GHE workflows. Fix: probe `gh auth status --hostname $HOST` before falling back to forgejo. (source: codex) — P2
- [ ] [debt] `hub.sh:64` — Forgejo PAT passed in curl argv (`-H "Authorization: token …"`), visible via process list to local users. Fix: pass header via `--config`/stdin file. Low risk single-user tool. (source: security-review) — P3
- [ ] [debt] `hub.sh` — HUB_TYPE=none falls into the forgejo else-branch of operational subcommands → misleading "no token" error instead of "no remote". Fix: shared early guard. (source: pr-review-toolkit:review-pr) — P3
- [ ] [harness] `ci-wait.sh` — NO_CHECKS_GRACE_SECS=90 may be short for slow CI registration; make configurable via env (e.g. DRC_NO_CHECKS_GRACE_SECS). (source: pr-review-toolkit:review-pr) — P3

### PR #44 — harness-curator repo-fit plugin disable (2026-06-11)

- [ ] [debt] `loop-engineer/SKILL.md:37` — `/tmp/loop-engineer-<slug>.md` ledger collides in multi-user hosts (another user owns the file → `PermissionError` on write). Fix: per-user temp dir (`tempfile.gettempdir()` / `$TMPDIR`) or include uid in the name. (source: agy) — P2
- [ ] [debt] `loop-engineer/SKILL.md` — abnormal loop exit leaves a stale ledger; a later loop on the same artifact may mis-detect it as a resumable session. Fix: on start, purge a stale ledger unless the user explicitly requested resume. (source: agy) — P3

### PR #36 — hwpx: Now-backlog debt (2026-06-09)

- [ ] [debt] `build.py:cmd_analyze` — `"TABLE id=" in result` sentinel fragile; if `_analyze_section` format string changes, `--table-id` silently breaks. Fix: `_analyze_section` returns `(str, bool)` or separate `_section_has_table(root, id) -> bool`. (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/build.py:530`
- [ ] [debt] `build.py:cmd_analyze` — `--table-id` mode prints `_analyze_section` document-structure metadata header for every matching section, cluttering output. Fix: strip header from `table_id_filter` result path or refactor `_analyze_section` to skip metadata when filter is active. (source: agy) — `productivity/skills/hwpx/scripts/build.py:528`
- [ ] [debt] `_common.py:18` — `SECTION_RE` (non-capturing) unused outside `_common` now that `validate.py` uses `SECTION_N_RE` directly. Replace `SECTION_RE` with `SECTION_N_RE` in `get_ids_from_hwpx` and delete the `SECTION_RE` definition to reduce duplication. (source: pr-review-toolkit:review-pr) — `productivity/skills/hwpx/scripts/_common.py:18`

### PR #40 — fix: agy review silent failure on Windows (2026-06-10)

- [ ] [debt] `agy-review.sh` — Linux/Mac non-TTY context also silently loses agy output if agy uses platform-specific console rendering there too; no guard added for non-Windows platforms. (source: inline) — `dev-tools/skills/dev-review-cycle/scripts/agy-review.sh`
- [ ] [constraint] `preflight.sh` — no test coverage for the new Windows agy-disable branch; manual smoke test only. (source: code-review, pr-review-toolkit:review-pr) — `dev-tools/skills/dev-review-cycle/scripts/preflight.sh`

### PR #42 — refactor: compact skill descriptions (2026-06-10)

- [ ] [trigger] `dev-review-cycle/SKILL.md:3` — "full PR review and merge" dropped; trigger-router regex `pr.*review` covers it, but description-only matching is narrowed. Low risk. (source: pr-review-toolkit:review-pr)
- [ ] [trigger] `loop-engineer/SKILL.md:3` — "refine until convergent" and catch-all fuzzy directive dropped; remaining triggers cover most cases. (source: pr-review-toolkit:review-pr)

### PR #41 — feat(dev-review-cycle): consolidation re-verify, approval-bias, trivial short-circuit (2026-06-10)

- [ ] [harness] `plugin.json` — version bumped to `3.2.0` but AGENTS.md semver rule says skill modification = patch; correct value is `3.1.2`. Fix: `bash scripts/bump-version.sh dev-tools patch` and re-release. (source: agy, codex) — `dev-tools/.claude-plugin/plugin.json:4`
- [ ] [doc] `SKILL.md:14` — `--auto` argument description says "apply all in-scope suggestions" but after approval-bias gate P2/P3 in-scope items are routed to backlog, not applied. Update to reflect P0/P1-only apply. (source: pr-review-toolkit:review-pr) — `dev-tools/skills/dev-review-cycle/SKILL.md:14`
