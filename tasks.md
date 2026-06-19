## Review Backlog

### PR #73 — hwpx: preserve-style / style-map / fill / charPr font warning

- [x] `validate.py:_charpr_font_warnings` — regex misses runs where `<hp:t>` is not the immediate first child of `<hp:run>` (e.g. field markers before text). conf 65%. Consider ET walk over runs instead of regex.
- [x] `_common.py:load_charpr_heights` — `int(cp.get("height","0"))` could ValueError on malformed non-numeric height attribute. conf 45%. Wrap in try/except.
- [x] `validate.py:_charpr_font_warnings` — O(n×m) quadratic backward scan for table/cell context per match. Low impact on small section XMLs but refactor to bisect-based lookup if ever used on large documents. conf 70%, P3.

### Follow-up (from bundle QA)

- [x] `validate.py:do_validate` — `int(cp.get("height","0"))` charPr height extraction now wrapped in `try/except ValueError: continue`, mirroring `_common.py load_charpr_heights`. Red test VAL-4 added. (PR-pending fix/hwpx-charpr-height-parity)
- [x] `validate.py` / `_common.py` — stdlib `xml.etree.ElementTree` XXE/billion-laughs. **Won't-fix:** stdlib ET default parser does NOT expand internal entities (billion-laughs raises "undefined entity") and does NOT resolve external entities (no XXE); local-CLI risk is ~nil. Adding `defusedxml` would impose a third-party runtime dep on a shipped skill across 5 files for no practical gain. Revisit only if HWPX parsing scope broadens to untrusted network input.

---

# Bundle: harden hwpx charPr font warnings (PR #73 findings)

status: done

**Scope**
- `productivity/skills/hwpx/scripts/validate.py` — `_charpr_font_warnings`
- `productivity/skills/hwpx/scripts/_common.py` — `load_charpr_heights`

**Acceptance criteria**
- [ ] `_charpr_font_warnings` rewritten as ET walk over `hp:run`; warns for small-font runs where `<hp:t>` is NOT the first child (e.g. ctrl/field marker precedes text)
- [ ] ET rewrite removes the per-match `xml_str[:pos]` backward `re.finditer` scans (no O(n×m) quadratic table/cell context lookup)
- [ ] `load_charpr_heights` does not raise on a non-numeric `height` attribute; the malformed charPr is skipped
- [ ] Existing VAL-1 / VAL-1b / VAL-2 tests still pass; new Red tests added for non-first-child run and malformed height

**Out of scope**
- `validate.py:do_validate` line ~213 `int(cp.get("height","0"))` (same pattern, not named in findings)
- DuckDB reservoir rewrite (deferred backlog item)

**Lint/test command**
- `python productivity/skills/hwpx/scripts/validate.py --test`
- `python productivity/skills/hwpx/scripts/_common.py --test`
