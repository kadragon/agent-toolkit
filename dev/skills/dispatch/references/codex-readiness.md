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

Codex documents [hook trust and the /hooks browser](https://learn.chatgpt.com/docs/hooks).
