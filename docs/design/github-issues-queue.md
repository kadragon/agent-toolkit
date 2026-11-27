# GitHub Issues queue backend

## Problem Statement

The dev task cycle keeps its whole persistent queue in a tracked `backlog.md`: `task-tickets`
writes tickets there, `task-review-cycle` files review findings there, `security-overview`,
`harness-capture`, `test-prune`, `repo-architecture` and `harness-init/scripts/sweep.sh`
append to it, `task-next` and `dispatch.py pick` select from it through
`task-next/scripts/backlog_candidates.py`, and `task_nodes.py prune-backlog` deletes the done lines
at cleanup. Three costs follow from the queue being a tracked file:

1. **Merge conflicts.** Parallel `--tree` cycles and batch worktrees each prune and append lines in
   the same file, so their PRs conflict on `backlog.md` even when their code does not.
2. **Tracking means opening the file.** No list, filter, link, or notification exists outside a
   checkout; the queue state of a repo is visible only by reading its `backlog.md` at some commit.
3. **Queue writes leak into unrelated changes.** When several repos are worked at once, a finding
   about repo B is written into B's local checkout and rides along with whatever unrelated diff
   sits there. The uncommitted-`backlog.md` carve-outs in the working-tree gate
   (`task-next/SKILL.md` → *Working tree gate*) and the queue-edit commit-authority path in
   `task-new` (*Queue documentation cycle*) exist only to manage this.

Design goal: **a queue write leaves no trace in the working tree or the commit history.**

## Solution

Put a **queue backend** between every queue reader/writer and the storage. A backend is a script
with a JSON-in/JSON-out contract; one resolver picks it per repo from `origin`:

- `origin` on `github.com` → the built-in **GitHub Issues** backend (default).
- any other host with an adapter registered for it → that **external adapter** (agent-home-knue
  will register a Forgejo adapter; Forgejo itself is not built here).
- otherwise → the built-in **backlog.md** backend, i.e. today's behavior unchanged.

On the issues backend one queue item is one issue. Selection reads open issues; a claim is a local
worktree `## Covers` entry or an open PR that closes the issue; completion is the merge of that PR
(`Closes #N`), so `prune-backlog`, `[>]` reconciliation and blocked-marker sync have nothing to do.
Tickets, review findings and deferred follow-ups become issues. Security findings in a public repo
never become issues: they stay in the GitHub Security tab and are referenced by alert/advisory id.
A GitHub repo whose `backlog.md` still has open items warns on every selection and points to a
one-shot migration script. Pilot: `../knue-pic`.

## User Stories

- As a developer running two `--tree` cycles in one repo, I want neither PR to touch a queue file,
  so that they never conflict on the queue.
- As a developer, I want to see a repo's queue on GitHub (list, filter by label, dependency graph),
  so that I do not open `backlog.md` to know what is pending.
- As a home session dispatching to several repos, I want a finding about repo B filed against repo
  B's queue directly, so that it never sits uncommitted in B's checkout next to unrelated work.
- As a maintainer of a public repo, I want security findings kept out of public issues, so that an
  unfixed vulnerability is not published.
- As the agent-home-knue maintainer, I want to plug a Forgejo backend in from my own repo without
  patching agent-toolkit, so that Forgejo-hosted repos get the same queue model.
- As a user with an existing `backlog.md` on a GitHub repo, I want a warning and a dry-run
  migration, so that open items are never silently dropped.

## Implementation Decisions

### Backend resolution

- New script `dev/skills/task-next/scripts/queue_backend.py` is the only entry point for queue
  access. Callers pass an op; it resolves the backend and forwards.
- Resolution order: (1) `AGENT_QUEUE_BACKEND` env var naming `backlog`, `github`, or an adapter
  command — explicit override for tests and one-off runs; (2) `origin` host `github.com` →
  `github`, **unless the repo's `backlog.md` still has open items** (see *Legacy backlog.md*
  below); (3) the user-level registry
  `${XDG_CONFIG_HOME:-~/.config}/agent-toolkit/queue-backends.json`
  (`{"hosts": {"git.example.org": ["python3", "/abs/path/adapter.py"]}}`) keyed by `origin`
  host → that command; (4) `backlog`. The registry is user-level, not per repo, because one
  adapter serves every repo on its host and a repo-tracked config would itself be a tracked queue
  artifact.
- **Rollout guard.** Because step (2) skips a repo with open `backlog.md` items, a plugin release
  that ships the issues read path before the writers (tickets 5–6) and `migrate_backlog.py`
  (ticket 10) changes nothing for such a repo: it keeps selecting from and writing to `backlog.md`.
  A repo switches only once its file queue is empty — after migration, or when it never had one.
  A writer that still appends to `backlog.md` on a switched repo flips it back to `backlog` on
  the next resolution, so no item becomes invisible. agent-toolkit itself stays on `backlog` until
  ticket 11 migrates it, which keeps tickets 2–11 selectable throughout.
- `github` with `gh` missing or unauthenticated is a hard error naming the fix (`gh auth login`).
  It never falls back to `backlog.md`: a silent fallback re-creates the tracked queue on exactly
  the repos this change moves off it.

### Backend contract (version 1)

Reference doc: `dev/skills/task-next/references/queue-backend-contract.md` (owned by `task-next`,
cited by every caller). Invocation: `<command> <op>` with one JSON object on stdin, one JSON object
on stdout, diagnostics on stderr. Exit 0 = ok, 2 = op unsupported by this backend, 1 = error.
Every request carries `"contract": 1` and `"repo": "<abs toplevel>"`.

| Op | Required | Input | Output |
|----|----------|-------|--------|
| `describe` | yes | — | `backend`, `contract`, `visibility` (`public`/`private`/`unknown`), `ops`, `close_ref_template` (e.g. `"Closes {ref}"`) |
| `list` | yes | `full_scan`, `parked`, optional `ref` (read the queue as committed at that rev) and `tasks` (path) — `backlog` uses both as `backlog_candidates.py --ref/--tasks` does; `github` ignores them | `candidates[]` (`id`, `ref`, `title`, `tag`, `labels`, `items[]`, `url`), `parked[]` (`ref`, `kind`: `blocked`/`deferred`, `payload`), `claimed[]`, `warnings[]` |
| `show` | yes | `ref` | `ref`, `title`, `body`, `labels`, `blocked_by[]`, `parent`, `url` |
| `create` | yes | `items[]`: `key` (stable across retries), `title`, `body`, `labels`, `parent_key`, `blocked_by[]` (batch keys or existing refs) | `created[]`: `key`, `ref`, `url`, `reused` (bool); `incomplete[]`: `key` + the relation still missing |
| `rejected` | yes | — | `entries[]`: `ref`, `title`, `reason`, `refile_bar` |
| `reject` | no | `ref`, `reason`, `refile_bar` | `ref` |
| `defer` | no | `ref`, `reason` | `ref` |

Constraints the contract carries for the Forgejo case (edge proxy drops PATCH/PUT, DELETE
unproven): **claim needs no remote write**, **close happens through the PR/commit closing
keyword** (`close_ref_template`), and no required op removes a label or edits an existing item.
`reject` and `defer` are optional; on exit 2 the caller reports the item and the requested
action for the user to do by hand.

**`create` is retry-safe.** Each item's `key` is written into the issue body as
`<!-- queue-key: <key> -->`. Before creating, the backend looks the key up (open or closed) and
reuses a match instead of creating a duplicate; it then applies any parent/blocker relation the
match is missing. A relation that still fails is returned in `incomplete[]` and the item stays in
the pending store until a later `publish` completes it. A response lost after GitHub created the
issue is therefore re-sent safely.

The built-in `backlog` backend answers `create` with `{"edit_file": "backlog.md"}` (the caller
keeps today's hand-edit path and templates) and maps the rest onto the existing parser.
`backlog_candidates.py --json` prints a bare array of `{source, kind, title, line, items}`
(`items` is a count), so the mapping is explicit: `ref` = `backlog.md:<line>`, `title` = heading,
`tag` = the shared `[type]` of the group's items (else empty), `items[]` = the group's open item
texts in document order (read from the tokenizer, not the count), `labels`/`url` empty;
`parked[]` from `--parked --json`; `claimed[]` from the claimed-skip data. `show` (one item or
heading by `ref`) and `rejected` (the plain bullets under `## Rejected — do not re-file`, split
into title / reason / re-file bar) are new readers ticket 1 adds — today's script only skips that
section. Selection behavior on that backend is unchanged.

### GitHub mapping

- **Item = issue**, labelled `task-queue`. Only open issues carrying that label **and** authored
  by `OWNER`/`MEMBER`/`COLLABORATOR` are candidates. Labels need triage access, so the label is
  the trust gate; on a public repo a stranger's issue never reaches an unattended cycle. Comments
  are never read as instructions.
- **Type tag** (`[FEAT]`, `[FIX]`, …) stays the title prefix, so `task_nodes.py branch` and the
  full-scan type priority work unchanged.
- **Groups.** Today's `##` section role becomes a label: `review` (Review Backlog), `security`
  (private repos only), `someday`. Today's ≥2-item candidate group becomes a **parent issue with
  sub-issues** (the current "heading = one contract" rule). Selecting the parent takes its
  **eligible** open sub-issues — each passing the trust gate and not blocked, deferred or claimed —
  as one Sprint Contract; an ineligible sub-issue stays out of scope and is named in the plan.
  Sub-issues of a listed parent are never standalone candidates, so the fast path cannot take one
  alone. A parent whose open sub-issues are all ineligible is parked. A lone item is a plain issue. `task-tickets` keeps one ticket =
  one issue, no parent.
- **Order.** Fast path: oldest issue number first, `someday` last, cap 3. Full scan: today's type
  priority, then issue number.
- **Blocked by** → GitHub issue dependencies (`addBlockedBy`; read via `blockedBy`). An issue
  with an open blocker is parked. A closed blocker unblocks with no edit, so *Blocked-marker sync*
  and `prune-backlog`'s orphaned-marker warning do not apply.
- **Deferred** → label `deferred` plus a `Deferred: <reason>` body line; parked.
- **Claim** (no remote write): an issue is claimed when (a) a local `.worktrees/*/tasks.md`
  `## Covers` lists its ref, (b) an open PR closes it (`closedByPullRequestsReferences` with
  `includeClosedPrs: false`), or (c) a commit on the local default branch not yet on its remote
  carries its closing keyword (`git log origin/<default>..<default>`, where `<default>` is resolved
  as `dispatch.py` does: `git symbolic-ref --quiet refs/remotes/origin/HEAD`, else `main`/`master`
  when that remote branch exists; unresolvable → skip (c) and add a warning, never fail `list`).
  The local default-branch ref is shared by every worktree, so a `--tree` run reads the same
  commits as the main checkout. (a) matches today's same-machine claim; (b) adds
  a cross-machine claim from PR creation on. The window between `worktree add` and PR creation on a
  second machine stays unclaimed, as it is today.
- **Completion.** The cycle records each covered ref in `## Covers` — the selected sub-issues, plus
  the parent's ref only when every open sub-issue is covered (otherwise the parent stays open with
  the rest, and closes with the cycle that covers the last one); the review cycle writes one
  `close_ref_template` line per ref into the PR body **and** the squash/merge commit message, so
  the issue closes on merge or on a direct push to the default branch. No queue edit at cleanup.
- **Rejected — do not re-file** → the issue is closed as `not planned` with a comment holding the
  reason and re-file bar; `rejected` lists closed-not-planned `task-queue` issues. Writers check
  it before filing, as they check the section today.
- Labels are created on first `create` (`gh label create` only when missing).

### Writers and authority

- Writers call `create`; on `edit_file` they follow the existing backlog templates. Affected:
  `task-tickets`, `task-review-cycle` (*Recording out-of-scope and non-blocking findings*: a
  cycle with ≥2 findings files one parent `Review follow-ups — PR #N` with sub-issues),
  `harness-capture`, `test-prune`, `repo-architecture`, `reference-review` (rejected check),
  `harness-init/scripts/sweep.sh`, `dev/commands/security-overview.md`.
- **`queue-write` is a standing user grant on the `github` backend** (decided by the user,
  2026-11-27): every repo, public and private, attended or dispatched/unattended. Writers file
  tickets, review findings, deferred follow-ups and `harness-capture` deltas as issues with no
  per-run approval, plan-gate confirmation or forwarded grant. Reason: most runs are dispatched and
  unattended, and a grant-gated default would leave findings local again — the problem this change
  exists to fix. Filing an issue is not a Git write, so Git limits (`implementation-only`,
  `no-push`, `pr-only`, …) never restrict it.
- `git-authorization.md` records the standing grant and one limit, `no-queue-write`, set only from
  an explicit user instruction forbidding queue writes for that run.
- **Pending store = failure path only.** When `gh` becomes unreachable or unauthenticated mid-write,
  or `no-queue-write` is set, the writer stores the drafts in
  `$(git rev-parse --git-common-dir)/agent-queue/pending.json` — outside the working tree and
  history — reports them, and `queue_backend.py publish` posts them in a later run. It is never
  the default path.
- On the issues backend `task-new`'s *Queue without implementing* route needs no commit and no
  *Queue documentation cycle*: it calls `task-tickets`, which files the issues directly under the
  standing `queue-write` grant. The working-tree gate's `backlog.md` carve-out and `queue_delta` apply only on
  the `backlog` backend; `docs/design/` stays carried.

### Security findings

- Rule: a security finding is never filed to a backend whose `describe` reports `visibility:
  public`.
- `security-overview` on a public GitHub repo writes nothing to the queue: it reports the open
  alerts by number (Dependabot/code-scanning/secret-scanning) and the suggested fix for each; a fix
  starts with `/dev:task-new` naming the alert number. On a private repo it files one issue per
  alert labelled `security`, keyed by a hidden `<!-- gh-alert: <kind>/<number> -->` body marker so a
  rescan updates nothing it already filed.
- A review-cycle finding with category `security` on a public repo becomes a **draft repository
  security advisory** (`POST /repos/{o}/{r}/security-advisories`, visible to admins only),
  created automatically under the standing grant; the cycle report and any later PR cite only the
  GHSA id. On the failure path (advisory call fails, or `no-queue-write`) it is reported in-session
  only — never written to a file or the pending store.
- `unknown` visibility (built-in `backlog` backend on a non-GitHub host) keeps today's behavior.

### Legacy backlog.md on a GitHub repo

A github.com repo whose `backlog.md` has open items resolves to `backlog` (*Backend resolution*),
so those items stay selectable. Once `migrate_backlog.py` exists (ticket 10), `list` on such a
repo adds a warning (`backlog.md has N open item(s); this repo stays on the file queue until you run
migrate_backlog.py`). `task-next` relays it verbatim; `dispatch.py pick` passes it through on
stderr. Nothing is ignored silently at any point of the rollout.

### Migration

`dev/skills/task-next/scripts/migrate_backlog.py`: dry-run by default, prints the issue plan;
`--apply` writes under the standing `queue-write` grant. Mapping: each `- [ ]` item → issue (title from the item line's
first sentence, the rest + wrapped lines → body); an `##`/`###` group with ≥2 items → parent +
sub-issues; `*(blocked by: <slug>)*` → dependency on the issue created for that heading;
`*(deferred: …)*` → `deferred`; `## Rejected — do not re-file` bullets → issues closed
`not planned`; `## Security Fixes` items on a public repo → refused and listed. Each item's
`create` key is `backlog-migrated:<sha1 of heading+item>`, so a re-run reuses issues already
created and completes their missing relations (retry-safe `create`). `--apply` deletes a line
from `backlog.md` only after its issue exists **and** every parent/blocker relation it needs is
confirmed (no `incomplete[]` entry); a partial run leaves the unconfirmed lines in place. The
deletion is a working-tree change the user commits once; the file is deleted when nothing remains.

### Script and doc surface per backend

| Surface | Issues backend change |
|---------|-----------------------|
| `backlog_candidates.py` | unchanged; becomes the `backlog` backend's reader |
| `task_nodes.py prune-backlog` | not run (cycle skips it); unchanged on `backlog` |
| `task-next` SKILL, `cycle.md`, `tree.md`, `batch.md`, `edge-cases.md` | select via `queue_backend.py list`; `## Covers` holds refs; cleanup skips prune; `--ref` pins the branch base only |
| `dispatch.py pick` | calls `queue_backend.py list`; `no backlog.md` check becomes backend-aware |
| `reconcile-harness.py` | skips its `backlog.md` writes on the issues backend |
| `validate-harness.sh` §9 | GitHub origin: absent `backlog.md` is expected; open items → WARN with migration pointer |
| `check_plugin_contracts.py` backlog-history | not applicable on the issues backend |
| `scripts/ci/check_harness_drift.py` | touched only if new prose names a target-repo file it flags |
| `harness-init` templates, `harness-invariants.md` *Reconciliation Contract*, `workflows-template.md` | state the backend split; `backlog.md` created only on the `backlog` backend |

## Alternatives rejected

- **Keep `backlog.md` and fix conflicts with a merge driver or per-item files** — removes
  conflicts only; queue writes still land in the working tree and history (goal fails).
- **Queue on an orphan branch / git notes** — no working-tree trace, but still not trackable
  without a checkout and conflicts move to that ref.
- **GitHub Projects v2 as the queue** — extra object and scopes (`project`) per repo; issues
  already carry labels, dependencies and PR links.
- **Claim by label (`in-progress`) or assignee** — needs a removal on release; Forgejo cannot
  remove labels through its proxy and DELETE is unproven; a crashed run leaves a stale claim.
- **Claim by opening a draft PR at worktree creation** — needs feature-push and PR authority at
  claim time, which many runs lack; the current same-machine claim already covers the window.
- **Close issues from cleanup via the API** — a cleanup that runs before merge would close work
  that never landed; the closing keyword ties closure to the merge itself.
- **Groups as labels only (no sub-issues)** — loses the "one heading = one contract" selection
  unit; a label is a filter, not a scope boundary.
- **Per-repo adapter config file** — a tracked queue artifact again, and one host's adapter would be
  configured repo by repo.
- **Grant-gated `queue-write` with the pending store as the default** — most runs are dispatched
  and unattended, so findings would stay local until someone publishes them: the original problem.
- **Hold the dev release until tickets 5, 6 and 10 ship** (to avoid a half-switched queue) —
  blocks unrelated releases for the whole rollout; the resolver's open-items rule makes any
  release order safe instead.
- **Silent fallback to `backlog.md` when `gh` fails** — re-creates the tracked queue on GitHub
  repos without anyone noticing.
- **Pick any open issue** — on a public repo it hands untrusted issue bodies to an unattended
  cycle.

## Testing Decisions

- `queue_backend.py --test`: resolver order (env, github host, registry, fallback), contract
  framing (exit codes, unsupported op), `backlog` backend parity after the documented mapping — same candidate titles, order and
  open-item counts as `backlog_candidates.py --json --counts` on the existing fixtures; `list`
  with `ref` reads the committed queue; `show` and `rejected` readers.
- GitHub backend tests run against recorded `gh api graphql` JSON fixtures through an injectable
  runner (no network in CI): trust gate, sub-issue groups, blocked/deferred parking, the three
  claim sources (including an unset `origin/HEAD`), sub-issue eligibility, resolver staying on
  `backlog` while open file items exist, retry-safe create (key reuse, `incomplete[]`), create
  with batch-key dependencies.
- `migrate_backlog.py --test`: fixture `backlog.md` → plan JSON (groups, blockers, deferred,
  rejected, security refusal, idempotency marker); `--apply` against the fake runner.
- A test-contract adapter (tiny script under the test fixtures) proves an external command plugs
  in through the registry.
- Each new `--test` gets its `harness-check.yml` step (`AGENTS.md` → Working with Existing Code).
- Manual: `migrate_backlog.py` dry-run on `../knue-pic` reviewed by the user, then `--apply`, then
  one `task-next --tree` cycle on knue-pic that closes an issue through its PR.
- `bash dev/skills/harness-init/scripts/validate-harness.sh` and `python3 scripts/ci/check_harness_drift.py`
  green on every ticket.

## Out of Scope

- The Forgejo adapter and any Forgejo API work (agent-home-knue).
- GitLab, Bitbucket, or GitHub Enterprise hosts (they resolve to `backlog` unless an adapter is registered).
- Changing `tasks.md`'s role (Sprint Contract + `## Covers`), the contract archive, or the
  CHANGELOG closure record.
- Projects v2 boards, milestones, issue types, assignees.
- Auto-fixing or dismissing security alerts.

## Further Notes

- Bootstrap: these tickets are written to this repo's `backlog.md` because the issues backend does
  not exist yet. The resolver's open-items rule keeps agent-toolkit on `backlog` while they are
  open, so they stay selectable; the last ticket migrates agent-toolkit itself.
- GraphQL fields verified to exist on 2026-11-27 (`gh api graphql` introspection): `Issue.blockedBy`,
  `blocking`, `closedByPullRequestsReferences`, `subIssues`, `parent`, `stateReason`; mutations
  `addBlockedBy`, `removeBlockedBy`, `addSubIssue`, `closeIssue`. Draft security advisory creation
  (`POST /repos/{o}/{r}/security-advisories`) was not exercised — verify in the ticket that uses it.
- knue-pic (public): 8 open items, all `[debt]`/`[feat]`/Someday — no security items to refuse.
- Risk: GitHub API rate limits on large `list` calls. Fetch issues with labels, blockers,
  sub-issues and closing PRs in one GraphQL query shape, but page every connection selection
  depends on; a page limit reports an incomplete result, never an empty queue.
- Risk: issue bodies are written by the agent for a public audience on public repos; writers must
  apply the same care as a public PR body (no secrets, no internal hostnames).
