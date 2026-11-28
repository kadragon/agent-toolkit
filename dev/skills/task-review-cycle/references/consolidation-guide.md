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
   the relevant code. Use confirmed `pre_existing` status to determine scope and keep the
   finding's P0–P3 priority for filing. Drop unrelated code, inapplicable concerns, and findings
   with no concrete path to harm.
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
   Keep verified in-scope P0/P1 security findings blocking throughout the cycle. Route remaining
   findings through *Recording out-of-scope and non-blocking findings*. Map Codex's structured
   `critical`/`high`/`medium`/`low` to P0/P1/P2/P3 respectively. A `contract` finding is
   in-scope P0 by construction and
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

## Resume checkpoints

Record initial source launches and consolidated verdicts in `cycle_state.py note`, along with
the review window and confirmation records below. Recover them through `inspect` before Step 2.
Resume the first unfinished step. Reuse completed results and reclaim pending panel results.
When a launched initial source has no recoverable result, mark it skipped and follow Step 2's
fallback policy. Keep the original launch history and the accepted blockers across resume.

## Fix rounds and re-review

For dispatched work, record each review launch and consolidation per *Dispatch timing*.

- Run at most **one general independent re-review per cycle** after the initial review. Use it
  only when the first repair materially changes behavior. Check the route floor before spending
  the re-review on a lite repair. Reuse the primary reviewer, with the current diff and targeted
  evidence. Record its launch in `cycle_state.py note` before calling it. A timeout or
  unavailable result consumes the launch. A new HEAD, CI repair, or route
  change does not reset the budget or restart the general panel. For dispatched pre-merge
  verification on a new head, follow *Dispatch pre-merge report*.
- Apply the normal gate until the one general re-review has been consolidated. If unused,
  keep the normal gate through late reclaim. Record closure in `cycle_state.py note` after
  consolidating the re-review, or when ready without it. Route valid new ordinary findings
  from later sources through the filing threshold below, even at P0/P1. This includes late
  reclaim and findings incidental to focused confirmation. Retain accepted blockers. A repeat
  keeps its ID and gate.
- For each blocker, check the branch diff for the same failure pattern and fix every in-scope
  instance in one pass. During repairs, run the tests or checks covering the changed behavior.
  If a targeted check fails, fix forward once within the finding's scope. If it still fails,
  stop on contract or blocking security findings. For other findings, withdraw only its edits
  and route it through the filing threshold if the remaining candidate can still satisfy the
  contract and final checks. Keep advisory edits separable and use `comment-rules.md` for their
  disposition.
- Confirm fixed contract and security blockers against their original criteria or failure
  paths, including those first surfaced after the cap. Batch ready findings and give the
  permitted reviewer their stable IDs, changed scope, and targeted evidence. Allow one focused
  confirmation per blocker across the cycle. Count the general re-review when it confirms a
  blocker. For a separate confirmation, request only those findings and skip the full-diff
  launchers and panel. On a Codex-only route, re-grade the contract inline and disclose it.
  Record the finding IDs before launching confirmation. A failed or unverified confirmation
  stops the cycle. If a later change invalidates a confirmation, stop unless current evidence
  directly re-establishes it. Record the result under the same finding ID. Unresolved contract
  and blocking security findings stop the cycle on every route.

## Final verification

On GitHub, record the full SHA of the committed candidate covered by the review in the existing
review checkpoint as `Reviewed head <sha>`. Use that SHA as `REVIEWED_HEAD` for every CI wait
and the merge command. After a repair or resync, record a new SHA when review and targeted
evidence cover the new candidate under the existing review budget.

On hub, follow `ci-failure-handling.md` for CI and merge timing on the current PR head, then reclaim late results
per `late-source-reclaim.md`. On the local-only route, reclaim at its stop point. If reclaim leads
to an in-scope repair, run targeted checks, commit it, and return through CI on hub. Apply the
existing review budget and gate to every repair, including CI repairs and fixes after resync.

After repairs and applicable reclaim settle, run the full required local checks once on the
final candidate per the shared cycle's *Validation evidence*. Reuse equivalent passing evidence
for the exact candidate. If a check fails after advisory edits, withdraw only those edits, defer
them, and run targeted checks on the withdrawal. For other failures, diagnose and repair the
in-scope cause under the existing review budget and approval rules. Use targeted checks and
Step 5 for each repair or withdrawal. On hub, push it and confirm CI on the new head before
returning to the full local checks. An unresolved failure or missing result blocks merge and
a ready report. A later change invalidates affected evidence. Reclaim any newly completed panel
result before ready or merge without waiting for work still running. On GitHub, confirm local
`HEAD` still equals `REVIEWED_HEAD` after the final checks, then run a final CI wait with that SHA.
Use the same SHA in the merge command or ready report. On Forgejo, confirm that the remote head
and its applicable CI match the local candidate.

Apply the [Dispatch pre-merge report](#dispatch-pre-merge-report) gate to every dispatched
task cycle that has a PR, Codex or Claude, before a ready report or any authorized base merge.

Finalize dispositions and update the PR's `Verification:` section from final evidence when
authorized. Keep its closing lines and report local and remote check outcomes. On lite, preserve
the final evidence in the merge commit message before retiring the archive.

## Dispatch timing

Use the receipt beside the assigned `result.json`. Start one measurement before each
independent review round, including a re-review or a focused confirmation. Use the
committed candidate's full Git SHA. Keep the printed attempt ID in
the review checkpoint and finish that attempt when consolidating its verdict. Use
`incomplete` if the attempt produced no verdict. Reuse the ID when reclaiming the
same attempt. A new reviewer launch gets a new ID.

```bash
DISPATCH="<absolute path to dev/skills/dispatch/scripts/dispatch.py>"
RESULT="<assigned result.json path>"
DISPATCH_TIMING_RUN="${RESULT%/*}/run.json"
HEAD_SHA=$(git rev-parse --verify HEAD) || exit 1
ATTEMPT=$(python3 -I "$DISPATCH" timing "$DISPATCH_TIMING_RUN" start review "$HEAD_SHA")
```

After consolidating the verdict, recover the recorded ID and close its measurement.

```bash
DISPATCH="<absolute path to dev/skills/dispatch/scripts/dispatch.py>"
RESULT="<assigned result.json path>"
DISPATCH_TIMING_RUN="${RESULT%/*}/run.json"
ATTEMPT="<from the review checkpoint>"
python3 -I "$DISPATCH" timing "$DISPATCH_TIMING_RUN" finish review "$ATTEMPT" complete
```

When reviewing changes before committing them, stage the exact reviewed changes and verify the
working tree matches the index. Capture the reviewed SHA with `git write-tree`. Start with
`timing <receipt> start review <tree SHA> --tree`. After committing, run
`timing <receipt> bind-review <attempt> <commit SHA>`. The helper verifies that the commit
contains that tree before assigning the head.

Report unavailable timing and continue the review when recording fails. Pass the same receipt
to the CI wait and merge helper per `ci-failure-handling.md`. For a separately verified merge
(including a confirmed lite push), run
`dispatch.py timing <receipt> merged <confirmed feature head>`. Omit the head when unavailable.

## Dispatch pre-merge report

All dispatched PRs report the reviewed head and sources. For receipts with
`review_policy: three-source` (legacy receipts without a policy: `require_review_sources`), consolidate the independent Claude primary and the agy and Codex panel
results from Step 3 and late reclaim. A missing required source blocks readiness and merge.
Keep pending results available for resume and follow the existing review budget when reclaiming.

After final verification, pass the pre-merge report as UTF-8 JSON on stdin to the installed
dispatch script. Use the assigned path beside the current dispatch receipt. The helper exits 0 even
when it rewrites the report as `blocked`; check that the call itself succeeded, then re-read `result.json` and proceed only when this call wrote `status: ready`. The helper applies
the receipt's reviewer requirements, so Claude continuations report the independent reviews
required by their review route. A report without a receipt uses the three-source gate.
Include the full PR head SHA in `head` and the usual PR, CI and evidence fields. Record the commit
the independent results cover in `review.head` (use `null` when unavailable) and list the reviewers in
`review.sources`. Set `review.status` to `passed` when the required reviews pass for that
head, `pending` while awaiting a result, or `missing` when a required result is unavailable.
Carry the reviewed SHA forward from the evidence. Collection preserves PR completion reports
and warns when their review record or required source results are missing, stale or incomplete.

After a repair or a requested resync changes the head, the child resumes at final verification.
Confirm that the local checkout matches the current PR head and recover the prior source results.
Obtain one read-only confirmation for the current SHA from each required source whose result
covers a different head. Give each source the previous SHA, its findings and the delta to check.
Use the regular source launch when no prior result exists. The disposition and re-review budgets still
apply to code findings. Reclaim agy results from the matching invocation directory per
`late-source-reclaim.md`. Record the outcomes on the current SHA before reporting ready. Resume
a legacy report the same way, using archived evidence that identifies the reviewed head.

For a receipt with `review_policy: three-source` (legacy: `require_review_sources`), set `review_sources` to an object with the keys
`claude`, `agy` and `codex`. Use `"complete"` only for a completed, consolidated independent
result. Otherwise give the reason, such as `"approval denied"`, `"policy excluded"` or
`"still running"`.

```bash
DISPATCH="<absolute path to dev/skills/dispatch/scripts/dispatch.py>"
RESULT="<assigned result.json path>"
python3 -I "$DISPATCH" report-review "$RESULT" <<'REPORT_JSON'
{
  "status": "blocked",
  "phase": "review-sources",
  "summary": "agy: still running",
  "head": "<PR head SHA>",
  "review": {
    "head": "<reviewed commit SHA>",
    "sources": ["claude", "codex"],
    "status": "pending"
  },
  "review_sources": {"claude": "complete", "agy": "still running", "codex": "complete"}
}
REPORT_JSON
```

For a pre-merge stop, pass `status: ready` once all required reviews and final gates pass on
the reported head. For a failed gate, pass `status: blocked` and state the blocker. A child
authorized to merge proceeds to the merge helper only when the review and final gates pass on
the current PR head. In the confirmed merge report, keep that PR head in `head` and carry forward
the review record and source outcomes.

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
  `pre_existing` and findings left in a PR comment or filed in the queue. Use the actual
  adjudication for low-confidence findings.

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

Classify security findings first and apply *Public security findings* before writing any
comment or queue entry. Apply the following order to the remaining verified findings, including
late results and unapplied advisory comment findings.

| Finding | Disposition |
| --- | --- |
| P3, a nit, or an unapplied `comments` finding | At most a PR comment. The `comments` source uses a placeholder severity. |
| P2 introduced or worsened by this branch | Fix in this PR if in scope and approved. Otherwise leave a PR comment. |
| Verified pre-existing defect above P3 | File only if it occurs on an everyday path or has reproduction evidence from real use. Otherwise leave a PR comment. |
| P0/P1 introduced or worsened by this branch | Apply the blocking gate. Preserve the existing queue route when scope, the review window, or withdrawal of a failed fix under *Fix rounds and re-review* defers the finding. |
| Other advisory findings | At most a PR comment. |

For a pre-existing defect, name the everyday command or workflow and explain why the failing
condition occurs during ordinary use, or cite a real incident, user report, or reproduction
from actual use. A synthetic test or a hypothetical supported input can establish the
defect. Eligibility also requires evidence of exposure or an everyday path.
For legacy pre-existing findings without a priority, assign a priority from verified impact
or leave a PR comment if the impact is unclear.

On hub, authorize `pr-write` before posting non-sensitive comment-only findings on the PR.
Include the finding ID, priority, file:line and concrete failure. On resume or late reclaim,
post only IDs that have not already been commented on. Without a PR or comment authority,
keep them in the cycle report. Keep comment-only findings out of `create`, file-queue edits,
and pending drafts for both backends.

When any findings qualify for filing, use `queue_backend.py` (bundled with `dev:task-next`) →
*Filing findings* in `../../task-next/references/queue-backend-contract.md`. Read `rejected`
before filing ordinary findings. Withhold a matching finding unless this cycle's evidence
meets the entry's re-file bar. List each withheld finding and its matching entry in the cycle
report. Call `create` only with the remaining eligible findings.

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
`[harness]` tooling/CI. Append to an existing section and preserve earlier groups.
Mark a verified pre-existing bug `(pre_existing)`.

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
