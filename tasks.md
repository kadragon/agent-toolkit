# Tasks

## Review Backlog

### PR #188 review — pre-existing task-next ambiguities

Refuted as *introduced by* PR #188 (all three verified pre-existing on `main`), but each is a real
wording gap worth closing on its own.

- [ ] [DOCS] `task-next/SKILL.md` Step 2 row 0 tells the orchestrator to report "backlog and tasks are clear — nothing open" unconditionally, ~30 lines from the Step 1 rule that forbids exactly that on an empty stdout alone. Add the qualifier to the row itself.
- [ ] [DOCS] `docs/delegation.md` → *Role Routing* scopes the qa-verifier gate exception to "this one spawn", but `task-next/references/batch.md` mandates one qa-verifier per unit in `--all` mode. Scope the exception to every QA spawn `task-next` owns.
- [ ] [DOCS] The pre-merge cleanup cascade ("drop any heading left with no open `- [ ]` items") is unqualified in both `task-next/SKILL.md` and, before it, `main`. Restrict heading deletion to the group the sprint actually touched.
