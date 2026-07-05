# Backlog

Items below sourced from the 2026-07-04 marketplace-wide skill review (9 skills, per-skill evaluator agents); PR #109 fixed the top-priority findings, these are the remainder.

## Someday

- [ ] [REFACTOR] next-tasks progressive disclosure — move `--all`/`--tree` sections (~215 lines) to `references/{batch,tree}.md`; replace hardcoded `Co-Authored-By: Claude Sonnet 4.6` (SKILL.md:269) with a current-model placeholder; make working-tree gate vs "work already in flight" edge-case precedence explicit.
- [ ] [FIX] harness-init cleanup — sweep.sh purpose wording mismatch (SKILL.md:224 vs :415); `references/maintenance.md` orphan (cite or delete); remove `scripts/__pycache__/` from harness-init and dependabot-manager skill dirs (+ .gitignore entry).
- [ ] [TEST] hwpx — add `--test` self-tests to `build.py`/`office.py`/`text.py` (only `_common`/`table`/`validate` have them).
- [ ] [REFACTOR] harness-curator — make Step 2 `$asset` loop an explicit fenced `for asset in ...` block; replace Step 5 guarantee prose (SKILL.md:116-122) with pointer to `disable_plugins.py --test`.

## History

- [x] [HARNESS] `commit-guard/guard.py` — branch guard now models in-chain `git checkout -b/-B/--orphan <n>` / `git switch -c/-C/--create/--orphan <n>`: a `git checkout -b X && git commit ...` one-liner on main is allowed (commit lands on the new branch). Attribution carries only across `&&` and is dropped across `||`/`;`/`|`/`&`/newline/`cd`, closing the `||`/`;`/cross-repo mis-attribution holes. (v3.6.5)
- [x] [HARNESS] `commit-guard/guard.py` — type guard now fails open on statically-undecidable messages: a `-m "$(...)"` / backtick command-substitution message skips the type check instead of blocking, per the hook's fail-open contract. (v3.6.5)
