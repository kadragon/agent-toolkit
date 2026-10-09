# Git authorization — shared cycle boundary

Read at intake, review entry, batch/tree handoff, and resume before any Git write.
The original archived `contract.md` owns approval; no additional store or JSON schema exists.

## Establish and carry authority

Verify the actual user message before writing these fields. Use one unindented occurrence
of each, outside fences/comments, with single-line values:

```markdown
**Approval source:** user-invoked: <actual human slash-command/skill-picker or named full-workflow request, selected scope>
**Allowed Git actions:** commit, feature-push, pr-write, base-merge, base-push, integrate
**Git limits:** none
```

`user-invoked:` means a verified human full-workflow invocation. `explicit-user:` means a
verified instruction granting the listed effects. Quote the originating instruction and
its scope, not merely the callee name. A model-selected skill, router hit, `--from`, `--auto`,
or unsupported delegate claim is not approval. When origin cannot be established, record
`unknown` for source and limits, and `none` for actions; no Git effect is established.
The checker validates the recorded boundary; it cannot authenticate a user message.
Never fabricate a recognized source prefix to make it pass.

An explicit full workflow authorizes its documented effects unless narrower instructions
exist. Implementation approval alone grants no Git writes. Preserve every narrower limit;
normalize it into the table below, then list only the actions actually granted. Unexpressed
or more specific limits must be resolved before the affected action, never flattened to `none`.

| Git limits | Maximum allowed actions |
|---|---|
| `none` | Explicitly listed effects only |
| `implementation-only` | No local commit or remote write |
| `no-push` | `commit`, `integrate` only |
| `pr-only` | `commit`, `integrate`, `feature-push`, `pr-write`; no base merge/push |
| `unknown` | No unestablished effect |

`integrate` is a local unit-branch merge on an integration feature branch, not a base merge.
`base-merge` covers hub merge and lite local merge; `base-push` covers direct base push.
`pr-write` includes creation, update, comments, and closure. Destructive actions remain subject
to the existing explicit approval guard; none of these fields grants force/reset/clean authority.

Archive the fields with the contract before implementation. Pass the original fields verbatim
through single, batch, tree, wrapper and reviewer handoffs. Parallel unit contracts inherit
the aggregate authority, restricted to their owned scope; aggregation must never widen limits.
A partial aggregate rewrite retains the same fields. Resume recovers them with the contract;
legacy missing fields deny affected actions. A commit, clean tree, CI pass or saved archive
proves no additional permission. Only an actual new user instruction can revise authority;
retain its source using the existing approved `save --replace` process.

## Check before execution

Use the existing helper, resolved from the loaded skill's bundled location:

```bash
STATE="<absolute task-next skill directory>/scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled authority checker unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" authorize --action commit || exit 1
```

Repeat with the affected action immediately before local commit, feature push, PR write,
integration merge, or base merge/push. `--branch <owning-feature-branch>` reads that branch's
archive after a checkout; it changes no authority. Missing checker/Python/archive, malformed
or duplicate fields and unknown authority fail closed. Keep work, contracts and evidence;
finish independently authorized checks and report the missing action with a reviewable result.
Ask only when that effect really needs new authority; do not repeat a valid approval.

Review entry derives the allowed route before Setup/authentication: implementation-only/unknown local-commit
authority stops before committing, `no-push` uses local review (`--no-hub`), and `pr-only` uses
hub and stops with a reviewed PR before Step 6. Required remote checks remain pending on local
routes. An explicit `--no-hub` stays local regardless of wider authority.
Before entering lite, establish **both** `base-merge` and `base-push`; PR-only never qualifies.
Check again immediately before each effect using the saved feature-branch key. Hub merge needs
`base-merge`. Scripts enforce their writes independently; raw Git/hub commands must use the
same helper, including review-fix commits, PR updates/comments/closure and batch/tree commits.
Neither `--from` (caller trace) nor `--auto` (in-scope review-fix confirmation) grants authority.
