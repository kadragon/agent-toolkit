# Queue backend contract (version 1)

Every queue read or write goes through `../scripts/queue_backend.py`; callers never parse
`backlog.md` or call an issue tracker for queue data directly. Design record:
`docs/design/github-issues-queue.md` in the agent-toolkit repo.

## Invocation

```bash
QB="<absolute directory of this file>/../scripts/queue_backend.py"
printf '%s' '{"contract": 1, "repo": "/abs/toplevel", "full_scan": false, "parked": false}' \
  | python3 "$QB" list
```

`<op>` is the only argument; one JSON object on stdin, one JSON object on stdout, diagnostics on
stderr. Every request carries `"contract": 1` and `"repo"` (the absolute repo toplevel).

| Exit | Meaning | Caller action |
|------|---------|---------------|
| 0 | ok — stdout holds the response | use it |
| 2 | op unsupported by the resolved backend | report the item and the requested action for the user to do by hand |
| 1 | error (bad request, unreadable queue, backend failure) | stop and relay stderr |

## Backend resolution

First match wins:

1. `AGENT_QUEUE_BACKEND` — `backlog`, `github`, or an adapter command line (shell-split; on
   Windows backslashes stay literal).
2. `origin` host `github.com` → `github`, **unless `backlog.md` has an open `- [ ]` item**
   (parked ones included); such a repo stays on `backlog` until its file queue is empty. For a
   `list` with `ref`, the check reads `backlog.md` as committed at `ref`. An unreadable (not
   absent) `backlog.md` is an error, never a switch to `github`.
3. `${XDG_CONFIG_HOME:-~/.config}/agent-toolkit/queue-backends.json`, keyed by `origin` host:
   `{"hosts": {"git.example.org": ["python3", "/abs/path/adapter.py"]}}` → that command.
4. `backlog`.

An adapter is run as `<command...> <op>` with the request on stdin; its stdout, stderr and exit
code (0 / 2, anything else → 1) pass through. Stdout on exit 0 must be one JSON object.

## Ops

| Op | Required | Input | Output |
|----|----------|-------|--------|
| `describe` | yes | — | `backend`, `contract`, `visibility` (`public`/`private`/`unknown`), `ops`, `close_ref_template` |
| `list` | yes | `full_scan`, `parked`, optional `ref` (read the queue as committed at that rev), `tasks` (path) | `candidates[]`, `parked[]`, `claimed[]`, `warnings[]` |
| `show` | yes | `ref`, optional `rev` (`backlog`: the `rev` a `list` returned) | `ref`, `title`, `body`, `labels`, `blocked_by[]`, `parent`, `url` |
| `create` | yes | `items[]`: `key`, `title`, `body`, `labels`, `parent_key`, `blocked_by[]` | `created[]` (`key`, `ref`, `url`, `reused`), `incomplete[]` |
| `rejected` | yes | optional `rev` | `entries[]`: `ref`, `title`, `reason`, `refile_bar` |
| `reject` | no | `ref`, `reason`, `refile_bar` | `ref` |
| `defer` | no | `ref`, `reason` | `ref` |

`candidates[]` entries: `id`, `ref`, `title`, `tag`, `labels`, `items[]`, `url`, and `counts`
(`open`/`deferred`/`blocked`), in selection order. `parked[]`: `ref`, `kind`
(`blocked`/`deferred`), `payload`. `claimed[]`: `ref`, `by` (the worktree holding it). A
`backlog` `list` also returns `rev`: the commit SHA its `ref` resolved to, or `null`.

Forge constraints the contract keeps: a claim needs no remote write, closing happens through the
PR/commit closing keyword (`close_ref_template`), and no required op removes a label or edits an
existing item.

## Built-in `backlog` backend

- `describe`: `visibility` `unknown`, `close_ref_template` `null` (closure is the cycle's
  `prune-backlog` plus the `CHANGELOG.md` entry), `ops` without `reject`/`defer` (exit 2).
- `list` runs `backlog_candidates.py --json --counts` (plus `--full-scan`, `--ref`, `--tasks`)
  and maps each row: `ref` = `id` = `<source>:<line>` (`backlog.md:14`, `tasks.md:1`), `title` =
  heading, `items[]` = the group's open, unparked, unclaimed item texts in document order
  (tokenizer-folded: wrapped lines joined, checkbox prefix dropped), `tag` = the `[TYPE]` every
  listed item shares (else `""`), `labels` = `[]`, `url` = `""`, `counts` from `--counts`. A
  `tasks.md` h1 sprint block carries `items: []`. `parked[]` comes from `--parked --json`, one
  entry per marker; `claimed[]` from the same `.worktrees/` claim scans (items and sprint
  blocks); `warnings[]` is the script's stderr (claim skips, truncation, zero-candidate
  diagnosis, fence warnings).
- `list` pins `ref` to one SHA for every read; on the working tree, a queue that changes between
  its reads fails with exit 1 (retry) rather than pairing one group's title with another's items.
- `show` takes `backlog.md:<line>` or `tasks.md:<line>` naming a heading or a checkbox item.
  Line numbers are those of the queue `list` read: pass `list`'s `rev` back as `rev` when it
  listed with `ref`. A heading gives its region as `body` (a `tasks.md` h1 runs to the next h1) and the nearest enclosing heading as `parent`; an item
  gives its raw lines as `body`, its text without markers as `title`, its
  `*(blocked by: …)*` payloads as `blocked_by`, and its heading as `parent`.
- `create` answers `{"edit_file": "backlog.md"}`: the caller writes the item by hand with the
  existing templates (`harness-init/references/backlog-template.md`).
- `rejected` reads the plain bullets under `## Rejected — do not re-file`
  (`- **<title>** — <reason>. Re-file only with <bar>.`) into `title` / `reason` / `refile_bar`.

## `github` backend

Reads `origin`'s `owner/name` and queries `gh api graphql`. `gh` missing or unauthenticated is a
hard error (exit 1, naming `gh auth login`), never a `backlog.md` fallback. `create`, `rejected`,
`reject` and `defer` answer exit 2 until the write path lands.

- `describe`: `visibility` from the repo's `isPrivate`, `ops` `describe`/`list`/`show`,
  `close_ref_template` `"Closes {ref}"`.
- **Trust gate.** Only open issues labelled `task-queue` **and** authored by
  `OWNER`/`MEMBER`/`COLLABORATOR` are queue items; another author's labelled issue is skipped
  with a warning. Comments are never read.
- **Refs.** `#N` for this repo, `owner/name#N` for a linked issue elsewhere.
- **Groups.** An open sub-issue of a queue issue is never a standalone candidate. A queue issue
  with open sub-issues is one candidate whose `items[]` are its eligible sub-issues' titles —
  each a same-repo queue item that is not claimed, blocked or deferred — with `item_refs[]`
  (parallel refs) and `excluded[]` (`ref`, `reason`) naming the rest. `counts` cover every open
  sub-issue. A lone issue carries itself: `items` `[title]`, `item_refs` `[ref]`. A parent with no
  eligible sub-issue is parked (`deferred` when every non-claimed one is deferred, else
  `blocked`), or left out when all are claimed. `tag` is the `[TYPE]` title prefix the items share.
- **Parking.** An open `blockedBy` issue parks it (`blocked`, payload: the open blocker refs); a
  closed blocker is ignored. Label `deferred` parks it (`deferred`, payload: its `Deferred:
  <reason>` body line).
- **Claims** (`claimed[]`, no remote write): (a) a `.worktrees/*/tasks.md` `## Covers` line naming
  `#N` (this checkout and the main worktree too when the request has `ref`); (b) an open PR in
  `closedByPullRequestsReferences`, `by` = its URL; (c) a closing keyword in a commit on the local
  default branch not yet on `origin` (`origin/HEAD`, else `origin/main`/`origin/master`;
  unresolvable → a warning, never a failed `list`).
- **Order.** Issue number ascending, `someday` last; the fast path caps at 3, `full_scan` is
  uncapped (issues have no h3/h2 kinds, so the backlog's type priority reduces to number order).
- **Paging.** Every connection selection reads (issues, labels, blockers, sub-issues, closing
  PRs) is paged up to a page limit. Hitting it sets `incomplete: true` with a warning, leaves out
  any issue read only in part, and fails with exit 1 when no candidate remains — never an empty
  queue. `ref` and `tasks` in a `list` request are ignored.
- `show` takes `#N`, refuses an issue that fails the trust gate, and returns `blocked_by` as its
  open blockers plus the issue `state`.
