# Legacy GitHub queues

## Preview

The inventory uses the running environment's queue override. For a project with its own
environment, run the check in that environment with `--project`.

For each `legacy-backlog` finding, include the repo path, each steering line and its proposed
replacement in the Step 6 report. Preserve any independent instructions on the same lines.
Show the proposed steering changes as a diff. When deletion is proposed, show a diff from the
current `backlog.md` to an absent file, including for an untracked backlog.

If the check calls for a dry run, run the migration tool in that mode and show its plan.

```bash
SKILL_DIR="<absolute parent directory of harness-curate/SKILL.md>"
python3 "$SKILL_DIR/../task-next/scripts/migrate_backlog.py" --repo "/abs/path/to/repo" --keep-file
```

When `backlog-history` also refers to these lines, use the migration plan as the first action.

## Apply on approval

Ask the user to confirm the repository and each proposed effect. The preview covers filing issues
and pruning migrated lines, deleting the file, or editing steering.

- For an approved migration, add `--apply --expect-plan <fingerprint from the dry run>` to the
  same command. If the fingerprint changes or a migration needs a retry, show the new plan and
  confirm it before applying. Check the apply report for kept, refused or incomplete items.
- Leave unresolved items in place and rerun the check. If it now proposes deleting a
  remaining file, show the new deletion diff and get confirmation before deleting.
- Apply only the approved steering edits and check that they point at GitHub issues labeled
  `task-queue`. Rerun the check and report unresolved findings.
