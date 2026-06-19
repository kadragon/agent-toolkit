## Review Backlog

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
