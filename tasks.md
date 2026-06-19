## Review Backlog

### PR #79 — dependabot-manager consolidate group-PR parsing (out-of-scope, pre-existing)

These live in `consolidate-deps.py` functions untouched by PR #79; surfaced by Antigravity/review during that PR's review cycle. All pre-existing, not introduced by the group-PR parser work.

- [ ] `consolidate-deps.py` `update_pip_tools_dependencies` / `update_requirements_txt` — version-replace regex `{pkg}==[\d\.]+` lacks a line-start anchor, so package `foo` can match inside `bar-foo==...`. Use `(?m)^{re.escape(pkg)}==`. conf ~85%, P1. (source: agy)
- [ ] `consolidate-deps.py` same regex assumes numeric-only versions `[\d\.]+`; pre-release/local versions (`1.0.0b1`, `2.0.0-beta.3`) leave a stale suffix. Widen the version class. conf ~85%, P1. (source: agy)
- [ ] `consolidate-deps.py:run_tests` — pip/pip-tools branch runs `pytest` with `check=False`, so a failing test suite is treated as success and the script proceeds to push. Drop `check=False` for the test invocation. conf ~90%, P1. (source: agy)
- [ ] `consolidate-deps.py:update_uv_dependencies` — `uv add` runs with `check=False`; a failed add is swallowed and consolidation proceeds with a stale/incomplete lock. conf ~90%, P2. (source: agy)
- [ ] `consolidate-deps.{py,cjs}` — no test harness locks the Dependabot grouped-PR body format the parser depends on (case-sensitive `Updates` anchor). Add a fixture-based `--selftest` so a format/casing drift fails loudly instead of silently routing every group PR to the WARNING path. conf ~75%, P2. (source: review)

### PR #77 — persona-debate reproducible --seed (DuckDB reservoir)

- [x] `sample_personas.py:cmd_test` — inner `sample()` closure references module-level `sample_sql` implicitly; fragile if the function is ever moved/renamed. conf 88%, P3. Pass `sample_sql` as a param or reference via module. (source: review)

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
