# Invocation

Who may fire a skill. This is the one axis every skill in this repo is classified on. The
rules below are the target state — the repo is **partially migrated onto them**: the
`task-review` / `task-review-cycle` split, the *Notation* migration and both halves of
*Per-platform fields* have landed, as have the user-invoked one-line descriptions; only the
`## Invocation axis — CI enforcement` item in `backlog.md` is still open. `docs/design/invocation-axis.md`
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
defect, not a partial rollout. Both halves are in force in this repo: each `user` skill below
carries the Claude frontmatter field *and* an `agents/openai.yaml` sidecar.

| Platform | Field | Value for user-invoked |
|---|---|---|
| Claude Code | `SKILL.md` frontmatter | `disable-model-invocation: true` |
| Codex | `skills/{name}/agents/openai.yaml` | `policy.allow_implicit_invocation: false` |

Codex's bundled `plugin-creator` validator rejects `disable-model-invocation: true` outright — it
expects the lock to ride on the sidecar alone. This repo keeps both halves anyway, because Claude
Code has no other way to express the axis; `docs/platform-specs.md` → *SKILL.md frontmatter (Codex)*
records the measured conflict and what it costs.

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
model-invoked skill fire a destructive orchestrator. The repo shipped exactly that violation —
`dev/skills/task-tickets/SKILL.md` → *Hand off* named `task-next`, a model-invoked caller
pointing at a user-invoked target — until the *Notation* migration rewrote it as an instruction
for the human.

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
half, carry the caller's flags across — every skill-to-skill hand-off (`task-new`, `task-next`,
batch, tree) passes `args: --auto`, and dropping it would stall an unattended cycle at
the confirmation gate. The `task-review` wrapper is the exception by design: it forwards the human's
own flags verbatim, so a bare `/task-review` passes no `--auto` and the confirmation gate is what the
human came for. The extracted half also
takes a `--from <caller>` token so it can refuse a call that came from nobody: see
`dev:task-review-cycle` → *Caller gate*. The token is what makes the primitive's "not a standalone
entry point" a checkable precondition rather than a wish.

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
reference file — the `dev:harness-init → references/harness-invariants.md` form — invokes
nothing and stays as it is. It is also the only form
available when the owning skill is user-invoked, since the invariant forbids calling it.

## What is not an invocation

Prose that names skills as **labels** — for a human to pick from, or as a string a hook emits
— invokes nothing, and keeps `/name` or `Skill(name)` spelling as plain text. Known sites:

- `dev/skills/harness-init/examples/agents-md-example.md`

Three further sites survive the *Notation* migration for a different reason — they mention a
skill without instructing anyone to run it right now, so rewriting them into tool calls would
create a call where none belongs:

- `dev/skills/task-grill/SKILL.md` and `dev/skills/task-spec/SKILL.md` `description:` frontmatter
  — these still spell `Skill(dev:task-grill)`. Both skills are **model-invoked**, so the
  user-invoked description rewrite passed them by: it touched only the six human-facing
  descriptions and left model-invoked trigger phrasing intact. Rewording these two is a separate,
  unqueued decision — descriptions are trigger-scored, so any edit has to be measured against
  `scripts/ci/check_skill_triggers.py` before it lands.
- `dev/skills/harness-init/references/design-rationale.md` — an availability note ("`task-grill`
  is available when the conflicts need real interviewing"), not a step.

These three carry markers. The router-prose site above needs none: the checker's regex is
namespace-anchored, so the `Use Skill(X)` form is outside the rule by construction rather than
by exemption.

**The markers now exist.** `scripts/ci/check_skill_frontmatter.py` enforces the notation rule,
and each exempt site carries its own marker where the text is — never a path allowlist inside the
checker, per `docs/conventions.md` → *Adjudicated Exceptions Need a Marker, Not a Standing
Warning*:

```
<!-- notation-exempt: <reason> -->        markdown prose
# notation-exempt: <reason>               inside a YAML frontmatter block
```

Accepted on the flagged line, the line above it, or the line above an enclosing code fence,
and only as a complete HTML comment — prose that merely *mentions* `notation-exempt:` is not
a marker, or a page explaining this convention would exempt its own examples.
A `<!-- call-graph-exempt: <reason> -->` marker does the same job for a line that names a
user-invoked skill in order to *describe* the invariant rather than call it.
**Inside frontmatter the rule is narrower, deliberately:** the marker sits on its own
unindented line directly under the key it covers, and covers *only that key* — a folded scalar has no line a
marker can share without leaking into the value the loader reads, but a block-wide exemption
would let one justified marker launder an unrelated violation under the next key. An
*indented* `#` line is not a marker at all — YAML folds it into the scalar above, so it
would leak into the description and exempt itself. Only the
three marked sites need one today: the checker's regex is namespace-anchored, so the router-prose
`Use Skill(X)` form is outside the rule by construction rather than by exemption.

`docs/design/*.md` are historical records of decisions as they were made. They are out of
scope for every rule on this page — do not rewrite their notation.

## Classification — `dev/`

The single source the `backlog.md` migration items apply. **Both halves are in force**: each
skill marked `user` below carries `disable-model-invocation: true` in its `SKILL.md` and
`policy.allow_implicit_invocation: false` in its `agents/openai.yaml`. `prod/` skills (`hwpx`, `persona-debate`, `repo-quiz`)
are all model-invoked, which is the default, so they carry no fields and need no change.

| Skill | Axis | Why |
|---|---|---|
| `task-new` | user | Owns a full code cycle incl. commit/PR. Human picks the moment. |
| `task-next` | user | Same, plus queue mutation and `--all`/`--tree` fan-out. |
| `task-review` | user | Named human entry point; merges to `main`. |
| `harness-init` | user | Writes repo-wide scaffolding (AGENTS.md, docs index). |
| `harness-curate` | user | Cross-session mining; expensive, and prunes assets. |
| `repo-dependabot` | user | Acts across every owned repo via `gh`. |
| `repo-architecture` | user | Scans the whole repo and appends to the queue; the human picks the moment. |
| `task-grill` | model | Pure interview discipline. |
| `task-debug` | model | Reusable diagnosis discipline. |
| `task-spec` | model | Writes one design doc; no destructive effect. |
| `task-tickets` | model | Splits an approved spec. |
| `harness-capture` | model | Retrospect discipline; called mid-review by design. |
| `task-review-cycle` | model | The callable half of the review cycle, extracted from `task-review`. |

Adding a skill means placing it in this table in the same PR.
