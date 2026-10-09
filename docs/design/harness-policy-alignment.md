# Harness Policy Alignment and Subagent Model Evaluation

## Problem Statement

The 2026-10-09 conversation reviewed this repository at commit
`95bae7c78dbc7cce6b962a068230258686e0a47b` after the user's global AGENTS.md was
replaced with a smaller policy. The agreed outcome is to remove obsolete assumptions,
make workflow authorization explicit, and simplify initialization where structure adds
no operational value. It is not to shrink every Toolkit workflow in proportion to the
global file: global instructions are always loaded; Toolkit procedures load on demand.

Observed issues in the reviewed baseline:

- `AGENTS.md`, `docs/delegation.md`, and `docs/workflows.md` attribute numeric
  delegation thresholds to a global gate that the new global policy no longer contains.
  The new global policy still respects repository-specific thresholds, so the numbers
  themselves are not a conflict.
- `docs/delegation.md` rejects delegation when work is not parallel, while its review
  rationale separately recognizes the value of independent verification.
- `docs/invocation.md` says invocation-axis CI enforcement remains open, but
  `scripts/ci/check_skill_frontmatter.py` implements axis, call-graph, and notation checks and is
  wired into `.github/workflows/harness-check.yml`.
- `task-new` and `task-next` descriptions enumerate implementation and review without
  clearly exposing the eventual commit, push, PR, or direct base-branch merge/push.
  Their Codex `agents/openai.yaml` entries also use the opaque phrase "full code cycle".
- `task-review-cycle` accepts any `--from` caller token. This is an accidental-entry
  guard, not authentication or evidence of user authorization. `--auto` skips review-fix
  confirmation; it does not confer additional Git authority. `--no-hub` still commits
  locally. The lite path merges locally and pushes the base branch.
- `harness-init` promises minimal scaffolding but requires named sections and verbatim
  blocks. Its example requires delegation for analysis exceeding 20 output lines.
  Its validator fails above 120 lines while initialization and maintenance describe a
  100-line target and a warning above 200; existing explanations do not fully reconcile
  the failure threshold with the described soft zone.
- Project-local role definitions pin Sonnet/Opus, while generated role guidance favors
  inheritance. Neither removing every pin nor preserving every pin has been evaluated.

## Solution

Keep the existing task lifecycle and executable checks. Deliver the agreed P0/P1 fixes
first, then a separate P2 policy-and-evaluation sequence. Use the existing contract
archive and evaluation workflows rather than adding approval or routing infrastructure.

The five queue entries below each own one Sprint Contract. The first three retain the
agreed three-PR boundaries; P2 separates policy documentation from live experimentation.
Dependencies enforce the agreed rollout order, not a claim that all work is technically
coupled. Backlog markers use these frozen identifiers:

The Outcome column names each slice; the Required evidence table in Testing Decisions
is the acceptance authority. Preserve this priority sequence even where work could run
independently. Starting P2 earlier would change the agreed rollout, not resolve a dependency bug.

| Order | Priority | Identifier | Outcome |
|---|---|---|---|
| 1 | P0 | `delegation-policy-alignment` | Accurate delegation and invocation documentation |
| 2 | P0 | `review-authorization-boundary` | Inherited authorization limits on both merge paths |
| 3 | P1 | `harness-init-simplification` | Minimal initialization accepted without hiding defects |
| 4 | P2 | `subagent-model-selection-policy` | Task-specific policy and accurate platform resolution docs |
| 5 | P2 | `subagent-model-selection-evaluation` | Measured baseline versus per-task selection |

## User Stories

- As a repository operator, I want local delegation policy described accurately so
  obsolete global references do not dictate execution.
- As a workflow user, I want its Git effects visible before invocation and my existing
  authorization limits preserved through review and resume.
- As an initialization user, I want only useful repository guidance generated and checked.
- As a lead agent, I want model choices based on the delegated task and measured total
  cost, with platform defaults and overrides resolved correctly.

## Implementation Decisions

### 1. P0 — Delegation and invocation alignment

Scope: `AGENTS.md`, `docs/delegation.md`, `docs/workflows.md`, `docs/invocation.md`,
and directly affected references discovered during implementation.

- Preserve the numeric research/implementation thresholds as provisional local policy,
  pending evidence for changing them; the conversation supplied no evaluation establishing
  10 files or 3 units as optimal. Use this replacement policy wording consistently:

  > Default inline; delegate research or implementation only when the user or an applicable
  > skill directs it and the work meets this repository's provisional threshold: 10+ files
  > to investigate, 3+ genuinely independent units, or substantial context pressure.
  > An authorized workflow's independent verification is assessed separately for its
  > independence benefit and cost; neither file count nor parallelism alone gates it.

- Apply platform/base/global constraints first. Local thresholds specialize only what
  those layers permit; they never relax a higher-level prohibition or invent an exception.
  The new global policy explicitly allows repository-specific thresholds, so this is not
  a claim that repository policy overrides it. Independent verification remains optional
  unless an already authorized workflow requires it, including existing review/worktree QA.
- Replace Pattern Selection with the following routing order, after the permission and
  local-policy checks above have passed:

  | Task shape | Route |
  |---|---|
  | One isolated research/verification task with a material context or independence benefit | Subagent eligible; no parallel sibling required |
  | Independent parallel tasks requiring findings to be exchanged during execution | Agent Team eligible where supported |
  | Independent parallel tasks whose results can be combined at completion | Subagents eligible |
  | Tightly coupled/sequential work, or no material isolation benefit | Inline |

  Eligibility does not mandate a spawn. This removes "No parallel tasks → no delegation"
  without making every verification a delegation trigger.
- Replace the obsolete open-backlog/partial-migration sentence in docs/invocation.md
  with the implemented axis-coherence, call-graph, and notation checks, their owning
  checker, and CI wiring. Removing the stale sentence alone is not sufficient.
- Do not add a router, new agent, model policy, or tool-call-budget redesign in this slice.

### 2. P0 — Review authorization boundary

Scope: `task-new`, `task-next` (including shared cycle and relevant batch/tree/resume
handoffs), their Codex sidecars, `task-review`, `task-review-cycle`, and focused tests.
Update owning workflow/invocation docs where the behavior is stated.

Keep this slice within the existing contract archive, caller handoffs, descriptions,
and Git action boundaries. Before editing, enumerate the affected entry/handoff paths
and their test locations in the contract. If the fix requires a new approval store,
execution-engine rewrite, or unrelated batch/tree redesign, stop that expansion and
propose another bounded ticket; the enumerated authorization cases alone do not require
splitting an otherwise coupled change.

- Expose commit, push, PR creation, and possible direct base-branch merge/push in both
  platforms' invocation descriptions. Preserve task-new/task-next mutual name pointers
  required by trigger-collision checks.
- Reuse the original Sprint Contract's approval source and scope. Carry explicit Git
  limits through every handoff and resume instead of introducing a separate approval store.
- Store authorization as explicit Markdown fields in the archived `contract.md`:
  `Approval source` (actual user instruction/invocation and scope), `Allowed Git actions`,
  and `Git limits`. Carry them verbatim with the original contract. `cycle_state.py`
  already persists contract text, so this plan requires no new JSON schema or archive
  format. Add focused validation/tests if needed without making missing fields in a legacy
  contract count as permission. Document that schema decision in the completed ticket.
- A direct human slash-command/skill-picker invocation, or user text expressly asking
  for the named full workflow, is a workflow approval source. A model-selected skill,
  router match, callee flag, or an unsupported claim in an agent report is not. A caller
  must pass the originating user instruction; `--from` identifies only the caller.
  If an execution environment cannot establish the origin, treat authority as unknown.
- An explicit full-workflow invocation may authorize its documented effects when no
  narrower instruction exists. Do not repeatedly ask for an already authorized action.
- Implementation approval alone does not imply permission to commit, push, or merge.
  Honor implementation-only, no-push, and PR-only limits. Legacy contracts that establish
  only implementation approval do not establish merge authority.
- Check authority before the first affected action, not only at final merge. Cover local
  commits, remote PR writes, lite base-branch push, and hub merge. Stop at the authorized
  boundary with a reviewable result; seek clarification only for genuinely missing authority.
- Apply the following boundary definitions. Existing narrower user instructions win:

  | Approval | Permitted Git effects |
  |---|---|
  | Implementation-only | Working-tree changes and authorized checks; no local commit or remote writes |
  | Explicit full workflow without narrower limits | Its documented commit/push/PR/merge effects, subject to risk/CI/platform gates |
  | Explicit full workflow with no-push limit | Local commit/review only; remote writes require separate explicit permission |
  | Explicit workflow limited to PR-only | Local commit, feature-branch push and PR creation/update; no base-branch merge/push |
  | Unknown or legacy implementation-only source | No unestablished Git effect; preserve work and report missing authority |

  Unknown authority denies the affected action, not all independently authorized work.
  Before entering lite, explicitly establish permission for direct base-branch merge
  and push; PR-only permission never satisfies that check. Hub merge likewise needs merge
  permission. `--no-hub` local commits still need local-commit permission.
- `--from` traces the caller; `--auto` permits in-scope review-fix application without its
  confirmation. Neither grants or expands authority. `--no-hub` is local-only, not read-only.
- Retain existing flags, risk routing, required checks, and authorized automation. Branch
  protection/CI are execution controls, not substitutes for user authorization.
- Keep recoverable contract/evidence state when execution stops. Do not infer completion
  or permission from a commit, version bump, or clean working tree.

### 3. P1 — Initialization simplification

Scope: `dev/skills/harness-init/SKILL.md`, its example, validator, affected rationale,
invariant/maturity/workflow references, and focused validator regression fixtures.

- Remove the example's blanket "analysis >20 lines means delegate" rule.
- Use the following section policy in both generation and validation:

  | Section | Requirement |
  |---|---|
  | Golden Principles | Conditional on real project invariants; no invented minimum count |
  | Delegation | Conditional on configured roles or an actual delegation workflow; no mandatory table when neither exists |
  | Token Economy | Optional; retain only useful project-specific guidance |
  | Maintenance | A concise applicable policy or an existing valid pointer is sufficient; no fixed heading or numbered-rule count |

  Leave unrelated navigational/language/runbook requirements unchanged. Preserve useful
  project-specific safety boundaries. With no applicable optional section, report INFO
  rather than a standing warning. The baseline already conditions docs/delegation.md
  absence, but AGENTS.md's missing Delegation section is still an unconditional WARN.
- Remove the unconditional copy/heading mandates for these generic blocks and their
  `harness:verbatim` exemption from pruning. Update example, rationale and validation
  together; the new section policy must not coexist with a contradictory verbatim mandate.
- Keep a useful size check. Make generation, validation, and session-warning purposes,
  thresholds, messages, and boundary tests coherent. The conversation approved alignment,
  not an arbitrary replacement cutoff or removal of size checks altogether.
- This ticket owns the size-policy decision. Before implementation, its Sprint Contract
  must specify generation target, validator warning and failure boundaries (including
  any deliberate absence of a size-only failure), session-warning boundary, and exit/message
  semantics, with a rationale against the existing 100/120/200 behavior. Treat this as a
  bounded implementation decision within the approved scope, not permission to remove
  useful checks. Test immediately below, at, and above every selected boundary and update
  harness-invariants/maturity/rationale wording in the same change.
- Reconcile Step 0b and generated delegation guidance with slice 1: higher-level
  prohibitions remain binding, and granted local-policy choices are specializations.
  Generated docs must not claim a numeric global rule that the inspected layer lacks.
- Detect configured delegation surfaces on the supported platforms, without requiring
  unsupported or nonexistent assets. Existing conditional docs checks are already partly
  implemented; extend the missing AGENTS.md-section behavior rather than duplicating it.
- A minimal valid repository must pass without optional sections. Existing repositories
  must retain meaningful checks for broken references, malformed configuration, and
  applicable enforcement requirements. Template conformance alone is not correctness.

### 4. P2 — Model selection policy

Scope: `docs/delegation.md` and `docs/platform-specs.md`. Label existing role pins as
current defaults retained until evaluation. This is a provisional selection policy and
evaluation hypothesis, not evidence that dynamic routing improves quality or cost.

The agreed common policy is:

> Choose the model and reasoning effort per delegated task based on complexity, risk,
> and verifiability. Optimize expected total cost, including retries and verification.
> Escalate only when evidence indicates insufficient reasoning capability.

- Light/Standard/Deep are advisory task classifications, not mandatory workflow gates or
  provider-specific model mappings. Consider ambiguity, failure impact, and detectability.
- Keep the existing Simple/Comparison/Complex Effort Tier and its budgets unchanged.
  Define it as task/brief budget classification; Light/Standard/Deep describes model
  selection needs. The axes are independent: there is no mandatory one-to-one mapping,
  and a model tier neither grants more calls nor changes the existing stop/report rule.
- Use supported model/effort combinations. Prefer a justified per-spawn choice; otherwise
  use the resolved platform default. Preserve findings and unresolved issues across retries.
- Environmental failure is not evidence for a model upgrade. Retain evaluated role-specific
  pins where they improve results; removing all pins is not the objective.
- Keep headless review model policy separate. Create no router skill/script, additional
  global AGENTS.md block, permanent telemetry system, or speculative custom roles.

Platform facts checked in the conversation on 2026-10-09; reverify for the installed
clients before writing authoritative platform docs or running evaluation:

Slice 4 acceptance requires dated official-source URLs/sections and installed client
version evidence, not just repeating the facts below. If an installed client is unavailable,
mark its local support unverified and name the remaining slice 5 preflight; do not claim
official documentation establishes that unavailable installation's behavior.

- Claude Code v2.1.251+: per-invocation model, role frontmatter, ordinary
  `CLAUDE_CODE_SUBAGENT_MODEL`, then main model. Earlier versions prioritized that
  environment variable. `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` is a separate forced-mode
  exception supported from v2.1.257. Supported effort overrides and their precedence are
  version-dependent; model precedence is not automatically effort precedence.
- Codex: custom-agent model/effort fields win over explicit spawn values, which win over
  `[agents]` defaults, which otherwise fall back to parent settings. Model and effort
  resolve separately; selecting a model without specifying effort can use its default
  effort, and custom-agent model-only configuration can preserve previously resolved effort.
- Codex custom roles use TOML under `.codex/agents/` or `~/.codex/agents/`. Distinguish
  these from AGENTS.md instructions and from plugin asset packaging. Creating duplicate
  roles for existing built-ins is not required by this work.
- Defaults and model omission do not themselves implement task-specific automatic routing.
  The active runtime's allowed spawn options and higher-level instructions still govern.

### 5. P2 — Model selection evaluation

Scope: a bounded evaluation artifact following existing repository eval conventions;
policy refinements only when directly supported by the results.

- Use 10–20 distinct task IDs total, not 10–20 additional tasks per platform, across
  Light/Standard/Deep. Reuse those IDs on each available platform, with paired baseline
  and experiment inputs/Acceptance Criteria. With both platforms, this is 40–80 primary
  runs before repeats/retries; do not describe 20 tasks as at most 40 two-platform runs.
  Include tasks whose wrong result is hard to detect. This is an initial evaluation,
  not statistical proof or a requirement to exhaust the upper bound.
- Before live runs, preregister task IDs, settings, grading checks, platform order,
  maximum total attempts (including repeats/retries), wall-clock budget per platform,
  and available cost/token ceiling in the evaluation artifact and Sprint Contract.
  Choose finite limits using the actual clients and task sizes, not invented prices.
  Run one platform as a bounded stage before the next; use an initial paired task as an
  observation smoke check. When a budget is exhausted, report partial/unverified results
  and remaining work; budget exhaustion is not completed evaluation.
- Preserve current Claude role pins for the baseline; test overrides without first deleting
  them. For Codex, use an unpinned temporary evaluation role or suitable built-in so custom
  file precedence does not invalidate the experiment. Keep role instructions, permissions,
  context, and checks comparable; document unavoidable differences.
- Record tool/client version, parent model/effort, relevant defaults/forced settings,
  requested model/effort, actual applied model/effort and evidence source, task tier, and
  a one-line selection reason. Exact model IDs belong in run records, not common policy.
- Record criteria completion, important omissions/errors, retries, lead re-verification,
  total elapsed time, tokens, and cost. Separate measured cost, estimates, and proxies.
  Unobservable applied settings are `unverified`, not assumed matches.
- Preregister the observation method: Claude agent model/effort display or structured
  session/debug records; Codex subagent/session metadata or execution logs. Preserve a
  run ID and bounded evidence excerpt/artifact for each. A user-visible requested model,
  aggregate billing usage, or a prompt naming a model does not establish the child setting.
  Check availability before bulk runs; exclude setting-unverified runs from model-effect
  comparisons while retaining them as routing/observability limitations.
- Include retry and lead review costs. A cheap scan that makes the lead repeat the work
  is not a cost win. A missing permission/dependency is not a reasoning failure.
- Keep the short structured selection record evaluation-only. No requirement to expose
  lengthy rationale or to log every future delegation permanently.
- Report keep/change/unverified recommendations per role/task class. A justified finding
  can create a later bounded configuration-change ticket; this evaluation does not itself
  remove production pins. Preserve existing settings if improvement is not demonstrated.
- Preregister the smallest worthwhile total-cost or completion-time improvement before
  seeing results. A change recommendation needs at least two distinct paired inputs in
  the recommended role/task class, observed model/effort settings, all relevant criteria
  met, no material new error/omission, and a repeat confirming the claimed benefit.
  Compare costs on the same measured basis; a token/time proxy supports only a proxy claim.
  If evidence is sufficient but shows no benefit, recommend keep; if observability, coverage,
  or budget prevents judgment, recommend unverified. Do not extrapolate one favorable run
  into removing the entire role's pin or tune the threshold after viewing outcomes.

## Testing Decisions

Each future ticket must translate its criteria into observable checks in its Sprint
Contract. Use the current runbook and affected test suites at execution time.

| Slice | Required evidence |
|---|---|
| 1 | Fixed policy wording/routes distinguish provisional local thresholds and permitted independent verification; no obsolete attribution; invocation docs describe axis/call-graph/notation and CI wiring; applicable checks pass |
| 2 | Approval source/actions/limits survive archive and every relevant handoff without a new archive schema; actual user invocation differs from router/flag claims; implementation-only blocks local commit; unknown authority denies affected actions; lite checks direct base merge/push permission before entry; hub/batch/tree/resume and authorized automation have action-boundary regression evidence |
| 3 | Contract settles generation/validator/session thresholds and semantics before edits; the enumerated optional-section policy and removal of verbatim mandates agree across templates/docs/checks; minimal/existing fixtures, malformed configuration/references, delegation surfaces, and all size boundaries are covered |
| 4 | Provisional policy distinguishes model tiers from unchanged budget tiers; dated official-source and installed-version evidence supports platform precedence/forced-mode claims (unavailable installations explicitly unverified); existing runtime configurations remain unchanged |
| 5 | Task count, observation methods, finite per-platform budgets and decision thresholds are preregistered; paired/repeated evidence satisfies recommendation bars or is unverified; aggregate cost includes retries/lead review; missing actual settings cannot support model-effect claims; production pins remain unchanged |

Relevant existing checks include `scripts/ci/check_skill_frontmatter.py`,
`scripts/ci/test_check_skill_frontmatter.py`,
`dev/skills/task-next/scripts/test_cycle_state.py`, the affected review-cycle tests,
`dev/skills/harness-init/scripts/validate-harness.sh`, and
`scripts/ci/check_test_suites_wired.py` when a test is added. New bug regression checks
must fail for the broken behavior. Do not substitute document assertions for action-boundary
checks where executable behavior is affected.

Apply the existing plugin/skill version rules when future work changes shipped assets;
keep Claude and Codex manifests synchronized. This recording-only change touches no
plugin assets and requires no plugin bump. Do not weaken CI or branch protection.

## Out of Scope

- Shortening explicitly invoked task-new/task-next full cycles or detailed task-debug,
  review, spec, tickets, capture, or curate procedures merely because the global file shrank.
- Moving the repository-only `.claude/agents/` roles into a plugin, adding duplicate Codex
  roles, automatically deleting model pins, or modifying headless reviewer model settings.
- New approval stores, model-router skills/scripts, generic semantic policy-conflict
  detection, permanent selection telemetry, and an additional A/B evaluation framework.
- Removing tool-call budgets wholesale. Their scope/cost/stop semantics remain a separate
  evidence-driven follow-up, not part of the approved five slices.
- Changing the user's global instructions or executing implementation, commits, pushes,
  publication, or merges as part of this recording request.

## Further Notes

Future task-next sessions must recover the accepted rationale, exclusions, and checks
from this document before forming a contract; the backlog's source pointers preserve
this conversation across sessions without adding another state system.

Approval source: the user accepted the refined P0/P1 plan and separate staged P2 plan in
this conversation, then explicitly requested durable design/backlog records. Reuse the
agreed scope and order when task-next is later invoked; ask only for material deltas or
missing execution authority. The present request authorizes recording, not executing
these tickets. Recover the actual future invocation and any limits as the Git authority.

At baseline, harness validation returned 35 PASS / 0 WARN / 0 FAIL and the invocation
checker passed. These are historical structural checks from the review, not evidence of
completed fixes, model routing success, or authorization correctness. No live model
override experiment was performed in the discussion.

The earlier proposals to make inheritance universal, add another A/B system, move local
agents into plugins, and shorten every full cycle were explicitly withdrawn. Keep these
exclusions visible when forming each Sprint Contract.

Official references used for platform review:

- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [OpenAI subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

Before implementation, read this design and the selected slice, verify current repo and
client state, and preserve unrelated backlog entries. After a predecessor lands, remove
only the matching `blocked by` marker from its successor; the parser does not resolve
dependencies automatically. Identifiers stay frozen even when preceding headings are pruned.
The existing headless review-effort experiment remains separate from this P2 evaluation.
