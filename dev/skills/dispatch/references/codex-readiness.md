# Codex readiness

## Before a Codex wave

A Codex startup that updates a kadragon plugin invalidates running Codex children's hook
approval. Before starting one while another is mid-cycle, fetch agent-toolkit, then compare each
plugin's version in `origin/main` with `~/.codex/plugins/cache/kadragon/<plugin>/<version>`.
Launch only if the fetch succeeds and all versions match; otherwise wait and prepare the wave as below.
Treat a live agent-toolkit child that may merge as a mismatch.
If a wave needs multiple Codex children, launch all of them idle (omit `--task`), then
send tasks with `dispatch.py send --run <receipt> -- <address> '<first message>'`.

When the dev plugin version may have changed, such as after an agent-toolkit merge, wait for
active Codex cycles to finish, then prepare the wave:

1. Start an idle Codex child and wait for the plugin update at startup. Close the child.
2. Start a second idle Codex child. Use **Review hooks** in the startup dialog, or `/hooks`
   if the dialog is absent. Verify that the required hooks are trusted and active, then close the child.
3. Launch the task children once both warm-up children are closed.

Close an idle warm-up with `dispatch.py collect <receipt> --close --force` after verifying that
it is the idle child started for this preparation.

Before a long wave, run `codex plugin marketplace upgrade` and then the warm-up above, so no
startup during the wave finds a newer plugin to install.

## Plugin update during a wave

Any Codex startup outside the wave can update a kadragon plugin and delete the old version
directory. Live children keep pointing at it: every tool call prints `• Hook failed … os error 2`
and the session continues without its guards.

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

Retry with `dispatch.py send --run <receipt> -- <address> '<first message>'` only with the hooks
approved and the composer clear. If the source cannot be verified, approval is unavailable, or
a warning remains, report the blocker and withhold the task. For an unconfirmed send, inspect
whether the task already started before retrying.

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
