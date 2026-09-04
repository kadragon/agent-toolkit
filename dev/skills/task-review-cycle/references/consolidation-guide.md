# Review Consolidation Guide

Step 3 of `task-review-cycle`. Sources tag their findings: `code-review` (the reviewer's
`code-review` run), `contract` (the reviewer's Sprint Contract grading), and under `--panel`
`agy` and `codex`.

## Procedure

1. **Deduplicate.** Merge identical issues from several sources into one row listing all sources.
2. **Re-read the diff** for each finding. Drop it when the flagged line was not changed by this
   branch, the concern does not apply to the actual pattern, or there is no concrete path to harm.
3. **Drop low confidence and excluded categories.** Confidence < 50 goes to a collapsed
   "Low confidence (not actioned)" note, not the table. Also drop: purely theoretical risk
   (DoS, timing), style a linter owns, missing rate limiting / audit logs / monitoring,
   third-party vulnerabilities, test-file nits unless the test is wrong, doc gaps in untouched
   files.
4. **Conflicts** between sources: prefer the project convention (`AGENTS.md` / `CLAUDE.md`), else
   the more conservative option; note the disagreement.
5. **Scope.** In-scope = introduced or made worse by this branch and fixable without widening its
   purpose. Everything else is out-of-scope; when in doubt, out.
6. **Gate.** Every in-scope finding is applied before merge, P0 first. A `contract` finding is
   in-scope P0 by construction and bypasses the confidence filter and `--auto`.

## Present

Table: Priority · Title · Source · Scope (In/Out) · Gate (Apply/Skip) · Recommendation. Then a
"Reviewers Skipped" line for any source that did not run or return (reason: sentinel, timeout,
`codex review already running`, `claude CLI unavailable`).

Without `--auto`: stop and wait for the user. With `--auto`: apply all in-scope.

## Recording out-of-scope findings

Append to `backlog.md` (never `tasks.md`) under `## Review Backlog`, one `### PR #N — <title>
(<date>)` group per cycle (`### <branch> — <commit summary> (<date>)` on the lite or `--no-hub`
path):

```markdown
- [ ] [debt] <summary> (source: <tag>) — <file:line>
```

Tags: `[debt]` code quality · `[doc]` documentation · `[constraint]` missing test or rule ·
`[harness]` tooling/CI. Append to an existing section; never overwrite earlier groups.
