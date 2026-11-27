# T3 Code backend

Used when SKILL.md → *Backend* selects T3. Steps 1–3 (repo, layout, first message, routing,
quota) are unchanged; this file replaces the `hc` commands of steps 4–5. The T3 tools are MCP
tools, so `dispatch.py` cannot call them: `dispatch.py prompt` renders the launch and the model
makes the calls.

A dispatch request counts as the user asking for a new thread: it authorizes
`t3_thread_launch` for each child dispatch launches. `delegate_task` is not used — it runs
only in the parent's own project (finding 2).

## Launch

```sh
python3 -I "<dispatch>/scripts/dispatch.py" prompt --cli <claude|codex> --model <model> --effort <effort> \
  --cwd "<repo path>" --title='<short title>' --work-kind <kind> --request='<verbatim user request>' \
  --unit='<assigned unit>' --git-limits='<verbatim Git limits>' '<first message>'
```

It applies `launch`'s handoff validation and `repos/handoff.json` lines, writes a receipt
(`run`, with `backend: "t3"`) next to the child's `result` path, and prints:

- `t3_thread_launch` — the arguments to pass as given: `title`, `modelSelection`
  (`instanceId` `claudeAgent` or `codex`, the full `model` id, and `options` as a list of
  `{id, value}` holding the routed effort under `effort` or `reasoningEffort`),
  `workspaceStrategy: {"type": "root"}`, and `message`. The message is the first message, the
  `<dispatch-handoff>` block, configured lines, a line telling the child to stop if it did not
  start in the target repo (a worktree its task skill creates from there is fine), the result-report instruction (Herdr passes it as
  `--append-system-prompt`), and a request to write `summary` as one string.
- `project_lookup` — the target repo as `workspaceRoot`. Call `t3_project_list` and take the
  project whose `workspaceRoot` is that path; none → register it with `t3_project_create`.
  Pass that id as `projectId`.

Always pass the effort: T3's defaults differ from the routing tables (Claude `sonnet` defaults to
`high`). Pass the model as the id `orchestrator_capabilities` lists for the routed tier: a full
Claude id (e.g. `claude-sonnet-5-5`) or the Codex slug for the family. `prompt` refuses a bare
alias or family name, since the local Codex cache need not match T3's list, and an effort outside
the provider's list (Claude has `ultrathink`, not `ultra`). The `fable`/`astra` ban applies.

Then record the `threadId` and `projectId` `t3_thread_launch` returned:

```sh
python3 -I "<dispatch>/scripts/dispatch.py" record "<run>" --thread-id '<threadId>' --project-id '<projectId>'
```

If the launch response is lost (timeout, restart) before `record`, do not launch again: list the
target project's threads and read the candidates for the receipt's `result` path, which only this
child's message contains, then `record` that thread.

**Confirm delivery** before the first wait, as Herdr does: `t3_thread_read` the thread and check
that the child took the message and loaded the task skill (open item 3). If it did not, interrupt
the thread and report; the user decides whether to dispatch again under Herdr.

**Worktree units.** Keep `--tree` in the first message and `workspaceStrategy` `root`: the task
skill creates and cleans its own worktree, and a T3 `worktree` strategy would nest it.

The wave limit stays at four live children (two under `both-hot`), below T3's
`maxBatchThreads` of 20. The one-task-session-per-checkout rule also stands, across both
backends and every home session: before launch, list the T3 threads for the target project, and
run `hc ls` too when Herdr is installed.

## Watch, stop, collect

- **Watch** — a top-level thread does not wake the parent. Wait with
  `t3_thread_wait(threadId, timeoutMs)` (keep the timeout under the prompt-cache lifetime) and
  read the child's messages with `t3_thread_read(threadId)`. No `task_status` loops, sleeps or
  Monitor.
- **Collect** — after a wait returns, `dispatch.py collect <run>` reads the result file for a T3
  receipt without Herdr and prints `thread_id`, `project_id`, `result` and
  `scope_decision_categories`. With no screen to read, `stop_reason` reports only silence: no
  result file, or no update to an unfinished one, for `--stall-minutes` (default 30). Then read
  the thread yourself.
- **Restart** — the receipt's `thread_id` is enough to `t3_thread_wait` or `t3_thread_read`
  the child again.
- **Stop, relaunch, escalate** — `t3_thread_interrupt(threadId)`, then a new `prompt` +
  `t3_thread_launch` per `escalation.md`. `collect --close` refuses a T3 receipt.
- **Clean up** — once the thread completed or was interrupted and you collected and saved what
  you need, call `t3_thread_organize` with action `settle` for the child. Then remove the receipt's
  `run.json`, `run.lock`, `result.json` and any `run.tmp`, then the directory if empty
  (SKILL.md → *Close the child terminal*, without the close).
- **Decide** — answer the child through the T3 thread tools instead of `hc send`; the
  decision rules in SKILL.md step 5 apply as written. Run `dispatch.py record <run> --resume`
  just before each answer: it hides the paused result from `collect` until the child writes a
  new one and restarts the stall clock, as `send --continue` does for Herdr.

Not used under T3: `launch`, `send`, Codex readiness (`codex-readiness.md`), trust keys,
`hc wait`, `hc read`.

## Findings (2026-11-27, home session with the `t3-code` MCP connected)

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

2. **Cross-repo launch — `delegate_task` no, `t3_thread_launch` yes.** `delegate_task` with
   `target.projectId` of another project was rejected (`invalid_request: A local task runs in this
   thread's project. Omit target.projectId, or pass target.environmentId ...`); without it the
   child ran in the parent's checkout, where the cwd guard stopped it with `status: blocked`.
   `t3_thread_launch` with the target `projectId`, `modelSelection` and `workspaceStrategy`
   `root` ran the child at the target repo root on its base branch. The target must be a
   registered T3 project (`t3_project_list` by `workspaceRoot`, `t3_project_create` when missing).

4. **Completion** — `t3_thread_wait` returned `status: completed`; `t3_thread_read` returns the
   child's messages. The child wrote a valid result file at the receipt's path and `collect` read
   it. A Codex child once wrote `summary` as a JSON array (PowerShell `ConvertTo-Json`), which
   `collect` rejects; the message now asks for one string, and the next child complied.
   (`delegate_task`, for the record, reports completion as a short summary message in the parent
   thread.)

5. **Restart recovery** — `threadId` alone is enough to `t3_thread_read` / `t3_thread_wait`
   again, so the receipt records `thread_id` and `project_id`.

7. **Sidebar placement** — passing `delegatedFrom` to `t3_thread_launch` did not set
   `parentThreadId` or `relationshipToParent`; the child stayed a top-level thread in the target
   project, with or without `includeSubagents`, so dispatch does not pass it. Settling is what
   clears the sidebar: `t3_thread_organize` `settle` on an MCP-launched thread returned a
   `sequence`, and `t3_thread_list` then showed `settled: true`.

## Open

3. **Skill invocation — partial.** A Codex child under T3 had the dev plugin 4.12.30 loaded and
   listed its model-invocable dev skills; `task-next` / `task-new` are user-invoked, so they were
   not listed, as expected. Whether `$task-next` / `/dev:task-*` as the first message triggers
   them under T3 (dev plugin >= 4.12.4 for `--tree`) is unverified. 2026-11-27: a Codex child
   (dev 4.12.34) ran `$task-new --tree` through the contract and edits, then stopped `blocked` at
   review hand-off: it had no Skill tool to call `task-review-cycle`.
6. **Concurrency** — not measured; `maxBatchThreads: 20` is the only data point against this
   skill's four live children per wave.

Record each answer here when verified; until then treat the matching step as unconfirmed and
read the child's thread yourself.
