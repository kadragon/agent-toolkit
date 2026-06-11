---
name: loop-engineer
description: >-
  Iterative quality loop for non-testable artifacts (skills, prompts, agent defs, CLAUDE.md, plans, docs) — Reflexion-style structured reflection + independent verifier. Trigger: "evaluate and improve", "loop-engineer this", "keep improving until good", "improvement cycle on this", "improve a skill iteratively", "run eval loop on this agent", "이걸 루프 돌려서 개선해줘", "퀄리티가 만족스러울 때까지 고쳐줘", "자기 개선 루프", "루프 엔지니어링", "반복 개선", "스스로 평가하고 고쳐줘". NOT: code with tests (→ orchestrate), PR review+merge (→ dev-review-cycle), new skill from scratch (→ skill-creator), transcript analysis (→ harness-curator).
version: 1.1.0
---

# Loop Engineer — iterative quality improvement without a test gate

When you can't run `pytest` or `cargo test` to know if you're done, this skill is the discipline. It structures the loop so you don't spin in place: define a rubric up front, verify with an independent agent (not self-grade), reflect structurally, improve minimally, repeat until the rubric is satisfied or progress stalls.

The canonical reference is Reflexion (Shinn et al. 2023): Actor → Evaluator → Self-Reflection → improved Actor. The key insight is that **verbal reflection stored as structured memory** beats "try again differently" because it accumulates — each round starts from a richer hypothesis, not a blank slate.

## Step 1 — Define artifact + exit criteria

Before the first iteration:

1. **Identify the artifact.** File path, inline text, or description of the thing being improved.

2. **Write a rubric.** 3–6 criteria, each with an observable signal:

   | Criterion | Signal |
   |-----------|--------|
   | Trigger accuracy | Skill fires on ≥9/10 correct cases, silent on near-misses |
   | Step ordering | Plan steps are dependency-correct; no step needs a later step's output |
   | Completeness | Covers the 3 scenarios from Step 1 without gaps |
   | Clarity | A new collaborator could follow it without reading the codebase |

   Rubric quality matters more than quantity. Vague criteria ("good quality", "well-written") are not rubric entries — they produce noise, not signal.

3. **Set an exit condition.** State it as a verifiable sentence: *"Verifier scores all 5 criteria green for two consecutive rounds"* or *"User accepts the output."*

4. **Set a loop ceiling.** Default: stop after 4 rounds of no improvement or 8 rounds total. Loops without ceilings drift; ceilings force reflection on whether the rubric itself is wrong.

5. **Open a loop ledger.** This skill's value is *accumulated structured reflection* — each round builds on the last round's hypotheses. But an 8-round loop that spawns a verifier subagent every round can hit context compaction mid-loop, which silently erases the reflections the skill depends on. So the ledger lives on disk, not in context.

   Write it to a scratch path keyed to the artifact — `/tmp/loop-engineer-<artifact-slug>.md` — not next to the artifact (it improves arbitrary files; a ledger dropped beside a `CLAUDE.md` or a plan is litter). Seed it now with the rubric, exit condition, and ceiling. Steps 3 and 5 append to it; Step 6 reads it. **Delete it on exit** (any exit — success, plateau, or ceiling). On resume after a compaction, read the ledger first to recover state instead of restarting the loop.

## Step 2 — Evaluate with an independent verifier

**Do not self-grade.** Self-preferential bias is documented — the same model that wrote the artifact will rationalize it. Spawn a verifier subagent with no context of prior iterations:

```
Verifier brief:
- Goal: score this artifact against the rubric. Be adversarial.
- Rubric: [paste rubric from Step 1]
- Artifact: [paste current version]
- Output per criterion: PASS / FAIL / PARTIAL — plus one line of evidence.
- Constraint: do not read prior iterations or prior reflections. Cold read only.
```

Aggregate the verdicts. If all criteria PASS → exit. If not → proceed to Step 3.

## Step 3 — Reflect structurally

For each FAIL or PARTIAL, append a structured reflection entry to the ledger:

```
[FINDING]: <what failed>
[ROOT_CAUSE]: <why it failed — not surface symptoms, the underlying reason>
[HYPOTHESIS]: <one concrete change that would fix it>
[CONFIDENCE]: high / medium / low
```

Do not write a long analysis. One terse entry per failing criterion. The reflection is a handoff to the next round's "improve" step — make it actionable, not retrospective.

If multiple criteria fail, prioritize: fix root causes before symptoms. Two criteria that share a root cause → one fix addresses both.

## Step 4 — Improve minimally

Apply the hypotheses from Step 3 — no more. Surgical changes only. The loop's purpose is convergence, not rewriting.

If you find yourself changing things not tied to a reflection entry, stop. That's scope creep and it resets the verifier's ability to attribute pass/fail to the change you made.

## Step 5 — Verify, then repeat or exit

Re-run the verifier from Step 2 (cold read, new subagent, same rubric). Append to the ledger:

```
Round N:
  - Changed: <list of criteria targeted>
  - Verdicts: <PASS/FAIL per criterion>
  - Delta: improved / flat / regressed
```

**Exit when:**
- All criteria PASS (exit: success)
- 2 consecutive rounds of flat delta (exit: plateau — see Step 6)
- Loop ceiling reached (exit: ceiling — escalate to user)

On any exit, delete the loop ledger (`/tmp/loop-engineer-<artifact-slug>.md`). It's scratch state for the loop, not a deliverable — leaving it behind is litter. For a plateau or ceiling exit, fold its contents into the Step 6 user report first.

## Step 6 — Handle convergence failures

If the loop exits on plateau or ceiling without full PASS:

1. **Check the rubric first.** A plateau often means the rubric is wrong, not the artifact. Read the ledger's round log: if a criterion keeps producing contradictory verdicts across rounds, it's not observable enough. Rewrite that criterion before adding more iterations.

2. **Report to user.** State: which criteria are still failing, why improvement stalled, and what decision is needed (user rewrites from scratch, weakens the rubric, or accepts current state).

3. **Do not silently accept.** A plateau is information — it means the current artifact shape can't satisfy the rubric as written. That's useful, even if it means stopping.

## Step 7 — Promote cross-session insights

If the loop surfaced a rule that would prevent the same failure pattern in future artifacts:

- **One session:** note it in context (don't write files).
- **Cross-session pattern:** promote to memory (`~/.claude/projects/.../memory/`) via the auto-memory system. Use feedback type.
- **Harness-level rule:** if this failure type appears in other skills/agents in this repo, write it into `docs/conventions.md` or `docs/eval-criteria.md` and open a PR.

Promotion is optional and deliberate — not every reflection becomes a rule. The test: *"Would a new session make the same mistake if this insight weren't encoded?"* If yes, promote.

## Prerequisites

**Requires top-level session context.** The `Agent` spawn tool is not available in subagent threads. If loop-engineer is invoked from inside a subagent (another skill, Workflow stage, etc.), the verifier step cannot run. Stop immediately and return:

> "loop-engineer requires top-level session context — no Agent tool available here. Re-invoke from the main session."

Do not substitute self-grading when the Agent tool is absent. That defeats the skill's entire purpose.

## Anti-patterns

- **Self-grading.** The model that wrote the artifact cannot neutrally evaluate it. Independent verifier, every round.
- **Rubric drift.** Weakening criteria to make the loop converge is cheating. If a criterion consistently fails, challenge the artifact, not the rubric.
- **Infinite loops.** A loop without a ceiling is a process defect. Set one before starting.
- **Over-improvement.** Changing things not tied to a failing criterion adds noise and makes attribution harder. One reflection entry → one minimal change.
- **Skipping Step 1.** Jumping straight to "improve" without a rubric produces direction-less iteration. It feels productive but doesn't converge.
- **Using this skill when a test gate exists.** If `pytest` can tell you pass/fail, use `orchestrate`'s verify/fix loop instead — it's faster and more reliable than judgment-based iteration.
- **Cognitive surrender.** The verifier reduces the maker's blind spots; it does not eliminate them. A loop of green verdicts is not understanding — if you can't say *why* a change moved a criterion from FAIL to PASS, the loop is shipping artifact you don't comprehend. The ceiling exists partly as a human checkpoint: stop and read what actually changed before accepting it. Automating the loop is the point; automating away your judgment is the failure mode.
