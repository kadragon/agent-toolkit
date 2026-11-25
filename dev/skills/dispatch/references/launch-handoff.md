# Home-configured handoff lines

Create a UTF-8 `repos/handoff.json` in the home repo. Map each repo path prefix to an array of
nonblank, single-line strings.

```json
{
  "~/src/team-projects": ["Use the team review checklist."]
}
```

Run `launch` from the home repo. Prefixes may be absolute, start with `~/`, or be relative to
the home repo root. The resolved child path matches a prefix by exact path or descendant.
`launch` appends all matching lines in file order after the verbatim metadata in the first Claude
or Codex message. Codex quotes lines that begin with screen markers or hook notices so they
appear as message text. Use `--dry-run` to preview the first message with Claude or Codex `--task`.

Codex receipts retain the launch-time lines for delayed delivery and first-message retries.
Verify approvals using the original user request and Git limits carried in the handoff.
