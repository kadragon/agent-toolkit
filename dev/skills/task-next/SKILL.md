---
name: task-next
version: 2.21.0
description: >-
  Pull the next queued item from the repo's queue (backlog.md/tasks.md, or GitHub issues)
  and run the full code cycle: branch,
  Sprint Contract, implement, version bump, review, commit, push, PR and merge (possibly
  direct base-branch merge/push). Flags: --all (batch execution), --tree (worktree isolation).
  New work you just described → task-new.
disable-model-invocation: true
---

# Next Tasks

Pick queued work and run the code cycle in `references/cycle.md`. This skill is the selection
layer; the cycle and the review are elsewhere.

**Modes:** default = single-pick (Steps 1–4). `--all` (or "전부 처리", "모두 돌려", "batch all")
→ `references/batch.md`. `--tree` → single-pick through a git worktree, `references/tree.md`.
`--resume <slug>` → resume the stopped run in `.worktrees/<slug>` instead of selecting.
A free-text request not yet on the queue is `task-new`'s job.

## Phase index

Use `rg -n '^#{2,3} ' <file>` to find Markdown headings and ignore matches inside code fences.
Read each section up to the next heading at the same or a higher level. Resolve paths from
this skill. For a dispatched `--tree` cycle, use this order:

| Phase | Sections to open |
|---|---|
| Confirm the exact assignment | *Prerequisites*, then *Step 1 — Gather candidates* through its dispatched rule |
| Create the worktree and archive the contract | `references/tree.md` → *--tree mode* and `references/cycle.md` → *Branch* (including *Worktree cycle*), *Plan gate*, *Sprint Contract*. For Git effects, open `references/git-authorization.md` → *Establish and carry authority*, *Check before execution* |
| Implement and prepare the candidate | *Step 3 — Run the cycle* and `references/cycle.md` → *Implement*. After implementation, open *Version bump*, *Cleanup*, *Validation evidence* there |
| Start review | *Step 4 — Hand off* and `references/cycle.md` → *Hand off*. Follow its direct call to `dev:task-review-cycle` and start at *Caller gate* |

Open *Step 2* for manual selection or parked entries, and open `references/edge-cases.md` when
an edge case applies.

## Prerequisites

**Sweep merged worktrees.** Resolve `SKILL_DIR` to this skill's absolute directory. Before queue
selection, relay the sweep output and keep the main checkout on its current branch.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
REPO=$(git rev-parse --show-toplevel) || exit 1
PY=$(command -v python3 || command -v python || true)
[[ -z "$PY" ]] || "$PY" -I -X utf8 "$SKILL_DIR/scripts/worktree_sweep.py" "$REPO"
```

**Pin the worktree base.** For `--tree`, pin the remote base before resolving the queue or
applying the working-tree gate:

```bash
git fetch origin || exit 1
BASE=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD) \
  || { echo "origin/HEAD unset — run: git remote set-head origin --auto" >&2; exit 1; }
BASE_SHA=$(git rev-parse --verify "$BASE^{commit}") || exit 1
echo "base: $BASE  selecting from: $BASE_SHA"
```

**Queue backend.** Every queue read goes through `scripts/queue_backend.py`
(`references/queue-backend-contract.md`). Resolve it once before applying the working-tree gate.
Under `--tree`, set `REF` to the pinned `BASE_SHA`, so it resolves against the same base
`backlog.md` the `list` calls read (this checkout's copy may differ):

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
QB="$SKILL_DIR/scripts/queue_backend.py"
[[ -r "$QB" ]] || { echo "Bundled script missing or unreadable: $QB" >&2; exit 1; }
REPO=$(git rev-parse --show-toplevel) || exit 1
REF="<BASE_SHA under --tree, else empty>"
DESCRIBE=$(jq -nc --arg r "$REPO" --arg ref "$REF" \
  '{contract: 1, repo: $r} + (if $ref == "" then {} else {ref: $ref} end)' | python3 "$QB" describe) || exit 1
BACKEND=$(jq -r '.backend' <<<"$DESCRIBE")
CLOSE_REF_TEMPLATE=$(jq -r '.close_ref_template // empty' <<<"$DESCRIBE")
echo "queue backend: $BACKEND"
```

Exit 1 → relay stderr and stop (a `github` backend without `gh` auth names `gh auth login`; it
never falls back to `backlog.md`). Every rule below that names `backlog.md` lines, markers or
`prune-backlog` applies to the `backlog` backend; the **issues backend** (`CLOSE_REF_TEMPLATE`
non-empty: `github`, or an adapter that closes through a keyword) takes the branch stated beside it.

**Required:** on `backlog`, `backlog.md`. Missing → stop and point to `dev:harness-init`. Under `--tree`, this
checkout's copy does not count: test the pinned base commit's copy
(`git cat-file -e "$BASE_SHA:backlog.md"`); missing there → stop with the same
pointer. The issues backend needs no queue file. Read `docs/conventions.md` when present; when absent the linter is the authority.

**Working tree gate.** Capture the state before judging dirty files:

```bash
BACKEND="<backend printed by describe>"
dirty=$(git status --porcelain)
current_branch=$(git branch --show-current)   # every row below reads it, dirty or clean
task_worktree=$(git worktree list --porcelain | grep -E '^worktree .*/\.worktrees/' || true)   # dirty or clean
if [[ -n "$dirty" ]]; then
  task_contract_dirty=$(git status --porcelain -- tasks.md)
  design_dirty=$(git status --porcelain -- ':(top)docs/design')
  backlog_dirty=''
  queue_delta=''
  if [[ "$BACKEND" == backlog ]]; then
    backlog_dirty=$(git status --porcelain -- ':(top)backlog.md')
    queue_delta=$(git diff --stat HEAD -- ':(top)backlog.md')   # HEAD includes staged changes
    non_queue_dirty=$(git status --porcelain -- ':(exclude,top)backlog.md' ':(exclude,top)docs/design')
  else
    non_queue_dirty=$(git status --porcelain -- ':(exclude,top)docs/design')
  fi
fi
```

Base branch means `main` or `master`.

| State | Action |
|-------|--------|
| `--resume <slug>`, or the user names a worktree | *Work already in flight* on `.worktrees/<slug>` only (`references/edge-cases.md`) |
| `--tree`, any branch, clean or dirty — except on base with `task_contract_dirty` non-empty, which takes the legacy row below | proceed: this checkout is never read for selection, edited, or switched, so its branch and dirty files are someone else's (at most one non-`--tree` session, or the user). Announce them in one line — `main checkout: <current_branch>, <N> dirty file(s), left as is` — and, when `backlog_dirty` or `design_dirty` is non-empty, add that those edits are invisible to `--tree` until committed to base. Step 1 selects from the base |
| clean on base branch | proceed |
| feature branch, even clean | inspect *Work already in flight* before selecting new work |
| dirty, not on base branch | *Work already in flight* (`references/edge-cases.md`) |
| on base branch, `task_contract_dirty` non-empty | same edge case — legacy only: a pre-collapse-free `--tree` run stopped after removing its worktree |
| on base branch, `non_queue_dirty` empty | Carry dirty `docs/design/` files on either backend and dirty `backlog.md` only on `backlog`. Announce the carried design docs and, when `backlog_dirty` is non-empty, quote `queue_delta` (or the file's line count when untracked). Proceed |
| anything else | list the dirty files, stop, ask the user to commit, stash, or discard |

On the `--tree` row or a base-branch row that proceeds, a non-empty `task_worktree` is other sessions' runs, not this
one's: announce them in one line (`skipping 2 in-flight worktrees: .worktrees/foo,
.worktrees/bar`), then select without asking. Never inspect or adopt one unasked — Step 1
skips the `backlog.md` items they claimed.

`tasks.md` is optional. It holds the Sprint Contract and nothing else, exists only when a
`## Covers` list is needed (a pre-existing `status: open` h1 block, or a ≥2-item group;
`--tree` and the issues backend always), and every persistent item lives in the queue. If `list` warns
that `tasks.md` still carries a `## Review Backlog` / `## Security Fixes` section, move it to
`backlog.md` verbatim first.

## Step 1 — Gather candidates

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
QB="$SKILL_DIR/scripts/queue_backend.py"
[[ -r "$QB" ]] || { echo "Bundled script missing or unreadable: $QB" >&2; exit 1; }
REPO=$(git rev-parse --show-toplevel) || exit 1
REF="<BASE_SHA under --tree, else empty>"
REQ=$(jq -nc --arg r "$REPO" --arg ref "$REF" \
  '{contract: 1, repo: $r} + (if $ref == "" then {} else {ref: $ref} end)') || exit 1
jq -c '. + {full_scan: false}' <<<"$REQ" | python3 "$QB" list   # fast path, cap 3
jq -c '. + {full_scan: true}' <<<"$REQ" | python3 "$QB" list    # full list, type priority
jq -c '. + {parked: true}' <<<"$REQ" | python3 "$QB" list       # .parked[]: blocked/deferred items, Step 2 stop
```

Exit 1 → relay stderr and stop. Each candidate is `ref`, `title`, `tag`, `items[]` and `counts`;
on the issues backend also `item_refs[]` (parallel to `items[]`) and `excluded[]` (sub-issues left
out, with the reason — name them in the plan).

`--tree` selects from the pinned base commit it will branch from. Use `REF="$BASE_SHA"` from
*Prerequisites*, so on `backlog` both files are read as committed there and claims are
measured against it (this checkout's own `## Covers` and pruned lines included); on the issues
backend `ref` pins only the branch base and adds this checkout's own `## Covers` to the claims. On
`backlog`, read the selected lines in Steps 2–3 from the same commit (`git show
"$BASE_SHA:backlog.md"`). Hand the printed SHA to `references/tree.md` → *Branch* — a later fetch
must not move the worktree off the queue it was selected from.

The backend owns selection. On `backlog`: `tasks.md` `status: open` h1 blocks, then `backlog.md` h2/h3 groups
with open `- [ ]` items, skipping `[x]`/`[>]`/deferred/blocked items, items another
`.worktrees/` run has claimed, and anything inside comments or code fences. On the issues backend:
trusted open queue issues, oldest first, skipping blocked, deferred and claimed ones (a
`.worktrees/*/tasks.md` `## Covers` ref, an open closing PR, an unpushed closing commit); a parent
issue is one candidate whose items are its eligible sub-issues. **Read `warnings[]` every
run** (on `backlog`, the candidate script's stderr): a claimed-skip line names each item another worktree holds, by line — relay it, and
leave those lines out of Step 2–3 scope even when their group is selected; an
unbalanced-fence warning makes that file untrustworthy; a persistent-section warning means
`tasks.md` needs the move above; a zero-candidate diagnosis is relayed verbatim and goes to Step 2's zero-groups report
(the full scan qualifies groups by the same test, so it finds none either); a truncation note
means the fast path hid groups — say how many when offering more.

| Fast-path count | Action |
|-----------------|--------|
| 1 | announce the group → Step 3 |
| 2–3 | one `AskUserQuestion` (Codex: a numbered list) listing the candidates plus **"더 많은 항목 보기"** as the last option; that option → the full scan → Step 2 |

Unattended run: no question — run the full scan, take `[1]`, announce.

**Dispatched `--tree` with `Dispatch mode: parallel-worktree`** → this overrides the selection defaults.
The forwarded request and Git limits are handoff metadata.
Run the full scan against the pinned base. Match the assigned source file, heading, and exact
item text (issues backend: the assigned refs) against the eligible candidates. Select only those assigned items. If the assignment
is missing, ambiguous, changed, blocked, or claimed, report the mismatch to the home session
and stop before branch or worktree creation. Never substitute another candidate.

## Step 2 — Select (full-scan list)

Print every group as `[N] <source>: <title> (<M> items)` (issues backend: `[N] <ref>: <title> (<M> items)`) and wait for a number (unattended:
`[1]`). Zero groups → read `warnings[]` first; report "backlog and tasks are clear" only when nothing
was hidden. The issues backend prints no zero-candidate diagnosis or fast-path truncation note:
run the parked list before reporting it clear, and offer the full scan whenever the fast path
shows 3. A group of >8 open items → offer all-or-subset (unattended: take the first 8 open items in
document order and name the remainder). A group whose every open item is deferred/blocked is not a candidate — surface the
blocker.

**All groups blocked → report the blockers, then stop.** Run the parked list and end the report with
every entry of `parked[]`: the item, its marker (`kind` and `payload`), and one label.

- **agent can clear** — the blocker is work this session can do, such as a check to run or a
  change no queue item covers. Say what the work is.
- **needs you** — a decision, a credential or access, an external event, or a date. Say what.

Label by the root blocker. An item `blocked by` another queue item inherits that item's label,
followed down the chain: in an all-blocked stop the named item is itself parked, so it is never
clearable just because it is on the queue. Read each marker's payload and check it against the
repo before labelling; an unverified guess is labelled `unknown`.

A marker whose blocker has verifiably landed is not a blocker. Delete it per
`references/cycle.md` → *Blocked-marker sync*, re-run Step 1, and report the stop only if the
queue is still all blocked; name the markers removed. Under `--tree` Step 1 reads the base, so a
local delete changes nothing: do not delete, list the marker as **agent can clear** (remove it on
base) and stop. On the issues backend there is no marker to delete: a closed blocker unparks its
issue with no edit, so a listed blocker ref is still open — label it like any other. Clearing any other blocker is new work:
offer it, do not start it unasked.

## Step 3 — Run the cycle

Follow `references/cycle.md` end to end with these overrides; Git authority is
`references/git-authorization.md`:

**Mark active — after the plan gate.**
- `tasks.md` h1 block (`status: open`) → flip to `status: active`; the block is the contract.
- `backlog.md` group with ≥2 in-scope items → write `tasks.md`: `# <heading verbatim>`,
  `status: active`, the contract, and `## Covers` listing each item line **verbatim** (the
  deletion list). Leave the items `- [ ]` in `backlog.md` until cleanup.
- exactly 1 item → no `tasks.md`; archive the contract per `cycle.md` and carry the item's verbatim line to
  `prune-backlog` yourself. Worktree runs (`--tree`, exit 3) write `tasks.md` even for one item, in
  the worktree before the plan gate (`references/cycle.md` → *Worktree cycle* → *Claim*).
- issues backend, any item count → write `tasks.md`: `# <candidate title verbatim>`, `status:
  active`, the contract, and `## Covers` with one `- <ref> <title>` line per covered ref
  (`references/cycle.md` → *Covered refs*). The issues are never edited. Before the plan gate,
  read each selected ref's body with `show` (and the parent's): the Source / Done when a backlog
  line carries inline lives there, and the contract takes its criteria from it.

**Cleanup** runs `prune-tasks` only when a sprint block exists, and on `backlog` `prune-backlog`
over the `## Covers` lines (or the single carried line). Post-merge, `backlog.md` and `tasks.md`
carry no `[x]`, `[>]`, or stale sprint markers. The issues backend runs no `prune-backlog` and no
*Blocked-marker sync*: its covered refs close through the closing lines the review cycle writes.

## Step 4 — Hand off

Per `references/cycle.md` → *Hand off*: `args: --from task-next --auto`, Sprint Contract restated
verbatim, with saved archive and targeted evidence, plus covered refs and `close_ref_template`
on the issues backend. `--tree` and parallel batches check the integrated candidate before
hand-off. The review cycle runs full verification on the final candidate.

## Edge cases

Recognise by name; open `references/edge-cases.md` before acting.

- **Work already in flight** — a feature branch in this checkout (not under `--tree`), or a `.worktrees/<slug>` run
  named by `--resume <slug>` or the user, including clean committed work. Recover the contract, then choose the earliest unmet obligation.
- **Deferred backlog item (≥2 candidates)** — surface the blocker, confirm it is resolved.
- **Deferred item in a group** — warn and continue with the group's other items.
- **Parent issue with no open sub-issue** — issues backend; cover just its ref.
- **Review finding spans multiple PRs** — scope to the specific `file:line`.
