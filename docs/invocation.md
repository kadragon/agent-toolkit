# Invocation

Who may fire a skill. This is the one axis every skill in this repo is classified on. The
rules below are the target state — the repo is **partially migrated onto them**: the
`task-review` / `task-review-cycle` split has landed, the remaining
`## Invocation axis — …` items in `backlog.md` have not. `docs/design/invocation-axis.md`
holds the rationale. Field syntax lives in `docs/platform-specs.md`; the policy lives here.

Adapted from [mattpocock/skills](https://github.com/mattpocock/skills) `.agents/invocation.md`
(PR #878, PR #880), with one deviation — this repo ships two plugins, so every cross-skill
call carries its namespace.

## The axis

| | user-invoked | model-invoked |
|---|---|---|
| Who fires it | the human, explicitly — nothing else | model **or** human |
| `description` reader | a person picking it from a list | the model, deciding whether to reach for it |
| `description` shape | one human-facing line; no trigger lists (but see the collision carve-out below) | rich trigger phrasing — auto-invocation depends on it |

"The human, explicitly" is spelled differently per harness: Claude Code exposes a
user-invoked skill as `/name` in the slash-command list; Codex has no `commands/` analog
(`docs/platform-specs.md` → *Quick Comparison*), so there it is the skill picker entry named
by `interface.display_name` in the sidecar. Do not write repo docs as if `/name` were the
path on both.

**Collision carve-out.** Stripping trigger phrasing must not strip a *mutual skill-name
pointer*. `scripts/ci/check_skill_triggers.py` fails any description pair at cosine ≥ 0.25
"whose descriptions lack mutual skill-name pointers" — `task-new` ↔ `task-next` is the
corpus's closest pair and passes only because each names the other. Both are user-invoked, so
a one-liner that drops `→ task-next` / `→ task-new` turns CI red. Trim the trigger *list*;
keep the pointer.
| What it holds | orchestration: order, gates, side effects | reusable discipline |

The test, quoted from upstream:

> The test for whether a skill should stay model-invoked: *could the model usefully reach
> for this autonomously?* (Reuse is the reason to extract a skill, not the test.)

Reuse alone never justifies leaving a skill model-invoked. A skill that only other skills
call, and that a human would never usefully fire mid-conversation, is still model-invoked;
a skill whose side effects the human must time — a commit, a merge, a cross-repo sweep — is
user-invoked even though callers exist.

## Per-platform fields

A skill is user-invoked in **both** harnesses or neither. Marking one and not the other is a
defect, not a partial rollout.

| Platform | Field | Value for user-invoked |
|---|---|---|
| Claude Code | `SKILL.md` frontmatter | `disable-model-invocation: true` |
| Codex | `skills/{name}/agents/openai.yaml` | `policy.allow_implicit_invocation: false` |

Model-invoked is the default: omit the frontmatter key, omit the `policy` block. Do not write
the permissive value explicitly — it says nothing the default does not, and it costs a version
bump to add.

`disable-model-invocation: true` also keeps a skill out of subagent preload. Before locking a
skill, confirm no agent definition in `.claude/agents/` reaches it implicitly.

## The invariant

**No skill may call a user-invoked skill — not a user-invoked one, not a model-invoked one.**
A user-invoked skill is reachable by the human and by nothing else. Upstream states it as:

> A user-invoked skill can never be reached this way, full stop — per the invariant above, no
> other skill can call it, including by naming it to the Skill tool.

Do not weaken this to "user-invoked may not call user-invoked": that reading lets a
model-invoked skill fire a destructive orchestrator. The live example is
`dev/skills/task-tickets/SKILL.md` → *Hand off*, which names `task-next` — a model-invoked
caller pointing at a user-invoked target.

Orchestrators calling orchestrators makes it untraceable which skill owns the commit and how
many times a gate ran in one cycle. When a step's precondition is a user-invoked skill, write
it as an instruction for the human — never as a tool call:

```
WRONG:   Call the Skill tool with "dev:task-review".
RIGHT:   Tell the user to run `/task-review`.
```

The usual fix when automation must survive the ban is to extract the callable half as a
model-invoked skill and leave the human entry point as a thin wrapper over it. That is what
`docs/design/invocation-axis.md` → *2. `task-review` split* did: `task-review-cycle` now holds
the callable workflow, and `task-review` forwards to it. When a call is repointed at an extracted
half, carry the caller's flags across — all six `task-review` call sites pass `args: --auto`,
and dropping it would stall an unattended cycle at the confirmation gate.

## Notation

An operative cross-skill instruction — a skill's own steps telling the agent to go run
another skill right now — is written as an explicit Skill tool call, with the namespace:

```
Call the Skill tool with "dev:task-grill".
```

Not `Skill(dev:task-grill)`, not `/task-grill`, not a `../other-skill/FILE.md` path.
Naming the tool is what actually loads the target; a skill name dropped into prose is read as
prose. The namespace (`dev:` / `prod:`) is required here because this repo ships two plugins.

**One skill per call.** A step needing two skills is two calls, and must say so:

```
Call the Skill tool twice, for "dev:task-spec" and "dev:task-tickets".
```

"Call it with X and Y" reads as a single call taking both, which is not a thing the tool does.

This rule governs **operative** instructions only. A read-only pointer at another skill's
reference file — the `dev:harness-curate → references/delegation-template.md` form used in
about eighteen places today — invokes nothing and stays as it is. It is also the only form
available when the owning skill is user-invoked, since the invariant forbids calling it.

## What is not an invocation

Prose that names skills as **labels** — for a human to pick from, or as a string a hook emits
— invokes nothing, and keeps `/name` or `Skill(name)` spelling as plain text. Known sites:

- `dev/skills/harness-curate/references/trigger-router-template.md`
- `dev/skills/harness-curate/references/orchestrator-template.md`
- `dev/skills/harness-init/SKILL.md` — trigger-router section
- `dev/skills/harness-init/examples/agents-md-example.md`

No marker exists at any of those sites today — they are listed here by inspection, not by
annotation. Each must carry an explicit marker by the time a checker enforces the notation
rule, per `docs/conventions.md` → *Adjudicated Exceptions Need a Marker, Not a Standing
Warning*; adding them is part of that checker's ticket. A silent path allowlist inside the
checker is not an acceptable substitute: the exemption has to be visible where the text is.

`docs/design/*.md` are historical records of decisions as they were made. They are out of
scope for every rule on this page — do not rewrite their notation.

## Classification — `dev/`

The single source the `backlog.md` migration items apply. Nothing here is in force yet — no
`SKILL.md` carries the field and no sidecar exists. `prod/` skills (`hwpx`, `persona-debate`, `repo-quiz`)
are all model-invoked, which is the default, so they carry no fields and need no change.

| Skill | Axis | Why |
|---|---|---|
| `task-new` | user | Owns a full code cycle incl. commit/PR. Human picks the moment. |
| `task-next` | user | Same, plus queue mutation and `--all`/`--tree` fan-out. |
| `task-review` | user | Named human entry point; merges to `main`. |
| `harness-init` | user | Writes repo-wide scaffolding (AGENTS.md, docs index). |
| `harness-curate` | user | Cross-session mining; expensive, and prunes assets. |
| `repo-dependabot` | user | Acts across every owned repo via `gh`. |
| `task-grill` | model | Pure interview discipline. |
| `task-spec` | model | Writes one design doc; no destructive effect. |
| `task-tickets` | model | Splits an approved spec. |
| `harness-capture` | model | Retrospect discipline; called mid-review by design. |
| `task-review-cycle` | model | The callable half of the review cycle, extracted from `task-review`. |

Adding a skill means placing it in this table in the same PR.
