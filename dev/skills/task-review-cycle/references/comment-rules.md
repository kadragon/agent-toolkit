# Comment Rules

The `comments` review axis of `task-review-cycle`. Adapted from pstack's Comment Sicko
(`cursor/plugins@bf0c7cd:pstack/agents/comment-sicko.md`) and its `/no-comments` driver
(`cursor/plugins@2f87c85:pstack/skills/no-comments/SKILL.md`). `scripts/claude-review.sh`
appends this file to its prompt verbatim; the inline pass (SKILL.md Step 2) reads it here.

## Scope

Code comments that this branch's diff adds or edits, in source files only: scripts, programs,
configs. Prose documents (`*.md`, docs, `SKILL.md` text) are not comments. Untouched comments
are out of scope even when they break these rules.

Tooling directives are not comments and are never flagged: any comment a compiler, build tool,
bundler, linter, formatter, or type checker reads. Examples, not a closed list: shebangs, encoding
lines, `# shellcheck shell=`, `"use strict"`, `//go:build`, `//go:embed`, `//go:generate`,
`# frozen_string_literal`, a Dockerfile `# syntax=`, `/*#__PURE__*/`, bundler magic comments,
`# type:` annotations, JSDoc types under `// @ts-check`, formatter on/off markers. When unsure
whether a tool reads it, it is a directive.

## Keep list

Only these comments stay. When unsure whether one applies, the comment goes.

- Legal or license headers.
- Non-obvious behavior forced by an external dependency, platform, vendor, or protocol this repo
  cannot reshape: a bash 3.2 quirk, an upstream CLI bug, a vendor API limit. Name the external
  thing; a surprise in our own code does not qualify.
- Doc comments that define a public API contract: a function docstring of an exported API, a
  script's usage header naming its arguments and output.
- Issue or RFC links that explain a constraint code cannot express.
- Lint suppressions whose rule is faulty, pedantic, or style-only for this line.

## Verdicts

Every other comment in scope gets one finding. `IMPORTANT`, `do not remove`, `too risky`,
`fine for now` and long justifications are a reason to look closer, not a keep: read the nearby
code and trace the named symbol; keep only a keep-list case proven true on a live path today. A
long justification with no proven keep is a confession. Never propose a shorter rewrite of a
comment that should go.

- `delete` — narration, banners, commented-out code, restated code, history (`was X`,
  `changed to`), TODOs with no tracked item. Fix: delete the comment.
- `must-kill` — the comment explains a surprise in our own code. Fix: delete the comment and
  name the exact symbol to rename, extract, type, or restructure so the behavior reads without
  prose. Also for a workaround comment: name the workaround to remove at its root cause.
- `suppression` — a lint or type suppression (`# noqa`, `# type: ignore`,
  `# shellcheck disable=`, `eslint-disable`, `@ts-ignore`, `@ts-expect-error`) whose rule
  protects correctness or safety. Fix: remove the suppression and name the code that must change
  so the rule passes.
- `constraint` — a comment that guards against a future edit (`do not remove`,
  `do not change wording`, `talk to X first`) about something this repo controls. Fix: name the
  cheapest in-scope encoding — a test, type, runtime check, or CI lint — that enforces it, then
  delete the comment.

Each finding names a file and line inside the diff and says what the comment claims. Flag only;
never propose application-code changes beyond the named symbol.

## Applying (orchestrator, Step 4)

Re-read each finding against the diff first. Reject one that touches code rather than a comment,
lands outside the diff, deletes a keep-list comment, or misstates a `must-kill` reason. For a
thin `IMPORTANT` / `do not remove` verdict either way, trace the symbol before accepting.

- `delete` → delete, without waiting for confirmation even without `--auto`: a non-directive
  comment carries no behavior. Reject a `delete` aimed at a directive. List it in the Step 3
  table as already applied.
- `must-kill` / `suppression` → without `--auto`, offer the smallest in-scope fix that makes the
  comment unnecessary, removing the workaround it named (never a symptom guard), and wait.
  Approved → apply it, then delete the comment. `--auto`, declined, or a fix that needs work
  outside this branch's purpose → delete the comment and file the reshape under
  `## Review Backlog` as `[debt]`; `--auto` never renames or restructures code for a comment.
- `constraint` → without `--auto`, offer the encoding and wait. Approved → encode, then delete.
  Declined or `--auto` → delete and file the constraint under `## Review Backlog` as
  `[constraint]`.
