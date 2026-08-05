# Agent Teams Onboarding

Claude Code's Agent Teams (still experimental) let multiple Claude Code
sessions coordinate via shared tasks, mailbox, and file locking. This file is
the opt-in path — enable **only** for projects where work genuinely
parallelizes.

Source: Claude Code docs → ["Orchestrate teams of Claude Code
sessions"](https://code.claude.com/docs/en/agent-teams), read 2026-07-30
(doc states the v2.1.178+ contract). Version-sensitive mechanics below carry
the version that introduced them — re-read the page before trusting one on a
much newer CLI.

**No team-creation step.** A team forms when the lead spawns its first
teammate, and its directories are cleaned up when the session exits. The
`TeamCreate` / `TeamDelete` tools were removed in v2.1.178 and no longer
exist; the `Agent` tool still accepts `team_name` but ignores it, and the
`team_name` field in the `TaskCreated` / `TaskCompleted` / `TeammateIdle`
hook payloads is deprecated (it carries the session-derived name). Any
harness text or orchestrator step that calls a team-creation tool is stale.

## Decision: Is Agent Teams Right for This Project?

Answer **yes** to at least TWO of the following before enabling:

- Cross-layer refactors (frontend + backend + tests) appear weekly or more
- Code review discipline requires multiple independent lenses (security,
  perf, test coverage)
- Adversarial debugging (see
  `references/competing-hypotheses-playbook.md`) is a regular need
- Large parallel codebase migrations are on the roadmap
- Team accepts ~3-5× token cost vs single session for affected workflows

If fewer than two apply, stick with subagents + Orchestrator-Subagent. Teams
add coordination overhead and token cost that most repos never recoup.

## Setup (5 minutes)

> **Path note:** Paths shown as `~/.claude/…` are the default location of
> Claude Code's user config directory. When `CLAUDE_CONFIG_DIR` is set they
> resolve under that directory instead — this includes user `settings.json`
> and the native task store. There is no *project-level* override for these.

### 1. Enable the flag

```json
// .claude/settings.json (project) or ~/.claude/settings.json (user)
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Or export in shell:

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

Restart `claude` after setting.

### 2. Choose display mode

- **In-process** (the default, works anywhere): the agent panel below the
  prompt lists teammates — up/down selects, `Enter` opens that teammate's
  transcript to message it directly, `Esc` interrupts its turn, `x` stops it.
- **Split panes** (tmux, or iTerm2 with the [`it2`
  CLI](https://github.com/mkusaka/it2)): one pane per teammate.

```json
// ~/.claude/settings.json
{
  "teammateMode": "in-process"
}
```

Values: `"in-process"` (default) · `"auto"` (split panes when already inside
tmux, or iTerm2 with `it2`, else in-process) · `"tmux"` · `"iterm2"`
(v2.1.186+, requires `it2`). Per-session override: `claude --teammate-mode
auto` (experimental, absent from `--help`).

**The default changed** — before v2.1.179 it was `"auto"`, so an upgraded
setup that used to open split panes now stays in one terminal unless the mode
is set explicitly. Leave it at the default unless you have a preference;
split panes shine for 4+ teammates, in-process is fine for 3.

### 3. Define reusable roles

See `references/teammate-role-template.md`. Every teammate should reference a
`.claude/agents/{role}.md` definition — do not inline role prompts at spawn
time.

### 4. Wire the team hooks

Add to `.claude/settings.json` hooks block (see
`references/enforcement-template.md` → "Agent Teams Quality Gates"):

- `TaskCreated` — enforce Spawn Prompt Contract (reject tasks missing any
  of the 4 fields)
- `TaskCompleted` — enforce eval-criteria before marking done
- `TeammateIdle` — feedback loop if teammate stopped with incomplete work

## Operating Rules

Embed these in `AGENTS.md` under a `## Agent Teams` section (only if
enabled):

1. **File ownership is declared upfront.** The lead assigns file globs per
   teammate via the native shared task list (`TaskCreate`, persisted under
   the Claude config dir, default `~/.claude/tasks/{team-name}/`). No
   teammate edits outside its glob.
   `tasks.md`/`backlog.md` stay the durable backlog — read-only during team
   work. See `references/workflows-template.md` → "Step 1.5: File Ownership
   Declaration".

2. **Start with 3–5 teammates.** There is no hard platform limit, but token
   cost scales linearly and coordination overhead grows — the docs recommend
   3–5, with 5–6 tasks per teammate. Three focused teammates beat five
   scattered ones.

3. **Lead does NOT implement.** If the lead starts coding instead of
   coordinating, prompt: "Wait for your teammates to complete their tasks
   before proceeding." This is a common failure mode.

4. **One team per session, cleaned up automatically.** A session has exactly
   one team, scoped to that session; you cannot create additional named teams
   or share a team across sessions. No teardown step — the team config
   directory is removed when the session exits. To end a single teammate
   early, ask it to shut down by name; it may approve or reject.

5. **Session resume is broken for in-process teammates.** `/resume` and
   `/rewind` do NOT restore them. After resume, spawn fresh teammates.

6. **Teammates do not inherit lead conversation.** Every spawn prompt must
   be self-contained (Spawn Prompt Contract — all 4 fields).

7. **Task store separation.** `tasks.md`/`backlog.md` = durable backlog
   (read-only mid-session input). Live coordination, status, and file globs
   live in the native shared task list (Task tools, persisted under the
   Claude config dir, default `~/.claude/tasks/{team-name}/`; see the Path
   note in Setup). At session end the lead manually syncs completion back to
   `tasks.md`. There is no project-level override for the native store path —
   it follows `CLAUDE_CONFIG_DIR` (default `~/.claude`). The team config
   (`~/.claude/teams/{team-name}/config.json`, plus per-agent mailboxes under
   `inboxes/{agent-name}.json`) is runtime state — never hand-edit or
   pre-author it; the next state update overwrites it. `{team-name}` is
   `session-` + the first eight characters of the session id. The task-list
   directory persists (retention follows `cleanupPeriodDays`); the team config
   directory does not.

8. **Permissions do not flow backwards through teammates.** Teammates start
   with the lead's permission mode and cannot be given per-teammate modes at
   spawn time. A teammate cannot approve a permission prompt or supply consent
   on your behalf, and one that was denied an action cannot relay it to
   another teammate to get around the check — a relayed approval claim is
   treated as untrusted input. Teammate permission prompts surface in the lead
   session; approve them there. Plan approval is the one designed exception:
   the lead grants teammate plan approvals itself.

9. **Plan approval is available for risky work.** Ask for it at spawn time and
   the teammate stays in read-only plan mode until the lead approves; on
   rejection it revises and resubmits. The mechanism is the
   `plan_approval_request` / `plan_approval_response` message pair on
   `SendMessage`. Give the lead explicit approval criteria in the prompt —
   otherwise it decides alone.

## When to Shut Teams Down

- Task is actually sequential (you noticed mid-flight)
- Single teammate is doing all the work
- Token burn exceeds value — check `/cost` periodically
- User feedback requires redirect affecting all teammates simultaneously
  (cheaper to kill and re-spawn than re-message each)

## Limitations (docs read 2026-07-30)

- Experimental — API and behavior may change
- No nested teams (teammates can't spawn their own teammates; only the lead
  manages the team)
- No background subagents from an in-process teammate — its own subagents run
  in the foreground, and requesting a background one (`run_in_background`, or
  a subagent definition with `background: true`) errors, because a teammate's
  background work can't outlive the lead's process
- Lead is fixed for team lifetime
- `CLAUDE.md` is re-read per teammate (not shared) — keep it tight
- Permissions set at spawn; per-teammate mode changes require post-spawn
  adjustment
- Task status can lag — a teammate that fails to mark a task complete blocks
  its dependents; check and fix status manually if a task looks stuck
- Shutdown can be slow — a teammate finishes its current tool call first
- Split-pane mode not supported in VS Code integrated terminal, Windows
  Terminal, or Ghostty

## Worked Example

```
You: "Review PR #142 with three independent lenses."

Claude (lead):
  Creating team with 3 teammates:
    - sec-reviewer (security-reviewer role)
    - perf-reviewer (qa-verifier role with perf focus)
    - test-coverage-reviewer (qa-verifier role with coverage focus)

  Shared task list seeded with 3 tasks (one per lens).
  Each teammate has its own Spawn Prompt Contract referencing PR #142 diff.

  [teammates work in parallel — lead monitors TaskCompleted]

  Synthesis:
    - Sec: 2 findings (JWT expiry race, CSRF on /settings)
    - Perf: 1 finding (N+1 in UserList)
    - Coverage: missing tests for error paths

  Recommended fix order: sec findings first, then N+1, then tests.
```

All three lenses investigated in parallel in ~5 minutes vs ~15 sequentially.
That is the payoff — and also roughly the token cost multiplier to expect.
