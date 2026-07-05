## `--tree` mode (single task, worktree isolation)

Triggered by `--tree`. Runs Steps 1–2 identically to default single-pick. The code cycle (Step
3) is modified so implementation and QA run in an isolated git worktree, keeping the main
checkout on `main` throughout — useful when the user wants to preserve a clean working tree
while a task is in flight.

**Modified Branch step (replaces `git checkout -b` under `--tree`):**

```bash
SLUG=<slug>            # short slug derived from item title
BRANCH=<type>/<slug>   # derived as normal from item [type] tag + slug
git fetch
# ensure .worktrees/ is git-ignored — add to .gitignore if missing (edit main checkout, uncommitted)
# if $BRANCH already exists locally (prior failed run), delete it first: git branch -D "$BRANCH" (confirm with user)
git worktree add ".worktrees/$SLUG" -b "$BRANCH" origin/main
```

**Implement (workflows.md Step 3):** spawn `implementer` agent. Brief must include the **absolute
worktree path** AND these explicit CWD instructions (the Bash tool is stateless — CWD resets
to the main checkout on every call; a standalone `cd` has no persistent effect):

> "Your spawn CWD is the main checkout. The Bash tool is stateless — CWD resets each call.
> Every Bash command must begin with `cd <absolute-worktree-path> &&`
> (e.g. `cd /path/to/worktree && git status`, `cd /path/to/worktree && npm test`).
> Read/Edit/Write tool calls must use absolute paths under `<absolute-worktree-path>/`.
> Do NOT read or edit any file in the main checkout."

The agent works entirely inside the worktree — it must NOT touch `plugin.json` manifests,
`backlog.md`, `tasks.md`, or `CHANGELOG.md` anywhere (those are main-checkout edits done after QA).

**QA (workflows.md Step 4):** spawn `qa-verifier` pointed at the worktree path, verifying
against the Sprint Contract. Include the same CWD instructions in the brief: every Bash command
must begin with `cd <absolute-worktree-path> &&`; Read/Edit/Write use absolute paths under the
worktree. Same retry policy as Step 3 (one fix-and-re-verify cycle).

**If QA fails after one retry:** clean up and stop.
```bash
SLUG=<slug>            # same slug used in the Branch step above
BRANCH=<type>/<slug>   # same branch used in the Branch step above
git worktree remove --force ".worktrees/$SLUG"
git branch -D "$BRANCH"
```
Report the failure; main checkout remains on `main`.

**Version bump (workflows.md Step 5):** performed in the **main checkout** only — do NOT edit manifests inside the worktree. Read which files changed inside the worktree to determine which plugin directory to bump, then edit the manifests in the main checkout. Leave uncommitted (carries through to `$BRANCH` on `git checkout` since there is no conflict — implementer cannot touch manifests per the constraint above).

**Collapse after QA passes:**

Ensure the worktree is clean (implementer committed all changes to `$BRANCH`). If `git status` inside the worktree shows dirty files, commit them before proceeding — `git worktree remove` refuses on a dirty worktree.

```bash
SLUG=<slug>            # same slug used in the Branch step above
BRANCH=<type>/<slug>   # same branch used in the Branch step above
git worktree remove ".worktrees/$SLUG"   # worktree gone; branch $BRANCH still exists
git checkout "$BRANCH"                   # switch main checkout onto the feature branch
```

Now run **pre-merge cleanup** (backlog / tasks.md / CHANGELOG edits) in the main checkout on
`$BRANCH`, then hand off: `Skill(dev-tools:dev-review-cycle)` with `args: --auto` (Step 4).
