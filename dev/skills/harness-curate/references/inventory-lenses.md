# Inventory file-lenses — snippets and rationale

`SKILL.md` → Step 2 names four file-lenses and keeps only the rules a run must not violate.
This file holds the runnable snippet for each and the reasons behind the constraints — read the
lens you are about to run. Nothing here is optional detail for the overlap and memory lenses:
their `--project` and `TARGET_REPO` requirements are correctness, not style.

## Stale code

Resolve each asset's repo before checking history. For every inventoried `SKILL.md` / agent
`.md` / command `.md`, run the loop below: new/untracked files (empty `git log` output) skip the
age check; assets with a commit date 60+ days ago are flagged; if repo detection fails, mark the
asset `non-git` and skip the age check rather than running `git log` from the current project.

```bash
assets=("path/to/skill/SKILL.md" "path/to/agent.md")  # populate from Step 2 Glob results
for asset in "${assets[@]}"; do
  repo_root=$(git -C "$(dirname "$asset")" rev-parse --show-toplevel 2>/dev/null)
  if [ -z "$repo_root" ]; then
    echo "non-git: $asset"  # skip stale-code age check
    continue
  fi
  last_commit=$(git -C "$repo_root" log --follow -1 --format='%ci' -- "$asset")
  if [ -z "$last_commit" ]; then
    echo "new/untracked, skip age check: $asset"
    continue
  fi
  # flag if $last_commit is 60+ days ago
done
```

Stale-but-firing → review for refresh. Never-fires (≈0 in `SKILLS-ACTIVE`) → delete candidate,
and every delete goes through Step 7's adversarial check first.

## Unparseable

Flag any `SKILL.md` / agent `.md` whose frontmatter lacks `name` or `description` — it silently
never loads, so the triggering miss has a structural cause rather than a description-quality
one. Route to a frontmatter fix, not to the description optimizer.

## Instruction-layer overlap

Read these layers in full, then pair rules that govern the same behavior.

**Read set (bounded), highest layer first:**

- **The platform's base instructions** — the model's own system prompt for this session. No file
  to open: it is already in front of you, and it is the *only* layer you cannot cite by
  `file:line` (see the evidence rule below).
- Global `~/.claude/CLAUDE.md`; `~/.codex/AGENTS.md` if present (Codex's global layer).
- The repo's `CLAUDE.md` / `AGENTS.md` at the repo root and any `AGENTS.md` in directories
  between cwd and that root — **stop at `git rev-parse --show-toplevel`, never walk into `$HOME`
  or `/`**.
- `<repo root>/.claude/rules/*.md` (Claude-only path-scoped rules — resolve from that same repo
  root, not from cwd, or a run started in a subdirectory silently drops them).
- **The `docs/*.md` files the repo's AGENTS.md Docs Index actually points to**, resolved from the
  same repo root. `docs/` is where `harness-init` deliberately routes procedure and delegation
  detail, so a rule that duplicates or contradicts an upper layer lands there just as often as in
  AGENTS.md — and never got read before. Bound the read to indexed files (an unindexed `docs/`
  file is a separate `harness-init` finding, not an overlap one); if that set is large, delegate
  the reading to `Explore` / an `Agent` and pair from the returned quotes, same as Step 1.

A pair is a finding only when it is a **duplicate** (same rule, no scope or strictness delta), a
**conflict** (incompatible instructions for the same situation), or **base-redundant** (a
repo-side rule whose entire content is behavior the base instructions already impose every turn)
— see `references/signal-taxonomy.md` §7 for the three subtypes (plus the four within-layer
diet subtypes), the non-findings list (starting with cross-tool reach, the main false positive)
and the ownership-based routing. Every finding
must carry both sides quoted verbatim with `file:line` — the base-instruction side excepted,
where the verbatim quote carries a `[base instructions — {model id}, this session]` label
instead. Unquotable pairs are dropped, not reported. Then filter the surviving pairs through the
dismissal state so resolved-or-kept pairs don't re-fire every run:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
OSTATE="$SKILL_DIR/scripts/overlap_state.py"
TARGET_REPO="<the --project path, or cwd on `current` scope>"
REPO_ROOT=$(git -C "$TARGET_REPO" rev-parse --show-toplevel)
# Write pairs.json first — one entry per candidate pair. The two keys are positional,
# not literal file names: "global" is the UPPER layer's side (base instructions,
# ~/.claude/CLAUDE.md, or ~/.codex/AGENTS.md) and "repo" is the repo-side one
# (CLAUDE.md / AGENTS.md / .claude/rules/ / docs/).
# Each value = the source, then the verbatim line you quoted above:
#   [{"global": "~/.claude/CLAUDE.md: <verbatim line>",
#     "repo":   "docs/delegation.md: <verbatim line>"}, ...]
# For a base-instruction side, the source is the label: "[base instructions — {model id}]".
# The key is a hash of the two *values*, so the source prefix is load-bearing: without it,
# the same duplicated sentence appearing in two indexed files collapses to one key, and
# dismissing one pair silently suppresses the other. Use the path, NOT path:line — line
# numbers shift on unrelated edits and would resurface settled pairs as noise. Including
# the model id in the base label is what makes a model upgrade invalidate that dismissal.
# Pairs dismissed before this rule existed were keyed on the bare lines; they resurface
# once, then re-dismiss under the new key.
python3 "$OSTATE" --check --project "$REPO_ROOT" < pairs.json   # NEW / DISMISSED per pair + counts
```

`--project` is required, not optional: the script defaults to `os.getcwd()`, so a `--project
/other/repo` run launched from anywhere else would read the *current* repo's dismissals.
`REPO_ROOT` is the same root the read set above is bounded by — reuse it for both.

Report only `NEW` rows, and carry the printed `suppressed=` count into the report. Runs on
`current` / `--project` scope only — `all` scope has no resolvable repo path per project (same
limitation as the Codex fold-in), so run `--project` per repo for cross-repo coverage.

Step 7 dismisses a resolved-or-kept pair with `--dismiss` over the same pairs.json shape and the
same `--project "$REPO_ROOT"`; a dismissal written under a different project key re-fires next
run.

## Memory-store promotion

The auto-memory store (`<config>/projects/<encoded>/memory/*.md` + its `MEMORY.md` index) is a
fifth instruction layer, and the only one that is **Claude-only and per-project**. A
repo-specific fact written there is invisible to Codex and every other tool that reads
`AGENTS.md`/`docs/` — exactly the loss the global routing rule ("repo facts → owning repo's
`docs/`, indexed by `AGENTS.md`") exists to prevent. `harness-capture` tidies this store from
inside one session; nobody audits it across sessions, which is this lens.

Resolve the directory with the scanner's own path helpers rather than re-deriving the encoding by
hand — but check the **exact** encoded path before the resolver's fuzzy pick, for the reason
spelled out below the snippet:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
TARGET_REPO="<the --project path, or cwd on `current` scope>"
MEMDIRS=$(TARGET_REPO="$TARGET_REPO" SKILL_DIR="$SKILL_DIR" python3 -c 'import os, sys; sys.path.insert(0, os.path.join(os.environ["SKILL_DIR"], "scripts")); from scan_transcripts import encode_project, resolve_project_dir; cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"); root = os.path.join(cfg, "projects"); repo = os.environ["TARGET_REPO"]; cands = [os.path.join(root, encode_project(repo)), resolve_project_dir(repo, root)]; [print(os.path.join(d, "memory")) for d in dict.fromkeys(cands)]')
echo "$MEMDIRS" | while read -r d; do [ -d "$d" ] && echo "store: $d"; done
# nothing printed → no auto-memory store for this project; the lens is a no-op
```

**`TARGET_REPO`, never `os.getcwd()`.** The resolver defaults to the current directory, so a
`--project /other/repo` run launched from anywhere else would read *this* repo's memory store
while proposing promotions into the other repo's `docs/` and writing dismissals under the other
repo's key — the same hazard the overlap lens carries above, in the same direction. Pass the
audited repo in explicitly. The one-liner is `python3 -c`, not a heredoc, on purpose: in
`SKILL.md` this snippet was nested in a list item, where an indented `PY` terminator would never
close a `<<'PY'` heredoc.

**Why two candidate paths, exact one first.** `resolve_project_dir` picks the encoded sibling
holding the most `*.jsonl` — the right rule for transcripts, the wrong one for memory. The two
directories have different producers: transcripts are written per session, the memory store by
the memory writer under the project's own encoded path, and nothing ties "most transcripts" to
"holds `memory/`". Under the case/underscore drift `_loose_key` exists to absorb, the jsonl-heavy
winner can even be a **different repo**, so the fuzzy pick is a fallback, never the primary —
check `encode_project(TARGET_REPO)` first and treat a match there as authoritative. Auditing only
the resolver's pick returns a clean "no candidates" over a store that exists, which is
indistinguishable from a real no-op. If both paths exist and disagree, report it rather than
merging them: one of them belongs to another project.

Read `MEMORY.md` and every memory file in that directory. The read produces **two** outputs
from two frontmatter fields — check `metadata.status` first, because it settles the file:

- `metadata.status` is `superseded` or `rejected` → **prune candidate**, routed to
  `dev:harness-capture` Memory hygiene for the deletion and index repair. Nothing further to
  judge; the lifecycle value already carries capture's judgment. An absent `status` reads as
  `active` and is never a finding. Detection rules and the evidence requirement:
  `references/signal-taxonomy.md` §6 → *Second output of the same lens*.
- otherwise, `metadata.type` decides promotion, below.

A memory is a **promotion candidate**
only when its frontmatter `metadata.type` is `project` or `reference` **and** its content is
scoped to this one repo. `user` and `feedback` memories are cross-repo by definition — promoting
them into a single repo's `docs/` would silently drop them everywhere else, so they stay. Full
detection rules, non-findings, and the `already-promoted` subtype:
`references/signal-taxonomy.md` §6.

**Evidence requirement (hard, same as the overlap lens) — promotion candidates:** every promotion
candidate quotes the memory body verbatim with `file:line` and names a concrete target
`docs/<topic>.md`. Cannot quote it → drop it entirely, not even `Watch:`. Before proposing,
confirm the fact is not already in `AGENTS.md` / `CLAUDE.md` / an existing `docs/*.md`.

**A prune candidate is held to its own evidence rule, not this one.** It has no `docs/` target by
construction, so requiring one here would drop every prune candidate and make the output a no-op.
It quotes the `status:` line verbatim with `file:line` and names the entry's `MEMORY.md` index
line, so the deletion's index repair has its target (`references/signal-taxonomy.md` §6 →
*Second output of the same lens*).

Filter both outputs through the same `overlap_state.py` suppression so a declined promotion —
or a `rejected` memory the user consciously keeps — does not re-fire every run. The two use
different `"repo"` values (`docs/<topic>.md (proposed)` vs `prune (harness-capture)`), so a
dismissal of one never suppresses the other for the same file. The script is unchanged and its
two keys are **positional** (see the overlap snippet above): for this lens `"global"` is always
the memory side, and `"repo"` is the proposed docs target for a promotion, `prune
(harness-capture)` for a prune.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
OSTATE="$SKILL_DIR/scripts/overlap_state.py"
TARGET_REPO="<the same repo the MEMDIRS snippet audited — or the two sides disagree>"
REPO_ROOT=$(git -C "$TARGET_REPO" rev-parse --show-toplevel)
# pairs.json for this lens — one entry per candidate, either output. The two `repo` shapes are
# what keeps a dismissed prune from suppressing the promotion for the same file:
#   promotion: {"global": "memory/<file>.md: <verbatim body line>",
#               "repo":   "docs/<topic>.md (proposed)"}
#   prune:     {"global": "memory/<file>.md: status: superseded",
#               "repo":   "prune (harness-capture)"}
python3 "$OSTATE" --check --project "$REPO_ROOT" < pairs.json
```

Same `--project "$REPO_ROOT"` requirement, same `NEW`-rows-only reporting, same `suppressed=`
count carried into the report. `current` / `--project` scope only — `all` cannot resolve the
owning repo path to promote *into*.
