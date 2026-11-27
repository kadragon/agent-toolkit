# Sweep Script Template

The sweep script is the automated garbage collector for the harness. It catches drift, stale docs, and principle violations before they compound.

## Base Script

A ready-to-use sweep script is available at `../scripts/sweep.sh`. Install it with its queue
modules so `bash tools/sweep.sh` also works from cron or harness sync. From the target
project's root:

```bash
SKILL_DIR="<absolute harness-init skill directory>"
QUEUE_SCRIPTS="$SKILL_DIR/../task-next/scripts"
mkdir -p tools/queue
cp "$SKILL_DIR/scripts/sweep.sh" tools/sweep.sh
cp "$QUEUE_SCRIPTS/queue_backend.py" "$QUEUE_SCRIPTS/backlog_candidates.py" tools/queue/
```

Adapt the marked `# ADAPT:` sections to the project's tech stack. Keep the two installed queue
modules together when upgrading. A launcher can instead set `AGENT_QUEUE_BACKEND_SCRIPT` to the
absolute bundled script path. Both routes need `python3` on PATH. On GitHub, use an authenticated
owner, member or collaborator account so the queue can select the issues it files.

Sweep calls `queue_backend.py create` under the standing grant, reports issue refs and
failure-path pending drafts, and uses its existing `## Sweep` section format on `edit_file`.
Set `AGENT_QUEUE_LIMITS=no-queue-write` for a run whose contract expressly forbids issue writes.
Mark security findings from adapted checks with `[security]` at the start so sweep can check
visibility and withhold them from a public queue. A withheld finding is shown only to an
interactive terminal. Unattended logs carry its count without the details. An open GitHub issue
is reused on a repeat sweep. A completed issue can be filed again if the finding recurs, and an
issue closed without completion stays closed.

## Adapting to Other Ecosystems

### Node.js / TypeScript
- Lint: `npx eslint . --format compact`
- Golden principles: check for `any` type usage, missing error boundaries, untyped API responses
- Doc drift: check if modified API routes have corresponding OpenAPI spec updates

### Python
- Lint: `ruff check .` or `flake8 .`
- Golden principles: check for bare `except:`, missing type hints on public functions, raw SQL
- Doc drift: check if modified modules have corresponding docstrings

### Rust
- Lint: `cargo clippy -- -W warnings`
- Golden principles: check for `unwrap()` in non-test code, missing error types
- Doc drift: check if public API changes have doc comment updates

### Go
- Lint: `golangci-lint run`
- Golden principles: check for ignored errors (`_ = func()`), missing context propagation
- Doc drift: check if exported functions have godoc comments

---

## Load-Bearing Assessment

Every harness component encodes an assumption about what the model can't do alone. As models improve, some assumptions stop being true — and the component becomes dead weight that adds complexity without improving output.

The sweep should include a periodic (quarterly or after model upgrades) **load-bearing assessment**:

### What to check

For each harness component, ask:

1. **Is this still compensating for a real limitation?** Run the task without the component. If the output quality is the same, the component is no longer load-bearing.
2. **Has the cost/benefit shifted?** A sprint decomposition that added 2 hours overhead was worth it when it prevented context anxiety. If the model now sustains 3-hour sessions coherently, the overhead is pure waste.
3. **Is this solving a problem that no longer exists?** Explicit "don't use any type" rules made sense when models defaulted to `any`. If the model now generates strict types by default, the enforcement is noise.
4. **Does the model's own base instruction layer already say it?** Read the new model's base/system guidance and `~/.claude/CLAUDE.md` after an upgrade. A harness line the model is already given every turn is redundant on that tool — though on a multi-tool repo it may still be load-bearing for the others (see `harness-init` SKILL.md → Step 3, cross-tool limit). This is the one check where you must quote the covering text; "I think the base prompt covers it" is how correct rules get deleted.

### On a model upgrade, re-examine these first

They expire earliest because each encodes a capability ceiling rather than a repo fact:

| Component | Expires when |
|---|---|
| Context-anxiety countermeasures, forced resets, mid-task handoffs | window grows / model is told to work through summarization |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and similar early-compaction tuning | same |
| Sprint decomposition with QA gates between every feature | model sustains multi-hour coherence |
| Blocking delegation gates, per-role model pinning | main-loop model handles inline what a sub-agent was spawned for |
| Token-economy micro-rules (batch tool calls, don't re-read files) | behavior ships in the model's base instructions |

### Assessment template

```markdown
| Component | Assumption it encodes | Still true? | Evidence | Action |
|---|---|---|---|---|
| Sprint decomposition | Model can't sustain >1hr coherent work | Test | {run without it, compare quality} | Keep / Simplify / Remove |
| Pre-edit analysis gate | Model misunderstands modules it hasn't explored | Test | {check if exploration skips cause bugs} | Keep / Simplify / Remove |
| Evaluator | Model can't self-evaluate reliably | Likely still true | {self-eval bias is persistent across model generations} | Keep |
| {component} | {assumption} | {yes/no/test} | {evidence} | {action} |
```

### Simplification principle

From Anthropic's harness research: **"Find the simplest solution possible, and only increase complexity when needed."** The harness should be the minimum viable scaffolding for the current model's capabilities — not the maximum possible scaffolding for the weakest model you've ever used.

When an assessment finds a component is no longer load-bearing:
- **Remove it** if it adds friction or complexity.
- **Simplify it** if the core function is still useful but the current implementation is over-engineered.
- **Keep it** only if the cost is negligible and removal risks regression.
