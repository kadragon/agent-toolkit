# Out-of-Scope Review Findings

Deferred items surfaced during task-review. Not blocking; triage later.

## Review Backlog

### PR #176 — pin ruff ruleset so the pre-commit gate is usable; fix comment-stripper EOF line loss (2026-07-30)

- [ ] [HARNESS] `commit-and-push.sh` cannot stage a file the cycle deleted (source: task-review self-observed) — `dev/skills/task-review/scripts/commit-and-push.sh:59` — `changed-files.sh` correctly lists a deleted path, but `git add -- $FILES` fails on a path already removed from the index (`fatal: pathspec 'tasks.md' did not match any files`), so Step 1 dies. task-next's own cleanup deletes `tasks.md` whenever it empties, so every such cycle hits this. PR #176 worked around it by dropping the path from `--files` (the deletion was already staged). Likely fix: `git add -A -- $FILES`. Add a regression test covering a delete-only file in the stage list.
- [ ] [HARNESS] nothing mechanically enforces the new `ruff.toml` (source: review) — `.github/workflows/harness-check.yml` — no workflow runs ruff; `harness-check.yml` only executes `scripts/ci/*.py`, never the gated `*/scripts/*.py`. The gate is the untracked local `.git/hooks/pre-commit` only, so the load-bearing `target-version = "py312"` is asserted in a comment alone — lowering it silently re-breaks the gate (py311 → 6 invalid-syntax errors on `prod/skills/hwpx/scripts/table.py`), and no `requires-python`/`.python-version` records the 3.12 floor elsewhere. Per "mechanical enforcement > verbal agreement", add a ruff step (e.g. pinned `ruff check --no-cache .`). Cheapest moment: the repo is at 0 violations repo-wide as of PR #176.
