# Legacy GitHub queues

## Preview

For each `legacy-backlog` finding, include the repo path, each steering line and its proposed
replacement in the Step 6 report. Preserve any independent instructions on the same lines.
Show the proposed steering changes as a diff. When deletion is proposed, show a diff from the
current `backlog.md` to an absent file, including for an untracked backlog.

If open items remain, run the migration tool in dry-run mode and show its plan.

```bash
SKILL_DIR="<absolute parent directory of harness-curate/SKILL.md>"
python3 "$SKILL_DIR/../task-next/scripts/migrate_backlog.py" --repo "/abs/path/to/repo"
```

When `backlog-history` also refers to these lines, use the migration plan as the first action.

## Apply on approval

Ask the user to confirm the repository and each proposed effect. The preview covers filing issues
and pruning migrated lines, deleting the file, or editing steering.

- For an approved migration, run the same command with `--apply --keep-file`. Refresh the
  preview and approval if the backlog or target repository changes. Check the apply report for
  kept or refused items and rerun the contract check.
- Leave unresolved open or in-flight items in place. If the check now proposes deleting a
  remaining file, show the new deletion diff and get confirmation before deleting.
- Apply only the approved steering edits and check that they point at GitHub issues labeled
  `task-queue`. Rerun the check and report unresolved findings.
