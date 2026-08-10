---
name: task-new
version: 1.1.2
description: >-
  Intake for NEW work the prompt itself describes: classify → grill → spec and
  tickets if large → full code cycle (branch → Sprint Contract → implement →
  qa-verifier → version bump → task-review). Trivial work gets a lite path.
  Pulling the next item from the existing queue instead → task-next.
---

# New Task

Intake and drive a **fresh, free-text request** — a feature, refactor, or fix the user just
described that is not yet an item in `backlog.md`/`tasks.md`. Sibling to `task-next`: that skill
picks work already on the queue; this one turns a spoken request into work and runs it through
the same `code` cycle in `docs/workflows.md`. Delegate the heavy lifting — this skill is the
**intake, sizing, and sequencing layer**, not the implementation engine.

Boundary vs `task-next`: if the request is already a `backlog.md`/`tasks.md` item, stop and use
`task-next` — do not re-enter it here. This skill runs when the request has no tracking entry yet.

## Prerequisites

**Required:** `backlog.md`, `docs/workflows.md`, `docs/eval-criteria.md` — the queue and the two
docs this skill executes. If any is missing, stop and point the user to `dev:harness-init`.

**Conditional:** `docs/conventions.md` is generated at init only when rules exist that the linter
does not already own, so a repo whose linter owns every rule correctly has none. Read and follow it
when present; when absent, proceed and take the linter as the authority. Never stop on its absence.

**Working tree gate:** Run `git status --porcelain`. If the output is non-empty, stop and list
the dirty files — do NOT proceed. Ask the user to commit, stash, or discard first. (This gate is
checked once, here. Later steps deliberately dirty `tasks.md`/`backlog.md` as part of the cycle;
that is expected and rides into the feature branch.)

**Roster check — before any agent spawn in any step below.** A role exists only if
`.claude/agents/{role}.md` or `~/.claude/agents/{role}.md` is present. `dev:harness-init` creates
**no** roles (its Step 4b), so an empty roster is the designed state of a freshly initialized repo,
not a defect — never stop on it, and never create the role mid-task. Route around it per the
fallback attached to each spawn point, say in one line which fallback you took, and note that
`dev:harness-curate` is what adds a role once the transcripts show the delegation recurring.

```bash
role_exists() { [[ -f ".claude/agents/$1.md" || -f "$HOME/.claude/agents/$1.md" ]]; }
role_exists implementer && echo present || echo absent
```

The probe covers repo- and user-level roles only. A role can also arrive from an installed plugin
(`plugin.json` → `agents`, see `docs/platform-specs.md`), which no path check finds — if the runtime
lists the role as an available agent type, treat it as present regardless of the probe.

## Step 1 — Classify & size-gate

Free text carries no `[type]` tag yet, so infer one from what the request describes before
gating — adds/changes user-visible behavior → `[FEAT]`; restructures existing behavior without
changing it → `[REFACTOR]`; fixes broken behavior → `[FIX]`; anything else → leave untagged.

Then judge **trivial**: trivial iff ALL hold — inferred/explicit tag is NOT `[FEAT]`/`[REFACTOR]`,
total in-scope files ≤2, no new public API/schema. An untagged one-file typo fix stays trivial;
an untagged one-file behavioral addition ("로그인 버튼 추가해줘") is not, because it infers to
`[FEAT]`.

If the file count isn't obvious from the request text, run a quick scoped scan (or spawn
`explorer` if the scan itself would be large — the built-in `Explore` subagent when `explorer` is
absent from the roster) to estimate it before classifying.

## Step 2 — Route by size

**Trivial** → skip task-grill/`task-spec`/`task-tickets` entirely. Build the Sprint Contract directly from
the request and go to Step 3. The Step 3 lite-path offer still applies.

**Non-trivial and ambiguous** (scope, requirements, or a design decision is not already clear from
the request) → `Skill(dev:task-grill)` to resolve scope. Do not proceed until task-grill reports the
open questions resolved.

**After resolution, judge size:**

- **Single-session-sized** → build the Sprint Contract directly from the task-grill output (or directly
  from the request, if task-grill was skipped because it was unambiguous but not trivial) and go to
  Step 3.
- **Multi-session or architecturally significant** → `Skill(dev:task-spec)` to write
  `docs/design/{slug}.md`, then `Skill(dev:task-tickets)` to break the approved spec into
  ordered `backlog.md` items. Once `task-tickets` has written the tickets, **pick the first
  ready ticket** (the topologically-first item with no unresolved `*(blocked by: ...)*` marker) and
  run Step 3 on that single ticket. The remaining tickets stay in `backlog.md` for future
  `task-next` runs — do NOT try to implement more than one ticket in this invocation.

Either way, Step 3 runs **exactly one** code cycle before handoff.

## Step 3 — Run the code cycle

Execute `docs/workflows.md` → `code` cycle (Steps 0–6). This skill is a thin front-end over that
cycle; the overrides below are what differ for a **request-sourced** task. Standard steps apply
where not overridden.

**Branch (Step 0)**
Pass the `[type]` inferred in Step 1; omit `--tag` if it was left untagged and the script falls back
to `fix/` with a stderr warning.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
NODES="$SKILL_DIR/../task-next/scripts/task_nodes.py"   # one shared copy; same dev plugin
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }
BRANCH=$(python3 "$NODES" branch --title "<short title for the request>" --tag <TYPE>)
git checkout -b "$BRANCH"
```

**Scope check (Step 1)**
If the target area has >3 files AND was not explored this session → spawn `explorer` before writing
the Sprint Contract. **`explorer` absent from the roster:** spawn the built-in `Explore` subagent
with the same brief — it is the ad-hoc fan-out `dev:harness-init` points at for a repo with no roles.

**Plan mode gate (before Step 2)**
- **Non-trivial** (tag is `[FEAT]`/`[REFACTOR]`, OR ≥3 files, OR new public API/schema): use
  `ToolSearch` (`query: "select:EnterPlanMode,ExitPlanMode"`) to load plan-mode tools, call
  `EnterPlanMode`, design the approach, call `ExitPlanMode` for user approval. If `ToolSearch`
  returns no results, present the plan as a numbered list and wait for explicit "proceed".
- **Trivial**: skip plan mode.

**Sprint Contract (Step 2)**
Write to `tasks.md` only when running a `task-tickets`-generated backlog ticket (the
multi-session path) — that's the only case needing `## Covers` as a deletion target for cleanup.
Every other path (trivial, single-session-sized, unambiguous-but-not-trivial) authors the
contract inline in the conversation and writes no file. Either way the contract has the same
shape, per `docs/eval-criteria.md`:
- `# heading` = a short title for the request
- `status: active`
- **Tag** / **Scope** / **Acceptance criteria** / **Out of scope** / **Lint/test command** — the
  **Tag** is the `[TYPE]` this change will commit under, and it must be written into the contract:
  the verifier grades the contract alone, so a tag it cannot see gates nothing (a `[FIX]` contract
  missing its reproduction criterion then reads as a well-formed non-`[FIX]` one)
- File-backed only: add a `## Covers` line with the ticket's `- [ ]` item copied **verbatim**
  from `backlog.md` — this is the deletion target for cleanup.

**Implement (Step 3)**
- 1–2 files AND not `[FEAT]`/`[REFACTOR]`: inline edit.
- Otherwise: spawn `implementer` (brief per `docs/delegation.md` four-field format: Objective /
  Output format / Tools to use / Boundaries — include the Sprint Contract, absolute paths of all
  in-scope files, and the lint/test command). `implementer` must NOT verify its own output.
- **`implementer` absent from the roster:** implement inline on the main thread. Sprint Contract,
  in-scope paths and lint/test command still apply — only the spawn brief is dropped. Whoever
  implemented does not verify, so QA below still goes to a separate agent.
- **Stuck-fix stop condition:** if the same fix is attempted 3+ times on one file without the
  lint/test command passing, stop and report instead of retrying.
- **Destructive-command guard:** never run `git push --force`/`--force-with-lease`,
  `git reset --hard`, `git clean -f`/`-fd`, or `git branch -D` while implementing. If a fix seems to
  require one, stop and ask.
- **If `implementer` fails or returns unusable output:** stop and report; do not proceed to QA.

**QA (Step 4 — mandatory)**
ALWAYS spawn `qa-verifier` as a separate agent.

**Brief it adversarially.** The objective is *find violations*, not *confirm compliance* — tell it
to hunt for each way the change could fail a criterion and to record a pass only where it has
evidence. Do **not** pass your own reasoning about why the implementation is correct; a supplied
conclusion is what a verifier confirms. Applies to the `general-purpose` fallback below too.

If it reports blocking issues: surface them, then **classify each one first** — a finding caused by
an unclear, incomplete or wrong Sprint Contract is a *contract* defect, so correct the contract and
re-brief from it rather than sending it to `implementer`, which re-litigates it as an
implementation defect and burns the one allowed retry. Spawn `implementer` on the surviving
findings, re-run `qa-verifier` **once** against the corrected contract. If still blocking after one
retry: stop and report — do NOT hand off with unresolved blockers.

**`qa-verifier` absent from the roster:** spawn the built-in `general-purpose` subagent as the
verifier instead. The brief keeps the same shape a role file would have carried — `docs/delegation.md`
four-field format (Objective / Output format / Tools to use / Boundaries) plus effort tier — filled
with the Sprint Contract's acceptance criteria verbatim, the in-scope paths and the lint/test
command, and telling it to verify against those criteria and change nothing. **Carry the
standing-checks floor in the brief too** — with no role file there is no `## Checks (always run)`
for the brief to point at, so the gates every contract inherits reach the verifier only if the
brief states them. Take them from `harness-init` → `references/harness-invariants.md` →
*Verifier Standing-Checks Floor*; do not reconstruct the list from memory. The
independence is what must not be dropped, not the role name: the agent that implemented — the main
thread included, when the implementer fallback above was taken — never verifies its own output.
Fixes on the retry path go to `implementer`, or inline when that role is also absent.

**Version bump (Step 5)**
The judgment is *which* plugin and *which* bump level; the rewrite is scripted. Do this AFTER all
changes, BEFORE handoff.

```bash
[[ -f scripts/bump-version.sh ]] && bash scripts/bump-version.sh <plugin> <major|minor|patch> \
  [--skill <name> <major|minor|patch>]
```

Pass `--skill` when the changed files include that skill's own `SKILL.md`, so its `version:`
frontmatter does not go stale. The script takes **one** `--skill` per run and bumps the plugin on
every run, so a change touching two skills needs the second skill's `version:` edited by hand —
re-running would bump the plugin twice for one change.

`bump-version.sh` keeps both platform manifests in sync and states the semver table in its own
header; `docs/conventions.md` → *Plugin Version Bump Rules* is the prose copy where that doc exists.
Read one of them rather than recalling the rules — the script header suffices on its own when the
repo has no `docs/conventions.md`. No `scripts/bump-version.sh` → edit the manifests by hand per the
same rules; no `plugin.json` at all → skip this step. With **neither** the script nor
`docs/conventions.md` present, the repo has stated no release policy — ask the user for the bump
level instead of inventing one.

**Do NOT commit.** Leave everything uncommitted — `task-review` Step 1 makes the single commit.

**Pre-merge cleanup (before handoff)**
Leave everything uncommitted so it lands in the initial PR commit.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
NODES="$SKILL_DIR/../task-next/scripts/task_nodes.py"   # one shared copy; same dev plugin
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }

# only if the Sprint Contract was written to tasks.md (multi-session path); deletes tasks.md if nothing remains
python3 "$NODES" prune-tasks --file tasks.md --block "<Sprint Contract title>"
# multi-session path only — the ## Covers ticket line, verbatim
printf '%s\n' "<the ## Covers line>" | python3 "$NODES" prune-backlog --file backlog.md
# one CHANGELOG entry; drop --plugin/--version in a repo with no versioned plugin
python3 "$NODES" changelog --file CHANGELOG.md --title "<title>" \
  --plugin <plugin> --version <X.Y.Z> [--link docs/<owning-doc>.md]
```

`prune-*` refuses (exit 1) and changes nothing on a line that does not match verbatim. A heading is
dropped only where this run emptied it — headings elsewhere with all-`[x]`/`[>]` items are
deliberate history and stay. What the script cannot decide — the character cap, and the ban on
explanatory clauses, file lists and narration — lives in the *CHANGELOG Entry Contract* in
`harness-invariants.md` (bundled with `dev:harness-init`). Read it before choosing the title.

## Step 4 — Hand off

Invoke `Skill(dev:task-review)` with `args: --auto`. It commits (including the cleanup
above), creates the PR, collects reviews, applies in-scope findings, records out-of-scope items to
`backlog.md`, waits for CI, and merges.

If `task-review` reports CI failure and the PR must be abandoned: close the PR and delete the
feature branch — `main` retains its pre-cleanup state, no rollback needed.

## Lite path

For a **trivial** request only. The lite path changes **only the handoff** — everything in Step 3
(branch, Sprint Contract, implement, QA, version bump, cleanup) runs identically; only Step 4
differs. Present the choice when entering Step 3 (before branching) so the user isn't surprised:

```
[1] 라이트 패스 — 구현+QA 후 main에 직접 머지 (PR·CI 없음)
[2] 풀 사이클 — task-review (PR, CI, 코드리뷰 포함)
```

- User picks **1** → run Step 3 (branch, Sprint Contract, implement, QA, version bump, cleanup) then
  skip `task-review` and merge directly:

```bash
git add <changed files>
git commit -m "[TYPE] <description>

Co-Authored-By: Claude <noreply@anthropic.com>"
git checkout main
git pull origin main
git merge --no-ff <type>/<slug> -m "Merge branch '<type>/<slug>'"
git push origin main
git branch -d <type>/<slug>
```

  **Branch-protection caveat:** if `git push origin main` is rejected (PR-only rule), reset local
  main (`git reset --hard origin/main`), check out the feature branch, and fall back to
  `Skill(dev:task-review)` with `args: --auto`.

  Report: "라이트 패스 완료 — main에 직접 병합 및 푸시됨. PR·CI 없음."
- User picks **2** → proceed to Step 3 / Step 4 normally.

## Edge cases

**Request is already tracked** — if the described work matches an existing `backlog.md`/`tasks.md`
item, stop and route the user to `task-next` instead of duplicating the entry.

**Batch of unrelated requests** — this skill runs one request per invocation. If the user lists
several independent tasks, handle the first and tell them to re-invoke for the rest (or add them to
`backlog.md` and point at `task-next --all`).

**Work already in flight** — if `git status` shows an in-flight feature branch rather than a fresh
request, this is `task-next` territory (its "Work already in flight" edge case). Route there.
