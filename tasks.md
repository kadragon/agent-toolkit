## Review Backlog

### PR #81 — consolidate-deps PR #80 fixes review cycle (out-of-scope findings)

Pre-existing items surfaced during PR #81's review; the regex/version class predates this PR (introduced in PR #80), so they were left out of scope.

- [ ] `consolidate-deps.py:_replace_pinned_versions` (and `parse_group_pr_body`) — version-replace class `[\w.!+-]+` uses Unicode `\w`; a non-ASCII version token (e.g. `1.0.0α`) would match. Scope to ASCII via `re.ASCII` flag or an explicit `[A-Za-z0-9_.!+-]` class. Pre-existing (PR #80). conf ~70%, P3. (source: review)
- [ ] `consolidate-deps.py:--selftest` — no assertion covers a PEP 440 epoch version (`foo==1!1.0.0` → `foo==2.0.0`) even though `!` is in the version class. Add an epoch case to `_replace_pinned_versions` and/or `parse_group_pr_body` selftest. Pre-existing behavior. conf ~60%, P3. (source: review)

### PR #80 — consolidate-deps review-backlog fixes (out-of-scope findings)

Out-of-scope items surfaced during PR #80's review cycle. Behavior changes / refactors that need their own design pass, not part of the 5 bundled fixes.

- [x] `consolidate-deps.py:update_pip_tools_dependencies` / `update_requirements_txt` — `re.sub` silently no-ops when the package isn't found in the file (zero replacements → still reports success, commits stale versions). Use `re.subn` and warn/fail on `count == 0`. Caveat: pip-tools transitive deps legitimately absent from `requirements.in`, so a hard `raise` would over-abort — needs warn-vs-raise design. conf ~75%, P2. (source: agy)
- [x] `consolidate-deps.py:run_tests` — pip/pip-tools branch runs bare `pytest`, which may resolve to a global binary instead of the project venv. Use `python -m pytest`. conf ~70%, P2. (source: agy)
- [x] `consolidate-deps.py:update_uv_dependencies` — return contract inconsistent with sibling updaters: `return True` is unreachable on failure (relies on raise→main cleanup) while `update_pip_tools_dependencies`/`update_requirements_txt` return `bool`. Pick one contract across all updaters. conf ~82%, P2. (source: review)

### PR #79 — dependabot-manager consolidate group-PR parsing (out-of-scope, pre-existing)

These live in `consolidate-deps.py` functions untouched by PR #79; surfaced by Antigravity/review during that PR's review cycle. All pre-existing, not introduced by the group-PR parser work.

- [x] `consolidate-deps.py` `update_pip_tools_dependencies` / `update_requirements_txt` — version-replace regex `{pkg}==[\d\.]+` lacks a line-start anchor, so package `foo` can match inside `bar-foo==...`. Use `(?m)^{re.escape(pkg)}==`. conf ~85%, P1. (source: agy)
- [x] `consolidate-deps.py` same regex assumes numeric-only versions `[\d\.]+`; pre-release/local versions (`1.0.0b1`, `2.0.0-beta.3`) leave a stale suffix. Widen the version class. conf ~85%, P1. (source: agy)
- [x] `consolidate-deps.py:run_tests` — pip/pip-tools branch runs `pytest` with `check=False`, so a failing test suite is treated as success and the script proceeds to push. Drop `check=False` for the test invocation. conf ~90%, P1. (source: agy)
- [x] `consolidate-deps.py:update_uv_dependencies` — `uv add` runs with `check=False`; a failed add is swallowed and consolidation proceeds with a stale/incomplete lock. conf ~90%, P2. (source: agy)
- [x] `consolidate-deps.{py,cjs}` — no test harness locks the Dependabot grouped-PR body format the parser depends on (case-sensitive `Updates` anchor). Add a fixture-based `--selftest` so a format/casing drift fails loudly instead of silently routing every group PR to the WARNING path. conf ~75%, P2. (source: review)

### PR #77 — persona-debate reproducible --seed (DuckDB reservoir)

- [x] `sample_personas.py:cmd_test` — inner `sample()` closure references module-level `sample_sql` implicitly; fragile if the function is ever moved/renamed. conf 88%, P3. Pass `sample_sql` as a param or reference via module. (source: review)

---

# Sprint: consolidate-deps PR #79 review-backlog fixes (bundle of 5)

status: done

**Scope**
- `dev-tools/skills/dependabot-manager/scripts/consolidate-deps.py` — `update_pip_tools_dependencies`, `update_requirements_txt`, `update_uv_dependencies`, `run_tests`, `__main__`.
- `dev-tools/skills/dependabot-manager/scripts/consolidate-deps.cjs` — `require.main` block (selftest only).

**Acceptance criteria**
- [ ] `.py` version-replace regex (both sites) is line-anchored: package `foo` no longer matches inside `bar-foo==…`. Pattern `rf'(?m)^{re.escape(pkg)}==[\w.!+-]+'`.
- [ ] `.py` version-replace regex matches PEP 440 pre-release/local/epoch versions (`1.0.0b1`, `2.0.0rc1`, `1.0.0.post1`, `1.0.0+local`, `2!1.0.0`) with no stale suffix left.
- [ ] `.py` `run_tests` pip/pip-tools branch runs `pytest` with check enabled → failing suite returns `False` (no push).
- [ ] `.py` `update_uv_dependencies` runs `uv add` with check enabled → failed add raises and aborts via `cleanup_and_exit(1)`.
- [ ] `--selftest` flag added to both `.py` and `.cjs`: feeds a canonical Dependabot grouped-PR body fixture, asserts correct parse, ignores lowercase `bump` noise, strips trailing punctuation, handles pre-release version, last-occurrence wins. Drift (e.g. lowercased `Updates`) → non-zero exit. `python … --selftest` and `node … --selftest` both exit 0.

**Out of scope**
- `.cjs` package.json extras-name matching (`foo` vs `foo[extra]`) — pre-existing.
- title-regex / `parse_package_update` behavior.
- any change to `sample_sql` or other skills.

**Lint/test command**
- `python dev-tools/skills/dependabot-manager/scripts/consolidate-deps.py --selftest`
- `node dev-tools/skills/dependabot-manager/scripts/consolidate-deps.cjs --selftest`

---

# Sprint: persona-debate sample_sql closure decoupling

status: done

**Scope**
- `productivity/skills/persona-debate/scripts/sample_personas.py` — `cmd_test` inner `sample()` helper.

**Acceptance criteria**
- [x] Inner `sample()` no longer relies on implicit free-variable lookup of `sample_sql`; the builder is passed/bound explicitly.
- [x] `python sample_personas.py test` still passes all checks (run via `uv run --with duckdb`).

**Out of scope**
- Any change to `sample_sql` itself, `cmd_sample`, or other subcommands.

**Lint/test command**
- `uv run --with duckdb python productivity/skills/persona-debate/scripts/sample_personas.py test`

---

# Sprint: consolidate-deps PR #80 review-backlog fixes (bundle of 3)

status: done

**Scope**
- `dev-tools/skills/dependabot-manager/scripts/consolidate-deps.py` — `update_pip_tools_dependencies`, `update_requirements_txt`, `update_uv_dependencies`, `update_poetry_dependencies`, `update_dependencies`, `run_tests`, `cmd_selftest`.

**Acceptance criteria**
- [x] #1: version-replace uses `re.subn`; packages with zero substitutions are collected and a `WARNING` is printed to stderr naming them (warn, not raise — pip-tools transitive deps legitimately absent from `requirements.in`); file still written. Substitution logic lives in a shared pure helper `_replace_pinned_versions(content, updates) -> (text, missing)`, unit-tested in `--selftest` (covers a hit, a missing package, and the line-anchor `bar-foo` non-match).
- [x] #2: `run_tests` pip/pip-tools branch runs `python -m pytest` (not bare `pytest`) so it resolves the project venv, not a global binary.
- [x] #3: all four updaters + `update_dependencies` share one contract — annotated `-> None`, raise on failure; `update_dependencies` raises `RuntimeError` on unknown project type. No `return True`/`return False` in any updater. `main` already ignores the return and relies on the raise→cleanup path.

**Out of scope**
- `.cjs` parser changes (no behavioral overlap with these `.py`-only sites).
- `parse_group_pr_body` / title-regex behavior.
- Network/subprocess integration tests for `uv add`, `pip-compile`, `gh`.

**Lint/test command**
- `python dev-tools/skills/dependabot-manager/scripts/consolidate-deps.py --selftest`
- `node dev-tools/skills/dependabot-manager/scripts/consolidate-deps.cjs --selftest`
