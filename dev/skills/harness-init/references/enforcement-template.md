# Enforcement Chain Template

Documentation alone does not prevent violations. Each layer below makes a rule mechanical; ship
only the layers the repo's maturity level or a demonstrated risk calls for (SKILL.md Step 7).

```
Settings deny the action outright            (Layer 0: model-independent)
Agent edits a file
  -> PostToolUse hook reports immediately      (Layer 1: real-time)
  -> Pre-commit blocks the commit if unfixed   (Layer 2: pre-commit)
  -> CI blocks the merge                       (Layer 3: CI gate)
```

Any repo with a destructive surface (auth/billing/migrations/infra) carries Layer 0 deny rules at
any maturity level.

## Layer 0: Settings-Level Enforcement (`.claude/settings.json` / managed settings)

**The only model-independent layer.** Hooks run code (can be argued with via clever prompts, or skipped if a hook path breaks); prose (CLAUDE.md, AGENTS.md) is guidance the model "has no guarantee of strict compliance" with. `permissions.deny` and `sandbox.enabled` are enforced by the client *before the model's decision matters at all*. Hard blocks belong here.

```json
{
  "permissions": {
    "deny": [
      "Bash(rm -rf*)",
      "Bash(git push --force*)",
      "Read(./.env)",
      "Read(./secrets/**)",
      "Write(/etc/**)",
      "Edit(/etc/**)",
      "MultiEdit(/etc/**)"
    ]
  },
  "sandbox": { "enabled": true }
}
```

- **`permissions.deny`** — glob/command patterns the agent can never run, regardless of prompt. Use for destructive Bash, secret reads, writes outside the repo. **A path-write block must list every write-capable tool** — `Write` *and* `Edit`/`MultiEdit` — or an agent edits the existing file through the unlisted tool and the guard is bypassed. (Reads similarly: pair `Read` with `Grep`/`Glob` if you mean to hide a path entirely.) For broad isolation, prefer `sandbox.enabled` over enumerating tools.
- **`sandbox.enabled`** — OS-level filesystem + network isolation for Bash; commands run without prompts inside defined boundaries and cannot escape them.
- **Managed settings** (`managed-settings.json`, or platform-specific managed `CLAUDE.md` via the `claudeMd` key) — org-level, **cannot be excluded by the repo**. Use when policy must hold across every clone, not just this checkout.

**Enforcement ladder (official decision rule):**

| Need | Mechanism |
|------|-----------|
| Must be **blocked no matter what** | Layer 0: `permissions.deny` / `sandbox` / managed settings |
| Must **always run** on an event | Hook (Layer 1) — `PreToolUse` to gate, `PostToolUse` to react |
| Must be **followed when relevant** | `docs/` (cross-tool) — or `.claude/rules/` path-scoped on a Claude-only repo |
| Background knowledge | `docs/` (on demand) |

CLAUDE.md and prose are guidance, never enforcement. "To block an action regardless of what Claude decides, use a PreToolUse hook" or a settings-level deny.

## Hook Signaling Reference (exit codes vs JSON)

Pick **one** signaling style per hook — exit codes OR exit-0 + JSON, never both.

- **Exit 0** → success. On blockable events, stdout is parsed for JSON (JSON is only processed on exit 0).
- **Exit 2** → blocking error. stdout/JSON ignored; **stderr is surfaced to the agent as feedback**. Effect depends on the event.
- **Other exit codes** → non-blocking error; execution continues.

**Which events can actually block (exit 2 / `deny` honored):** `PreToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `PermissionRequest`, and the task/team lifecycle events. **Cannot block (exit 2 only surfaces stderr, the action already happened):** `PostToolUse`, `PostToolUseFailure`, `SessionStart`/`SessionEnd`, `Notification`, `SubagentStart`.

**Preferred `PreToolUse` form** — exit 0 with JSON, which is clearer than exit 2 and can also rewrite tool input:

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse",
 "permissionDecision":"deny","permissionDecisionReason":"why, and how to proceed instead"}}
```

`permissionDecision` ∈ `allow` | `deny` | `ask` | `defer`.

**Event set is larger than the classics** (`SubagentStart`, `PostToolBatch`, `TaskCreated`/`TaskCompleted`, `InstructionsLoaded`, `PreCompact`/`PostCompact`, `SessionEnd`, …); the classics cover single-agent harnesses.

## Layers 1–3: hooks, pre-commit, CI

Each layer runs the **same check script** (`tools/check-<rule>.sh`), so a rule has one
implementation and three trigger points. Its failure output names the violated rule, how to fix
it, and the doc that owns the rule.

- **Layer 1 — real-time hook.** Register in `.claude/settings.json`; `PreToolUse` to gate an edit,
  `PostToolUse` to report after it (cannot block — see the signaling table above):

  ```json
  {"hooks": {"PostToolUse": [{"matcher": "Edit|Write",
    "hooks": [{"type": "command", "command": "bash .claude/hooks/post-edit-check.sh"}]}]}}
  ```

- **Layer 2 — pre-commit.** Wire the script into the repo's existing framework (`pre-commit`,
  Husky/lint-staged) or a plain `.git/hooks/pre-commit`; pass the staged file list.
- **Layer 3 — CI gate.** Run the script as a required job on pull requests. This is the only layer
  that holds for every contributor and every tool, so a Level 3 rule always lands here.
