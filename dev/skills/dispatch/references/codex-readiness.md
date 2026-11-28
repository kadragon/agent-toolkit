# Codex readiness

## Verified wave

Use `dispatch.py pin --repo "<agent-toolkit checkout>" --commit "<full verified commit SHA>"
--codex "<absolute native Codex executable>"`. Review the chosen commit, including the
hook manifests and the files their commands run. Each wave exports the plugins in that commit's marketplace into a uniquely named local
marketplace and installs them in a private `CODEX_HOME`. Current commits ship dev, prod, and
guard. Earlier supported commits ship dev and prod with the hooks inside dev.
A shared marketplace refresh cannot replace those files. Prepare a new wave for a later commit.
Dispatch protects the snapshot files against ordinary edits and verifies the plugin trees,
including executable scripts and skills, before each launch
and send. Codex's effective hook inventory must point at those same cached bytes.

The command prints a wave receipt, the private home and the native executable. If needed,
sign in with `codex login` using that exact executable and `CODEX_HOME` only for that process.
The private home uses file-backed credentials. Keep its path private, and leave the shared
home, settings and trust decisions intact.

1. Start the review child with the normal Codex launch fields and `--wave <wave receipt>`,
   omitting `--task`. Confirm the target directory in Codex when required.
2. In the native hook dialog, review and approve each required hook individually. Check the
   hook paths and commands in the pinned cache. Close the review child with
   `collect <child receipt> --close --force`. The restart runs SessionStart with approval.
3. Start the task children idle with the same `--wave`. Use `send-wave` for
   [reserved queue assignments](launch-handoff.md#reserved-queue-waves), or
   `send --run <child receipt>` for an individual task. Launch never accepts `--trust-hooks` with a wave. A warning, a changed or
   incomplete hook inventory, a missing snapshot, or an unverifiable Herdr process holds delivery.
4. Close each child with `collect --close` when it stops. Retain those receipts until
   `dispatch.py release <wave receipt>` removes the private home and snapshot. An uncertain
   launch or missing child receipt blocks release. Inspect the launch and confirm its terminal
   stopped before manual recovery.

The adapter uses Codex CLI 0.172.0 and its local marketplace and app-server hook inventory.
Dispatch starts the native Codex executable via Herdr's `hc connect` and `terminal.run`.
The call sets `CODEX_HOME` for the one terminal. Herdr 0.1.22 exposes this in its API on
Windows even though its `hc run` command has no `--env` option. The delivery gate requires
Herdr to identify the foreground program as that Codex executable.

The private home omits shared user configuration, instructions and personal plugins. If the
task requires those guards or settings, use the shared-cache wait unless equivalent guards
are present in the verified plugin snapshot and the private configuration preserves the policy.
The adapter holds launch and delivery when it detects additional user-level hooks, rules or
approval, sandbox, feature or shell environment settings. It also holds when Herdr cannot pass the
environment, the Codex CLI is incompatible, or the project exposes hooks outside the verified
snapshot or a hook command leads to an external entrypoint. Explicit pinned launches stay blocked in those cases. Use the shared-cache readiness
wait below separately.

Sources: [Codex local marketplaces](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli),
[native hook trust](https://learn.chatgpt.com/docs/hooks), and
[Herdr JSON-RPC](https://github.com/herdrdev/herdr-core/blob/master/schema/README.md#connecting).

## Approval checks before a wave

Dispatch's `--approve-for-me` selects workspace-write sandboxing, on-request approval and
`approvals_reviewer = "auto_review"`. Codex evaluates the proposed action and conversation
history. The command path and arguments help identify what the action does. Repository
visibility can inform the risk assessment, while the user supplies transfer authorization.
On Codex CLI 0.172.0, a generic PR review request and a Git-only handoff produced declined
Claude and agy launches. Their approval checks cited the absence of a grant covering the
data and destination. Comparable calls reached the shell with an explicit review request and
scoped approval descriptions. Those observed decisions are specific to their call context.

Queue, new and `task-review` launches carry the standing review transfer approval. The
`task-review` invocation approves sending the target repository's diff, relevant source, Sprint
Contract and `REVIEW.md` to Anthropic Claude, OpenAI Codex and Google Antigravity, so do not ask
before dispatch. Pass a separate user grant verbatim with `--review-transfer-approval`; it
replaces the standing line. When the user restricted transfers, keep the restriction in the
original request and pass `--no-standing-review-approval`. The receipt preserves the field for
the first send and any first-message retry. Git authority, public visibility and hook trust each have
their own scope. The child follows [Data-sharing policy](../../task-review-cycle/references/review-sources.md#data-sharing-policy)
for approval requests and reports a denial to the merge owner as `blocked`.

For approvals that need human review, an operator may use `approvals_reviewer = "user"` with
`approval_policy = "on-request"`, when managed policy permits. This changes who handles an
approval, while rules determine which command prefixes can run without one. With dispatch's
`--approve-for-me` still active, do not assume a user-level setting takes precedence. Verify the
effective launch configuration. Command rules match argument prefixes and run before a
matching command would prompt. Keep reviewer launchers, generic interpreters and reviewer CLIs
under the normal approval policy so each transfer can be checked in context. A replacement
auto-review policy has a broader scope than the per-task handoff and is subject to managed
requirements.

For routine commands, use the sandbox for local `git status`, `git log`, `git show`,
`git rev-parse` and reading or atomically writing the assigned result under writable `/tmp`.
For approved network reads, the operator can add a `.rules` file under an active Codex
config layer's `rules/` directory and restart the child. Use a trusted project layer for
repository-specific rules. For example:

```python
prefix_rule(pattern=["gh", "pr", ["view", "checks"], "--repo", "kadragon/agent-toolkit"], decision="allow")
```

Prefix matches allow trailing arguments, including another `--repo` flag. Enable the example
only if the permitted read commands fit that scope. Use the shown token order and set the tool's
working directory for direct calls. A rule for `gh pr checks` applies to that outer invocation.
Run `git fetch origin` through normal approval. A fetch prefix would allow trailing refspecs
that update local branches. Keep `git push`, PR writes and generic shell or filesystem commands
under normal approval as well.

`codex execpolicy check --rules <file> -- gh pr view --repo kadragon/agent-toolkit 541` shows the
matched rule and decision. Check the intended invocations and nearby writes such as `git push origin` and
`gh pr create` before enabling a rule. Rule matching was verified with Codex CLI 0.172.0.
A dispatched run using these rules through PR creation without routine approval requests is
unverified. Check that in the child's transcript when enabling the rules for a wave.

Sources: [Codex command rules](https://developers.openai.com/codex/rules) and
[configuration reference](https://developers.openai.com/codex/config-reference).

## Windows worktree readiness

`dispatch.py launch` sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` for Codex shell
commands. Run Bash-labeled task-cycle snippets through Git Bash on Windows. Python's
environment settings govern Python I/O. PowerShell console encoding is configured separately.

`git fetch origin` requires network access and permission to write `FETCH_HEAD` in the Git
directory. Worktree creation also writes to the shared Git directory. If a child receives
`Permission denied`, use normal approval for the affected Git command. On a machine that
allows these commands inside its sandbox, check the child's effective local Codex permissions
for the exact Git directory (`git rev-parse --path-format=absolute --git-dir --git-common-dir`).
The machine's permission policy may protect `.git` even within a writable checkout. Configure
any approved write access in the machine's Codex permission profile and confirm it from the
child. See the [Codex sandbox documentation](https://learn.chatgpt.com/docs/sandboxing).

## Hook trust at launch

On the shared cache, Herdr's `dispatch.py launch --trust-hooks` passes `--dangerously-bypass-hook-trust` to Codex
with or without `--task`. Check `codex --help` for support (verified on Codex CLI 0.172.0).
Verify the enabled hook sources and commands and get explicit authorization for the bypass.
The flag runs enabled hooks without requiring persisted trust for this process and does not
save approval. Repository trust, hook failures, plugin cache checks and delivery checks still apply.
On the first send for a verified opt-in receipt, dispatch opens the warning viewer with F2
and reads each page in order. It recognizes these native Startup notices:

- The `--dangerously-bypass-hook-trust` notice that enabled hooks may run without review.
- The `Under-development features enabled:` notice, with the feature list and the
  `suppress_unstable_features_warning = true` setting in the Codex config path. Dispatch checks
  the full message template.

Dispatch closes the viewer with Esc only after recognizing every page and finding the bypass
notice. It then rechecks the composer and waits for an idle terminal before sending. An
unrecognized page or a missing bypass notice leaves the viewer open and withholds the task
for manual review.
Omit `--trust-hooks` to use the manual review below.

## Before a shared-cache Codex wave

Install and enable `guard@kadragon` when updating from a dev release that bundled its hooks. Approve its hooks
once in an idle Codex child. Codex fingerprints the full `guard` bundle, so a new guard release
requires review. A dev-only or prod-only release preserves the guard approval.
Dispatch holds task delivery when the installed dev has moved its hooks and guard is missing
from the shared cache.

Run the preparation command from the home session and specify the trusted target directory.

```sh
python3 -I "<dispatch>/scripts/dispatch.py" prepare-codex --repo "<agent-toolkit checkout>" --cwd "<target repo>"
```

The command fetches the checkout's default remote branch, resolves its head to a full commit SHA,
and compares installed kadragon plugin versions. When the home's `[marketplaces.kadragon] ref` in
`config.toml` is not that SHA, or the versions differ, it rewrites `ref` to the SHA, upgrades the
marketplace, then starts and closes an idle Herdr child. The JSON reports `pinned` (the SHA) and
`previously_pinned` (the old SHA, or null for a home that floated).
Read `pending_hooks` in its JSON for the exact enabled hooks Codex marks untrusted or modified.
`hook_content_diffs` compares the affected kadragon plugin's hook manifest and bundled hook
files with a previously observed trusted copy in this Codex home. If native startup refresh
replaces the old cache before its trust can be inspected, the command uses the last recorded
trusted copy or reports that no trusted copy is available. Third-party pending hooks appear in `pending_hooks` with their
native source paths and review status.

If hooks need approval, launch an idle child and use **Review hooks** or `/hooks`. Close the
review child and restart so approved SessionStart hooks can run. Start the task children idle,
then use [Reserved queue waves](launch-handoff.md#reserved-queue-waves) for independent queue units
or `dispatch.py send --run <receipt> -- <address> '<first message>'` for an individual task.

Preparation and dispatch startup share a local lock scoped to the Codex home. Prepared
launches carry a Herdr label for that cache. While a labeled child is live, preparation is
held, and launches from a different home session are warned and held. Before launching a sibling,
dispatch compares the installed versions with the plugin versions at the pinned SHA. A home that
is not pinned gets a stderr warning to run `prepare-codex`, and is compared with a fresh fetch of the
remote head instead. Use an explicit Herdr parent when launching from outside a home session.
A failed check or a version mismatch holds startup. Close the wave before
preparing another one. Standalone Codex startup and dispatch versions predating the label can
still refresh the cache.

Codex 0.172.0 starts a configured-marketplace upgrade on every startup, and a new marketplace
commit force-reinstalls the plugins and deletes the previous version directories. A `ref` set to a
full commit SHA stops that: Codex resolves it without contacting the remote, and an installed
snapshot that already matches is left alone. Every wave therefore runs on a pinned home, and the
pin only moves in `prepare-codex`, between waves. `codex plugin marketplace add --ref` cannot
move an existing pin, and a `-c` override leaves `config.toml` on the old SHA so the next startup
reverts the snapshot; preparation edits `config.toml` instead. Use a [verified wave](#verified-wave)
when concurrent work needs a fixed plugin version on an unpinned home.
[Codex startup implementation](https://github.com/openai/codex/blob/rust-v0.172.0/codex-rs/core-plugins/src/manager.rs#L3139-L3181),
[marketplace config type](https://github.com/openai/codex/blob/rust-v0.172.0/codex-rs/config/src/types.rs#L1291-L1299).

## Plugin update during a shared-cache wave

On a home pinned by `prepare-codex`, a Codex startup outside the wave cannot update or delete
anything: the pin holds until the next preparation advances it. The detection below is the
fallback for a home that is not pinned (an older preparation, or a hand-edited `ref`).

A Codex startup outside the wave can update guard and delete its old version directory.
Live children can still point at that directory and report `• Hook failed … os error 2`.
A dev-only update leaves these hook entrypoints in guard in place. Before migration, the
same hook failure can occur when the older dev plugin is updated.

`launch` records the installed `~/.codex/plugins/cache/kadragon/<plugin>/<version>` for each
plugin in the receipt, and each `collect` compares it with the installed one. A change prints a
warning on stderr and adds `plugin_drift`. A removed launch-time directory, or a `• Hook failed`
event on the screen, reports `stop_reason: hooks_broken`.

On either signal, stop the child before its next Git write — a commit, push, or merge made
without hooks skips their guards. Keep the receipt and any work already produced, warm up the
new plugin as above once no other Codex cycle is mid-task, then relaunch per
[escalation.md → Relaunch](escalation.md#relaunch) after checking what the child already did.

## Readiness blockers

Read the live screen with `hc read --lines 0 <address>` before resolving a blocked send.

- **Hooks need review** — select **Review hooks** in the startup dialog. In the event list,
  select each event with pending review, then press Enter to inspect its hooks. Check the
  source and command of each new or modified hook. Press `t` to trust an individual hook you
  are authorized to approve and verify that it shows **Trusted** and is active. Use Esc to
  return to the event list and close it once review is complete.
- **Warning in the footer** — press `hc keys <address> f2` to read the warning. For hook
  warnings, close the warning view and open the local `/hooks` command from a clear composer
  with `hc keys <address> / h o o k s enter`. Review and approve as above. F2 only opens the
  warnings view. Dismiss an unrelated warning after confirming it does not affect hook trust.
- **Hook failed, blocked, or stopped** — inspect the cause before any task. For a changed-plugin warning or failure,
  if the live `/hooks` view has nothing to approve, restart the child without a task and use
  **Review hooks** at startup. Restart after approval if the failure remains on screen or if
  a SessionStart hook had already been skipped.
- **Plugin hook approval required after a send** — stop the affected child before it proceeds
  with hooks disabled. Keep its receipt, preserve any work already produced, and review the
  hooks in a fresh idle child once the other Codex cycles have finished. Check what the affected
  child already did before deciding whether to resend the task.
- **Repository trust** — tell the user before accepting a known target directory. Select
  **Yes, continue** in its own dialog and then check for hook review.

Retry with `dispatch.py send --run <receipt> -- <address> '<first message>'` once the hooks are
active, all blockers are resolved, and the composer is clear. If the source cannot be verified,
approval is unavailable during manual review, or a warning remains, report the blocker and
withhold the task. For an unconfirmed send, check for work with `dispatch.py peek <receipt>`.
If no work is visible, inspect the raw screen for the submitted prompt, drafts, or dialogs before retrying.

A send hold with a clear composer can indicate a stale installed plugin. Update it or use the current script.
If a marketplace update replaced the installed directory, run `send --run <receipt>` using
the current installed script. By default an unconfirmed receipt blocks another scripted send until
the child writes a new result or starts a turn past the one recorded at send; then `send`
accepts it as delivered. Otherwise inspect the transcript and result file first. If the task
started and its hooks are trusted, let the existing session finish. If the text is still in its
composer, confirm that it is the intended task and submit it once there. If the task never
started, the composer is clear, and the child is still on the recorded turn, use
`dispatch.py send --run <receipt> --resend -- <address> '<same message>'`.
The child must be idle or on the previous completed turn of a follow-up. A matching prompt in
the transcript blocks resend. Relaunch only after verifying that the task never started and
preserving any changes. A startup can report turn 1.
For older receipts missing the delivery phase, a resend on turn 1 requires the startup screen.

## Send recovery

- A paste left in the idle composer gets one Enter if its text matches the message or Herdr
  acknowledged sending it.
- A stray draft in an owned child's composer before its first task (turn 0, or the startup
  screen at turn 1) is cleared with `ctrl+u` — up to five presses a second apart, for a stale
  frame or several rows — and named on stderr. Any other draft is reported and the task withheld.
- A submit that left no trace — composer clear, same turn, still idle for two seconds, the task
  not echoed in the transcript — is sent once more. A paste, Enter retry, or working status seen
  after the send rules that out.
- An unconfirmed receipt is accepted as delivered once the child writes a new result. After
  Herdr acknowledges a send, a clear composer and a working or completed turn can also
  confirm it. The send checks for plugin hook approval failures for two seconds after
  delivery first appears confirmed. If the failure appears later while watching the child,
  follow the same stop and review procedure under *Readiness blockers*.

Codex documents [hook trust and the /hooks browser](https://learn.chatgpt.com/docs/hooks).
