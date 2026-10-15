# HWPX Content Comparison

## Problem Statement

Editing an existing HWPX needs an auditable account of what changed. A request to
change a budget must also expose an unintended date change, including its location.
The first release reports facts; it does not decide whether the user's request was met.

Current evidence:

- `prod/skills/hwpx/scripts/text.py`: `_section_lines` removes blank lines;
  `_walk` flattens paragraphs and tables without cell coordinates. Its output cannot
  serve as a position-preserving comparison model.
- `prod/skills/hwpx/scripts/validate.py`: `compare_metrics` compares counts, table
  shapes and text lengths. Equal-length date or amount replacements can pass
  `page-guard` without revealing their content differences.
- `_common.py` already owns `SECTION_RE`, including numeric section ordering.
  Paragraph and table IDs can repeat or be placeholders, so IDs alone cannot prove
  correspondence.

## Solution

Add `prod/skills/hwpx/scripts/compare.py` with separate reading, comparison and
rendering responsibilities. Python determines changes deterministically. An AI may
explain the resulting report but must not infer missing matches or turn incomplete
comparison into a clean result.

Deliver in the user's proposed order:

1. Read-only content comparison for documents with the same form, with human-readable
   and JSON reports and explicit incomplete results.
2. Original-location and expected-value checks for an explicitly allowed edit scope.
3. Side-by-side HTML review; extend formatting comparison to resolved style definitions.

The first implementation cycle delivers phase 1 only. Phases 2 and 3 remain follow-ups;
their interfaces require separate design when they become actionable.

## User Stories

- As a document editor, I want original and revised text with paragraph or cell
  locations so that I can review every detected content change.
- As a reviewer, I want uncertain correspondence and unsupported changes exposed
  so that a partial comparison cannot look like proof of no changes.
- As an automation author, I want structured output and distinct result states
  so that a changed document and a failed comparison take different paths.
- As a document owner, I want both input files preserved so that the original
  remains available for validation and visual review.

## Implementation Decisions

### Phase 1 scope and reading model

Read packaged `.hwpx` inputs directly; do not compare `text.py` output or rewrite XML.
Reuse existing section naming and safe XML parsing conventions where applicable.
Preserve the hierarchy of section, body paragraph, table, cell and cell paragraph,
including empty paragraphs. Preserve text spaces, tabs and explicit line breaks;
do not trim or collapse them. XML parsing has XML-defined newline normalization;
byte-for-byte source spelling is not the content contract.

Locations identify the section member and a hierarchical path. Display ordinals are
one-based. Table cell positions come from the original `cellAddr` grid, with row/column
spans retained, rather than enumeration of serialized cells. Report parent paths so
that repeated text cannot erase its location. Explain the numbering in CLI help.
Do not use sentence segmentation to align paragraphs: show complete before/after
paragraph strings, and group changed cell paragraphs under their containing cell.
Count each changed body paragraph or cell once, with child details that do not inflate
the summary count.

### Conservative correspondence

Compare paragraphs and cells only within a scope whose correspondence is established.
Matching element counts alone are insufficient evidence. Use hierarchy and structural
signatures, with stable identifiers or unique unchanged anchors only as corroboration;
placeholder and duplicate IDs never establish identity alone.

An insertion, deletion, reorder, grid change or merge change produces a structural
finding. Do not zip the remaining ordinals and emit misleading replacements. Mark
the affected enclosing scope incomplete when correspondence is uncertain; continue
only in independently established scopes. Include original and revised locations
separately where available. Same-count replacement/reorder ambiguities also remain
incomplete rather than claiming semantic identity.

Merged cells must retain their grid address and spans or be explicitly unsupported.
Nested tables may be reported as an unsupported enclosing scope in phase 1; they
must not be flattened into the parent cell or silently omitted.

### Coverage and non-content differences

Every result declares coverage. Detect changed unsupported objects, controls,
non-section XML and embedded assets; report their locations or ZIP members and mark
coverage incomplete where their meaning cannot be compared. Unchanged unsupported
objects are listed as exclusions, not described as fully compared.

ZIP entry timestamps, compression and member order are packaging differences, not
body edits. Attribute ordering and namespace-prefix spelling are serialization
differences, not body edits. Semantic XML comparison must preserve text and child
order. Do not blanket-ignore unfamiliar attributes or changed objects.
Classify known layout-cache differences separately from content; unknown changes
remain visible. Style changes are non-content findings in phase 1, with semantic
formatting interpretation reserved for phase 3. A zero content-change count never
means the entire documents are equivalent.

### Result contract

Provide a human-readable default and a JSON mode with no prose mixed into stdout.
Include content changes, structural findings, non-content findings, unsupported
coverage and affected incomplete scopes. Keep the change count independent of
comparison completeness: confirmed differences can coexist with incomplete scopes.
Use separate exit outcomes for complete/no differences, complete/differences,
incomplete comparison and input/processing error. Assign numeric codes and the
concrete JSON schema in the phase-1 contract before implementation.

Missing files, invalid ZIP/XML, duplicate member names, missing document sections
and unreadable required members are errors. A malformed document cannot become an
empty successful comparison. Input files must remain byte-identical after every
success and failure path. This command complements validation rather than replacing it.

### Skill integration

Document the CLI and its limits in the owning HWPX skill/reference documentation.
For edits, preserve the original, edit, validate against the original, run applicable
`page-guard`, compare, then inspect in Hancom. Retain the existing applicability of
`page-guard`; do not impose restore-only layout requirements on fresh generation.
Report unintended-looking changes for human review without automatic intent judgment.
The comparison result does not prove layout or actual Hancom loading.

## Testing Decisions

Phase 1 needs executable CLI and model regressions, wired into the existing CI
test-suite gate. Use synthetic ZIP/XML fixtures plus template-based HWPX pairs.
Write a failing feature test before implementation. Cover:

- Unpack/repack, ZIP metadata, XML attribute-order and namespace-prefix changes:
  zero content changes; no false unsupported-content alarm.
- One changed table cell: exactly that original grid location, with before/after values.
- Equal-length dates and amounts: detected despite unchanged text lengths.
- Empty paragraphs, repeated labels, significant spaces, tabs and line breaks:
  preserved and correctly located.
- Paragraph/row insertion, removal, reorder and same-count structural ambiguity:
  structural/incomplete findings without cascaded positional replacements.
- Merged cells and nested tables: valid paths/spans or explicit unsupported scopes.
- Changed unsupported objects, embedded assets and header definitions:
  visible findings, never an unqualified no-change result.
- Invalid ZIP/XML, absent sections, duplicate ZIP members and missing inputs:
  error outcome and no traceback-only success.
- Text and JSON output, all exit states, mixed changed/incomplete reports and
  input hashes before/after both successful and failing runs.

The implementation contract records the exact test command once its test entrypoint
is selected. Run repository lint, suite-wiring checks and required harness checks on
the final candidate. Visual Hancom verification is required for claims about rendered
documents; automated comparison tests make no such claim.

## Out of Scope

- Phase-1 automatic interpretation of the user's requested edit or allowed changes.
- Phase-1 HTML review and resolved-style visual comparison.
- General alignment across arbitrary document rewrites or different forms.
- Rendering, pagination proof, legacy binary HWP parsing and editing input files.
- Changing `text.py` extraction behavior or replacing existing validation gates.

## Further Notes

Source: the user's `dev:task-new` request, including its six required test scenarios.
The user approved this design with "ok." on 2026-10-15 after reviewing the draft.
This approval covers one independently mergeable phase-1 backlog ticket; its Sprint
Contract is written during implementation intake. Keep later phases deferred until
their public interfaces are specified. Shipped changes will
require synchronized prod manifest patch bumps and an HWPX skill minor bump under
`docs/conventions.md`; this design-only draft requires no release bump.
