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
git checkout -b "$BRANCH"
```

The script applies the shared-`[type]`-else-`fix/` rule and warns on stderr when it falls back.

## Scope

Look yourself first — one or two searches. Spawn `explorer` (or the built-in `Explore` when no
such role exists) only when the survey means reading 10+ files or would flood the main context.

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

## Sprint Contract

```markdown
**Tag:** [FEAT] | [REFACTOR] | [FIX] | [TEST] | [CONSTRAINT] | [DOCS] | [HARNESS] | [PLAN]
**Scope:** files or areas this change touches
**Acceptance criteria:**
- [ ] one concrete, testable criterion per item
**Out of scope:** explicit exclusions
**Lint/test command:** the command that must exit 0
```

The Tag is what the reviewer grades a `[FIX]` reproduction criterion against — write it in. A
`[FIX]` contract names the test that fails before and passes after. A multi-item group gets one
checkbox per item. Keep the original contract in a branch-local archive before implementation, including the
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
`save --replace` only for an approved scope revision or a confirmed new cycle on a reused branch.
For `--tree`, save from the implementation worktree; for parallel batches, save the aggregate
contract on the integration branch before convergence cleanup.

## Implement

Inline by default. Delegate to `implementer` only past the global gate — 10+ files or 3+
independent units (`docs/delegation.md`) — with a brief carrying the contract, absolute paths of
every in-scope file, and the lint/test command; the implementer runs related checks and
reports through its final output, the only channel a role-file agent has
(`docs/delegation.md`); brief it never to finish silently. Rules either way:

- **Per-item checkpoint** — run relevant tests/type checks after each meaningful change.
  Reserve full required checks for the completed integration, not every item. Do not commit per item.
- **Stuck-fix stop** — the same fix attempted 3+ times on one file without the command passing →
  stop and report.
- **Destructive-command guard** — never `git push --force`/`--force-with-lease`, `git reset
  --hard`, `git clean -f`/`-fd`, or `git branch -D` while implementing. Stop and ask instead.
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
manifests by hand; no `plugin.json` → skip; neither script nor conventions doc → ask the user
for the level (never default it, even unattended).

## Cleanup

Confirm the branch archive can be read with `cycle_state.py inspect` before pruning any contract
or backlog line. Cleanup changes are provisional until review and merge succeed.

Leave everything uncommitted — it lands in the review cycle's first commit. Your judgment is
*which* lines are done; the edits are scripted and refuse (exit 1, nothing written) on an
ambiguous or non-verbatim match — re-read and re-run rather than loosening the input.

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

A heading is dropped only where this cycle emptied it. `changelog` validates the line against the
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

`inspect` returns that record as `evidence` and compares the recorded tree with the current index
as `tree_matches_current`; `false` or a null `evidence` means rerun.

A later commit with the same tree (`git rev-parse HEAD^{tree}`) may reuse passing evidence if the
command, environment, and external inputs remain equivalent. HEAD-sensitive checks (version/trigger
ratchets, ancestry checks) must run against the new commit. Unknown equivalence means rerun.
Review fixes invalidate affected evidence: run focused checks while fixing, then full required
checks on the final changed candidate. Additional reviewers never substitute for checks or CI.

## Hand off

**Do not commit.** Call the Skill tool with "dev:task-review-cycle" and
`args: --from <task-next|task-new> --auto`, and **restate the Sprint Contract verbatim** in the
invocation, with the archive path and validation evidence. If the hand-off loses context, recover
the saved original rather than infer it from the diff. The review cycle commits, reviews the diff
against the contract, routes by risk and required CI, applies findings, records out-of-scope items to
`backlog.md`, and merges.

If the cycle reports CI failure and the PR is abandoned: close the PR and delete the branch —
`main` never received the cleanup edits, so nothing rolls back.
