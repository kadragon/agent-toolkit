# Backlog

## Review Backlog

### PR #119 — replace _workspace/ convention with scratchpad (2026-07-05)

- [ ] [debt] Adopt `defusedxml.ElementTree` in `productivity/skills/hwpx/scripts/validate.py` to mitigate XXE/billion-laughs risk from parsing untrusted `.hwpx` files (source: security-guidance hook) — flagged on `_check_table_grid`, applies to the whole file's `xml.etree.ElementTree` usage, out of scope for this PR (pre-existing pattern, needs a new dependency decision)
