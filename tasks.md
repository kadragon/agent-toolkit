## Review Backlog

### PR #73 — hwpx: preserve-style / style-map / fill / charPr font warning

- [ ] `validate.py:_charpr_font_warnings` — regex misses runs where `<hp:t>` is not the immediate first child of `<hp:run>` (e.g. field markers before text). conf 65%. Consider ET walk over runs instead of regex.
- [ ] `_common.py:load_charpr_heights` — `int(cp.get("height","0"))` could ValueError on malformed non-numeric height attribute. conf 45%. Wrap in try/except.
- [ ] `validate.py:_charpr_font_warnings` — O(n×m) quadratic backward scan for table/cell context per match. Low impact on small section XMLs but refactor to bisect-based lookup if ever used on large documents. conf 70%, P3.

