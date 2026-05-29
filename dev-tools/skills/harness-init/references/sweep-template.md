# Sweep Script Template

The sweep script is the automated garbage collector for the harness. It catches drift, stale docs, and principle violations before they compound.

## Base Script

A ready-to-use sweep script is available at `../scripts/sweep.sh`. Copy it into the target project's `tools/` directory and adapt the marked `# ADAPT:` sections to the project's tech stack.

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
