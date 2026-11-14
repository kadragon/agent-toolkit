# Code cycle — shared by `task-next` and `task-new`

One implementation cycle from branch to hand-off. The calling `SKILL.md` names the item(s) and
the overrides that apply; everything else is here. `CYCLE_DIR` below is the absolute directory
of this file (`task-next/references/`), whichever skill is reading it.

## Branch

```bash
CYCLE_DIR="<absolute directory of this cycle.md>"
NODES="$CYCLE_DIR/../scripts/task_nodes.py"
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }
# queue item(s): pipe each selected item line verbatim; free-text request: pass --tag <TYPE> and no stdin
BRANCH=$(printf '%s\n' "<each selected item line, verbatim>" | python3 "$NODES" branch --title "<title>")
rc=$?
[[ -n "$BRANCH" ]] || { echo "branch derivation failed — see stderr above" >&2; exit 1; }
echo "branch: $BRANCH (exit $rc)"
[[ $rc -eq 0 ]] && git checkout -b "$BRANCH"
```

The script applies the shared-`[type]`-else-`fix/` rule and warns on stderr when it falls back.
Exit 1 with no name: origin/HEAD is unset and the base is unsure — run the `git remote set-head`
it names, then re-run the block.

**Exit 3** — this checkout is on a branch other than the base, or a detached HEAD. Landed or
not, a `checkout -b` here would branch from that HEAD instead of the base, and would switch any
cycle in flight out from under it. The block made no checkout; keep it that way and run this whole cycle in its own
worktree. Shell variables do not survive between Bash calls, so write the printed branch and the
base the warning names in as literals:

```bash
BRANCH="<the branch the block printed>"
BASE="<the base the warning names>"   # origin/<name>, or a local main/master when there is no origin
SLUG="${BRANCH#*/}"
if git remote get-url origin >/dev/null 2>&1; then git fetch || exit 1; fi
EXCLUDE=$(git rev-parse --git-path info/exclude)
mkdir -p -- "$(dirname -- "$EXCLUDE")"
grep -Fxq '.worktrees/' "$EXCLUDE" 2>/dev/null || printf '\n.worktrees/\n' >> "$EXCLUDE"
# if $BRANCH already exists locally (a partial run), delete it first: git branch -D "$BRANCH" (confirm with user)
git worktree add ".worktrees/$SLUG" -b "$BRANCH" "$BASE"
```

These are `tree.md`'s Branch lines minus leveling the local base, which this checkout does not
hold. From here on every step of this cycle and the review cycle — contract `save`, edits,
checks, version bump, cleanup, commits — runs in the worktree: each Bash command begins
`cd "<repo root>/.worktrees/<slug>" &&` with the literal path, file tools take absolute paths
under it, and the in-flight checkout is never read or edited. Unlike `--tree`, nothing collapses
back into this checkout: when the review cycle issues `merge-and-cleanup.sh`, append that
absolute worktree path as its optional fifth argument, `worktree_path`, so the merge removes the
worktree. Run it from inside the worktree — from the in-flight checkout, the script runs
`git checkout <base>` there — but keep the merge command itself unprefixed, the only shape an
auto-mode allow rule matches: issue `cd "<repo root>/.worktrees/<slug>"` as its own Bash call
first (the cwd carries to the next call), then the merge command.

## Scope

Look yourself first — one or two searches. Research delegation (`explorer`, else the built-in
`Explore`) follows the repository's delegation policy (`docs/delegation.md` where it exists);
without one, delegate only when the user or an applicable skill directs it. Eligibility never
mandates a spawn.

## Plan gate

This is the approval authority for intake, tickets, implementation, and resume. Carry forward
approved scope, acceptance criteria, and approach, citing the spec/ticket or explicit user
instruction in the contract. File count and `[FEAT]`/`[REFACTOR]` tags do not trigger approval.

Ask only for a material decision still open: changed scope, a new public API/schema decision,
architecture tradeoff, or an unauthorized irreversible effect. Present that delta and a
recommended choice; approval covers it once. Routine implementation choices within approved
constraints proceed. A same-session explicit "continue" already authorizes resume of that scope.
Unattended runs proceed within approved constraints; unresolved material decisions are reported
as blocked, never silently approved.

Git effects have a separate boundary: `git-authorization.md`.

## Sprint Contract

```markdown
**Tag:** [FEAT] | [REFACTOR] | [FIX] | [TEST] | [CONSTRAINT] | [DOCS] | [HARNESS] | [PLAN]
**Scope:** files or areas this change touches
**Approval source:** user-invoked: <verified invocation, scope> | explicit-user: <verified instruction, scope> | unknown
**Allowed Git actions:** <subset of: commit, feature-push, pr-write, base-merge, base-push, integrate | none>
**Git limits:** <none | implementation-only | no-push | pr-only | unknown>
**Acceptance criteria:**
- [ ] one concrete criterion per item → the test, command, or observation that proves it
**Out of scope:** explicit exclusions
**Lint/test command:** the command that must exit 0
```

The Tag is what the reviewer grades a `[FIX]` reproduction criterion or a `[REFACTOR]` behavior
pin against — write it in. A `[REFACTOR]` contract names the tests that hold the touched behavior,
green before the first structural edit (a characterization test written first where none exist).
A skill-authoring summary's `Skill slots:` block rides along per
`../../task-grill/references/skill-extraction.md` → *Carrying the slots*; for a queued item,
recover it from the cited spec/summary before implementation.
`cycle_state.py save` refuses a criterion with no `→ <check>`. A `[FIX]` contract names the test that
fails before and passes after; for other tags, write the test first where that sharpens the
criterion. A multi-item
group gets one checkbox per item. Keep the original contract in a branch-local archive before implementation, including the
approval source and exact selected backlog lines. `tasks.md` remains the optional queue-facing
copy when the caller needs a `## Covers` deletion list.

```bash
CYCLE_DIR="<absolute directory of this cycle.md>"
STATE="$CYCLE_DIR/../scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled state helper unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" save <<'SPRINT_CONTRACT'
<approved contract verbatim, approval source, and selected backlog lines>
SPRINT_CONTRACT
```

The helper prints the archive path under the common Git directory, keyed by branch; it survives
new sessions and worktree removal. Preserve it through review and merge, including failed or
abandoned runs. A different existing contract stops the write: inspect it first, and use
`save --replace` only for an approved scope revision or a confirmed new cycle on a reused branch;
it clears the old contract's notes and evidence. For `--tree`, save from the implementation
worktree; for parallel batches, save the aggregate contract on the integration branch before
convergence cleanup.

## Implement

Inline by default; delegating to `implementer` follows the same policy as *Scope*. A delegated
brief carries the contract, absolute paths of every in-scope file, the lint/test command and the
rules below, and tells the agent to put its full result in its final response — never finishing
silently, even when the result is empty or the run failed. Rules either way:

- **Per-item checkpoint** — run relevant tests/type checks after each meaningful change.
  Reserve full required checks for the completed integration, not every item. Do not commit per item.
- **Stuck-fix stop** — the same fix attempted twice on one file without the command passing →
  record what was tried, why it failed, and the next hypothesis (block below; `--tree` prefixes
  `cd ".worktrees/$SLUG" &&` as for `save`), then stop and report. Recommend resuming in a fresh
  session (`/clear`): accumulated failed attempts degrade the context, and `inspect` hands the
  notes to the next run. A delegated
  implementer only reports its attempts; the parent records that report as the note. An unknown
  cause routes to `dev:task-debug`.

  ```bash
  CYCLE_DIR="<absolute directory of this cycle.md>"
  STATE="$CYCLE_DIR/../scripts/cycle_state.py"
  python3 "$STATE" note <<'STUCK_NOTE'
  <what was tried, why it failed, next hypothesis>
  STUCK_NOTE
  ```
- **Destructive-command guard** — never `git push --force`/`--force-with-lease`, `git reset
  --hard`, `git clean -f`/`-fd`, or `git branch -D` while implementing. Stop and ask instead.
- **Worktree briefs** (`--tree`, batch) — the absolute worktree path; every Bash command begins
  with `cd <absolute-worktree-path> &&` (CWD resets to the main checkout each call); file tools use
  absolute paths under the worktree; nothing in the main checkout is read or edited.
- An implementer that fails or returns unusable output → stop and report.

Before leaving implementation, account for every acceptance criterion with a concrete result;
unmet or unknown criteria keep the cycle here. Independent review grades requirements and code
quality separately; it does not replace the implementer's feedback loop or required checks.
After version bump and cleanup, follow *Validation evidence* before hand-off.

## Version bump

After all changes, before hand-off. Judge *which* plugin and *which* level; the rewrite is scripted:

```bash
[[ -f scripts/bump-version.sh ]] && bash scripts/bump-version.sh <plugin> <major|minor|patch> \
  [--skill <name> <major|minor|patch>]
```

Pass `--skill` when the change touched that skill's own `SKILL.md`; the script takes one `--skill`
per run, so a second skill's `version:` is edited by hand. Rules: the script header, or
`docs/conventions.md` → *Plugin Version Bump Rules* where it exists. No script → edit the
manifests by hand; no `plugin.json` → skip; neither script nor conventions doc → choose the level
by semver and state it, with the reason, in the hand-off and PR body.

## Cleanup

Confirm the branch archive can be read with `cycle_state.py inspect` before pruning any contract
or backlog line. Cleanup changes are provisional until review and merge succeed.

Leave everything uncommitted — it lands in the review cycle's first commit. Your judgment is
*which* lines are done; the edits are scripted and refuse (exit 1, nothing written) on an
ambiguous or non-verbatim match — re-read and re-run rather than loosening the input.
`prune-backlog` also deletes each item's wrapped continuation lines and nested sub-bullets; an
item whose body holds a fence or comment is refused by line number — delete that one by hand, not
its body alone.

```bash
CYCLE_DIR="<absolute directory of this cycle.md>"
NODES="$CYCLE_DIR/../scripts/task_nodes.py"
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }
# only when a sprint block exists in tasks.md
python3 "$NODES" prune-tasks --file tasks.md --block "<h1 title>"
# the backlog.md line(s) this cycle completed, verbatim
printf '%s\n' "<each completed - [ ] line>" | python3 "$NODES" prune-backlog --file backlog.md
# one CHANGELOG entry; drop --plugin/--version in a repo with no versioned plugin
python3 "$NODES" changelog --file CHANGELOG.md --title "<title>" \
  --plugin <plugin> --version <X.Y.Z> [--link docs/<owning-doc>.md]
```

A heading is dropped only where this cycle emptied it. Never re-add a pruned line as `[x]`: the
`CHANGELOG.md` entry is the closure record. A repo rule that demands `[x]` history is contract
drift for `harness-curate`. `changelog` validates the line against the
repo's `scripts/ci/check_changelog_entries.py` (one line, ≤160 chars, at most one `→` link, no
explanatory clauses).

`prune-backlog` exits 0 but warns on stderr when a surviving `*(blocked by: …)*` marker still names
an item or heading it just deleted — this cycle *was* the blocker. Act on that warning: delete the
named marker before you hand off, or the marked item is invisible to candidate selection with
nothing left to clear it. The warning is advisory because the marker's rewording is a judgment
call, so an unread one is a silently unselectable item.

**Blocked-marker sync** (queue items only, scoped to items inspected this run): an item you
verified is blocked and carries no marker → append `*(blocked by: <slug>)*` or `*(deferred:
<reason>)*`. A marker whose blocker you can see has landed (`[x]`, or removed in git) → delete
it. Match on the slug by judgment, never on a numeric prefix; failing to find a match is not
evidence the blocker landed. Disclose synced markers in the PR body.

## Validation evidence

Run the full contract commands and inherited mandatory checks once on the completed candidate,
after version bump and cleanup. Before running, stage only the reviewed in-scope files; require
no unstaged or relevant untracked inputs. Capture the tree before and after checks; changed inputs
invalidate the result. A nonzero exit, absent result, or unaccounted input blocks hand-off.

Record the run beside the archived contract, so a later session can judge reuse without guessing
a filename or format. The helper stamps `HEAD` and `git write-tree` itself:

```bash
CYCLE_DIR="<absolute directory of this cycle.md>"
STATE="$CYCLE_DIR/../scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled state helper unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" evidence --command "<exact command>" --exit <code> \
  [--log "<result/log location>"] [--env "<tool versions relevant to reproducibility>"]
```

`inspect` returns one record per command as the `evidence` list — a rerun replaces only that
command's record, so an earlier failure stays visible — and reports `tree_matches_current` true
only when every record's tree equals the current index; `false` or a null `evidence` means rerun.

A later commit with the same tree (`git rev-parse HEAD^{tree}`) may reuse passing evidence if the
command, environment, and external inputs remain equivalent. HEAD-sensitive checks (version/trigger
ratchets, ancestry checks) must run against the new commit. Unknown equivalence means rerun.
Review fixes invalidate affected evidence: run focused checks while fixing, then full required
checks on the final changed candidate. Additional reviewers never substitute for checks or CI.

## Hand off

**Do not commit.** Call the Skill tool with "dev:task-review-cycle" and
`args: --from <task-next|task-new> --auto`, and **restate the Sprint Contract verbatim** in the
invocation, with the archive path, validation evidence, and the Git authorization fields
(`git-authorization.md`). If the hand-off loses context, recover
the saved original rather than infer it from the diff. The review cycle commits, reviews the diff
against the contract, routes by risk and required CI, applies findings, records out-of-scope items to
`backlog.md`, and merges.

If the cycle reports CI failure: preserve the PR, branch, and archive, and report. A failed check
authorizes no closure or deletion (`git-authorization.md`). Only on an explicit user instruction to
abandon: first restore any carried `task-spec`/`task-tickets` edits (`docs/design/`, the unpruned
`backlog.md` tickets) onto the base branch — they exist only on this branch — after `authorize
--branch <feature-branch> --action base-push` (denied → hand the restore to the user); then close
the PR after `authorize --branch <feature-branch> --action pr-write`, and delete the branch.
