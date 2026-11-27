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

Resolves today but answers exit 2 for every op until its read path lands; `gh` missing or
unauthenticated will be a hard error, never a `backlog.md` fallback.
