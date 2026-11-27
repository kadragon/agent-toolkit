# T3 Code backend

Used when SKILL.md → *Backend* selects T3. Steps 1–3 (repo, layout, first message, routing,
quota) are unchanged; this file replaces the `hc` commands of steps 4–5. `delegate_task` is an
MCP tool, so `dispatch.py` cannot call it: `dispatch.py prompt` renders the launch and the model
makes the call.

## Launch

```sh
python3 -I "<dispatch>/scripts/dispatch.py" prompt --cli <claude|codex> --model <model> --effort <effort> \
  --cwd "<repo path>" --title='<short title>' --work-kind <kind> --request='<verbatim user request>' \
  --unit='<assigned unit>' --git-limits='<verbatim Git limits>' '<first message>'
```

It applies `launch`'s handoff validation and `repos/handoff.json` lines, writes a receipt
(`run`, with `backend: "t3"`) next to the child's `result` path, and prints:

- `prompt` — the first message, the `<dispatch-handoff>` block, configured lines, then the
  result-report instruction. Herdr passes that instruction as `--append-system-prompt`; under T3
  it is part of the prompt body. Pass `prompt` to `delegate_task` verbatim.
- `target` — `provider` (`claudeAgent` or `codex`), `model`, and `options` holding the routed
  effort under the provider's key (`effort` for Claude, `reasoningEffort` for Codex). Always pass
  the effort: T3's defaults differ from the routing tables (Claude `sonnet` defaults to `high`).
- `cwd` — the target repo (see open item 2).

A Codex family (`luna`, `terra`, `sol`) resolves to a slug as in `launch`. Pass a Claude model
as the id `orchestrator_capabilities` lists for the routed tier (e.g. `claude-sonnet-5-5`).
The `fable`/`astra` ban applies.

Then record the task id `delegate_task` returned:

```sh
python3 -I "<dispatch>/scripts/dispatch.py" record "<run>" --task-id '<task id>'
```

**Worktree units.** Keep `--tree` in the first message and do not set `isolation: "worktree"`:
the task skill creates and cleans its own worktree, and a T3 worktree would nest it.

The wave limit stays at four live children (two under `both-hot`), below T3's
`maxBatchThreads` of 20. The one-task-session-per-checkout rule also stands; check this
session's T3 receipts instead of `hc ls`.

## Watch, stop, collect

- **Watch** — follow the delegate's own `next` guidance. T3 forbids polling: no `task_status`
  loops, sleeps or Monitor.
- **Collect** — `dispatch.py collect <run>` reads the result file for a T3 receipt without
  Herdr and prints `task_id`, `result` and `scope_decision_categories`. `stop_reason` is
  always null: there is no screen to read.
- **Stop, relaunch, escalate** — `task_cancel` the task id, then a new `prompt` +
  `delegate_task` per `escalation.md`. `collect --close` refuses a T3 receipt.
- **Decide** — answer the child through the T3 thread tools instead of `hc send`; the
  decision rules in SKILL.md step 5 apply as written.

Not used under T3: `launch`, `send`, Codex readiness (`codex-readiness.md`), trust keys,
`hc wait`, `hc read`.

## Verified (2026-11-27, home session with the `t3-code` MCP connected)

1. **`orchestrator_capabilities`** — succeeded with no arguments. The parent inherited
   `claudeAgent` / `claude-opus-5-5`, `runtimeMode: "full-access"`. Usable providers, each
   with `canRunChildTask` and `canRunCrossProviderChildTask` true:
   - `codex`: `sol`, `terra`, `luna` slugs. `reasoningEffort` low|medium|high|xhigh|max|ultra
     (`luna` has no `ultra`); defaults `sol` medium, `terra` low, `luna` medium. Also
     `serviceTier` default|priority (`terra` defaults to priority).
   - `claudeAgent`: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`. `effort`
     low|medium|high|xhigh|max|ultrathink; defaults opus medium, sonnet high, haiku medium.
     Also `ultracode` (bool); opus also `fastMode`.
   - Other providers (cursor, grok, opencode, antigravity, fx, kiro, muse, pi) are disabled.
   - `features`: appOwnedSubagents, asyncPolling, cancellation, batchThreadCreation,
     threadManagement, incrementalThreadRead, scheduledTasks, `maxBatchThreads: 20`.

   Earlier the same day the session had `T3CODE_THREAD_ID` / `T3CODE_CLI_PATH` set while the
   MCP server answered HTTP 403: a Claude `env.NO_PROXY` override sent `127.0.0.1` traffic to the
   campus proxy. Hence the branch keys on a successful call, not on the environment.

2. **Cross-repo cwd — partial.** `t3_project_list` shows agent-toolkit registered
   (`workspaceRoot: c:\dev\agent-toolkit`), so registration through MCP exists;
   `t3_project_create` / `t3_project_clone` are the registration path. Whether `delegate_task`
   accepts a cwd or project outside the parent's workspace is **open**.

## Open — verify with a real `delegate_task` run from a T3 session

3. Whether a Codex child under T3 receives `/dev:task-*` / `$task-*` as a working skill
   invocation and loads the dev plugin (>= 4.12.4 for `--tree`).
4. What `delegate_task` returns at completion (full text or summary), and whether the child can
   still write the result JSON at the receipt's `result` path.
5. How a running delegate is found again after the home session restarts, and whether the
   receipt's `task_id` is enough.
6. T3's concurrency limit against this skill's four live children per wave.

Record each answer here when verified; until then treat the matching step as unconfirmed and
check the child's thread yourself.
