## Review Backlog

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
