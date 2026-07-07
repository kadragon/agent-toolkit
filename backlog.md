# Backlog

## Harness

- [ ] [harness] `dev-review-cycle` preflight.sh returns local `base_branch` (e.g. `main`) without checking it's current vs `origin/<base>`. If local main is stale (strictly behind, no unique commits), every downstream `git diff ${BASE_BRANCH}...HEAD` (file count, line delta, security-hit grep, reviewer diff) is scoped against the stale ref and picks up already-merged commits as if they were part of this PR. Verified 2026-07-07 on `harness/fuzzy-project-dir-match`: local main was 21 commits behind origin/main, `git diff main...HEAD --stat` showed 59 files / 2309+ lines; after `git fetch origin main:main` (safe fast-forward, no unique local commits) the same diff correctly scoped to 2 files / 44 lines. Fix: in `preflight.sh`, after resolving `base_branch`, fetch and fast-forward it to match `origin/<base_branch>` when strictly behind (no divergence) before returning JSON. — dev-tools/skills/dev-review-cycle/scripts/preflight.sh

