# Home-configured handoff lines

Create a UTF-8 `repos/handoff.json` in the home repo. Map each repo path prefix to an array of
nonblank, single-line strings.

```json
{
  "~/src/team-projects": ["Use the team review checklist."]
}
```

Run `launch` from the home repo. The launch directory's config takes priority and the Git root
is the fallback for launches from subdirectories. Prefixes may be absolute, start with `~/`, or
be relative to the directory that owns the `repos/` registry. The resolved child path matches a
prefix by exact path or descendant.
`launch` appends all matching lines in file order after the verbatim metadata in the first Claude
or Codex message. Codex quotes lines that begin with screen markers or hook notices so they
appear as message text. Use `--dry-run` to preview the first message with Claude or Codex `--task`.

Codex receipts retain the launch-time lines for delayed delivery and first-message retries.
Verify approvals using the original user request and Git limits carried in the handoff.

## Git authority in the handoff

Pass the verbatim originating request in `--request`. For queue and new work, verify that the
request or a separate grant authorizes the Git actions the task needs. Record the exact grant,
grantor and date in `--git-limits` and confirm the record with `--git-grant-recorded`.
The values `none`, `no-push` and `pr-only` can follow a verified workflow invocation without
that flag. The child checks the originating request and recorded grant when establishing authority.

When the user stated no Git limits, omit `--git-limits` for queue and new work. The launcher
records the dispatch default through merge (`DEFAULT_GIT_LIMITS` in `dispatch.py`), and the child
applies `../../task-next/references/git-authorization.md` → *Dispatch default*. Forward a
user-stated Git limit instead, as `no-push`, `pr-only` or the verbatim grant with
`--git-grant-recorded`; narrower limits win. Never leave a Git restriction only in `--request`;
non-Git restrictions travel there. Queue and new launches reject blank and
recognized placeholder values. A free-form
restriction by itself cannot establish a grant. For implementation-only work, use
`--no-git-writes`. The child receives `implementation-only` and stops before commits, pushes
or PR writes. Any additional restrictions from `--git-limits` apply from worktree preparation
onward. The child quotes them separately in the Sprint Contract for handoff and resume.

## Reserved queue waves

Use this path for independent worktree assignments on the built-in file and GitHub queues.
Refresh the target's origin, then run `dispatch.py pick <repo> --reservable`. It returns one
`base` and the exact `candidates`, together with parked and claimed refs. Choose complete,
distinct candidates. Pass the selected objects verbatim on stdin to `dispatch.py reserve-wave
<repo>` as `{"base":"<base>","units":[<candidate>,<candidate>]}`. If the base, selection, or
eligibility changed, the entire reservation fails. Refresh the selection before retrying.

Keep the returned IDs and launch one idle Codex child per reservation from the target's main
checkout. On each `launch`, pass the candidate's ref as `--unit`, the original request, and the
verified Git limits for that unit. Use the reviewed plugin with reserved-intake support in both
the dispatcher and all children. Run `dispatch.py send-wave <repo>` with a JSON object on stdin:

```json
{"deliveries":[{"reservation":"<id>","run":"/abs/first/run.json"},{"reservation":"<id>","run":"/abs/second/run.json"}]}
```

The command validates and binds the entire set before sending. Each delivery uses its own
receipt, and later deliveries proceed while earlier children are in intake. The output includes
each run's delivery outcome and exact first-task prompt. For an unconfirmed send, follow the
normal checked resend flow using that prompt and receipt. Retry a withheld delivery through
`send-wave`. For a canceled or undelivered assignment, use
`dispatch.py release-reservation <repo> <id>`. The release only removes an unconsumed
reservation. A child's completed claim remains visible through its ordinary worktree claim.
Use `wait --first` after delivery and keep merges into the base sequential.

## Home merges a child PR

Verify the original user grant authorizes the home session to merge the exact repository
and PR under the handoff limits. If the child's archived contract is `pr-only`, preserve it.
Archive the home grant with `cycle_state.py save` from a separate home-owned feature branch in
the target repo. Scope that contract to the repository, PR and feature branch to be merged and
record the verified grant with `base-merge` as its allowed action.

Before merging, match the live PR to that scope and apply the review and CI checks in
`SKILL.md` → *Push and merge*. Merge one PR at a time. Syncing the pushed branch with its
base keeps the push fast-forward, and squash-merging the PR keeps that sync commit off the base.
In the target repo, run `cycle_state.py authorize --branch
<home-contract-branch> --action base-merge` per
`../../task-next/references/git-authorization.md` → *Check before execution*. On GitHub, pass the
same checked SHA to `gh pr merge --match-head-commit` and use the merge strategy the user granted.
