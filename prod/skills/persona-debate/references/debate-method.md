# Debate method — the why behind each step

Grounded in silicon-sampling and deliberation research (Argyle "Out of One,
Many"; Park generative agents; Ashkinaze *Plurals* CHI 2025; Cheng *CoMPosT*
on caricature). The failure modes below are empirical, not hypothetical — the
structure exists to defeat them.

## The two failures this method fights

1. **False consensus / sycophancy.** LLM personas drift toward agreeable,
   centrist positions and adopt each other's wording. Minority views vanish.
   *Defeated by:* independent opening answers (no persona sees another's view
   before forming its own), explicit skeptic mandates, and a dedicated
   devil's-advocate seat.
2. **Caricature / flattening.** Thin demographic prompts produce cartoon
   stereotypes, worst for marginalized groups and identity-coupled topics.
   *Defeated by:* feeding rich narrative persona fields (not just age/sex),
   keeping each persona an individual with idiosyncratic detail, and flagging
   identity-coupled topics in the output rather than asserting confident
   "representation."

## Why the round structure looks like this

- **`persona-actor` carries no tools**, so its context skips every tool schema a
  general-purpose agent loads — the largest controllable slice of per-spawn tokens
  across N×2 spawns — and its system prompt *is* the role-play instruction.
  Subagents still inherit the orchestrator's CLAUDE.md; clean framing makes that a
  non-issue in practice, and SessionStart-hook directives do not reach subagents.
- **Round 0 isolation** captures the true spread before any conformity pressure —
  the single biggest lever against false consensus.
- **Round 1 gets a condensed summary**, not the raw transcript: the full text is
  mostly redundant for rebuttal and multiplies input tokens across N spawns.
  Bake in skepticism: "Default to scrutinizing others' reasoning; concede only
  when the evidence forces it." The devil's advocate looks for the strongest
  objection everyone is missing.
- **Extra rounds tend to entrench errors** and manufacture groupthink — add a
  Round 2 only if positions are still moving and the topic clearly warrants it.
- **Depth moves N, rounds and models together:** more stances need more personas
  (N 4→8), shallow questions don't need a rebuttal round, and sonnet appears only
  where stronger reasoning changes the debate (deep spawns, the devil's-advocate
  seat). `deep` makes every spawn sonnet — reserve it for genuinely contested or
  policy topics; naming, product reactions and everyday opinion are usually
  `normal` or `simple`. The moderator synthesis runs in your main session, not a spawn.

## Moderator synthesis (you, in the main context)

Randomize persona order before synthesizing (position bias). Weight by
argument quality, not verbosity or confidence. Do NOT collapse to one verdict
— preserve the spread. Output template (Korean):

```
## 토론 결과: <질문 요약>

**패널 구성** (N명) — <representative random | targeted: 필터 요약>
<roster lines + attribution from `sample_personas.py roster` (pipe the panel JSON in)>

### 의견 스펙트럼
<the range of positions, grouped — who leans where and the core reason. Not a vote tally; a map of the terrain.>

### 합의점
<what genuinely converged, if anything>

### 쟁점 (갈린 지점)
<the real disagreements, stated as live tensions — not resolved>

### 소수의견
<any strong minority/dissenting position, preserved on its own so the majority doesn't bury it. Omit only if there truly was none.>

### 종합
<your read: where the weight of argument lies, what the user should take from this. Honest about uncertainty.>
```

If the topic is identity-coupled (the answer depends heavily on the persona's
demographic identity — e.g. gender, region, age-group politics), add a one-line
caveat: these are synthetic personas and may flatten real within-group
diversity; treat as idea-generation, not as a survey of what group X thinks.
