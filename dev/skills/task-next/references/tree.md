## `--tree` mode (single task, worktree isolation)

Triggered by `--tree`. Runs Steps 1–2 identically to default single-pick. The code cycle (Step
3) is modified so implementation and QA run in an isolated git worktree — the main checkout
stays on `main` throughout, but `--tree` isolates **code changes** only. The main checkout still
carries the uncommitted tracking files (`tasks.md`, and later the version bump) exactly as the
default single-pick path does; see the *Mark active* note and the *Version bump* paragraph below.

**Modified Branch step (replaces `git checkout -b` under `--tree`):**

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
NODES="$SKILL_DIR/scripts/task_nodes.py"
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }
BRANCH=$(printf '%s\n' "<each selected item line, verbatim>" \
  | python3 "$NODES" branch --title "<selected heading title>")
[[ -n "$BRANCH" ]] || { echo "branch derivation failed — see stderr above" >&2; exit 1; }
SLUG="${BRANCH#*/}"    # the branch name without its <type>/ prefix
git fetch
# ensure .worktrees/ is git-ignored — add to .gitignore if missing (edit main checkout, uncommitted)
# Persist ownership in .git/ because each Bash invocation starts without prior shell variables.
TREE_STATE_PATH=$(git rev-parse --git-path task-next-tree-state)
TREE_SNAPSHOT_PATH="${TREE_STATE_PATH}.gitignore"
if [[ -e "$TREE_STATE_PATH" || -e "$TREE_SNAPSHOT_PATH" ]]; then
  echo "stale task-next tree cleanup state exists; resolve the previous run first" >&2
  exit 1
fi
if ! grep -Fxq '.worktrees/' .gitignore 2>/dev/null; then
  if [[ -e .gitignore ]]; then
    cp -- .gitignore "$TREE_SNAPSHOT_PATH"
    printf '%s\n' restore > "$TREE_STATE_PATH"
  else
    printf '%s\n' remove > "$TREE_STATE_PATH"
  fi
  if [[ -s .gitignore ]]; then
    printf '\n.worktrees/\n' >> .gitignore
  else
    printf '.worktrees/\n' >> .gitignore
  fi
  GITIGNORE_ADDED=true
fi
# if $BRANCH already exists locally (prior failed run), delete it first: git branch -D "$BRANCH" (confirm with user)
git worktree add ".worktrees/$SLUG" -b "$BRANCH" origin/main
```

**Mark active:** runs in the main checkout, with one tree-mode exception to the default path's
single-item inline contract: every `--tree` run writes a backlog group's Sprint Contract —
`tasks.md`, `status: active`, and `## Covers` with the exact item line — there, uncommitted. It is
carried onto `$BRANCH` by the collapse `git checkout` below the same way the version bump is (see
**Version bump** further down), so a second invocation sees the run as in flight.

**Implement (`cycle.md` → *Implement*):** archive the approved contract per `cycle.md` →
*Sprint Contract*, prefixing that command with `cd ".worktrees/$SLUG" &&` — the Bash tool's CWD
resets to the main checkout on every call, and the archive is keyed by the branch of the checkout
it runs in, so an un-prefixed save keys this cycle's contract to the base branch (`cycle_state.py`
refuses that outright). Then spawn `implementer` agent. The implementer runs focused checks. Brief must include the **absolute
worktree path** AND these explicit CWD instructions (the Bash tool is stateless — CWD resets
to the main checkout on every call; a standalone `cd` has no persistent effect):

> "Your spawn CWD is the main checkout. The Bash tool is stateless — CWD resets each call.
> Every Bash command must begin with `cd <absolute-worktree-path> &&`
> (e.g. `cd /path/to/worktree && git status`, `cd /path/to/worktree && npm test`).
> Read/Edit/Write tool calls must use absolute paths under `<absolute-worktree-path>/`.
> Do NOT read or edit any file in the main checkout.
> Never run `git push --force`/`--force-with-lease`, `git reset --hard`, `git clean -f`/`-fd`,
> or `git branch -D` — if a fix seems to need one, stop and ask the user instead.
> If the same fix is attempted 3+ times on the same file without the lint/test command
> passing, stop and report to the user instead of continuing to retry.
> When you finish (or get stuck), put your full result in your final response — never finish
> silently, even when the result is empty or the run failed; a silent finish loses the result."

The agent works entirely inside the worktree — it must NOT touch `plugin.json` manifests,
`backlog.md`, `tasks.md`, or `CHANGELOG.md` anywhere (those are main-checkout edits done after QA).

**QA:** spawn `qa-verifier` pointed at the worktree path, verifying
against the Sprint Contract. Include the same CWD instructions in the brief: every Bash command
must begin with `cd <absolute-worktree-path> &&`; Read/Edit/Write use absolute paths under the
worktree; the same destructive-command guard applies — QA must not run
`git reset --hard`/`push --force`/`clean -f`/`branch -D` either. One fix-and-re-verify retry. Same
result-handoff instruction too: tell it to put its verdict in its final response, including an
empty/no-blocking-findings verdict (`docs/delegation.md`).

**If QA fails after one retry:** stop and preserve the worktree, branch, contract archive, and
main-checkout tracking/ignore state. Report unmet criteria. Destructive abandonment requires
explicit user authorization; a failed check does not authorize deletion.

Preserved state blocks the Branch step of every later `--tree` run ("stale task-next tree cleanup
state exists"), which is deliberate — that run must not start on top of this one. Resuming is the
default: collapse the worktree as below once QA passes. Only when the user explicitly authorizes
abandoning the run, undo the main-checkout ignore edit and clear the state files, in this order:

```bash
TREE_STATE_PATH=$(git rev-parse --git-path task-next-tree-state)
TREE_SNAPSHOT_PATH="${TREE_STATE_PATH}.gitignore"
TREE_STATE=$(cat "$TREE_STATE_PATH" 2>/dev/null || true)
if [[ "$TREE_STATE" == restore && -e "$TREE_SNAPSHOT_PATH" ]]; then
  cp -- "$TREE_SNAPSHOT_PATH" .gitignore   # the snapshot taken before `.worktrees/` was appended
elif [[ "$TREE_STATE" == remove ]]; then
  rm -f -- .gitignore                       # there was no .gitignore before this run
fi
rm -f -- "$TREE_STATE_PATH" "$TREE_SNAPSHOT_PATH"
```

Then drop the `status: active` block this run wrote to `tasks.md` (it covers work that never
landed), and remove the worktree and branch only with that same explicit authorization. Leave the
contract archive: `cycle_state.py retire` belongs after a merge, not after an abandonment.

**Version bump (`cycle.md` → *Version bump*):** performed in the **main checkout** only — do NOT edit manifests inside the worktree. Read which files changed inside the worktree to determine which plugin directory to bump, then run `bash scripts/bump-version.sh <plugin> <major|minor|patch>` (or hand-edit where that script is absent) in the main checkout. Leave uncommitted (carries through to `$BRANCH` on `git checkout` since there is no conflict — implementer cannot touch manifests per the constraint above).

**Collapse after QA passes:**

Ensure the worktree is clean (implementer committed all changes to `$BRANCH`). If `git status` inside the worktree shows dirty files, commit them before proceeding — `git worktree remove` refuses on a dirty worktree.

```bash
SLUG=<slug>            # same slug used in the Branch step above
BRANCH=<type>/<slug>   # same branch used in the Branch step above
git worktree remove ".worktrees/$SLUG"   # worktree gone; branch $BRANCH still exists
git checkout "$BRANCH"                   # switch main checkout onto the feature branch
TREE_STATE_PATH=$(git rev-parse --git-path task-next-tree-state)
TREE_SNAPSHOT_PATH="${TREE_STATE_PATH}.gitignore"
rm -f -- "$TREE_STATE_PATH" "$TREE_SNAPSHOT_PATH" # the added ignore rule now belongs to this branch
```

Now run **pre-merge cleanup** (backlog / tasks.md / CHANGELOG edits) in the main checkout on
`$BRANCH`, then `cycle.md` → *Validation evidence* on the complete candidate. The common Git
archive survives worktree removal. Carry it and the evidence when handing off: call the Skill tool with "dev:task-review-cycle" and `args: --from task-next --auto` (Step 4).
