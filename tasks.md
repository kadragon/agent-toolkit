## Review Backlog

### PR #77 — persona-debate reproducible --seed (DuckDB reservoir)

- [ ] `sample_personas.py:cmd_test` — inner `sample()` closure references module-level `sample_sql` implicitly; fragile if the function is ever moved/renamed. conf 88%, P3. Pass `sample_sql` as a param or reference via module. (source: review)
