# Wave retrospect

Run once per wave in the home session, after every child of the wave has finished or been
closed and before removing any receipt or telling the user to `/clear`. A wave that ends
blocked, or that you hand to the user, runs it when you stop watching. It looks for friction in
the dispatch skill itself: its `SKILL.md`, references and scripts. The target repo's code and
the children's task results are out of scope.

## Inputs

Use what this session already holds and the receipts still on disk. Do not relaunch or probe
children for it.

- This session's tool record for the wave: `dispatch.py` and `hc` commands, exits, warnings.
- Each receipt directory: `run.json`, `result.json`, `timing.json`, and `collect` output
  (`stop_reason`, review retries, `scope_decision_categories`).

Signals worth checking:

- stalls, stall probes, or `peek` needed to find out what a child was doing;
- send retries, unconfirmed sends, resends;
- relaunches and escalations;
- `hooks_broken` or `plugin_drift`;
- manual `hc keys` workarounds beyond the documented trust-dialog answer;
- held or withheld launches and deliveries;
- launcher validation errors that blocked a correct launch;
- guidance that was wrong, missing, or had to be worked around.

## Gate

Keep a candidate only if all three hold:

1. **Reusable**: a later wave would hit it again, and a change to the dispatch skill would
   prevent it. One-off environment failures, target-repo defects and child task bugs fail.
2. **Observed this session**: a receipt field, command exit or output line shows it.
   Speculation fails.
3. **Not a no-op**: it names a concrete change to a dispatch file. If existing guidance
   covers it and following that guidance worked, there is nothing to change.

Then drop candidates that an open agent-toolkit queue issue already covers (`inventory`).
Nothing usually qualifies. Report `Dispatch retrospect: nothing to file.` and continue the
close-out.

## File

File each surviving candidate without asking. The `queue-write` standing grant
(`../../task-next/references/git-authorization.md` → *Queue writes*) and the user's
2026-11-28 instruction cover it. A user's explicit `no-queue-write` for this session
skips filing; list the candidates in this session instead.

Always file into `kadragon/agent-toolkit`, even when the home repo is elsewhere. Use a local
checkout whose `origin` is that repo. Without one, shallow-clone it into a new temporary
directory and file from there. Remove the clone after `create` reports no `pending` drafts;
otherwise keep it and report its `pending_path`.

```bash
QB="<absolute task-next skill directory>/scripts/queue_backend.py"
[[ -r "$QB" ]] || { echo "Bundled script missing or unreadable: $QB" >&2; exit 1; }
TOOLKIT="<agent-toolkit checkout>"
ITEMS=$(cat <<'ITEMS_JSON'
[{"key": "dispatch-retro/<area>/<slug>", "title": "[FIX] <dispatch behavior>", "body": "<sanitized body>"}]
ITEMS_JSON
)
jq -nc --arg r "$TOOLKIT" --argjson items "$ITEMS" '{contract: 1, repo: $r, items: $items}' \
  | AGENT_QUEUE_BACKEND=github python3 "$QB" create
```

Derive the key from the dispatch behavior, never from the wave: `dispatch-retro/send/unconfirmed-paste`,
not a date or repo. The same friction in a later wave then reuses the open issue (`reused: true`).
Use the tag the fix needs (`[FIX]`, `[DOCS]`, `[HARNESS]`). Body sections:

```markdown
Source: dispatch wave retrospect (<YYYY-MM-DD>)

## Observed
<what dispatch did: subcommand, flag, receipt field, status, exit>

## Expected
<what the skill or script should have done>

## Evidence
<sanitized excerpts: subcommand and exit, receipt field names and values, CLI and plugin versions>

## Proposed change
<dispatch file and the change>
```

## Public-repo sanitization

agent-toolkit is public. Titles and bodies describe dispatch behavior only. Leave out:

- home and target repo names, owners, URLs, and branch or terminal names derived from them;
- local paths, user names and host names;
- the user's request text, assigned units, Git limit text and review transfer text;
- `repos/handoff.json` lines and other overlay or configuration content;
- organization, team and person names, and refs to issues or PRs in other repos.

Use neutral placeholders such as `<target repo>` or `<path>`. Re-read the final title and
body before `create`. Withhold any candidate whose evidence needs one of these to make
sense, and any security weakness. Describe withheld candidates to the user in this session only.

## Report

One line, such as `Dispatch retrospect: filed #612; reused #598; withheld 1.`. Then remove the
wave's receipts and continue the close-out.
