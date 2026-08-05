# `tasks.md` sprint-block boundary — deferred decision

**Status:** analysis done, no code written. The `harness-init` minimalization work is committed on
branch `feat/init-minimal-no-agents` (it did not touch `reconcile-harness.py`), so options 4 and 5
below are no longer blocked on it — they still share that file and belong in one change.

**Reported as:** "`prune-tasks` treats a `#`-level Sprint Contract as running to EOF and deletes
all of `tasks.md`."

---

## What actually happens

`prune_h1_block` (`dev/skills/task-next/scripts/task_nodes.py:370-384`) ends the block at the next
`#` heading, or EOF:

```python
end = next((t["line"] - 1 for t in h1s if t["line"] - 1 > start), len(lines))
```

`tasks.md` is a **mixed** file: an h1 Sprint Contract plus h2/h3 finding sections
(`## Review Backlog` with h3 per-PR groups, and h2 grab-bags — see
`dev/skills/task-review/references/consolidation-guide.md:116-153` and
`dev/skills/task-next/SKILL.md:186`). Nothing at h2/h3 stops the scan, so every finding section
positioned *after* the sprint h1 is swallowed with it. If nothing survives,
`_write_or_delete` (`task_nodes.py:453-458`) calls `os.remove(path)` under `delete_if_empty=True`
and the whole file is gone.

**Verified reproduction** (run against the current script; returned `('', [])`):

```python
from task_nodes import prune_h1_block
t = """# Fix the thing

status: active

## Covers

- [ ] [FIX] a

## Review Backlog

### PR #101 — earlier PR (2026-07-01)

- [ ] [debt] leftover finding

## Grab bag

- [ ] [doc] another
"""
prune_h1_block(t, "Fix the thing")   # -> ('', [])  => CLI unlinks tasks.md
```

## The real defect: a lost invariant, not a wrong boundary

`reconcile-harness.py:179-217` `strip_sprint_block` **already survived this exact incident and was
fixed**. Its docstring records the fix and the invariant it depends on:

> This preserves unrelated open `## Review Backlog` items that previously were destroyed by an
> unconditional `TASKS.unlink()` on sprint completion.

> Ordering invariant: non-sprint content (e.g. `## Review Backlog`) MUST appear BEFORE the Sprint
> Contract `#` heading. […] Any content placed AFTER the sprint heading is therefore treated as
> part of the sprint block and removed with it.

So h1-to-EOF is the *correct* boundary — **provided the sprint h1 is last in the file**. Three
protections were built there; `task_nodes.py` (added in `ae0ce1c`, "script the deterministic
`task-*` nodes") carries none of them:

| Protection | `reconcile-harness.py` | `task_nodes.py` |
|---|---|---|
| Sprint block identification | the h1 that **owns the `status:` field** (`_sprint_heading_index`) | title string match (`:376`) |
| Ordering invariant | stated in the docstring | absent |
| Empty-result handling | `strip` remainder; keep the file if anything survives | unconditional `os.remove` (`:455`) |

And the write side never states the invariant: `dev/skills/task-next/SKILL.md:190-193` and
`dev/skills/task-new/SKILL.md:100` tell the agent to write a `#` Sprint Contract but say **nothing
about where in the file**. The invariant lives only in a docstring inside a script that neither
skill reads. An agent that appends at the top destroys the file, and no check objects.

Test coverage does not close the gap: `task_nodes.py:809-833` (Test 4) exercises only a homogeneous
h1-only file (`# Sprint one` / `# Sprint two`), and asserts `only == ""` as correct behaviour — which
makes total deletion look intended.

`prune_lines` (the stdin path, `task_nodes.py:305`) shares `delete_if_empty=True` but is much safer:
verbatim matching plus the level-aware cascade in `_region_blank` (`:255`). The defect is specific to
the `--block` path.

## Answered along the way: does the Sprint Contract need to be on disk at all?

**Conditionally — one reason survives scrutiny, not four.** Re-verified against the code
2026-08-05; the four bullets originally listed here did not hold up equally.

- **`## Covers` — the one load-bearing reason.** At pre-merge cleanup the agent pipes the Covers
  lines straight into `prune-backlog` (`task-next/SKILL.md:277-278`), and the script refuses with
  exit 1 on a non-verbatim or ambiguous match (`SKILL.md:281`). Reconstructing a backlog item's
  exact `- [ ]` text from conversation is precisely what degrades across context loss, so for a
  multi-item backlog group the on-disk list has no substitute.
- **Resume diagnosis — nice-to-have, not decisive.** `task-next/SKILL.md:388` greps
  `^status: active` and it is the only cross-context recovery signal, but its absence degrades
  gracefully into check 3's generic fallback (`SKILL.md:407`). It does not justify the file alone.
- **`reconcile-harness.py` C-1 — does not hold in the current flow.** `remove_active_markers` /
  `revert_active_markers` (`:143-172`) anchor on `[>]` lines in `backlog.md`, but `task-next`
  explicitly forbids the `[>]` flip (`SKILL.md:187`, `:193`) and post-merge verification requires
  none survive (`:317`). **No automated path produces `[>]` any more**, so in a normal cycle C-1
  emits `WARNING: no [>] lines matched anchors` and changes nothing. This is a cleanup target, not
  evidence for keeping the sprint on disk.
  - Stale doc found alongside: `harness-init/references/backlog-template.md:15` still names
    "Human on sprint start, or `task-next` skill" as the writers of `[>]`.
- **Sprint inbox — read path only.** Pre-existing `status: open` h1 blocks are an *input* source
  for `task-next` (`SKILL.md:182`), which is independent of whether the write path exists. Correct
  as originally stated.

`implementer` / `qa-verifier` briefs pass the contract inline and never read the file — that is not a
reason to keep it.

**Trimmable — and the trim is larger than first assessed.** Write the contract when `## Covers` is
needed; skip it otherwise. That covers the trivial / lite path, single-item cycles, and the
tasks.md finding-group path (which `SKILL.md:187` already declares needs no `## Covers`). Note this
is a *change*, not current behaviour: the Lite path section lists "Sprint Contract" among the
sub-steps it runs normally, and `task-new/SKILL.md:99` writes one unconditionally. Making the write
conditional also shrinks the exposure surface of the boundary defect above by construction.

## Options — decide after init-minimal

1. **State the write-position invariant in the skills.** Add to `task-next/SKILL.md:190-193` and
   `task-new/SKILL.md:100`: the Sprint Contract h1 goes at the **end** of `tasks.md`; never above an
   existing `## Review Backlog` or other top-level section. Cheapest; matches what
   `reconcile-harness.py` already assumes. Prompt-level only — nothing enforces it.
2. **Harden `prune_h1_block` to `strip_sprint_block`'s contract.** Identify the block by `status:`
   ownership rather than title, and allow `delete_if_empty` on the `--block` path only when no
   non-sprint top-level section survives. Mechanical; closes the data-loss hole even if 1 is
   violated.
3. **Regression test.** Add the mixed h1 + h2/h3 file above to `--test`. Test 4 currently cannot fail
   on this shape.
4. **Converge the two implementations.** `strip_sprint_block` and `prune_h1_block` encode the same
   contract twice, and the copies have already diverged once. One owner. `reconcile-harness.py`
   ships from `harness-init`, so this lands there.
5. **Resolve the dead `[>]` anchor path** (found while re-verifying the section above). Either
   re-anchor `reconcile-harness.py`'s C-1 on `## Covers` — which is what actually exists — or drop
   the marker machinery and correct `backlog-template.md:15`, which still claims `task-next` writes
   `[>]`. Same file as option 4; do them together.
6. **Make the Sprint Contract write conditional** on `## Covers` being needed (see the section
   above). Touches `task-next/SKILL.md` and `task-new/SKILL.md` only — independent of 1–5.

Suggested shape: **2 + 3 first** (stop the data loss, prove it), **1 alongside** (cheap, removes the
trigger), then **4 + 5 together** as one `reconcile-harness.py` change. **6** is independent and can
go whenever; doing it early shrinks how often the boundary is exercised at all.

## Open question for the decider

Is the mixed-content `tasks.md` itself worth keeping? Splitting review findings into their own file
(e.g. `review-backlog.md`) removes the boundary problem by construction, but changes the contract
across `task-review`, `security-overview`, and `harness-init` at once. Not scoped here.
