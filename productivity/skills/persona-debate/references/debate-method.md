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

## Persona agent: use `persona-actor`, frame cleanly

Spawn each persona as the **`productivity:persona-actor`** subagent (defined in
this plugin). It carries no tools, so its context skips every tool schema a
general-purpose agent loads — the largest controllable slice of per-spawn
tokens — and its system prompt *is* the role-play instruction, so nothing fights
the persona. Its model defaults to haiku; override per spawn with the plan's
model. If that agent type isn't available, fall back to `general-purpose`.

**Frame the role-play cleanly. Do NOT tell the agent to "ignore inherited
instructions."** Measured: that override phrasing reads as a jailbreak and makes
**haiku refuse** ("I'm a Claude Code agent, I can't role-play"); a plain framing
works on both haiku and sonnet, costs fewer tokens, and the role-play context
already suppresses any inherited code/caveman style on its own. So just open with
the persona and the task, e.g.:

> 아래 인물이 되어 1인칭으로 답해줘. [페르소나]. [질문]. [출력 형식].

(Subagents inherit the orchestrator's CLAUDE.md and that can't be disabled, but
clean framing makes it a non-issue in practice. SessionStart-hook directives like
caveman mode don't reach subagents at all.)

## Token economy

Per-spawn cost is dominated by fixed inherited context (system prompt, tool
schemas, CLAUDE.md). Cut it where you can; across N×2 spawns it adds up:

- **Use `persona-actor`** (above) — drops tool schemas, the biggest controllable cut.
- **Trim the persona payload to the topic.** Don't inject all 17 sampled fields.
  Feed `persona` + the 1–2 narrative fields relevant to the question (e.g.
  `professional_persona` for a work-policy debate) + the key demographics
  (age/sex/region/occupation). Drop the rest. Roughly halves per-spawn input.
- **Condensed openings in Round 1** (see below), not the raw transcript.
- **Round discipline.** Shallow/binary questions: run Round 0 only and synthesize
  — skip Round 1 entirely. Only spend the second round when openings genuinely
  diverge and the topic warrants it. Keep N at the low end when unsure.
- **Don't over-classify depth.** `deep` makes every spawn sonnet; reserve it for
  genuinely contested/policy topics. Naming, product reactions, everyday opinion
  are usually `normal` (haiku openings) or `simple` (all haiku).

## Round structure

**Round 0 — Independent openings (parallel, isolated).**
Spawn one subagent per persona, each in its own context. Give it ONLY its own
persona fields + the question. It must NOT see other personas or their answers.
This captures the true spread of opinion before any conformity pressure — the
single biggest lever against false consensus. Ask for: position, the 1–2
reasons that actually move *this* person (rooted in their life, not generic),
and a confidence (low/med/high).

**Round 1 — Rebuttal (parallel, with openings injected).**
Spawn a fresh subagent per persona — do NOT try to keep Round-0 agents alive.
Inject a **condensed summary** of the openings (each persona: name + one-line
position + the 1–2 word reason), NOT the raw Round-0 transcript. The full text
is mostly redundant for rebuttal and multiplies input tokens across N spawns;
a tight summary preserves the disagreement map at a fraction of the cost. Each
persona must engage the *strongest opposing* argument directly (not restate its
own), and may move only if genuinely persuaded. Bake in skepticism: "Default to
scrutinizing others' reasoning; concede only when the evidence forces it."
Designate one persona as devil's advocate whose job is to find the strongest
objection everyone is missing.

**Stop here unless divergence is still high.** Extra rounds tend to *entrench*
errors and manufacture groupthink. Add a Round 2 only if positions are still
moving and the topic clearly warrants it.

## Plan: N, rounds, models

Your only judgment is classifying the question's depth — **simple** (binary
everyday), **normal** (multi-faceted opinion), or **deep** (contested/policy).
`sample_personas.py plan --depth <d>` then returns N, whether to run Round 1,
and the per-round model deterministically (add `--n` if the user gave a number).
Why these knobs move together: more stances need more personas (N 4→8), shallow
questions don't need a rebuttal round, and persona role-play is bounded work —
**opus is never used**; haiku carries shallow spawns, sonnet the deep ones and
always the devil's-advocate seat (the one spot stronger reasoning pays off). The
expensive model only appears where it changes the debate. The moderator
synthesis runs in your main session on the user's model — not a spawn, not
covered by this rule.

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
