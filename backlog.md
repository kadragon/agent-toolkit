# Backlog

Items below sourced from the 2026-07-04 marketplace-wide skill review (9 skills, per-skill evaluator agents); PR #109 fixed the top-priority findings, these are the remainder.

## Now

- [ ] [FIX] dependabot-manager `scripts/triage.sh:25` — failed detection only matches `conclusion == "FAILURE"`; `CANCELLED`/`TIMED_OUT`/`STARTUP_FAILURE` checks are neither failed nor pending, so mergeStateStatus CLEAN misclassifies them as `ready` (timed-out CI → auto-merge candidate). Also handle StatusContext-style entries (`state` field only, e.g. legacy Jenkins) in both failed and pending detection.
- [ ] [FIX] dev-review-cycle `SKILL.md:78` — `FILE_COUNT=$(echo "$CHANGED_FILES" | grep -c . 2>/dev/null || echo 0)`: on empty diff `grep -c` prints "0" then exits 1, so `|| echo 0` appends a second line → `FILE_COUNT="0\n0"` breaks the trivial short-circuit numeric compare. Drop the `|| echo 0`.
- [ ] [FIX] dev-review-cycle `SKILL.md:108` — reviewer prompt references `${SKILL_ID}` which is never defined (captured vars are `SLOT1`/`SLOT2`); define it or use `${SLOT1}` directly.
- [ ] [FIX] loop-engineer exit-condition contradiction — `SKILL.md:33` says "stop after 4 rounds of no improvement" but `SKILL.md:88` plateau-exits after 2 flat rounds, making the 4-round rule unreachable; keep one norm (Step 5) and delete/align the other.
- [ ] [FIX] harness-curator six-vs-seven signals — `SKILL.md:61` says "six signals" but the table (SKILL.md:65-73) has 7 rows; `references/signal-taxonomy.md` still says six and lacks detection rules/threshold/brief for "Recurring failure". Pick one resolution and apply to both files.

## Next

- [ ] [FIX] hwpx `$SKILL_DIR` capture-before-use — add an executable resolution snippet in the Environment section and a `SKILL_DIR=...` capture line at the top of each workflow's first bash block (~22 WARN sites in `check_harness_drift.py` output); then add `hwpx` to `HARD_FAIL_SKILLS`.
- [ ] [DOCS] dev-review-cycle capture-before-use — add example `COMMIT_MESSAGE=`/`FILES_TO_STAGE=` capture lines in Steps 1/5 blocks and captures for the remaining ~27 WARN sites; then add `dev-review-cycle` to `HARD_FAIL_SKILLS`.
- [ ] [REFACTOR] orchestrate brief template vs `docs/delegation.md` Spawn Prompt Contract — SKILL.md:41-47 uses Goal/Constraints/Exit criterion/Context, delegation.md mandates Objective/Output format/Tools/Boundaries; unify (superset or pointer) so following one doesn't violate the other. Also add the missing "parallel + share findings mid-flight → Agent Team" branch to the decision tree (SKILL.md:11-18).
- [ ] [REFACTOR] loop-engineer — move Prerequisites (SKILL.md:113-119, hard precondition) above Step 1; replace Step 7 auto-memory promotion (SKILL.md:108) with `docs/` write-back per memory policy (auto-memory = user prefs only).
- [ ] [REFACTOR] hwpx restore-mode gate dedup — rule stated 3× (SKILL.md:28-36 table, :362-379, Critical Rules 11-13); keep Workflow 5 as the norm, reduce others to pointers (~549 → ~450 lines).
- [ ] [REFACTOR] dependabot-manager category table dedup — SKILL.md:31-40 fully duplicated in `references/triage.md:21-30`; keep one, point from the other.
- [ ] [FIX] router coverage for generic phrases — `check_harness_drift.py` WARNs: hwpx ("회의록 만들어", "보고서 생성", "제안서 작성", "edit hwp file"), persona-debate ("여론", "다양한 관점", "사람들이 이걸 어떻게 생각할까"). Either add hwpx/persona-debate routes with skip guards, or scope the description phrasing so it stops advertising unrouted phrases.

## Someday

- [ ] [FIX] dependabot-manager `scripts/triage.sh:14` — non-numeric PR number in an entry kills the whole batch via `set -e` on `--argjson`; add per-entry `[[ "$number" =~ ^[0-9]+$ ]]` guard reusing the existing error-category path.
- [ ] [FIX] dev-review-cycle `SKILL.md:126` — unquoted `${CODEX_MODE} ${BASE_BRANCH} ${CODEX_COMPANION_PATH}` relies on empty-arg dropping; quote and document. Also document the `--no-push` + clean-tree fatal ("nothing to do") edge in the Error Handling table.
- [ ] [REFACTOR] next-tasks progressive disclosure — move `--all`/`--tree` sections (~215 lines) to `references/{batch,tree}.md`; replace hardcoded `Co-Authored-By: Claude Sonnet 4.6` (SKILL.md:269) with a current-model placeholder; make working-tree gate vs "work already in flight" edge-case precedence explicit.
- [ ] [FIX] persona-debate docs — `SKILL.md:20` "HTTP" → "HTTPS" (scripts use https); add note to keep `age,sex,province,occupation` when trimming `--fields`; `cmd_distinct` stderr hint that it scans shard 0 only.
- [ ] [FIX] harness-init cleanup — sweep.sh purpose wording mismatch (SKILL.md:224 vs :415); `references/maintenance.md` orphan (cite or delete); remove `scripts/__pycache__/` from harness-init and dependabot-manager skill dirs (+ .gitignore entry).
- [ ] [TEST] hwpx — add `--test` self-tests to `build.py`/`office.py`/`text.py` (only `_common`/`table`/`validate` have them).
- [ ] [REFACTOR] harness-curator — make Step 2 `$asset` loop an explicit fenced `for asset in ...` block; replace Step 5 guarantee prose (SKILL.md:116-122) with pointer to `disable_plugins.py --test`.
- [ ] [DOCS] orchestrate description — switch to directive "Use when..." phrasing and replace "Default to delegation" (SKILL.md:9) with the 10+ files / 3+ units threshold.
- [ ] [HARNESS] loop-engineer slug collision — document/mitigate ledger slug convergence (`a-b.md`/`a_b.md`/`A B.md` → same slug) for concurrent loops.

## History

- [x] [HARNESS] `commit-guard/guard.py` — branch guard now models in-chain `git checkout -b/-B/--orphan <n>` / `git switch -c/-C/--create/--orphan <n>`: a `git checkout -b X && git commit ...` one-liner on main is allowed (commit lands on the new branch). Attribution carries only across `&&` and is dropped across `||`/`;`/`|`/`&`/newline/`cd`, closing the `||`/`;`/cross-repo mis-attribution holes. (v3.6.5)
- [x] [HARNESS] `commit-guard/guard.py` — type guard now fails open on statically-undecidable messages: a `-m "$(...)"` / backtick command-substitution message skips the type check instead of blocking, per the hook's fail-open contract. (v3.6.5)
