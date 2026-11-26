# Review Consolidation Guide

Step 3 of `task-review-cycle`. Sources tag their findings: `code-review` (the reviewer's
`code-review` run), `contract` (the reviewer's Sprint Contract grading), `comments` (the
separate advisory pass, `comment-rules.md`), and on every non-lite
route the panel's `agy` and `codex`. Lite has one source, the engine that did not drive the cycle
(`risk-routing.md` → *Lite reviewer*): when that is `codex`, `contract` comes from the
orchestrator's inline grading.

## Procedure

1. **Deduplicate.** Merge identical issues from several sources into one row listing all sources.
2. **Re-read the diff and base** for each finding. A regression can surface on an unchanged
   line when this branch causes it. A `pre_existing` severity or title tag is advisory: verify the
   same failure existed at the base, the branch did not worsen it, and the diff touches or reads
   the relevant code. Normalize Codex's `[pre_existing]` title above its numeric priority. Drop
   unrelated code, inapplicable concerns, and findings with no concrete path to harm.
3. **Drop low confidence and excluded categories.** Confidence < 50 goes to a collapsed
   "Low confidence (not actioned)" note, not the table. So does a `code-review` finding with an
   empty `failure` — no input, state, test, command, or unmet User Story that shows it fails. Panel findings carry
   no `failure` field and skip that check. Normalize Codex confidence from 0–1 to 0–100 when
   it uses that scale. Also drop: purely theoretical risk
   (DoS, timing), style a linter owns, missing rate limiting / audit logs / monitoring,
   requests to add redundant defensive code (a new guard, retry, or validation for a state the
   diff itself shows no caller can reach — cite that evidence; never a removed existing guard),
   third-party vulnerabilities, test-file nits unless the test is wrong, doc gaps in untouched
   files.
4. **Conflicts** between sources: prefer the project convention (`AGENTS.md` / `CLAUDE.md`), else
   the more conservative option; note the disagreement.
5. **Scope.** In-scope = introduced or made worse by this branch and fixable without widening its
   purpose. Everything else is out-of-scope; when in doubt, out.
6. **Gate.** Every in-scope P0/P1 finding is applied before merge, P0 first. Send verified
   `pre_existing` findings and in-scope P2/P3 to `## Review Backlog` with no merge gate,
   including in late reclaim. Map Codex's structured `critical`/`high`/`medium`/`low` to
   P0/P1/P2/P3 respectively. A `contract` finding is in-scope P0 by construction and
   bypasses the confidence and `failure` filters and `--auto`. A `comments` finding carries no
   harm path or confidence by design: it bypasses the harm check in step 2 and the confidence and
   `failure` filters in step 3, and is applied per `comment-rules.md` → *Applying*, not by this gate.

## Present

Table: Priority · Title · Source · Scope (In/Out) · Gate (Apply/Skip) · Blocking category · Recommendation. Then a
"Reviewers Skipped" line for any source that did not run or return (reason: sentinel, timeout,
`still running`, `failed`, `locked`, `unavailable`, `claude CLI unavailable`).

Give each blocking finding a short lowercase category for the guarantee it breaks, such as
`atomicity`, `retry-safety`, or `input-validation`. Reuse the category when the same guarantee
fails again. Leave the category blank for other findings.

Without `--auto`: stop and wait for the user on blocking fixes. With `--auto`: apply every
in-scope P0/P1 that gates. Apply advisory comment decisions per `comment-rules.md`.

## Record finding dispositions

Use `cycle_state.py note`, the same channel as `Review send-back`. The disposition categories
follow https://claude.dev/blog/solving-code-review-at-anthropic/ (2026-10-15).
For each deduplicated finding, including filtered candidates and advisory findings, write one
single-line JSON object after `Review disposition ` when its outcome is known. For example:

```text
Review disposition {"head":"<reviewed commit>","id":"<stable finding ID within this cycle>","sources":["code-review","codex"],"disposition":"dropped","reason":"wrong"}
```

- `applied` means the fix survived Step 4; omit `reason`.
- `dropped` requires one reason: `wrong` for a mismatched or unsupported claim, `intentional`
  for verified deliberate behavior, `not-matter` for a valid observation with immaterial impact,
  or `out-of-scope` for a valid item deferred or outside the change, including verified
  `pre_existing` and advisory cleanup deferred to the backlog. Use the actual adjudication for
  low-confidence findings. Backlog filing counts as deferred, not applied.

Reuse the ID on re-review, resume, and late reclaim when the same defect appears again. Take the
last record for an ID within the cycle and retain all contributing sources, including any newly
arrived source. A late repeat of an applied fix adds its source to the applied row. A skipped reviewer contributes zero
findings. After a confirmed merge, `cycle_state.py retire` retains these rows as JSONL in the
common Git directory under `review-dispositions/`.

Count each finding once per listed source. Report false positives (`wrong` / adjudicated) and
noise (`wrong`, `intentional`, or `not-matter` / adjudicated), where adjudicated is `applied`
or one of those three reasons. Report `out-of-scope` separately and leave a zero denominator
unscored. Use the `comments` results when reconsidering the advisory-pass placement.

## Report review send-backs to dispatch

A consolidated verdict that sends the change back for another repair counts once, even if
multiple sources found the issue or dispatch collects it repeatedly. A passing verdict ends
the consecutive sequence. Preserve send-backs in the branch's archived cycle notes as one
`Review send-back` line per verdict with a JSON object after the label. Use the contract archive
path as `change`, the consecutive verdict number starting at 1 as `round`, and the deduplicated
blocking categories as `categories`. Recover the last verdict through `cycle_state.py inspect`
on resume. Record a `Review passed` line to end the sequence before starting a new one.

When reporting a send-back through dispatch, include up to the last two entries in order in
`result.json` as `review_sendbacks`. Keep `review_retries` as the measured retry count. When
reporting a blocked review to the home session, use `status: blocked` and point to the evidence
for each verdict. A newly approved scope starts a fresh sequence.

## Recording out-of-scope and non-blocking findings

Verified `pre_existing`, valid out-of-scope findings, and in-scope P2/P3 go here. Append to `backlog.md` (never
`tasks.md`) under `## Review Backlog`, one `### PR #N — <title> (<date>)` group per cycle (`### <branch> — <commit summary> (<date>)` on the lite or `--no-hub`
path):

```markdown
- [ ] [debt] <summary> (source: <tag>) — <file:line>
```

Tags: `[debt]` code quality · `[doc]` documentation · `[constraint]` missing test or rule ·
`[harness]` tooling/CI. An in-scope P2/P3 line ends with `(introduced here)`. Append to an
existing section; never overwrite earlier groups. Mark a verified pre-existing bug `(pre_existing)`.

Before appending, check `backlog.md` → `## Rejected — do not re-file`: a finding that matches an
entry there is not filed unless this cycle's evidence meets that entry's re-file bar. List each
withheld finding in the cycle report with the entry it matched, so a near-miss stays visible.
