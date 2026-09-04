# Signal Taxonomy — detection rules and delegate briefs

Five signals. Each names what the scanner output must show, the threshold, and the brief the
creator receives. Every brief names its acceptance check up front (SKILL.md → *Step 7*).

## 1. New-asset candidate

**Detect:** a cluster of `PROMPTS` (and `CODEX-PROMPTS`) with the same intent — same verb, same
object, same shape of output — in **≥3** sessions, and no inventory asset whose description
covers it. One session with three restatements is one occurrence.

**Promote / demote:** a deterministic repeat (the same command or edit every time, no judgment)
→ a hook via `update-config` / `hookify`. A judgment-bearing workflow → a skill via
`skill-creator`. A recurring *role* (a reviewer, a verifier) → an agent via
`plugin-dev:agent-creator`.

**Brief:** the quoted prompts (3+, with session dates), the intent in one line, the nearest
existing asset and why it does not cover this, scope from SKILL.md → *Step 4*. Acceptance: the
creator's own eval passes on the quoted prompts.

## 2. Triggering miss

**Detect:** prompts that sit in an existing skill's or agent's domain (its `description:` would
match a human reader) while that asset is absent or ≈0 in `SKILLS-ACTIVE` / `AGENTS-USED` for the
same sessions — **≥2** sessions. For an agent: the work was done inline on the main thread.

**Non-findings:** the user invoked a different skill deliberately; the prompt was answered
without needing the skill (a no-op skill is Signal 4 territory, not a miss).

**Brief:** the missed prompts quoted, the current `description:` verbatim, the competing asset
if one fired instead. Route: skill → `skill-creator` description optimizer; agent →
`plugin-dev:agent-development`. Acceptance: the missed prompts now rank the asset first.

## 3. Underperforming or over-firing asset

**Detect:** any of — `CORRECTION-SIGNALS` / `AGENT-CORRECTION-SIGNALS` on one asset in **≥2**
sessions (it was active, then the user redirected or rejected the output); `HARNESS-FRICTION` on
one hook or rule in **≥2** sessions (the user complains about, disables, or works around an
imposed behavior); or **≥2** same-cause `VERIFIER-FAILURES` (a CI check, a test command, a hook
denial) attributable to one asset's instructions. Read the causal status before routing — a
failure the task itself caused is not the asset's.

**Brief:** the corrections quoted with `file:line` of the asset text they contradict; for a
hook, the exact event that over-fired. Route: skill → `skill-creator` modify; agent →
`plugin-dev:agent-development`; hook → narrow it via `hookify` / `update-config` (never the
`permissions` block); a `CLAUDE.md` / `AGENTS.md` line → surface it for the user. Acceptance:
the correction case re-run without the correction.

## 4. Unused asset

**Detect:** a skill, agent, command, or hook at ≈0 in the cumulative `SKILLS-ACTIVE` /
`AGENTS-USED` — across the asset's whole lifetime, not since the last run — plus the stale-code
lens (60+ days without a commit). Consider both platforms before calling it unused.

**Adversarial check (mandatory before any delete):** one independent reviewer argues for keeping
it — a rare-but-critical path, a slash-command or hook route the scanner cannot see, a backstop
for a failure that has not recurred yet. A real reason → `Watch:`.

**Brief:** the usage counts per platform, the last commit date, the reviewer's verdict. Route:
remove the file(s), bump the owning plugin. Acceptance: the plugin's validate/CI passes without it.

## 5. Domain knowledge candidate

**Detect:** a fact or constraint about the repo — a path, an endpoint, a gotcha, a rule of
thumb — restated by the user or rediscovered by the agent in **≥2** sessions, and not already in
`AGENTS.md` / `CLAUDE.md` / an indexed `docs/*.md`. A repo-scoped `project` / `reference` memory
in the auto-memory store is the same finding from the other side: it is invisible to Codex and
every `AGENTS.md` reader.

**Brief:** the fact quoted with its sessions (or the memory file and line), the target
`docs/<topic>.md`. Route: write the doc and one Docs Index row; a memory source is then deleted
through `harness-capture` Memory hygiene. Acceptance: the doc exists and the index row resolves.

## Thresholds

| Signal | Threshold |
|--------|-----------|
| 1 New asset | ≥3 sessions |
| 2 Triggering miss | ≥2 sessions |
| 3 Underperforming / over-firing | ≥2 sessions, or ≥2 same-cause verifier failures |
| 4 Unused | ≈0 lifetime, both platforms, adversarial check passed |
| 5 Domain knowledge | ≥2 sessions, or 1 repo-scoped memory |

Near-misses (one short of the threshold) go on the report's `Watch:` line, never silently dropped.
