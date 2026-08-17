# Invocation Axis — user-invoked vs model-invoked

> Adapted from [mattpocock/skills](https://github.com/mattpocock/skills) —
> `.agents/invocation.md`, PR #878 (Skill-tool phrasing), PR #880 (no user-invoked
> → user-invoked calls). Adapted for this repo's plugin namespacing (`dev:`/`prod:`)
> and its existing CI validator layer; mattpocock enforces the invariant by review
> only, this repo enforces it mechanically.

## Problem Statement

Every skill in this repo is model-invoked. No `SKILL.md` sets
`disable-model-invocation`, and no `agents/openai.yaml` sets
`policy.allow_implicit_invocation: false` — both fields are documented as available
in `docs/platform-specs.md` (SKILL.md frontmatter section, Codex sidecar section)
but used nowhere.

Three consequences:

1. **Destructive skills are open to auto-invocation.** `task-next`, `task-new`, and
   `task-review` create branches, commit, open PRs, and merge. A loosely-worded
   prompt can fire them. The blast radius is a merge to `main`.
2. **The call graph has no rule.** Orchestrators call orchestrators — `task-new` →
   `task-review`, `task-next` → `task-review`. Nothing says which skill owns the
   commit, or how many times a review gate may run in one session.
3. **Cross-skill invocation is written as pseudo-code, not as a tool call.** 22
   sites use `Skill(dev:task-grill)`. That form is neither the real tool call nor a
   slash command, so the model may read it as prose and never load the target.

## Solution

Adopt invocation — *who may fire this skill* — as the single classifying axis, and
enforce all three of its rules in CI.

**The axis.** A skill is either user-invoked (only a human typing its name) or
model-invoked (model or human). The test, quoted from mattpocock's
`.agents/invocation.md`:

> The test for whether a skill should stay model-invoked: *could the model usefully
> reach for this autonomously?* (Reuse is the reason to extract a skill, not the
> test.)

Reuse alone never justifies leaving a skill model-invoked.

**The invariant.** A user-invoked skill may call model-invoked skills; it may never
call another user-invoked skill. When a step's precondition is a user-invoked
skill, phrase it as an instruction for the human ("tell the user to run
`/task-review`"), never as a tool call.

**The notation.** Operative cross-skill instructions read
`Call the Skill tool with "dev:task-grill"`. One skill per call; a step needing two
is `Call the Skill tool twice, for "dev:task-spec" and "dev:task-tickets"`.

## User Stories

- As the operator, I want `/task-next` to fire only when I type it, so that an
  ambiguous prompt cannot branch, commit, and merge on my behalf.
- As the operator, I want `task-new`'s hand-off to the review cycle to keep working
  unattended, so that adopting the axis costs me no automation.
- As a skill author, I want CI to reject a user-invoked → user-invoked call, so that
  the invariant survives the next skill I add without my remembering it.
- As the model, I want cross-skill instructions to name the Skill tool, so that the
  target actually loads instead of being read as prose.

## Implementation Decisions

### 1. Classification (dev plugin)

| Skill | Axis | Rationale |
|---|---|---|
| `task-new` | user | Owns a full code cycle incl. commit/PR. Human picks the moment. |
| `task-next` | user | Same, plus queue mutation and `--all`/`--tree` fan-out. |
| `task-review` | user | Named human entry point; merges to `main`. |
| `harness-init` | user | Writes repo-wide scaffolding (AGENTS.md, docs index). |
| `harness-curate` | user | Cross-session mining; expensive, and prunes assets. |
| `repo-dependabot` | user | Acts across every owned repo via `gh`. |
| `task-grill` | model | Pure interview discipline. Already declares itself callable. |
| `task-spec` | model | Writes one design doc; useful for the model to reach for. |
| `task-tickets` | model | Splits an approved spec; no destructive effect. |
| `harness-capture` | model | Retrospect discipline; called mid-review by design. |
| `task-review-cycle` | model | **New** — see below. |

`prod/` skills (`hwpx`, `persona-debate`, `repo-quiz`) are all model-invoked, which
is the default: the contract applies repo-wide, but no `prod/` file changes and no
`prod/` version bump is required.

### 2. `task-review` split

`task-review` currently serves both a human (`/task-review`) and its callers
(`task-new` at its hand-off steps, `task-next` at Step 4 / `references/batch.md` /
`references/tree.md`, all with `args: --auto`). Under the invariant those two roles
cannot coexist in one skill.

- **`task-review-cycle`** (new, model-invoked) holds the entire existing workflow —
  Arguments, Prerequisites, Setup, Steps 0–6, Error Handling, Scripts Reference —
  and the `scripts/` directory moves with it.
- **`task-review`** (user-invoked) stays as the human entry point: it parses the
  flags and calls the Skill tool with `dev:task-review-cycle`.

The name `task-review` is preserved deliberately. It is invoked by name, so
removing or renaming it would force a **major** bump under Golden Principle 1;
keeping it makes this a **minor** bump (new skill + behavior change) — dev
`4.4.20` → `4.5.0`, both `plugin.json` files in sync.

Every caller's `Skill(dev:task-review)` becomes
`Call the Skill tool with "dev:task-review-cycle"`.

### 3. `description` follows the axis

Model-invoked descriptions keep their trigger phrasing (`NOT for … → other-skill`)
— auto-invocation depends on it. User-invoked descriptions become a human-facing
one-liner for the slash-command list, with trigger lists and disambiguation arrows
stripped. This reclaims preload budget on the six user-invoked skills.

### 4. Mechanical enforcement

Extend `scripts/ci/check_skill_frontmatter.py` (already wired into
`harness-check.yml`) with three checks, and extend
`scripts/ci/test_check_skill_frontmatter.py` alongside:

1. **Axis coherence** — a skill marked user-invoked in `SKILL.md`
   (`disable-model-invocation: true`) must also carry
   `policy.allow_implicit_invocation: false` in its Codex sidecar, and vice versa.
   User-invoked in both harnesses or neither.
2. **Call graph** — scan `dev/skills/**` and `prod/skills/**` for
   `Call the Skill tool with "<ns>:<name>"`, resolve each target, and fail when the
   caller and the target are both user-invoked.
3. **Notation** — inside skill files, fail on residual `Skill(<ns>:<name>)`
   pseudo-code in operative prose.

**Exemptions the checker must honor.** Router prose that names skills as labels for
a human or emits them as hook payloads is not an invocation. Known sites:
`harness-curate/references/trigger-router-template.md`,
`harness-curate/references/orchestrator-template.md`,
`harness-init/SKILL.md` (trigger-router section), and
`harness-init/examples/agents-md-example.md` all emit literal `Use Skill(X)` strings
by design. Exemptions carry an explicit marker per `docs/conventions.md` →
*Adjudicated Exceptions Need a Marker, Not a Standing Warning* — not a silent
path allowlist.

`docs/design/*.md` are historical records and are out of the checker's scope.

### 5. Where the contract lives

A new `docs/invocation.md`, indexed from the `AGENTS.md` Docs Index ("Before adding
a new skill or changing how one is invoked"). It holds the axis definition, the
per-platform fields, the invariant, the notation standard, and the exemption rule.
`docs/platform-specs.md` keeps the raw field syntax and gains a pointer; it does not
duplicate the policy.

## Testing Decisions

- `python3 scripts/ci/test_check_skill_frontmatter.py` — extended with a positive
  and a negative fixture per new check (coherent/incoherent axis, legal/illegal
  call edge, standard/pseudo-code notation), plus one exempt-marker fixture.
- `python3 scripts/ci/check_skill_frontmatter.py` — exits 0 against the migrated
  repo. Verified to exit non-zero on the pre-migration tree, so the checks are shown
  to bite.
- `bash "$(ls -d ~/.claude/plugins/cache/kadragon/dev/*/skills/harness-init/scripts/validate-harness.sh | sort -V | tail -1)"` — harness validation still clean.
- `harness-check.yml` green on the PR.
- Manual: `/task-review` reaches the full cycle through the new wrapper, and
  `task-next` Step 4 hands off to `task-review-cycle` with `--auto` unattended.

## Out of Scope

- `prod/` frontmatter changes and any `prod/` version bump.
- `CONTEXT.md` / domain-modeling and a `writing-for-agents` skill — separate
  findings from the same upstream comparison, tracked independently.
- Changesets-based versioning, and the missing `version:` field on
  `harness-init` / `repo-dependabot` / `task-review` / `hwpx` / `persona-debate`.
- Rewriting `Skill(dev:…)` occurrences in `docs/design/*.md`.
- Any hook-level (runtime) blocking of skill invocation — the axis is enforced by
  frontmatter and CI, not by a new hook.

## Further Notes

- **Risk: the wrapper is thin.** `task-review` after the split is little more than
  flag parsing plus one tool call. That is the cost of preserving an invoked-by-name
  entry point while locking auto-invocation; the alternative was a major bump.
- **Risk: `disable-model-invocation` also removes a skill from subagent preload**
  (per `harness-curate/references/orchestrator-template.md`). Confirm no subagent
  path depends on reaching `task-next`/`task-review` implicitly before landing.
- **Follow-up:** once the checker exists, `harness-init` should teach the axis when
  scaffolding a new repo's skills, so downstream repos inherit the rule rather than
  rediscovering it.
