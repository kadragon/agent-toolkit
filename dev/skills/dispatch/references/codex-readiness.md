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
3. Start the task children idle with the same `--wave`. Use `send --run <child receipt>`
   for each task. Launch never accepts `--trust-hooks` with a wave. A warning, a changed or
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

## Hook trust at launch

On the shared cache, Herdr's `dispatch.py launch --trust-hooks` passes `--dangerously-bypass-hook-trust` to Codex
with or without `--task`. Check `codex --help` for support (verified on Codex CLI 0.172.0).
Verify the enabled hook sources and commands and get explicit authorization for the bypass.
The flag runs enabled hooks without requiring persisted trust for this process and does not
save approval. Repository trust, hook failures, plugin cache checks and delivery checks still apply.
On the first send for a verified opt-in receipt, dispatch opens a single warning with F2.
It closes the viewer with Esc only when the sole Startup page contains the exact native
hook-trust bypass notice. It then rechecks the composer and waits for the terminal to be idle
before sending. Other warnings still require manual review.
Omit `--trust-hooks` to use the manual review below.

## Before a shared-cache Codex wave

Install and enable `guard@kadragon` when updating from a dev release that bundled its hooks. Approve its hooks
once in an idle Codex child. Codex fingerprints the full `guard` bundle, so a new guard release
requires review. A dev-only or prod-only release preserves the guard approval.

Before starting a shared-cache child while another is mid-cycle, fetch agent-toolkit and
compare the plugin versions in `origin/main` with
`~/.codex/plugins/cache/kadragon/<plugin>/<version>`. A changed version can remove files
that a running session still uses. Launch only after the fetch succeeds and all versions
match. Treat a live agent-toolkit child that may merge as a mismatch.
If a wave needs multiple Codex children, launch all of them idle (omit `--task`), then
send tasks with `dispatch.py send --run <receipt> -- <address> '<first message>'`.

When a plugin version may have changed, wait for active Codex cycles to finish, then prepare the wave:

1. Start an idle Codex child and wait for the plugin update at startup. Close the child.
2. After installing or updating guard, start a second idle Codex child if a task child will
   rely on persisted trust. Use **Review hooks** in the startup dialog or `/hooks` to check
   that the guard hooks are trusted and active, then close the child.
3. Launch the task children once the warm-up children are closed. Pass `--trust-hooks` at
   launch for each child authorized to use it.

Close an idle warm-up with `dispatch.py collect <receipt> --close --force` after verifying that
it is the idle child started for this preparation.

Before a long wave, run `codex plugin marketplace upgrade` and then the warm-up above, so no
startup during the wave finds a newer plugin to install.

## Plugin update during a shared-cache wave

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
withhold the task. For an unconfirmed send, inspect whether the task already started before retrying.

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
