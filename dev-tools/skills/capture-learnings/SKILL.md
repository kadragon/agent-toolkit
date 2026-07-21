---
name: capture-learnings
description: >-
  On-demand check of the CURRENT session for reusable lessons worth persisting.
  Scans this project's active transcript for three objective capture signals —
  complex-task (≥10 action calls), error→recovery, user-correction — then applies
  the §Harness ratchet write-back gate to decide what (if anything) to save to
  docs/, auto-memory, or CLAUDE.md. Manual replacement for the retired
  self-improve-nudge hook, which surfaced automatically and broke flow. Trigger:
  "capture learnings", "self 갱신", "이번 세션 배운 점 정리", "회고", "reflect on this
  session", "should I save anything from this session". NOT for cross-session /
  cross-project asset mining or skill/agent/hook proposals (→ harness-curator).
  NOT for creating a specific named skill (→ skill-creator).
version: 1.0.0
---

# Capture Learnings — on-demand session retrospective

Invoked manually when you want to check whether the work just done contains a
reusable lesson worth persisting. It does **not** fire on its own — that was the
old `self-improve-nudge` hook, retired because auto-surfacing interrupted tasks
mid-flow and polluted context.

**Claude Code only.** The scan reads Claude's project-partitioned transcript
tree; Codex stores sessions in a different layout and record format, so under
Codex the script prints a notice and does nothing — use `harness-curator` there
(it parses Codex rollouts and covers cross-session mining anyway).

Distinct from `harness-curator`: this is the **warm path** — one session, three
objective signals, a quick write-back decision. `harness-curator` is the **cold
path** — cross-session/cross-project mining that routes to creators/optimizers.
Use that one for "what should I build across all my work"; use this one for "did
I just learn something worth saving?"

## When to use

- The user asks to reflect on / capture learnings from the current session.
- You just finished a non-trivial task and want to decide if a lesson is durable.

Do **not** use for cross-project audits, unused-skill cleanup, or building a
specific named asset — route those to `harness-curator` / `skill-creator`.

## How to run

1. Resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded
   this turn. Use that concrete path — do **not** infer it from a plugin-root
   environment variable (those are hook-only and absent in skill context).

2. Scan the current session:

   ```bash
   SKILL_DIR="/abs/path/to/dev-tools/skills/capture-learnings"   # parent of this SKILL.md
   python3 "$SKILL_DIR/scripts/scan_session.py"
   ```

   The script reads this project's newest Claude Code transcript (by mtime) and
   prints the detected signals (or a "nothing to capture" line). It tolerates
   Claude's project-dir case/separator drift and honors `CLAUDE_CONFIG_DIR`.
   Caveat: with two concurrent Claude sessions in the same project it scans
   whichever transcript was written most recently, which may be the other one.

3. Apply the **§Harness ratchet write-back gate** to each reported signal. Capture
   a lesson **only** if it is reusable **and** passed an objective check
   (test / exit-0 / verifier). Route by signal:

   | Signal | If durable → |
   |--------|--------------|
   | `[A]` complex-task | reusable workflow → `skill-creator`; one-off → pass |
   | `[B]` error→recovery | setup/infra fix → `docs/<topic>.md`; approach correction → auto-memory or CLAUDE.md delta; one-off → pass |
   | `[C]` user-correction | preference/style → auto-memory; workflow misunderstanding → `skill-creator` improvement; else → pass |

4. If nothing clears the gate, say so in one line and stop — **do not manufacture
   a lesson**. A no-op is the correct outcome for most sessions.
