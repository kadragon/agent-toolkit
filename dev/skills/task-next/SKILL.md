---
name: task-next
version: 2.14.0
description: >-
  Pull the next queued item from backlog.md/tasks.md and run the full code cycle: branch,
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

## Prerequisites

**Required:** `backlog.md`. Missing → stop and point to `dev:harness-init`. Under `--tree`, this
checkout's copy does not count: defer the check to right after Step 1 pins `BASE_SHA`, and test the
base commit's copy (`git cat-file -e "$BASE_SHA:backlog.md"`); missing there → stop with the same
pointer. Read `docs/conventions.md` when present; when absent the linter is the authority.

**Working tree gate.** Capture the state before judging dirty files:

```bash
dirty=$(git status --porcelain)
current_branch=$(git branch --show-current)   # every row below reads it, dirty or clean
task_worktree=$(git worktree list --porcelain | grep -E '^worktree .*/\.worktrees/' || true)   # dirty or clean
if [[ -n "$dirty" ]]; then
  task_contract_dirty=$(git status --porcelain -- tasks.md)
  non_queue_dirty=$(git status --porcelain -- ':(exclude,top)backlog.md' ':(exclude,top)docs/design')   # top: anchor at repo root
  queue_delta=$(git diff --stat HEAD -- backlog.md)                          # HEAD: a staged backlog.md still shows
fi
```

Base branch means `main` or `master`.

| State | Action |
|-------|--------|
| `--resume <slug>`, or the user names a worktree | *Work already in flight* on `.worktrees/<slug>` only (`references/edge-cases.md`) |
| `--tree`, any branch, clean or dirty — except on base with `task_contract_dirty` non-empty, which takes the legacy row below | proceed: this checkout is never read for selection, edited, or switched, so its branch and dirty files are someone else's (at most one non-`--tree` session, or the user). Announce them in one line — `main checkout: <current_branch>, <N> dirty file(s), left as is` — and, when `queue_delta` or a `docs/design/` file is dirty, add that these uncommitted queue edits are invisible to `--tree` until committed to base. Step 1 selects from the base |
| clean on base branch | proceed |
| feature branch, even clean | inspect *Work already in flight* before selecting new work |
| dirty, not on base branch | *Work already in flight* (`references/edge-cases.md`) |
| on base branch, `task_contract_dirty` non-empty | same edge case — legacy only: a pre-collapse-free `--tree` run stopped after removing its worktree |
| on base branch, `non_queue_dirty` empty | `backlog.md` and `docs/design/` alone are not stray (the `task-spec` → `task-tickets` hand-off leaves them uncommitted): announce that they are being carried, quote `queue_delta` (or the file's line count when untracked) and any design doc, proceed |
| anything else | list the dirty files, stop, ask the user to commit, stash, or discard |

On the `--tree` row or a base-branch row that proceeds, a non-empty `task_worktree` is other sessions' runs, not this
one's: announce them in one line (`skipping 2 in-flight worktrees: .worktrees/foo,
.worktrees/bar`), then select without asking. Never inspect or adopt one unasked — Step 1
skips the `backlog.md` items they claimed.

`tasks.md` is optional. It holds the Sprint Contract and nothing else, exists only when a
`## Covers` deletion list is needed (a pre-existing `status: open` h1 block, or a ≥2-item group;
`--tree` always), and every persistent item lives in `backlog.md`. If the candidate script warns
that `tasks.md` still carries a `## Review Backlog` / `## Security Fixes` section, move it to
`backlog.md` verbatim first.

## Step 1 — Gather candidates

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
CANDIDATES="$SKILL_DIR/scripts/backlog_candidates.py"
[[ -r "$CANDIDATES" ]] || { echo "Bundled script missing or unreadable: $CANDIDATES" >&2; exit 1; }
python3 "$CANDIDATES" --tasks tasks.md --backlog backlog.md              # fast path, cap 3
python3 "$CANDIDATES" --tasks tasks.md --backlog backlog.md --full-scan  # full list, type priority
python3 "$CANDIDATES" --backlog backlog.md --parked                      # blocked/deferred items, Step 2 stop
```

`--tree` selects from the base commit it will branch from, not this checkout: pin it first, then
add `--ref "$BASE_SHA"` to each command above, so both files are read as committed there and
claims are measured against it (this checkout's own `## Covers` and pruned lines included). Read
the selected lines in Steps 2–3 from the same commit (`git show "$BASE_SHA:backlog.md"`), and hand
the printed SHA to `references/tree.md` → *Branch* — a later fetch must not move the worktree
off the queue it was selected from.

```bash
git fetch origin || exit 1
BASE=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD) \
  || { echo "origin/HEAD unset — run: git remote set-head origin --auto" >&2; exit 1; }
BASE_SHA=$(git rev-parse --verify "$BASE^{commit}") || exit 1
echo "base: $BASE  selecting from: $BASE_SHA"
```

The script owns selection: `tasks.md` `status: open` h1 blocks, then `backlog.md` h2/h3 groups
with open `- [ ]` items, skipping `[x]`/`[>]`/deferred/blocked items, items another
`.worktrees/` run has claimed, and anything inside comments or code fences. **Read stderr every
run**: a claimed-skip line names each item another worktree holds, by line — relay it, and
leave those lines out of Step 2–3 scope even when their group is selected; an
unbalanced-fence warning makes that file untrustworthy; a persistent-section warning means
`tasks.md` needs the move above; a zero-candidate diagnosis is relayed verbatim and goes to Step 2's zero-groups report
(`--full-scan` qualifies groups by the same test, so it finds none either); a truncation note
means the fast path hid groups — say how many when offering more.

| Fast-path count | Action |
|-----------------|--------|
| 1 | announce the group → Step 3 |
| 2–3 | one `AskUserQuestion` (Codex: a numbered list) listing the candidates plus **"더 많은 항목 보기"** as the last option; that option → `--full-scan` → Step 2 |

Unattended run: no question — run `--full-scan`, take `[1]`, announce.

**Dispatched `--tree` with an assigned unit** → this overrides the selection defaults.
Run the full scan against the pinned base. Match the assigned source file, heading, and exact
item text against the eligible candidates. Select only those assigned items. If the assignment
is missing, ambiguous, changed, blocked, or claimed, report the mismatch to the home session
and stop before branch or worktree creation. Never substitute another candidate.

## Step 2 — Select (full-scan list)

Print every group as `[N] <source>: <title> (<M> items)` and wait for a number (unattended:
`[1]`). Zero groups → read stderr first; report "backlog and tasks are clear" only when nothing
was hidden. A group of >8 open items → offer all-or-subset (unattended: take the first 8 open items in
document order and name the remainder). A group whose every open item is deferred/blocked is not a candidate — surface the
blocker.

**All groups blocked → report the blockers, then stop.** Run `--parked` and end the report with
every item it lists: the item, its marker, and one label.

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
base) and stop. Clearing any other blocker is new work:
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

**Cleanup** runs `prune-tasks` only when a sprint block exists, and `prune-backlog` over the
`## Covers` lines (or the single carried line). Post-merge, `backlog.md` and `tasks.md` carry no
`[x]`, `[>]`, or stale sprint markers.

## Step 4 — Hand off

Per `references/cycle.md` → *Hand off*: `args: --from task-next --auto`, Sprint Contract restated
verbatim, with saved archive and validation evidence. `--tree` and parallel batches also verify
the integrated candidate after worktree checks.

## Edge cases

Recognise by name; open `references/edge-cases.md` before acting.

- **Work already in flight** — a feature branch in this checkout (not under `--tree`), or a `.worktrees/<slug>` run
  named by `--resume <slug>` or the user, including clean committed work. Recover the contract, then choose the earliest unmet obligation.
- **Deferred backlog item (≥2 candidates)** — surface the blocker, confirm it is resolved.
- **Deferred item in a group** — warn and continue with the group's other items.
- **Review finding spans multiple PRs** — scope to the specific `file:line`.
