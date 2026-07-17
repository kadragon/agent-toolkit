# Tasks

## Review Backlog

### Deferred from dev-review-cycle (PR #147 — router removal)

- [ ] Scrub the last router-var remnant: `docs/conventions.md` uses `ROUTES_FILE` (the deleted trigger-router's variable) as the SCREAMING_SNAKE naming example. Replace with a current var and drop `ROUTES_FILE` from `tools/sweep.sh:40`'s grep-exclusion list in the same edit (coupled — changing one without the other risks a sweep false-positive). Low confidence/cosmetic; deferred out of PR #147 scope.
