---
name: harness-capture
description: >-
  Retrospect on the CURRENT conversation — route any reusable lesson to docs/,
  auto-memory, or CLAUDE.md/AGENTS.md, and tidy the auto-memory store. Also the
  pre-merge retrospect in task-review. Cross-session mining → harness-curate.
version: 2.1.5
---

# Capture Learnings — on-demand session retrospective

Invoked manually when you want to check whether the work just done contains a
reusable lesson worth persisting. It does **not** fire on its own — that was the
old `self-improve-nudge` hook, retired because auto-surfacing interrupted tasks
mid-flow and polluted context.

Because you are **already inside the session**, reflect on the conversation
directly from your own context. There is no transcript to parse and no signal
threshold to compute — the old hook needed those only to decide whether to fire
automatically on a too-short session. Here the user made that call by invoking
the skill; your job is the reflection and the write-back decision.

Distinct from `harness-curate`: this is the **warm path** — this one session,
reflected on now. `harness-curate` is the **cold path** — cross-session /
cross-project transcript mining that routes to creators/optimizers. Use that one
for "what should I build across all my work"; use this one for "did I just learn
something worth saving?"

## When to use

- The user asks to reflect on / capture learnings from the current session.
- You just finished a non-trivial task and want to decide if a lesson is durable.
- The user asks to tidy the auto-memory store (dedup, prune stale entries, fix
  the index) — jump straight to **Memory hygiene** below.

Do **not** use for cross-project audits, unused-skill cleanup, or building a
specific named asset — route those to `harness-curate` / `skill-creator`.

## How to run

1. **Reflect** on this conversation. Look for the three kinds of signal the old
   hook detected mechanically — now judged qualitatively:

   - **Reusable workflow** — a multi-step procedure you'd repeat across sessions.
   - **Error → recovery** — something broke and the fix revealed a durable
     setup/infra gotcha or an approach correction.
   - **User correction** — the user redirected your approach, preference, or style.

2. Apply the **§Harness ratchet write-back gate**. Capture a lesson **only** if all
   three hold:

   - **Reusable** across sessions — a one-off of this task is noise.
   - **Objectively checked** this session (test / exit-0 / verifier) — a hunch that
     "felt right" does not qualify.
   - **Not a no-op** — it changes behavior versus what the agent does by default.
     An instruction the model already obeys pays load to say nothing. The test is
     model-relative, so two people disagreeing about a no-op are disagreeing about
     the default and settle it by running the delta, not by debate. A candidate
     that fails this is dropped whole, not trimmed down to a shorter no-op.

   Then route by kind — and let the destination's **load** set how high the bar
   sits. Always-loaded text spends tokens and attention every turn whether or not
   it fires; pointer-gated text spends only its pointer line, and that line's
   wording is what decides whether the material is ever reached:

   | Kind | If durable → | Load it pays |
   |------|--------------|--------------|
   | Reusable workflow | → `skill-creator` (new or improved skill); one-off → pass | Pointer-gated — the `description:` line is the whole standing cost |
   | Setup/infra fix | → `docs/<topic>.md` in the owning repo | Pointer-gated — the docs-index row is the whole standing cost |
   | Approach correction / preference | → auto-memory (see **Writing to auto-memory**), or an instruction-file delta: `CLAUDE.md` (Claude Code) / `AGENTS.md` (Codex) | Auto-memory: recall-gated. Instruction file: **every turn** — the highest bar in the table. Prefer memory unless the fact must be in context before anything asks for it |
   | Workflow misunderstanding | → `skill-creator` improvement to the relevant skill | Pointer-gated |

   Whatever the route, the write proposal names in one line **the concrete
   failure this write-back prevents** ("without this: X happens again") — the
   warm-path form of the loop contract's prediction field (`dev:harness-init` →
   `references/harness-evolution.md` §3). For auto-memory the line also lands in
   the memory body (see **Writing to auto-memory** step 4); for `docs/` or
   instruction-file deltas it stays in the proposal/commit context.

3. If nothing clears the gate, say so in one line and stop — **do not manufacture
   a lesson**. Nothing to capture is the correct outcome for most sessions.

## Writing the delta

The gate decides *whether* and the table decides *where*; these rules decide *how
the line reads* once it lands. The first binds every route. The second and third
bind the **pointer-shaped** routes only — a `MEMORY.md` hook, a docs-index row, a
skill `description:` — because both are about what makes material get reached; a
memory body, a `docs/` page and an instruction-file line are already in hand when
they are read.

- **State the positive target** (every route). Steering by prohibition drags the
  forbidden behavior into context and makes it more available: *don't think of an
  elephant*. Write the behavior you want ("quote the rule verbatim"), not the one
  you don't. A prohibition earns its place only as a hard guardrail that cannot be
  phrased positively — and even then, pair it with the positive target.
- **Front-load the leading word** (pointers). A pointer's first words do its
  triggering work, and the strongest opener is a **leading word** — a compact
  concept the model already thinks with, such as *tight*, *red*, *seam*, *fog*.
  One such word beats a clause describing it, and repeating the same word across
  the prompt, the doc and the code is what makes the agent link them.
- **One trigger per branch** (pointers). A branch is a distinct case the material
  handles. Synonyms that rename a single branch are one branch written twice,
  paying load for no extra reach.

**Portability.** The three rules above are self-contained and are the whole
contract wherever this skill runs. One repo carries a longer treatment of the same
levers — agent-toolkit's `docs/writing-for-agents.md` — so reach for it when that
file is present, and rely on the rules alone when it is not.

## Cycle-tail mode (invoked from task-review Step 4.5)

When `task-review` calls this skill just before merge, you are on a feature
branch with an open PR — so repo write-backs are *welcome* here (they ride into
the PR and CI validates them), provided you keep them **light and in-scope**:

- Preference / correction → auto-memory (Claude Code) or `AGENTS.md` (Codex) —
  see the platform note under **Writing to auto-memory**; both live where the
  runtime can read them back.
- Small doc or gotcha directly tied to this change → inline edit to
  `docs/*.md` / `AGENTS.md` / `CLAUDE.md`; it merges with the PR.
- Anything heavy — a new skill, a skill overhaul, a multi-file doc rewrite —
  does **not** belong in this PR. Record it to `backlog.md` as a follow-up, the
  same channel out-of-scope review findings use. Inlining it would balloon the
  PR and, for a skill, force a mid-cycle version re-bump.

**Under `--auto` (the non-interactive path `task-review` uses):** do not
pause for the per-write veto or hygiene approval described below — the open PR's
review and CI are the safety net. Write the light memory/doc delta directly, and
for any *destructive* memory prune (deleting an entry) defer it to `backlog.md`
rather than blocking, so the review cycle's `--auto` guarantee holds.

Signal-gated: if the cycle surfaced no correction, gotcha, or reusable workflow,
there is no write-back — say so in one line and let the merge proceed.

## Writing to auto-memory

**Platform note:** auto-memory — the `# Memory` store plus its `MEMORY.md` index
— is a **Claude Code** mechanism. If your runtime doesn't provide it (e.g. Codex,
which has no auto-memory store), route the same preference/correction to the
instruction file (`AGENTS.md`) instead; the dedup, minimality, and
show-before-write rules below apply identically to that edit, and the **Memory
hygiene** pass simply doesn't run (there's no store to tidy).

When step 2 routes a lesson to auto-memory, don't just append a fresh file — a
memory store that accumulates near-duplicates decays the same way a bloated
CLAUDE.md does: the signal drowns. Follow the schema in the **# Memory** section
of your instructions (frontmatter, one fact per file, `MEMORY.md` index line),
and before writing:

1. **Read the index first.** Open `MEMORY.md` and scan the one-line hooks for an
   entry that already covers this fact — or an adjacent one it belongs with.
2. **Update over create.** If an existing file covers the same ground, edit that
   file (sharpen it, add the new nuance) instead of minting a duplicate. Two
   files saying almost the same thing is the failure mode to avoid.
3. **Earn the entry.** A memory must be reusable across sessions and non-obvious
   from the repo. Skip anything the code, git history, or an existing doc already
   records, and skip one-off fixes unlikely to recur — those are noise, not
   signal. (Same minimality bar `claude-md-improver` applies to CLAUDE.md.)
4. **Show the write before applying.** State which file you'll create or edit and
   quote the fact (a short diff/block, phrased per **Writing the delta**), so the
   user can veto before it lands —
   then write, and add/refresh the one-line `MEMORY.md` pointer in the same pass.
   Include the failure-this-prevents line (How-to-run step 2) in the memory
   body itself: it is what lets a later hygiene pass judge whether the memory
   earned its keep instead of guessing. Body line only — no frontmatter or
   schema change.
5. **Opportunistic hygiene.** While you're in the store, if you notice a stale or
   contradicted neighbour, flag it and run **Memory hygiene** on it rather than
   leaving rot next to the fresh entry.

## Memory hygiene

Auto-memory is a persistent store, and stores collect **sediment** — stale layers
that settle because adding feels safe and removing feels risky. Facts go stale, the
same lesson gets written twice under different names, and the `MEMORY.md` index
drifts out of sync with the files it points at. Run this pass whenever you write a new
memory (on the neighbours you touched) or when the user asks to tidy memory (over
the whole store). It mirrors `claude-md-improver`'s **audit → report → targeted
diff → approval** flow — never bulk-delete silently.

1. **Inventory.** List the memory directory and read `MEMORY.md`. For a full
   tidy, read each memory file; for the opportunistic case, just the neighbours.
2. **Flag against these red flags** (borrowed from `claude-md-improver`):

   | Red flag | What to check |
   |----------|---------------|
   | **Stale** | References a file, flag, skill, or path that no longer exists — verify with a quick read/grep before flagging. |
   | **Wrong** | Contradicted by what actually happened this session. A memory reflects what was true when written; if the session disproved it, it's rot. |
   | **Redundant** | Two files cover the same fact — merge into the sharper one. |
   | **Index drift** | `MEMORY.md` pointer with no file, or a file with no pointer, or a hook that no longer matches its file's content. |
   | **Bloat** | Entry restates something the repo/docs/git already record, or was a one-off that never recurred. |
   | **No-op** | Entry describes what the agent does by default anyway — true but inert. Same test as the write-back gate: does it change behavior versus the default? |

3. **Report, then apply on approval.** Present the findings compactly — file,
   which red flag, proposed action (delete / merge / rewrite / fix index) — and
   show the concrete edit for each. Apply only what the user approves. Deleting a
   memory is cheap to redo but the user may know it's still load-bearing, so
   confirm rather than assume.
4. **Leave the index consistent.** After any change, `MEMORY.md` must have exactly
   one line per surviving memory file and none for deleted ones.

If the store is already clean, say so in one line — nothing to tidy is fine here too.

**Boundary with `harness-curate`.** Deciding that a repo-scoped fact should move *out* of
memory into the owning repo's `docs/` is `harness-curate`'s call, not this skill's — it needs
cross-session evidence and the repo's own doc layout, which the warm path does not have. When
curate routes such a promotion here, it has already written `docs/<topic>.md`; this skill
executes the deletion and index repair under step 3's confirm-then-apply flow. Everything
above — stale, wrong, redundant, index drift, bloat, no-op — stays this skill's, from either
path.
