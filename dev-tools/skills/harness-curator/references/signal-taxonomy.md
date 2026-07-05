# Signal Taxonomy — detection rules and delegate briefs

The scanner emits seven blocks per project: `SKILLS-ACTIVE`, `AGENTS-USED`, `CORRECTION-SIGNALS`, `AGENT-CORRECTION-SIGNALS`, `HARNESS-FRICTION`, `FAILED-COMMANDS`, `PROMPTS`. Seven output blocks, seven classification signals — `PROMPTS` is raw input for model clustering (Signals 1 and 6), not a classified signal on its own. Each signal maps to a single routing decision (one tool delegation, or a user-decision surface). The skill's value is correct routing — never reimplement a generator.

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

**No scanner change needed:** Signal 6 is detected by model judgment over the same `PROMPTS` block that drives Signal 1. The scanner produces no separate output block for it.

## 7. Recurring failure

**Detect:** Lines in `FAILED-COMMANDS` — a failure signature (command/error pair) repeating **≥3×**. Each recurrence means the agent re-derives the same broken assumption instead of learning it once.

**Route:**
- Typo / wrong flag repeated → CLAUDE.md/AGENTS.md note, or a PreToolUse block via `hookify` / `update-config` if mechanically detectable.
- Missing dependency/tool → setup doc (`docs/`) or a guard that fails fast with the fix.
- Systematic wrong flag/pattern → CLAUDE.md/AGENTS.md guardrail; surface the exact line for the user to decide — never auto-edit global instructions.

**Caution:** distinguish a genuine recurring gap from transient flakiness (network blip, rate limit) — the latter isn't a harness gap.

## Thresholds (no silent drops)

| Signal | Min occurrences |
|--------|-----------------|
| New-asset candidate | 3 |
| Triggering miss (skill or agent) | 2 |
| Underperforming asset (skill or agent) | 2 (or 1 with systematic cause) |
| Harness friction (over-protection) | 2 (or 1 with systematic cause) |
| Domain knowledge candidate | 2 (lower than Signal 1 — atomic facts never form large clusters) |
| Demote (unused skill or agent) | judgment — long history + ~0 use, **then adversarial check** |
| Recurring failure | 3 |

Report 2× near-misses under a `Watch:` line rather than dropping them.
