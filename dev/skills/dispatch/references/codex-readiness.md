# Codex readiness

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
- **Repository trust** — tell the user before accepting a known target directory. Select
  **Yes, continue** in its own dialog and then check for hook review.

Retry the guarded `send` only with the hooks approved and the composer clear. If the source
cannot be verified, approval is unavailable, or a warning remains, report the blocker and
withhold the task. For an unconfirmed send, inspect whether the task already started before
retrying.

If a marketplace update replaced the installed directory, run `send --run <receipt>` using
the current installed script. By default an unconfirmed receipt blocks another scripted send until
the child writes a new result or starts a turn past the one recorded at send; then `send`
accepts it as delivered. Otherwise inspect the transcript and result file first. If the task started, let the existing session
finish. If the text is still in its composer, confirm that it is the intended task and submit
it once there. If the task never started, the composer is clear, and the child is still on
the recorded turn, use `dispatch.py send --run <receipt> --resend -- <address> '<same message>'`.
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
  confirm it.

Codex documents [hook trust and the /hooks browser](https://learn.chatgpt.com/docs/hooks).
