# Path-Scoped Rules (`.claude/rules/`)

`.claude/rules/*.md` is Claude Code's mechanism for **instructions that load only when the agent touches matching files** — true just-in-time context, not "the agent remembers to read the doc."

It is a real upgrade for keeping a Claude-Code-only harness lean — but it carries one decisive caveat that determines whether you should use it at all.

## Decide first: is the repo single-tool or multi-tool?

`.claude/rules/` is **Claude Code-specific**. Codex, Cursor, Copilot, etc. do **not** read it — they read AGENTS.md and (via its Docs Index) `docs/`.

| Repo targets… | Put area rules in | Why |
|---------------|-------------------|-----|
| **Claude Code only** | `.claude/rules/{area}.md` with `paths:` | Mechanical JIT load, zero budget cost elsewhere, agent can't skip it |
| **Claude + Codex / Cursor / any other agent** | `docs/{area}.md` (cross-tool, single source) | A `.claude/rules/` split would hide the rule from every non-Claude tool — the source fragments |

**For a multi-tool repo, unify in `docs/`.** The mechanical-auto-load benefit of path-scoped rules only helps Claude; paying for it by fragmenting the source so Codex goes blind is a bad trade. (This `agent-toolkit` repo is multi-tool — Claude + Codex — so it keeps rules in `docs/`.)

**Non-fragmenting hybrid** (multi-tool repo where voluntary `docs/` reads are genuinely being missed): keep the *content* in `docs/{area}.md` and make `.claude/rules/{area}.md` a 2-line **pointer** — "When editing `src/billing/**`, read `docs/billing.md`." Claude gets the mechanical trigger-to-read; Codex reads the doc directly; the single source stays in `docs/`. Don't duplicate content across the two — that just creates drift.

## What it solves (single-tool case)

Older harnesses had two homes for guidance:

- **AGENTS.md** — always loaded, so it must stay small (≤100 lines). Cross-tool.
- **`docs/*.md`** — loaded on demand, but only if the agent *chooses* to read it via the Docs Index. Discovery is voluntary; the agent can skip it and act anyway.

In a Claude-only repo, path-scoped rules add a third, mechanical home: loaded automatically **and only** when relevant. No budget cost when irrelevant, no reliance on the agent deciding to read.

## Why it matters

Loading semantics, confirmed against official docs ([code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory)):

- `.claude/rules/*.md` (recursive) are **registered** at launch with the same priority as `.claude/CLAUDE.md`. A rule with **no** `paths:` glob loads its content fully then (like CLAUDE.md); a rule **with** a `paths:` glob does not — only its existence is registered.
- A rule file with a `paths:` frontmatter glob loads its content **only when Claude reads or edits a file matching the glob** — otherwise it stays out of context entirely.
- This is genuine lazy loading. Note the contrast: **`@`-imports do NOT save context** — an imported file loads fully at launch. Only **skills, path-scoped rules, and auto-memory topic files** achieve true on-demand loading. So content that would bloat AGENTS.md/CLAUDE.md should move to a path-scoped rule, not an `@`-import.

## Layout

```
.claude/rules/
├── api.md            # paths: src/api/**     — REST conventions, error envelope
├── migrations.md     # paths: db/migrations/** — irreversible-change checklist
└── billing.md        # paths: src/billing/**  — money-handling invariants
```

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "src/api/**/*.tsx"
---

# API conventions

- Every handler returns the `{ data, error }` envelope — never a bare value.
- 4xx vs 5xx: client mistake vs our mistake. Never 200 with an error body.
- Pagination is cursor-based; see `docs/architecture.md` for the cursor schema.
```

A rule file with **no** `paths:` frontmatter loads every session (like CLAUDE.md) — use that sparingly.

## When to use which home

| Content | Home | Reason |
|---------|------|--------|
| Map: where things are, golden principles, delegation table | `AGENTS.md` | Always-on, cross-tool, ≤100 lines |
| Area-specific rules, **multi-tool repo** | `docs/{area}.md` | Cross-tool single source; Codex/Cursor read it too |
| Area-specific rules, **Claude-only repo** | `.claude/rules/{area}.md` with `paths:` | Loads mechanically, zero budget elsewhere, can't be skipped |
| Deep reference read start-to-finish during a workflow | `docs/*.md` | On-demand, but discovery is voluntary |
| Hard block regardless of model decision | `.claude/settings.json` (`permissions.deny`) / hook | Prose can't enforce — see `enforcement-template.md` Layer 0 |

**Decision rule:** guidance shaped like *"when you edit X, remember Y"* (short Y) wants mechanical just-in-time delivery. In a **Claude-only** repo, that's a path-scoped rule. In a **multi-tool** repo, keep Y in `docs/` so every agent sees it — and only if voluntary reads are being missed, add a thin `.claude/rules/` pointer to that doc. Long-form reference material always lives in `docs/`.

## Migration from a fat AGENTS.md

If AGENTS.md is over budget because it carries area-specific rules ("in the billing module, always…"), move that content out:

- **Multi-tool repo:** extract the block into `docs/{area}.md`, add a Docs Index pointer in AGENTS.md, delete the block. (Optionally add a `.claude/rules/{area}.md` pointer to the doc for Claude's mechanical auto-load — no content duplication.)
- **Claude-only repo:** extract the block into `.claude/rules/{area}.md`, add a `paths:` glob, delete the block from AGENTS.md.

Either way brings an over-budget AGENTS.md back under 100 lines without losing the guidance.

## Portability note

Path-scoped rules are **Claude Code-specific**. AGENTS.md (+ `docs/`) remains the cross-tool source of truth (Codex, Cursor, Copilot, etc. read it). Treat `.claude/rules/` as a Claude Code accelerator — on a multi-tool repo it must never become the *only* home for a rule, or non-Claude agents go blind.

## Validation

`scripts/validate-harness.sh` does not require `.claude/rules/` (it is optional). If present, each rule file should either declare a `paths:` glob or be deliberately global; a rule file with neither a glob nor session-wide intent is usually a misplaced `docs/` file.
