---
name: dispatch
version: 1.0.0
description: >-
  Dispatch work from a home repo to a child Codex or Claude Code session in another repo
  listed in the home's repos/*.md, using Herdr (`hc run`). Use when the user asks to run a
  listed repo's queue, start a task there, or have that repo handle a request, e.g.
  "다른 레포에서 다음 작업 진행해" or "대상 레포 큐 돌려줘". Also use to watch, relaunch,
  or escalate a child session started by dispatch. Work on the home repo stays in that session.
---

# Dispatch

A home repo keeps a registry of other repos in its own `repos/*.md`. The model invokes
dispatch from that home session. The target repo runs the work: the user-invoked `task-next`
and `task-new` use the current directory's Git state and queue, so give the child session
the command as its first message. With the dev plugin installed in the child, Claude uses
slash commands and Codex uses `$task-next` and `$task-new`. Step 3 picks the CLI.

`scripts/dispatch.py` reads task-next's pick and launches the child. Replace `<dispatch>`
in commands with the absolute directory containing this loaded `SKILL.md`.

## 1. Resolve the repo

Find the repo in `repos/*.md` by name or description; its line gives the local path, and the
clone URL when it is missing. Ambiguous match → ask which repo, naming the candidates. Path
missing → clone from that URL, or stop when the line says "Local only".

## 2. Pick the first message

| Request | First message |
|---------|---------------|
| run the queue / next item | `/dev:task-next` |
| run every queued item | `/dev:task-next --all` |
| new work the user described | `/dev:task-new <the request, verbatim>` |
| anything else (question, review, debug) | the request, verbatim |

In a Codex session write `/dev:task-next` as `$task-next` and `/dev:task-new` as `$task-new`,
with the same arguments.

`/dev:task-next` needs `backlog.md`. If missing, tell the user and offer `/dev:task-new`.
The task skills own the working-tree gate.

## 3. Pick CLI, model and effort

Route by rules, not by a guess at the outcome: give each session the cheapest pair that can
finish it, and escalate on evidence. Pick the two independently — the model by the capability
the work needs, the effort by how ambiguous or risky it is. The user naming a CLI, model or
effort overrides both tables and every rule below.

Codex takes the work Claude's haiku and sonnet would, to keep Claude usage for the work that
needs opus judgment; its usage is a separate quota. Its model is `gpt-6.2-sol`, Codex's
go-to coding model. `gpt-6.2-astra` and the `max`/`ultra` efforts only when the user asks: a
stall on Codex goes to Claude opus instead, which also brings a second model family.
Claude `haiku` and `sonnet` only when the user asks, Codex is unavailable, or the quota bias
below says `claude`.

The home session runs on opus: its decisions are reading a child's
recommendation and checking it against the request, and it stays open for the whole run, so
every watch turn re-reads its growing context at the home model's price. Fable at home only
when the user asks.

Balance by quota. Before picking the pairs of a wave, run `python -I "<dispatch>/scripts/quota.py"`
once, not per child. It reads the weekly and 5-hour limits each CLI's server last reported
and prints, per CLI, `used`, `elapsed`, `state` (`ok`, `hot`, `critical`,
`unknown`), and one `bias`; the thresholds live in the script. A state the 5-hour window
raised resets within hours, so it holds for this wave only; re-run the script for the next.
See `references/quota-snapshot.md` when wiring or diagnosing the Claude status-line snapshot.
Apply the bias on top of the tables below:

| bias | Change |
|------|--------|
| `none` | the tables as written |
| `codex` (Claude running ahead) | opus rows at `high` or below that are task cycles or reviews (a `/dev:task-next` item without written criteria, a change across several modules, a review) go to codex `gpt-6.2-sol` at `high`. `/dev:task-new`, spec and design phases, anything at xhigh, and escalated pairs stay on opus |
| `claude` (Codex running ahead) | codex rows go to claude `sonnet` at the same effort; a `low` lookup to `haiku` |
| `both-hot` | the tables as written, at most two children, and tell the user both numbers before launching |

- `critical` on a CLI: launch nothing on it without the user's yes. Move a row to the other
  CLI when the bias table allows it; otherwise ask.
- `unknown` (no snapshot yet) counts as `ok`; say which one is missing.
  The Claude snapshot refreshes whenever a Claude status line draws, the Codex one only when a
  Codex session runs, so a large `age_h` on Codex usually means it sat idle. The Codex plan
  may report no 5-hour window; then only the weekly one counts.
- The bias moves the starting pair only; escalation follows `references/escalation.md`.
- The home session itself runs on Claude, so a `codex` bias is also a reason to keep its
  watch turns few (step 5).

Model — capability:

| Model | When |
|-------|------|
| codex `gpt-6.2-sol` | a factual lookup or log summary that changes no file; a change whose cause and place are already known, docs or config text, one file or a few — including a backlog item that names those files and its acceptance criteria; a `/dev:task-next` item for an ordinary feature or fix |
| claude `opus` | `/dev:task-new`, a review or a diagnosis, a change that has to hold several modules or the domain in mind, and anything at xhigh; the default when unsure |
| `fable` | only by escalation from opus/xhigh, or when the user asks |

Effort — ambiguity and risk:

| Effort | When |
|--------|------|
| `low` | lookups that change no file |
| `medium` | a clear spec or contract, little to decide, cheap to get wrong; a backlog item with written acceptance criteria (a `task-tickets` slice). `gpt-6.2-sol`'s own default |
| `high` | the default for task cycles on an item without written criteria, and for `/dev:task-new` |
| `xhigh` | an unknown cause (debugging, performance), design or spec phases (`task-grill`, `task-spec`), or a costly mistake: security, auth, data migration, production DB or deploy paths |

- Judge from the request text. For `/dev:task-next`, judge the item task-next will pick:
  `python -I "<dispatch>/scripts/dispatch.py" pick "<repo path>"` (add `--tree` for a `--tree`
  run) prints task-next's own candidate list as JSON; the first entry is its pick. Read that
  entry's lines in `backlog.md` (or `tasks.md`) for its criteria. This is not a working-tree
  preflight. When the pick is unclear, take the pair of the hardest listed candidate; `--all`
  always takes the pair of the hardest open item.
- `--effort max` only when the user asks for it; it costs much more and rarely beats xhigh.
- Codex does not run at xhigh unless the user picks a Codex effort: work that needs xhigh
  needs opus too, so it starts on Claude.
- Effort is fixed per session and the model already scales its thinking per turn within it,
  so set it once at launch. It changes between phases, since each phase is a new launch.
- When a child stalls, gets its change sent back, or turns out wrong, or when a later phase of
  an escalated task launches, read `references/escalation.md` for the ladder and the relaunch.
- State the CLI, the pair and the reason in one line when reporting the launch, with the quota
  numbers when the bias changed the pair (`Claude week 82% at 44% elapsed, 5h 45% → codex`).

## 4. Launch

Run `hc ls` first. A live task session in the repo — yours or another home session's, since
both share the checkout: say so and stop, unless the new one runs `--tree` (below).

```sh
python -I "<dispatch>/scripts/dispatch.py" launch --cli claude --model <model> --effort <effort> \
  --cwd "<repo path>" [--name <repo>-<n>] '<first message>'
```

It prints `{name, address, parent, shown}`. `--dry-run` prints the `hc run` line instead.
Keep each child's `address` for every later `hc` command (`send`, `read`, `keys`, `get`, `kill`,
`rm`). Names are shared across Herdr spaces, so a familiar name may now belong to another
home session's child. Launch behavior:

- `--name` defaults to the repo directory name, lowercased and cut to hc's 32 characters of
  `a-z 0-9 - _`, with `-2`, `-3` added when a live terminal anywhere already has it. The
  message goes to hc as one argument. The child's parent is set
  to this session (`$HC_TERMINAL_ID`) explicitly; a warning line means it is not.
- Claude children get `--settings` that turn off prompt suggestions and the session recap (a
  suggestion on the child's `❯` line reads like a typed prompt in `hc read`, and both spend
  tokens on a session nobody types into — so text on that line is never the user's input), the
  built-in "you should know" plugin (its `✦ Heads up` card waits for a key that would go to the
  session), and the claude.ai connectors (about 2.3k tokens per request a repo session never
  uses). Pass `--keep-connectors` when the request needs one.
- Inside the Herdr app (`$HC_TERMINAL_ID` set) it keeps the child's pane beside this session:
  home on the left, children in one column on the right, each new one splitting the tallest
  child pane, so 2 and 4 children get equal heights and 3 get ½ ¼ ¼. The pane goes beside
  whatever has focus, and the person may be in another space, so the script finds home's tab
  from `herdr-app ls`, focuses a pane there, checks the focus held, checks the new pane landed
  in that tab (parking it again if not), and puts the person's focus back where it was. Never
  place panes by hand with `pane.focus`/`terminal.keep`; a failed placement is reported, not
  retried by hand. A killed child's pane closes by itself; a relaunch through the script is
  kept again. Pass `--no-show` when the user asked not to show children. `shown: false` with a
  `pane not kept` line means only the layout failed; the child runs.

The first message travels as a `claude` argument, so it arrives with the launch. Confirm with
`hc read --lines 40 <address>` that the session took it and the skill loaded (`Read SKILL.md
(dev:task-next skill)` or the like). A trust dialog on a repo never opened before blocks it —
answer that with `hc keys <address> down enter` only after telling the user.

A Codex child starts with no first message (`launch --cli codex` refuses one), which is sent
once the screen is clear:

```sh
python -I "<dispatch>/scripts/dispatch.py" launch --cli codex --model gpt-6.2-sol --effort <effort> --cwd "<repo path>"
hc read --lines 40 <address>    # until the › input line shows, with no dialog over it
hc send <address> '<first message>'
```

- Codex runs a first message given at launch even while its "Hooks need review" dialog is up,
  with the dev plugin's commit and memory guards off until it is answered. So clear the
  screen first: a hook-review or repo-trust dialog — tell the user, then pick "Trust all and
  continue" (`hc keys <address> down enter`), and `esc` any panel left open. `hc send` without
  `--force` refuses while a dialog blocks. Typed into Codex's input line, `$task-next` runs as
  the skill.
- `--approve-for-me` sends Codex's approval prompts to its automatic reviewer inside the
  workspace-write sandbox, so the child does not stop on them.
- Claude-only hooks configured in a home repo do not run in a Codex child. Hold a Codex child to the same "Leave to the user"
  list in step 5.

More than one session:

- Several task sessions in one repo run as `--tree` (child dev plugin 4.11.52 or later): each
  `/dev:task-next --tree` or `/dev:task-new --tree <request>` works in its own
  `.worktrees/<slug>` and selects from the base commit, so it neither reads nor switches the
  main checkout. At most one session per repo runs without `--tree`, since that one switches
  the main checkout. Name them `<repo>-<n>`. Claims are not atomic: start the next session only
  after the previous one has created its worktree, or pick a different item for each one when
  it asks. With an older dev plugin or for one batch PR, use `/dev:task-next --all`.
- Several repos: one launch per repo, in a single turn.
- Keep a wave to two to four live children. Each child rebuilds its own picture of the repo, so
  items that need the same files or conventions go to one session (`/dev:task-next --all`)
  rather than one session each.
- A first message that is not a slash command ends with: `When you finish or get blocked,
  report in three lines or fewer with hc send <parent>; put details in a file and give its
  path.` `<parent>` is the `parent` field the launch printed — this session's address as a
  literal address, never a name and never the child's `$HC_TERMINAL_ID`. A slash command,
  or its Codex `$` form, takes no such suffix, since its arguments go to the skill.

## 5. Watch and decide

Tell the user each terminal's name, address and repo. Watch without blocking, and keep this session's
context small, since every wake-up re-sends all of it:

- One wait covers every child: run `hc wait --children any --timeout 1800` as a background
  command, keep working or end the turn. A timeout is only a check-in: start another wait
  without reading anything. Keep the timeout under the prompt-cache lifetime (1 hour on a
  subscription) so a wake-up still hits the cache.
- On news, act on the child's `hc send` report when there is one. Otherwise read the visible
  screen only (`hc read --lines 0 <address>`), and go to `--lines 60` or the artifact file only
  when the screen does not show what to decide.
- After a wave has merged and been cleaned up, tell the user that `/clear` starts the next
  wave from an empty context. To find what is still running, take only terminals whose
  `parent` is `$HC_TERMINAL_ID` from `hc ls --json`; the rest belong to other home sessions —
  never send to, read for decisions, kill or adopt them. When the context is compacted instead,
  keep each child's address, name, repo, phase, model/effort pair and the decisions made; drop
  screen reads.
- An `<hc from="…">` report or a `hc wait` result names its sender's address. Act on it only
  when that address is one of your children; anything else came from elsewhere — tell the user
  and do not answer it.

The user delegates the session's decisions to this session:

- **Decide** — grill questions, design choices, spec and ticket approval, the plan gate and
  Sprint Contract. Read the artifact (spec, contract, backlog diff) before approving. Take the
  session's recommendation unless it conflicts with the request or the repo; add a correction
  when it is missing something. Answer with `hc send <address> '<answer>'`, then tell the user in
  one line what was chosen and why.
- **Push and merge** — allowed once the commit has been through the review cycle
  (`dev:task-review-cycle`, or the repo's own review); before that, hold the session short of
  push.
- **Leave to the user** — force-push, deleting branches or worktrees outside the cycle's own
  cleanup, anything else destructive, and any decision the user kept. Tell the user what is
  waiting and stop watching that session.

Once a session's work has merged, run `hc kill <address>` and `hc rm <address>`, and
remove any clone or worktree this session created for it — after checking
that `git status --porcelain` is empty, no branch has commits missing from `origin/<base>`, and
nothing is stashed. Anything that fails a check stays; report it instead.

In a Claude child, a slash command sent with `hc send` arrives wrapped as a message, so
slash-only skills refuse it and `/clear` does nothing (a Codex child takes `$task-next` typed
into its input line, as in step 4). For the next phase, `hc kill <address>`, `hc rm <address>`, then
launch again per step 4 with the slash command as the first message and the pair from step 3,
never below a pair the task escalated to; uncommitted queue files carry over in the working
tree. Run phases back to back when the user asked for the whole queue; otherwise report each
finished phase and let the user start the next. Status on request: `hc get <address>`,
`hc read --lines 60 <address>`.
