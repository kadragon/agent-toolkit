---
name: persona-debate
description: Structured debate among synthetic Korean personas to pressure-test opinion, message, product, pricing, or policy — synthesizes consensus, disagreements, minority report. Trigger: "여론", "다양한 관점", "페르소나 토론", "갑론을박", "사람들이 이걸 어떻게 생각할까", "찬반 붙여줘", focus group, or any "how would real/ordinary people react" request — even without "persona". NOT for: real survey/poll analysis, summarizing real interviews, fictional dialogue, building debate software. Korean output.
---

# Persona Debate

Surface the **spread** of how ordinary Koreans would argue about the user's
question — not one answer. Sample real personas, debate in rounds built to
defeat false consensus, synthesize honestly.

`references/debate-method.md` — round structure, anti-sycophancy/anti-caricature
levers, output template, the why. Read it before running.
`references/dataset.md` — fields + exact Korean filter literals.
All deterministic steps (sampling, depth→plan, roster) are in this skill's
`scripts/sample_personas.py` (no install, no download — queries HF parquet over
HTTP in ~2s). **`…` below means** `uv run --with duckdb python sample_personas.py`
run from the skill's `scripts/` directory — e.g. `cd <this-skill-dir>/scripts`
first, then `… plan …`.

## Flow

### 1. Propose the panel (don't pick silently — it's the user's ask)
Tell the user your plan in one short message, recommend a default, let them adjust:
- **Composition** — the honest first fork:
  - **Representative random** (unfiltered) — roughly population-accurate. Default for general-public questions.
  - **Targeted** (a WHERE filter) — default when the question implicitly concerns a specific group. Say plainly: a targeted panel no longer represents the public and raises caricature risk.
- **N + rounds + models** — get the deterministic plan: `… plan --depth simple|normal|deep` (add `--n` if the user gave a number). Returns N, whether to run Round 1, and the per-round model. **Never opus.** Classify depth yourself; the script maps it.

Validate any Korean categorical literals with `… distinct --field <name>` (or `references/dataset.md`) before filtering — guessed strings silently match zero rows.

### 2. Sample
```bash
… sample --n 6                                   # representative
… sample --n 6 --where "age BETWEEN 25 AND 39 AND province IN ('서울','경기')"   # targeted
… sample --n 6 --fields "persona,professional_persona,age,sex,province,occupation"  # trim to topic
```
Returns a JSON array. Check stderr: if matched-rows < N, the filter is too narrow — loosen it, add `--shard all` (full 1M scan, ~18s), or tell the user you're proceeding with fewer. Never debate a silently-truncated panel.

### 3. Round 0 — independent openings (parallel subagents)
Spawn the **`productivity:persona-actor`** agent (tool-less → far fewer per-spawn tokens; falls back to `general-purpose` if unavailable), one **per persona, same turn, isolated** — each sees ONLY its own persona + the question, never the others (seeing others first manufactures consensus). For each spawn:
- **Frame the role-play cleanly** (see debate-method.md) — `아래 인물이 되어 1인칭으로 답해줘…`. Do NOT tell it to "ignore inherited instructions"; that phrasing makes haiku refuse.
- **Trim the persona to the topic** (use `--fields`, or drop irrelevant narrative fields) to cut per-spawn tokens.
- Set `model` to the plan's `opening_model`.
Ask for: position, the 1–2 reasons that move *this* person (rooted in their life), confidence (low/med/high).

### 4. Round 1 — rebuttal (parallel subagents) — only if `run_round1`
Skip for shallow questions / when openings already agree (halves spawn count). Otherwise spawn a **fresh** `persona-actor` per persona (don't keep Round-0 agents alive), clean framing again, `model` = plan's `rebuttal_model`. Inject a **condensed summary** of the openings (name + one-line position + key reason), not the raw transcript. Each persona engages the strongest *opposing* argument directly and moves only if genuinely persuaded; default to skepticism. Designate one **devil's advocate** (use `devil_advocate_model` = sonnet). Stop after this round unless positions are clearly still moving.

### 5. Synthesize (you, main context)
Pipe the panel JSON through `… roster` for the makeup block + attribution, then follow the output template in debate-method.md: opinion spectrum, consensus, live disagreements, a preserved **minority report**, honest 종합. Do not flatten to one verdict. Add the identity-coupled caveat when the answer hinges on demographic identity.

## Scope & honesty
Synthetic personas modeled on census distributions — for idea-generation and stress-testing, not a substitute for real polling. Say so when it matters. Keep each persona an individual, never a demographic mascot.
