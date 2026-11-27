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
6. **Gate.** Apply in-scope P0/P1 findings eligible under *Fix rounds and re-review*, P0 first.
   Keep every verified in-scope security defect blocking. Send eligible queue findings to
   *Recording out-of-scope and non-blocking findings*. Map Codex's structured `critical`/`high`/`medium`/`low` to
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
in-scope finding that gates. Apply advisory comment decisions per `comment-rules.md`.

## Fix rounds and re-review

- Run at most **one general independent re-review per cycle** after the initial review. Use it
  only when the first repair materially changes behavior. Reuse the primary reviewer, with the
  current diff and targeted evidence. Record its launch in `cycle_state.py note` before calling
  it. A timeout or unavailable result consumes the launch. A new HEAD, CI repair, or route
  change does not reset the budget or restart the panel.
- The initial consolidation and the result of the one general re-review can add ordinary
  blockers. Close that window after consolidating the re-review, or when proceeding to final
  verification without using it. Record closure in `cycle_state.py note` and recover both notes
  on resume. Route valid new ordinary findings from later sources to the queue, even at P0/P1.
  This includes late reclaim and findings incidental to focused confirmation. Retain blockers
  accepted before the window closed. A repeat keeps its existing ID and gate.
- For each blocker, check the branch diff for the same failure pattern and fix every in-scope
  instance in one pass. During repairs, run the tests or checks covering the changed behavior.
  If a targeted check fails, fix forward once within the finding's scope. If it still fails,
  stop on contract/security. For other findings, withdraw only that finding's edits and queue it
  if the remaining candidate can still satisfy the contract and final checks. Keep advisory
  edits separable and use `comment-rules.md` for their disposition.
- Confirm fixed contract and security blockers against their original criteria or failure
  paths, including those first surfaced after the cap. Batch ready findings and give the
  permitted reviewer their stable IDs, changed scope, and targeted evidence. Allow one focused
  confirmation per blocker across the cycle. Count the general re-review when it confirms a
  blocker. For a separate confirmation, request only those findings and skip the full-diff
  launchers and panel. On a Codex-only route, re-grade the contract inline and disclose it.
  A failed or unverified focused confirmation stops the cycle. If a later change invalidates
  a confirmation, stop unless current evidence directly re-establishes it. Record the result
  under the same finding ID. Keep unresolved contract and security findings blocking on every route.

## Final verification

On hub, follow `ci-failure-handling.md` for CI on the current PR head, then reclaim late results
per `late-source-reclaim.md`. On the local-only route, reclaim at its stop point. If reclaim leads
to an in-scope repair, run targeted checks, commit it, and return through CI on hub. Apply the
existing review budget and gate to every repair, including CI repairs and fixes after resync.

After repairs and applicable reclaim settle, run the full required local checks once on the
final candidate per the shared cycle's *Validation evidence*. Reuse equivalent passing evidence
for the exact candidate. If a check fails after advisory edits, withdraw only those edits, defer
them, and verify the resulting candidate. A required failure or missing result blocks merge and
a ready report. A later change invalidates affected evidence, which must be refreshed for its
final candidate, with CI required on its head on hub. Reclaim any newly completed panel result
before ready or merge without waiting for work still running.

Finalize dispositions and update the PR's `Verification:` section from final evidence when
authorized. Keep its closing lines and report local and remote check outcomes.

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
  `pre_existing` and advisory cleanup deferred to the queue. Use the actual adjudication for
  low-confidence findings. Filing counts as deferred, not applied.

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

Verified `pre_existing`, valid out-of-scope findings, in-scope P2/P3, and new ordinary findings
past the window in *Fix rounds and re-review* go here. This includes advisory comment follow-ups
and qualifying late findings. Use `queue_backend.py` (bundled with
`dev:task-next`) → *Filing findings* in `../task-next/references/queue-backend-contract.md`
(paths relative to the skill). Classify security findings before recording or reporting them.

Read `rejected` before filing ordinary findings. Withhold a matching finding unless this
cycle's evidence meets the entry's re-file bar. List each withheld finding and its matching entry
in the cycle report. Then call `create` for the remaining findings.

- **GitHub:** one finding becomes one issue. For two or more, include a parent
  `Review follow-ups — PR #N` and set each finding's `parent_key` to the parent's key. Without a PR,
  use `Review follow-ups — <branch>`. Use a stable review-cycle key (PR number, or the feature
  branch and original reviewed commit for a local cycle), suffix it with the stable finding ID
  for each child or standalone issue, and reserve a distinct key for the parent. The body carries
  the evidence, source tags and file location. Build the batch from all eligible findings in the
  cycle before filing. If a later reclaim takes the total past one, resend the earlier item under
  its original key with the new `parent_key`; `create` reuses and links the issue.
- **`edit_file`:** append to `backlog.md` (never
`tasks.md`) under `## Review Backlog`, one `### PR #N — <title> (<date>)` group per cycle (`### <branch> — <commit summary> (<date>)` on the lite or `--no-hub`
path):

```markdown
- [ ] [debt] <summary> (source: <tag>) — <file:line>
```

Tags: `[debt]` code quality · `[doc]` documentation · `[constraint]` missing test or rule ·
`[harness]` tooling/CI. An in-scope P2/P3 line ends with `(introduced here)`. Append to an
existing section; never overwrite earlier groups. Mark a verified pre-existing bug `(pre_existing)`.

On private or non-GitHub file queues, use the existing format and flag security findings as
`[security]` (the `security` label on GitHub).

### Public security findings

Identify `security` from the substance of each finding, regardless of its priority or source.
Separate it before forming the queue batch or editing a file. On public GitHub repositories,
file a draft repository security advisory under the standing grant. Resolve the owner and repo
from `origin`. Send a JSON body with `summary`, `description` and the affected `vulnerabilities`
array over stdin, using evidence-backed package and version data. For a repository with no package
ecosystem use `other` and the affected product name. Follow the
[GitHub advisory API](https://docs.github.com/en/rest/security-advisories/repository-advisories#create-a-repository-security-advisory).

```bash
QUEUE_SCRIPTS="<absolute task-next skill directory>/scripts"
REPO=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from queue_backend import github_slug; print("/".join(github_slug(".")))' "$QUEUE_SCRIPTS") || exit 1
# stdin is the in-memory JSON payload.
gh api --hostname github.com --method POST "repos/$REPO/security-advisories" --input - --jq '.ghsa_id' 2>/dev/null
```

Run with shell tracing off and pass the payload directly over stdin, without a scratch file or
inline shell expansion of the finding. Require a successful exit and a nonempty GHSA ID. Reuse
the advisory ID on re-review for the same finding. Keep
public PRs, cycle reports and saved dispositions to the GHSA ID, without details or file
locations. With `no-queue-write`, unverified visibility, an unsupported host or a failed advisory
call, keep the details in-session only and report the withheld count. The same applies when a
public adapter has no approved advisory route. This step never sends public security findings to
`create`, a queue file or the pending store.
