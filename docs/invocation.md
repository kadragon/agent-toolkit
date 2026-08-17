# Invocation

Who may fire a skill. This is the one axis every skill in this repo is classified on, and
the rules below are what tickets 2–7 of `docs/design/invocation-axis.md` migrate the repo
onto. Field syntax lives in `docs/platform-specs.md`; the policy lives here.

Adapted from [mattpocock/skills](https://github.com/mattpocock/skills) `.agents/invocation.md`
(PR #878, PR #880), with one deviation — this repo ships two plugins, so every cross-skill
call carries its namespace.

## The axis

| | user-invoked | model-invoked |
|---|---|---|
| Who fires it | the human typing its name (`/task-next`) — nothing else | model **or** human |
| `description` reader | a person browsing the slash-command list | the model, deciding whether to reach for it |
| `description` shape | one human-facing line; no trigger lists, no `NOT for … →` arrows | rich trigger phrasing — auto-invocation depends on it |
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

**A user-invoked skill may call model-invoked skills. It may never call another user-invoked
skill.**

Orchestrators calling orchestrators makes it untraceable which skill owns the commit and how
many times a gate ran in one cycle. When a step's precondition is a user-invoked skill, write
it as an instruction for the human — never as a tool call:

```
WRONG:   Call the Skill tool with "dev:task-review".
RIGHT:   Tell the user to run `/task-review`.
```

The usual fix when automation must survive the ban is to extract the callable half as a
model-invoked skill and leave the human entry point as a thin wrapper over it — how
`task-review` and `task-review-cycle` are split.

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

Shared reference material lives inside the skill that owns it; another skill reaches it by
calling that skill, not by linking across folders.

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

The single source tickets 4–5 apply. `prod/` skills (`hwpx`, `persona-debate`, `repo-quiz`)
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
| `task-review-cycle` | model | The callable half of the review cycle. |

Adding a skill means placing it in this table in the same PR.
