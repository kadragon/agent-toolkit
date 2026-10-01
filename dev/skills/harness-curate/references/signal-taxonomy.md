# Signal Taxonomy — detection rules and delegate briefs

Six signals. Each names what the scanner output must show, the threshold, and the brief the
creator receives. Every brief names its acceptance check up front (SKILL.md → *Step 7*).

## 1. New-asset candidate

**Detect:** a cluster of `PROMPTS` (and `CODEX-PROMPTS`) with the same intent — same verb, same
object, same shape of output — in **≥3** sessions, and no inventory asset whose description
covers it. One session with three restatements is one occurrence.

**Promote / demote:** a deterministic repeat (the same command or edit every time, no judgment)
→ a hook via `update-config` / `hookify`. A judgment-bearing workflow → a skill via
`skill-creator`. A recurring *role* (a reviewer, a verifier) → an agent via
`plugin-dev:agent-creator`.

**Dedupe against guardrails first:** a candidate check that already exists but runs nowhere is
the Step 2 *unwired check* finding — route "wire it", not "build it".

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
`permissions` block); a `CLAUDE.md` / `AGENTS.md` line → classify it (*Classify before
routing*, below) and surface the proposal for the user. Acceptance: the correction case re-run
without the correction.

## 4. Unused asset

**Detect:** a skill, agent, or command at ≈0 in the cumulative `SKILLS-ACTIVE` /
`AGENTS-USED` — across the asset's whole lifetime, not since the last run. Consider both
platforms before calling it unused. A **hook** has no usage count — the scanner sees only its
denials (`VERIFIER-FAILURES` `hook-deny`), and a hook that never denies may be passing silently
or preventing the failure outright. Zero denials puts a hook on `Watch:`, never on this list,
unless the event it matches no longer exists.

Last commit date, from the asset's *own* repo:

```bash
asset="path/to/skill/SKILL.md"
repo_root=$(git -C "$(dirname "$asset")" rev-parse --show-toplevel 2>/dev/null)
[ -n "$repo_root" ] && git -C "$repo_root" log --follow -1 --format='%ci' -- "$asset"
```

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

**Classify first** (*Classify before routing*, below): a constraint an exit code can decide is
a check, not a doc. Only a plain fact, or a judgement the check cannot carry, becomes prose.

**Brief:** the fact quoted with its sessions (or the memory file and line), the target
`docs/<topic>.md`. Route: write the doc and one Docs Index row; a memory source is then deleted
through `harness-capture` Memory hygiene. Acceptance: the doc exists and the index row resolves.

## 6. Tool cost

**Detect:** in `TOOL-COST`, the same oversized call shape (same command, same file, same API)
or search churn toward the same target in **≥2** sessions. Read the session's prompts before
counting churn — a broad exploratory task earns a long hunt; a narrow task that still hunted is
the finding.

**Route:** oversized → bound the call: a line range or `--jq` filter in the skill text that
issued it, or a script with a summary mode when the call is the skill's own. Churn → a
**navigation pointer** where the agent already looks — an `AGENTS.md` Docs Index row, a
`see <path>` line in the skill that was active, a comment at the entry file. The pointer's
wording follows `docs/writing-for-agents.md` → *Context pointers* where present: front-load the
leading word, one trigger per branch.

**Brief:** the two session ids with the call or the churn count, the target the agent finally
reached. Acceptance: re-run one of the sessions' opening prompts (`--session` on the fresh
transcript) and the call shrinks or the hunt shortens.

## Classify before routing

A rule or constraint surfaced by Signals 3 or 5 is sorted before it is written anywhere:

| Kind | Test | Route |
|------|------|-------|
| Mechanical | an exit code can decide it — a fixed pattern, a banned API, an import shape, a file location | a hook, lint rule, or CI job — whichever the repo's guardrail makes cheapest |
| Judgement | needs the diff and taste — cross-file consistency, "matches the surrounding style" | the review-time asset: a `code-review` rule or the reviewer agent's brief |
| Pre-context fact | the agent must hold it before anything asks | one `CLAUDE.md` / `AGENTS.md` line — the highest bar, paid every turn |

The reviewer receives a diff and carries the least context pressure, so judgement rules go
there rather than to the implementer's always-loaded files.

## Thresholds

| Signal | Threshold |
|--------|-----------|
| 1 New asset | ≥3 sessions |
| 2 Triggering miss | ≥2 sessions |
| 3 Underperforming / over-firing | ≥2 sessions, or ≥2 same-cause verifier failures |
| 4 Unused | ≈0 lifetime, both platforms, adversarial check passed |
| 5 Domain knowledge | ≥2 sessions, or 1 repo-scoped memory |
| 6 Tool cost | ≥2 sessions, same call shape or same churn target |

Near-misses (one short of the threshold) go on the report's `Watch:` line, never silently dropped.
