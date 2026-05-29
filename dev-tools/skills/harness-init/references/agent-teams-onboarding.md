# Agent Teams Onboarding

Claude Code's Agent Teams (experimental as of v2.1.32) let multiple Claude
Code sessions coordinate via shared tasks, mailbox, and file locking. This
file is the opt-in path — enable **only** for projects where work genuinely
parallelizes.

Source: Claude Code docs → "Orchestrate teams of Claude Code sessions".

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

- **In-process** (default, works anywhere): `Shift+Down` cycles teammates
- **Split panes** (tmux or iTerm2): one pane per teammate

```json
// ~/.claude.json (global only — no project override exists)
{
  "teammateMode": "in-process"
}
```

Leave at `"auto"` unless you have strong preference. Split panes shine for
4+ teammates; in-process is fine for 3.

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
   teammate in `tasks.md`. No teammate edits outside its glob. See
   `docs/workflows.md` → "File Ownership Declaration".

2. **Team size cap: 5.** Beyond that, diminishing returns + coordination
   cost spikes. Anthropic's own guidance.

3. **Lead does NOT implement.** If the lead starts coding instead of
   coordinating, prompt: "Wait for your teammates to complete their tasks
   before proceeding." This is a common failure mode.

4. **One team per session.** Clean up before starting another.
   `/agents cleanup` or "Clean up the team".

5. **Session resume is broken for in-process teammates.** `/resume` and
   `/rewind` do NOT restore them. After resume, spawn fresh teammates.

6. **Teammates do not inherit lead conversation.** Every spawn prompt must
   be self-contained (Spawn Prompt Contract — all 4 fields).

## When to Shut Teams Down

- Task is actually sequential (you noticed mid-flight)
- Single teammate is doing all the work
- Token burn exceeds value — check `/cost` periodically
- User feedback requires redirect affecting all teammates simultaneously
  (cheaper to kill and re-spawn than re-message each)

## Limitations (as of v2.1.32)

- Experimental — API and behavior may change
- No nested teams (teammates can't spawn their own teams)
- Lead is fixed for team lifetime
- `CLAUDE.md` is re-read per teammate (not shared) — keep it tight
- Permissions set at spawn; per-teammate mode changes require post-spawn
  adjustment
- Split-pane mode not supported in VS Code integrated terminal, Windows
  Terminal, or Ghostty

## Worked Example

```
You: "Review PR #142 with three independent lenses."

Claude (lead):
  Creating team with 3 teammates:
    - sec-reviewer (security-reviewer role, opus)
    - perf-reviewer (qa-verifier role with perf focus, sonnet)
    - test-coverage-reviewer (qa-verifier role with coverage focus, sonnet)

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
