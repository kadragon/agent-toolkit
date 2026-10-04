# Review Consolidation Guide

Step 3 of `task-review-cycle`. Sources tag their findings: `code-review` (the reviewer's
`code-review` run), `contract` (the reviewer's Sprint Contract grading), and on every non-lite
route the panel's `agy` and `codex`.

## Procedure

1. **Deduplicate.** Merge identical issues from several sources into one row listing all sources.
2. **Re-read the diff** for each finding. Drop it when the flagged line was not changed by this
   branch, the concern does not apply to the actual pattern, or there is no concrete path to harm.
3. **Drop low confidence and excluded categories.** Confidence < 50 goes to a collapsed
   "Low confidence (not actioned)" note, not the table. So does a `code-review` finding with an
   empty `failure` — no input, state, test, command, or unmet User Story that shows it fails. Panel findings carry
   no `failure` field and skip that check. Also drop: purely theoretical risk
   (DoS, timing), style a linter owns, missing rate limiting / audit logs / monitoring,
   third-party vulnerabilities, test-file nits unless the test is wrong, doc gaps in untouched
   files.
4. **Conflicts** between sources: prefer the project convention (`AGENTS.md` / `CLAUDE.md`), else
   the more conservative option; note the disagreement.
5. **Scope.** In-scope = introduced or made worse by this branch and fixable without widening its
   purpose. Everything else is out-of-scope; when in doubt, out.
6. **Gate.** Every in-scope P0/P1 finding is applied before merge, P0 first. In-scope P2/P3 —
   only the panel emits them; `code-review` reports merge-blocking problems only — do not gate:
   record them like out-of-scope findings. A `contract` finding is in-scope P0 by construction and
   bypasses the confidence and `failure` filters and `--auto`.

## Present

Table: Priority · Title · Source · Scope (In/Out) · Gate (Apply/Skip) · Recommendation. Then a
"Reviewers Skipped" line for any source that did not run or return (reason: sentinel, timeout,
`codex review already running`, `claude CLI unavailable`).

Without `--auto`: stop and wait for the user. With `--auto`: apply every in-scope P0/P1.

## Recording out-of-scope and non-blocking findings

Out-of-scope findings and in-scope P2/P3 both go here. Append to `backlog.md` (never
`tasks.md`) under `## Review Backlog`, one `### PR #N — <title> (<date>)` group per cycle (`### <branch> — <commit summary> (<date>)` on the lite or `--no-hub`
path):

```markdown
- [ ] [debt] <summary> (source: <tag>) — <file:line>
```

Tags: `[debt]` code quality · `[doc]` documentation · `[constraint]` missing test or rule ·
`[harness]` tooling/CI. An in-scope P2/P3 line ends with `(introduced here)`. Append to an
existing section; never overwrite earlier groups.
