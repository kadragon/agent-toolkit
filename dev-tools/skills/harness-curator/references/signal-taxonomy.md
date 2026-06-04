# Signal Taxonomy — detection rules and delegate briefs

The scanner emits five blocks per project: `SKILLS-ACTIVE`, `AGENTS-USED`, `CORRECTION-SIGNALS`, `AGENT-CORRECTION-SIGNALS`, `PROMPTS`. Classify findings into the four signals below. Each maps to exactly one delegate. The skill's value is correct routing — never reimplement a generator.

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

## Thresholds (no silent drops)

| Signal | Min occurrences |
|--------|-----------------|
| New-asset candidate | 3 |
| Triggering miss (skill or agent) | 2 |
| Underperforming asset (skill or agent) | 2 (or 1 with systematic cause) |
| Demote (unused skill or agent) | judgment — long history + ~0 use |

Report 2× near-misses under a `Watch:` line rather than dropping them.
