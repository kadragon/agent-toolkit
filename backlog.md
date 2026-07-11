# Backlog

## Now

- [ ] [infra] Create `.claude/agents/{explorer,implementer,qa-verifier,skill-evaluator}.md` — docs/delegation.md and skill-dev-orchestrator route to these subagent_type names but none exist in the repo, so `Agent({subagent_type: "implementer"})` etc. fail with "Agent type not found" every run and require silent fallback to `general-purpose`. Found 2026-07-08 while running skill-dev-orchestrator for a harness-curator fix.

