# Agent Rules Example

Adapt this example to verified repository needs. Keep the Docs Index, Working with Existing
Code and Language Policy; omit conditional sections with no applicable content. Index only
existing docs, and preserve project-specific safety boundaries.

## Docs Index (read on demand)

| File | When to read |
|------|--------------|
| `docs/runbook.md` | For build, test, deploy commands and troubleshooting |

Add architecture, conventions, workflows, or evaluation rows only for docs created under
harness-init Step 4. Add a delegation-doc pointer only when that doc exists.

## Golden Principles (conditional)

Include only real, project-specific invariants and their executable enforcement. For example,
a project whose lint config restricts database imports could document that boundary here.
No minimum item count; omit this section when there is no applicable invariant.

## Delegation (conditional)

Include when configured roles or a real delegation workflow exist. Default inline; delegate
only within higher-level authorization and the repository's justified thresholds. Independent
verification can justify separate work without parallel implementation. Name only available
roles, and point to an existing workflow/routing doc when detail is needed.

A new init creates no roles or orchestrator by default. Omit this section and its routing
pointers in that case. Derive local thresholds from evidence, not analysis-output length or
an assumed global numeric rule. Existing Claude roles and Codex custom-agent configuration
are delegation surfaces; neither platform requires duplicate roles on the other.

## Token Economy (optional)

Retain only useful project-specific instructions, such as which large generated artifacts to
exclude from routine reads. Omit this section when higher layers already cover its guidance.

## Working with Existing Code

State verified operational boundaries the linter cannot express. For example, generated
components may require regeneration rather than manual editing. Test/build commands belong
in the runbook. Replace these examples with the repository's actual boundaries.

## Language Policy

- Code, commits, docs: use the language resolved from existing repository/global policy.
- User-facing strings: follow the existing localization convention.

## Maintenance

Update this file for stable operational guidance that code/configuration does not reveal and
whose absence would cause mistakes. Prefer correcting stale guidance over appending. A valid
pointer to an existing edit policy is also sufficient; this heading and wording are optional.

Target <=100 lines. Validation warns above 100, strongly warns above 200, and never fails on
size alone; session checks warn above 200. Move detail into existing docs with a pointer.
Durable repository facts belong in version-controlled harness files; follow the operator's
memory policy for preferences and learned context. No block has a verbatim-copy exemption.
