# Signal Taxonomy — detection rules and delegate briefs

Step 1's scan (`scan_transcripts.py`) emits seven blocks per project: `SKILLS-ACTIVE`, `AGENTS-USED`, `CORRECTION-SIGNALS`, `AGENT-CORRECTION-SIGNALS`, `HARNESS-FRICTION`, `VERIFIER-FAILURES`, `PROMPTS`. Signal 7 has no scan block at all — it is read directly off the instruction files in Step 2, and so is Signal 6's second input, the auto-memory store. `PROMPTS` is raw input for model clustering (Signals 1 and 6), not a classified signal on its own. Each signal maps to a single routing decision (one tool delegation, or a user-decision surface). The skill's value is correct routing — never reimplement a generator.

Skills and agents are analyzed symmetrically: `SKILLS-ACTIVE`/`AGENTS-USED` drive triggering-miss and demote; `CORRECTION-SIGNALS`/`AGENT-CORRECTION-SIGNALS` drive underperform. Wherever a rule below names a skill, the agent equivalent applies via the agent block and routes to `plugin-dev:agent-creator` (create) or `plugin-dev:agent-development` (modify/description) instead of `skill-creator`.

## 1. New-asset candidate

**Detect:** Cluster `PROMPTS` by *intent*, not exact string ("add a test for X" + "write tests for Y" + "cover Z" → one cluster "write tests"). A cluster with **≥3** occurrences that no inventory asset (Step 2) covers is a candidate. Rank by frequency.

**Classify the target** (CLAUDE.md promote/demote logic):
- Deterministic single action, always the same → **hook** → `update-config` (settings.json) or `hookify`.
- Domain knowledge / reusable multi-step workflow → **skill** → `skill-creator:skill-creator`.
- Delegatable open-ended multi-step task → **agent** → `plugin-dev:agent-creator`.

**Brief to pass:** goal (the recurring intent in one line) · constraint (scope, what it must NOT do) · exit criterion (how the user will know it works) · example prompts from the cluster (for the skill-creator triggering eval).

## 2. Triggering miss

**Detect:** A cluster of `PROMPTS` clearly inside an **existing** skill's domain, but that skill is **absent from `SKILLS-ACTIVE`** (or present in far fewer sessions than the cluster size). The skill exists and is right for the job, but its description didn't match — a description problem, not a content problem.

**Confirm before routing:** the skill's domain genuinely covers the prompts (read its current `description`). If the prompts are actually a different need, this is a New-asset candidate, not a miss.

**Route:** `skill-creator:skill-creator` description optimizer. It writes ~20 trigger/non-trigger prompts, splits train/test, and rewrites the description until triggering is reliable. Hand it the existing skill path + the missed example prompts. Do not build a parallel eval harness — skill-creator owns this.

**Tip:** the most reliable descriptions are *directive* ("This skill should be used when the user asks to …") with concrete trigger phrases, not feature descriptions.

**Agent variant:** the main thread selects agents by reading their descriptions, so an agent that exists and fits the work but is **absent from `AGENTS-USED`** (while you did that work inline or via the wrong agent) is the same miss. Read the agent's `description`/`when to use`; route the fix to `plugin-dev:agent-development` to sharpen the triggering description.

## 3. Underperforming asset

**Detect:** A skill that appears in `CORRECTION-SIGNALS` — it loaded, then the user pushed back (short negative follow-up). The skill triggers fine but its instructions produced a wrong/unwanted result. Read the correction text to understand the failure mode.

**Route:** `skill-creator:skill-creator` modify mode. Brief: the skill path, the failure mode (quote the correction), and the desired behavior. This is a content/instruction fix, distinct from the description fix in signal 2.

**Agent variant:** an agent in `AGENT-CORRECTION-SIGNALS` triggered/was-invoked fine but produced a wrong result — a system-prompt/instruction fix. Route to `plugin-dev:agent-development` (modify) with the agent path, the quoted correction, and the desired behavior.

**Caution:** a single correction may be a one-off. Require **≥2** corrections against the same skill/agent, or one with an obvious systematic cause, before routing.

## 4. Promote / demote

**Promote (skill/agent → hook):** A repeated action that is fully **deterministic** (same trigger → same action, no judgment) is better as a hook than a skill the model must remember to invoke. Route to `update-config` (settings.json hook) or `hookify`.

**Demote (delete):** An installed asset with **~0 sessions-used** is dead weight — a skill absent from `SKILLS-ACTIVE` or an agent absent from `AGENTS-USED` over a long history (cross-reference the Step 2 inventory: the asset is installed but never appears in the use block). Surface it as a delete candidate. On confirmation, remove the file and bump the owning plugin version. Never delete without confirmation.

**Adversarial check before any DELETE.** A delete recommendation is a completeness output with no test, so self-judgment is biased (CLAUDE.md: self-check ≠ verification). Before routing a DELETE to confirmation, spawn one independent reviewer agent (`Explore` or `general-purpose`) with the single question: *"Asset X is flagged for deletion on ~0 transcript use. Argue why removing it is unsafe — does it guard a rare-but-critical path, fire only on phrasing the scanner can't see (slash-command-only, hook-invoked, sidechain), or backstop a failure mode that simply hasn't recurred yet?"* Downgrade DELETE → `Watch:` if the reviewer surfaces a real reason. Low transcript use ≠ uselessness — an asset that fires rarely but prevents a disaster is load-bearing.

## 5. Harness friction (over-protection)

**Detect:** Lines in `HARNESS-FRICTION` — the user complaining about a **recurring imposed behavior** ("you keep …", "every time …", "자꾸 …", "매번 …"). Unlike a correction, this targets the *harness*, not the answer: a hook firing too often, a permission gate re-asking, or a CLAUDE.md rule the user keeps working around. These carry no skill/agent attribution, so the scanner collects them standalone.

**Confirm before routing:** read each sample. The block deliberately over-collects (a "every time it crashes" task complaint matches the same phrasing) — keep only complaints aimed at a guardrail. Map the complaint to the specific hook (`.claude/settings.json`) or rule (CLAUDE.md / AGENTS.md) that produces the behavior.

**Route:**
- Over-firing hook / permission gate → `update-config` to narrow its matcher or add a staleness/scope guard (loosen, don't delete a safety hook outright).
- CLAUDE.md / AGENTS.md rule the user keeps overriding → propose shrinking or making it conditional (CLAUDE.md "Bloat signal" + "On model upgrade: re-examine guardrails"). Surface the line; let the user decide — never auto-edit global instructions.

**Caution:** one complaint is a mood, not a signal. Require **≥2** complaints about the same behavior, or one with an obvious systematic cause, before routing. A guardrail the user dislikes once may still be load-bearing — same adversarial caution as DELETE.

## 6. Domain knowledge candidate

**Detect:** From `PROMPTS` (same input as Signal 1, model judgment), a fact or constraint that appears in **≥2** sessions but is NOT a multi-step workflow and too atomic to warrant a standalone skill. Examples: a proxy bypass pattern ("NO_PROXY required for git.knue.ac.kr"), a platform quirk, a recurring env-var lookup, a fixed API constraint the model keeps re-deriving. Distinguishing from Signal 1: if the cluster reduces to a single constraint or lookup rather than a sequence of steps, it is a domain knowledge candidate, not a new-asset candidate.

**Route:** Write the fact to `docs/<topic>.md`. AGENTS.md and CLAUDE.md get only an *index pointer* to the doc (one-line `filename | summary` entry) — both files are intentionally capped and serve as navigation indexes, not knowledge dumps. If the fact belongs directly in a CLAUDE.md or AGENTS.md guardrail (a hard constraint, not just reference), surface the exact line for the user to decide — never auto-edit global instructions.

**Confirm before routing:** Verify the fact is not already in AGENTS.md, CLAUDE.md, or an existing `docs/` file. If it is present but the model keeps missing it, the problem is attention/placement — surface the existing location rather than duplicating.

**No scanner change needed:** Signal 6's `PROMPTS` input is detected by model judgment over the same block that drives Signal 1. The scanner produces no separate output block for it.

### Second input: the auto-memory store

The auto-memory store (`<config>/projects/<encoded>/memory/*.md` + `MEMORY.md`) holds facts someone already judged durable enough to persist. It is also **Claude-only and per-project**: Codex and every other tool reads `AGENTS.md` and `docs/`, never this directory. So a repo-scoped fact sitting in memory is a Signal 6 candidate that skipped the frequency question — it earned persistence when it was written; what it did not get is the right *home*.

**Detect:** Step 2's memory-store lens, not `PROMPTS`. A memory qualifies when **both** hold:
- frontmatter `metadata.type` is `project` or `reference`, **and**
- the content is scoped to one repo (a path, tool, endpoint, constraint, or convention that only makes sense inside it).

**Not a finding:**
- **`type: user` or `type: feedback`.** These are cross-repo by construction — who the user is, and how they want work done. Promoting one into a single repo's `docs/` drops it for every other repo, which is the same reach mistake §7 warns about in the other direction. They stay in memory.
- **A `project`/`reference` memory that is not repo-scoped** — a cross-repo tool quirk or an account-level fact has no owning `docs/` to move into.
- **Session-scoped residue.** If the "fact" only mattered to the work that produced it, the finding is a memory-hygiene one (`harness-capture`), not a promotion.
- **The `MEMORY.md` index itself.** It is the store's navigation layer, never promoted.

**Already-promoted subtype:** the fact is already in `AGENTS.md`, `CLAUDE.md`, or an existing `docs/*.md`. This is still actionable — memory and docs now hold the same rule and will drift, which is §7's duplicate cost — but the action is deletion only: no docs write, straight to the `harness-capture` route. Verify by quoting the existing location, exactly as Signal 6's "Confirm before routing" already requires.

**Evidence requirement (hard):** quote the memory body verbatim with `file:line` and name a concrete target `docs/<topic>.md`. Unquotable → dropped, not `Watch:`. Same Agent-integrity reasoning as §7.

**Route — the ownership split matters.** `harness-curate` decides the promotion, writes `docs/<topic>.md`, and adds the AGENTS.md Docs Index pointer. It **never deletes a memory file**: destructive memory prunes belong to `harness-capture`'s Memory hygiene (which also repairs the `MEMORY.md` index and defers risky prunes), so the deletion is routed there on confirmation. Curate is thin glue here as everywhere — it does not reimplement an owner.

**Cross-run suppression (required):** static, like §7 — a declined promotion would otherwise re-fire every run and keep `lastCandidateMs` permanently fresh. Reuse `scripts/overlap_state.py` unchanged, with its positional keys mapped `"global"` = the memory side, `"repo"` = the proposed docs target, and record both outcomes (promoted, or consciously kept) with `--dismiss`.

**Scope limit:** `current` / `--project` only — `all` scope cannot resolve the repo to promote *into* (same limitation as §7 and the Codex fold-in).

## 7. Instruction-layer overlap (base ↔ global ↔ repo/docs)

**Detect:** from Step 2's overlap lens, not from any scan block. Read the layers **in full this session** — the platform's base instructions (already in context), the global `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`, the repo's `CLAUDE.md` / `AGENTS.md` (plus any parent-directory `AGENTS.md`), `<repo root>/.claude/rules/*.md`, and the `docs/*.md` files the AGENTS.md Docs Index points to — then pair rules that govern the same behavior. Three subtypes:

- **Duplicate** — two layers state the same rule with no scope or strictness delta. Cost isn't just tokens: the two copies drift, and after one is edited the other silently contradicts it (which becomes the next conflict).
- **Conflict** — the layers give incompatible instructions for the same situation (global "never commit to `main` — branch first" vs. repo "commit fixes straight to `main`"). The agent resolves it by luck, differently each session.
- **Base-redundant** — a repo-side rule (`CLAUDE.md`, `AGENTS.md`, `.claude/rules/`, or an indexed `docs/*.md`) whose *entire* content is behavior the model's own base instructions already impose every turn: batch independent tool calls, don't re-read a file you just edited, don't restate the user's message, keep working through context summarization. This is `harness-init`'s Step 3 note ("Token Economy overlaps Claude's base instructions") and the sweep's load-bearing question 4 (`harness-init/references/sweep-template.md` → Load-Bearing Assessment) applied as an audit instead of a one-time generation-time judgment. Partial overlap is a *specialization*, not this subtype — the rule must reduce to nothing repo-specific.

**Not a finding:**
- **Cross-tool reach.** Repo `AGENTS.md` restating a global `~/.claude/CLAUDE.md` rule is *not* a duplicate. `~/.claude/CLAUDE.md` is Claude-only; `AGENTS.md` is the file every other tool reads (`docs/platform-specs.md`). The repo copy is that rule's only reach on Codex and friends — deleting it silently drops the rule for those sessions. Same for content synced from any shipped standard, where the copy is the delivery mechanism. **This applies to base-redundant pairs with full force:** base instructions are *per-tool*, so "the model is already told this" is only ever true of the tool whose base prompt you actually read this session. On a multi-tool repo the line stays load-bearing for every other reader.
- **`docs/` holding the repo's own facts.** The global layer's routing rule sends repo facts to the owning repo's `docs/`, indexed by AGENTS.md. So a `docs/*.md` file that expands on a topic the global file only gestures at is the designed mechanism working. The finding is a *copy of the rule itself* in `docs/`, not detail that lives there by design.
- Local **specializes** global — narrower scope, stricter threshold, or a repo-specific value filling a global placeholder. That's refinement, and deleting it loses information.
- Local is an **explicit opt-out the global rule itself grants** (e.g. global's "Exception: repo AGENTS.md/CLAUDE.md opts in"). That's the designed mechanism working, not a conflict.
- Blocks marked `<!-- harness:verbatim … -->`, **and** the AGENTS.md blocks `harness-init` mandates verbatim whether or not the marker is present (`harness-init/SKILL.md` → "Two embedded blocks mandatory in AGENTS.md") — mandated deliberately, out of scope. Marker coverage in generated files is incomplete, so match on the mandate, not just the comment.
- Similar phrasing, different subject.

**Evidence requirement (hard):** every finding carries both sides quoted verbatim with `file:line`. The Agent integrity principle — if you can't quote both, you haven't verified the pair, so drop it entirely (not even `Watch:`). This is the exact trap `harness-init` warns about: "some higher-precedence file already covers this" is the easiest claim to get wrong, because that file isn't in front of you while you edit.

**The one exception, and its price.** The base-instruction side has no `file:line` — quote the covering text verbatim and label it `[base instructions — {model id}, this session]`. The quote is still mandatory: `sweep-template.md` → Load-Bearing Assessment states it outright — *"This is the one check where you must quote the covering text; 'I think the base prompt covers it' is how correct rules get deleted."* A paraphrase, a summary, or "the model does this anyway" is not evidence, and a base-redundant finding without a verbatim quote is dropped. Because the quote is model-scoped, so is the finding: record the model id in the report, and treat a model upgrade as invalidating it. That invalidation is mechanical, not a matter of remembering — the model id rides inside the pairs.json value (SKILL.md Step 2), so a new model changes the key and the pair resurfaces even when the base prompt's wording is unchanged.

**Route by ownership.** The boundary is the one the global file itself sets: global holds cross-repo behavior; repo facts belong to the owning repo (`docs/`, indexed from AGENTS.md). **Deletion is never the default** — the layers reach different tools, so report first, delete only when reach is proven redundant.
- Duplicate, rule is cross-repo behavior → default is **reach-justified: report, don't delete**. Propose deleting the repo copy only after verifying the repo is single-tool — and **absence is not that verification**. No `.codex-plugin/`, no `~/.codex/` sessions, and no other tool's config are consistent with a repo that simply hasn't been opened in Codex *yet*; deleting on that basis drops the rule for the first non-Claude session that arrives. Require **positive evidence** that Claude is the only intended reader — an explicit statement in AGENTS.md/README (or from the user) that the repo targets Claude Code only — and quote it in the finding alongside the absence checks. Cannot quote it → the repo copy stays, reported as reach-justified.
- Duplicate, rule is repo-specific → the global file is the wrong owner. Surface the exact global line and let the user edit it; propose the repo-side home (`docs/<topic>.md` + index pointer, per Signal 6). **Never auto-edit `~/.claude/CLAUDE.md`.**
- Base-redundant → the base side is not editable, so the only move is a repo-side trim, and it needs the *same* single-tool verification as a duplicate. Verified single-tool repo → propose deleting the line on confirmation. Multi-tool repo → report as reach-justified and stop. Either way, exclude `harness:verbatim` and `harness-init`-mandated blocks (below), and prefer trimming the redundant *items* out of a block over deleting a whole section that also carries repo-specific rules.
- A `docs/*.md` finding routes exactly like its AGENTS.md counterpart — same subtypes, same single-tool gate. The only difference is that `docs/` is on-demand rather than always-loaded, so the token argument for trimming is weaker: a duplicated rule there costs drift risk, not context budget. Weigh accordingly and say so in the finding.
- Conflict → surface both quoted lines side by side and ask which is authoritative. Precedence between layers is **not documented in this repo and is model judgment, not spec**: if you cannot establish the winning layer from a quotable source, write `[unknown — precedence not verifiable]` rather than asserting one (the Agent integrity principle). If the user keeps the local override, propose labeling it explicitly ("Overrides global: …") so the next agent doesn't re-derive it. Never resolve a conflict silently.

**Cross-run suppression (required).** A static finding re-fires every run until a file changes, which would keep `lastCandidateMs` fresh forever and turn the staleness nudge into noise. So: filter candidate pairs through `scripts/overlap_state.py --check` before reporting, and after the user resolves a pair **or decides to keep it as-is**, record it with `--dismiss`. The key is a hash of both sides' values, each of which carries its source (file path, or the model-stamped base-instruction label) ahead of the quoted line — so dismissal suppresses that exact pair in that exact file, not the topic, and not the same sentence sitting in a second indexed file. Edit either line and the pair resurfaces. Report the `suppressed=` count so nothing drops silently.

**Scope limit:** `current` / `--project` only — the lens needs a resolvable repo path, which `all` scope doesn't have (same limitation as the Codex fold-in). For cross-repo coverage, run `--project` per repo.

## 8. Verifier-grounded failure

> Concept: Self-Harness weakness mining (Lilian Weng, "Harness Engineering for Self-Improvement", https://lilianweng.github.io/posts/2026-07-04-harness/) — cluster failures grounded in **machine verdicts**, not user pushback. Signals 3/5 fire only when the user notices and complains; Signal 8 fires when a verifier already said no, so the harness improves without the user carrying the detection load.

**Detect:** Lines in `VERIFIER-FAILURES`, three kinds:
- `ci-fail` — a Bash tool_use matching a CI/test command pattern (`ci-wait`, `pytest`, `validate-harness`, `--test`, …) whose tool_result errored. Detail is the failing command.
- `qa-reject` — a `qa-verifier` Agent invocation whose returned tool_result matches rejection phrasing (BLOCKING / FAIL / REJECT / 반려 / 불합격 …).
- `hook-deny` — any errored tool_result matching hook-block phrasing (`PreToolUse`, `hook error`, `commit-guard`, `PermissionDenial` …). Outranks `ci-fail` when both match: a hook-blocked CI command is a denial, not a CI failure.

Cumulative lifetime history, like `CORRECTION-SIGNALS`. **Deliberately over-collects** — a CI failure caused by the task under work (a genuinely broken change) matches the same pattern as one caused by a harness defect. Read each sample and establish the **terminal verifier-level cause** and the **causal status of harness behavior** before treating it as a finding: the signal is a failure the harness *let happen repeatedly* (a missing gate, a skill instruction that produces the same CI breakage, a hook matcher misfiring), not any red exit code.

**Not a finding:**
- A one-off task bug the verifier caught exactly as designed — that is the harness *working*.
- A hook-deny where the block was correct (e.g. commit-guard stopping a `main` commit). Repeated *correct* denials of the same attempted action are instead evidence the workflow doc/skill routes the model into the blocked path — route that as an underperforming-asset fix (Signal 3), quoting the denials.
- CI failures already hard-stopped and reworked to green within the same session with no recurrence across sessions.

**Route (same creators as Signals 3/5, evidence differs):**
- Recurring CI/test failure pattern traceable to a skill's instructions → `skill-creator` modify, brief quotes the failing commands/output cluster.
- qa-reject cluster naming the same criterion → fix the producing skill/agent (`skill-creator` / `plugin-dev:agent-development`) with the quoted verdicts.
- Hook matcher misfiring (wrong denials) → `update-config` to narrow; repeated correct denials of the same path → fix the routing skill/doc, per above.

**Brief to pass:** goal (the failure pattern in one line) · evidence (≥2 quoted verifier verdicts with session/kind) · constraint (the verifier itself is read-only — never edit `validate-harness.sh`, the qa-verifier definition's acceptance bar, or CI workflows to make the signal go away) · exit criterion (the objective check that must pass after the fix, per the validation gate).

## Thresholds (no silent drops)

| Signal | Min occurrences |
|--------|-----------------|
| New-asset candidate | 3 |
| Triggering miss (skill or agent) | 2 |
| Underperforming asset (skill or agent) | 2 (or 1 with systematic cause) |
| Harness friction (over-protection) | 2 (or 1 with systematic cause) |
| Domain knowledge candidate (from `PROMPTS`) | 2 (lower than Signal 1 — atomic facts never form large clusters) |
| Domain knowledge candidate (from the memory store) | 1 — static defect; the frequency bar was cleared when the memory was written, but the verbatim quote is still mandatory |
| Demote (unused skill or agent) | judgment — long history + ~0 use, **then adversarial check** |
| Verifier-grounded failure | 2 same-cause (or 1 with systematic cause) — after the causal-status read; raw `VERIFIER-FAILURES` lines are not findings |
| Instruction-layer overlap | 1 — static defect, but **only** with both sides quoted (`file:line`, or the labeled verbatim base-instruction quote); unquotable → dropped |

Report 2× near-misses under a `Watch:` line rather than dropping them.
