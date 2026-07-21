---
name: capture-learnings
description: >-
  Retrospective on the CURRENT conversation: decide whether the work just done
  holds a reusable lesson and route it via the §Harness ratchet gate (docs/,
  auto-memory, or CLAUDE.md/AGENTS.md). Also tidies the auto-memory store — dedup
  before writing, prune stale/redundant entries, keep MEMORY.md in sync. Also
  the pre-merge retrospect invoked by dev-review-cycle Step 4.5. Trigger:
  "capture learnings", "회고", "이번 세션 배운 점 정리", "self 갱신", "reflect on
  this session", "메모리 정리", "clean up memory". NOT for cross-session /
  cross-project mining or skill/agent/hook proposals (→ harness-curator); NOT for
  building a specific named skill (→ skill-creator).
version: 2.1.0
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

Distinct from `harness-curator`: this is the **warm path** — this one session,
reflected on now. `harness-curator` is the **cold path** — cross-session /
cross-project transcript mining that routes to creators/optimizers. Use that one
for "what should I build across all my work"; use this one for "did I just learn
something worth saving?"

## When to use

- The user asks to reflect on / capture learnings from the current session.
- You just finished a non-trivial task and want to decide if a lesson is durable.
- The user asks to tidy the auto-memory store (dedup, prune stale entries, fix
  the index) — jump straight to **Memory hygiene** below.

Do **not** use for cross-project audits, unused-skill cleanup, or building a
specific named asset — route those to `harness-curator` / `skill-creator`.

## How to run

1. **Reflect** on this conversation. Look for the three kinds of signal the old
   hook detected mechanically — now judged qualitatively:

   - **Reusable workflow** — a multi-step procedure you'd repeat across sessions.
   - **Error → recovery** — something broke and the fix revealed a durable
     setup/infra gotcha or an approach correction.
   - **User correction** — the user redirected your approach, preference, or style.

2. Apply the **§Harness ratchet write-back gate**. Capture a lesson **only** if it
   is reusable **and** passed an objective check this session (test / exit-0 /
   verifier) — a hunch that "felt right" does not qualify. Route by kind:

   | Kind | If durable → |
   |------|--------------|
   | Reusable workflow | → `skill-creator` (new or improved skill); one-off → pass |
   | Setup/infra fix | → `docs/<topic>.md` in the owning repo |
   | Approach correction / preference | → auto-memory (see **Writing to auto-memory**), or an instruction-file delta: `CLAUDE.md` (Claude Code) / `AGENTS.md` (Codex) |
   | Workflow misunderstanding | → `skill-creator` improvement to the relevant skill |

3. If nothing clears the gate, say so in one line and stop — **do not manufacture
   a lesson**. A no-op is the correct outcome for most sessions.

## Cycle-tail mode (invoked from dev-review-cycle Step 4.5)

When `dev-review-cycle` calls this skill just before merge, you are on a feature
branch with an open PR — so repo write-backs are *welcome* here (they ride into
the PR and CI validates them), provided you keep them **light and in-scope**:

- Preference / correction → auto-memory, as usual — it lives outside the repo.
- Small doc or gotcha directly tied to this change → inline edit to
  `docs/*.md` / `AGENTS.md` / `CLAUDE.md`; it merges with the PR.
- Anything heavy — a new skill, a skill overhaul, a multi-file doc rewrite —
  does **not** belong in this PR. Record it to `tasks.md` as a follow-up, the
  same channel out-of-scope review findings use. Inlining it would balloon the
  PR and, for a skill, force a mid-cycle version re-bump.

Signal-gated: if the cycle surfaced no correction, gotcha, or reusable workflow,
this is a no-op — say so in one line and let the merge proceed.

## Writing to auto-memory

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
   quote the fact (a short diff/block), so the user can veto before it lands —
   then write, and add/refresh the one-line `MEMORY.md` pointer in the same pass.
5. **Opportunistic hygiene.** While you're in the store, if you notice a stale or
   contradicted neighbour, flag it and run **Memory hygiene** on it rather than
   leaving rot next to the fresh entry.

## Memory hygiene

Auto-memory is a persistent store, and stores rot: facts go stale, the same
lesson gets written twice under different names, and the `MEMORY.md` index drifts
out of sync with the files it points at. Run this pass whenever you write a new
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

3. **Report, then apply on approval.** Present the findings compactly — file,
   which red flag, proposed action (delete / merge / rewrite / fix index) — and
   show the concrete edit for each. Apply only what the user approves. Deleting a
   memory is cheap to redo but the user may know it's still load-bearing, so
   confirm rather than assume.
4. **Leave the index consistent.** After any change, `MEMORY.md` must have exactly
   one line per surviving memory file and none for deleted ones.

If the store is already clean, say so in one line — a no-op is fine here too.
