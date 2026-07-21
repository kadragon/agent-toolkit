---
name: capture-learnings
description: >-
  On-demand retrospective on the CURRENT conversation: reflect on the work just
  done, decide whether it contains a reusable lesson worth persisting, and apply
  the §Harness ratchet write-back gate to route it (docs/, auto-memory, or the
  instruction file). You are already in the session — reflect directly, no
  transcript parsing. Manual replacement for the retired self-improve-nudge hook,
  which fired automatically and broke flow. Trigger: "capture learnings", "self
  갱신", "이번 세션 배운 점 정리", "회고", "reflect on this session", "should I save
  anything from this session". NOT for cross-session / cross-project asset mining
  or skill/agent/hook proposals (→ harness-curator). NOT for creating a specific
  named skill (→ skill-creator).
version: 2.0.0
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
   | Approach correction / preference | → auto-memory, or an instruction-file delta: `CLAUDE.md` (Claude Code) / `AGENTS.md` (Codex) |
   | Workflow misunderstanding | → `skill-creator` improvement to the relevant skill |

3. If nothing clears the gate, say so in one line and stop — **do not manufacture
   a lesson**. A no-op is the correct outcome for most sessions.
