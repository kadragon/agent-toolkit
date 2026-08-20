#!/usr/bin/env python3
"""Harness ratchet checks for shipped plugin skills (dev/, prod/).

Six independent checks, run over every `{plugin}/skills/*/SKILL.md`:

(a) Plugin-root portability — shared skill instructions and references must not
    depend on hook-only plugin root variables to locate bundled files.

(b) Capture-before-use — every `$VAR` / `${VAR}` (uppercase) referenced
    inside a fenced ```bash/```sh code block — including a bare name read inside
    `$(( ... ))` — must have a `VAR=` capture earlier in the *same* block; each block
    is a separate shell. Platform and shell-provided names are allowlisted.

(c) Section references - every `§N` / `§ "Title"` pointer and every
    `<file>.md` → *Title* arrow pointer that names a bundled `*.md` on the same
    line, plus every bare `Signal N`, must resolve to a real anchor in the
    target. PR #181 renumbered the signal taxonomy 8 -> 7 and
    shipped 5 orphaned references that only human review caught; this check is
    the mechanical replacement. Scope is deliberately cross-asset: a `§N` with no
    file named on its line (the owning file may be paragraphs back) is skipped
    rather than guessed at. A `references/`-qualified name that resolves to
    nothing fails closed — that path can only mean a bundled sibling doc, so an
    unresolvable one was deleted or renamed.

    The arrow form is what this repo actually writes (`§` is the minority
    spelling), so PR #215 found every `harness-invariants.md` citation verbally
    enforced. Two authoring conventions make it checkable without guessing:
    the section title must be *emphasised or quoted* (`*i*`, `**b**`, `"q"`, `'q'`
    — code ticks are not a title form, since `` → `--all` `` is a flag), which is
    what separates a pointer from an output label such as
    `` `refuted` → "Refuted by contest round" ``; and the file mention must sit
    *adjacent* to the arrow, with only closing punctuation or further formatted
    chain elements between them. A chain whose middle element is unformatted
    (``SKILL.md → Pre-merge cleanup → *Blocked-analysis sync*``) is therefore
    skipped — under-detection, which is the safe direction. An arrow whose target
    is itself a filename is a reading-order chain, not a section pointer.
    Because this repo hard-wraps markdown, a pointer that splits across a line
    break is graded on the two lines joined, as `(e)` already does.

    A citation may name a heading by its leading words where the remainder is a
    parenthetical or subtitle (`## Layer 0: Settings-Level Enforcement` cited as
    *Layer 0*); the remainder must start with `:`, `(` or an em dash, so *Non*
    does not "match" `## Non-Interactive Gate Defaults`. This applies to the
    arrow form only — `§ "Title"` keeps its exact match.

    An ambiguous basename (`SKILL.md`) resolves only within the referrer's own
    directory; naming another skill's copy requires the `<skill>/SKILL.md`
    qualifier, since guessing would grade the pointer against the wrong file and
    fail CI with a message naming a file the author never cited.

(d) Bundled-script references — every `$SKILL_DIR/scripts/<name>` named in a
    skill's markdown must resolve to a file that skill actually bundles, and
    every `$SKILL_DIR/../<sibling>/scripts/<name>` must resolve to a file that
    named sibling skill bundles. The runtime guard in the skill can only report
    this after invocation; this catches the packaging error at merge time
    instead. The sibling form exists because two skills in one plugin may share
    a single copy of a script (`task-new` invokes `task-next`'s `task_nodes.py`)
    rather than duplicating it and letting the copies drift.

(e) Bundled-with attributions — every `` `<file>` (bundled with `dev:<skill>`) ``
    must name the skill that actually holds `<file>`. PR #211 copied
    `task-review`'s *Result-handoff rule* verbatim into `task-next` and carried
    its stale pointer along with it: `delegation-template.md` ships with
    `dev:harness-curate`, not `dev:harness-init`. Quoting a rule verbatim
    propagates whatever cross-reference it already had wrong, so the attribution
    needs a mechanical owner check rather than a re-read of the source rule.

(f) Positional parameters — no positional in a code block or inline code span,
    in any spelling (`$1`, `${1}`, `${10}`, `${1:-x}`, `${#1}`). Observed once (PR #238): a positional inside a fenced block
    was substituted from the skill's own invocation arguments at load time, so
    `awk '{s+=$1}'` arrived as `awk '{s+=task-review}'` under `--from task-review`
    while the file on disk stayed correct — nothing in the repo showed it. The
    substitution rule is uncharacterized, so the ban is wider than the one
    confirmed case. See `docs/platform-specs.md` -> Positional Parameters in Skill
    Code Blocks.

Scope note: plugin-root portability, positional-parameter, section-reference,
bundled-script and bundled-with violations are unconditional errors.
Capture-before-use violations are HARD-FAIL only for HARD_FAIL_SKILLS (skills
fixed in an earlier sprint). Other skills report WARN so pre-existing debt
remains visible without blocking CI. Extend HARD_FAIL_SKILLS as each skill is
brought into compliance.

Usage: python3 scripts/ci/check_harness_drift.py
Exit: 0 if no hard-fail violations, 1 otherwise. Always prints a full report.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

REPO_ROOT = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)

SKILL_GLOBS = ["dev/skills/*/SKILL.md", "prod/skills/*/SKILL.md"]
# `examples/` is scanned for the same reason `references/` is: `harness-init/SKILL.md` tells the
# agent to copy blocks out of `examples/agents-md-example.md` verbatim, so it is loaded as skill
# text like any reference and carries the same load-time hazards.
REFERENCE_GLOBS = [
    "dev/skills/*/references/*.md",
    "prod/skills/*/references/*.md",
    "dev/skills/*/examples/*.md",
    "prod/skills/*/examples/*.md",
]

# Skills fixed in the skill-review-findings sprint — violations here block CI.
# All other skills are warn-only until brought into compliance separately.
HARD_FAIL_SKILLS = {"harness-init", "task-next", "hwpx", "task-review", "task-review-cycle"}

# Seeded into every block's captured set: a doc never captures these itself.
ALLOWLIST_VARS = {"HOME", "PATH"}
# Shell-provided names, applied to arithmetic-derived reads only. They turn up bare inside
# arithmetic (`(( SECONDS > 60 ))`) where nothing captures them, but a doc that assigns its
# own `LINES`/`COLUMNS` must still be graded on the `$VAR` reads of it.
SHELL_PROVIDED_VARS = {
    "SECONDS",
    "RANDOM",
    "LINENO",
    "EPOCHSECONDS",
    "OPTIND",
    "UID",
    "EUID",
    "PPID",
    "BASHPID",
    "SHLVL",
    "COLUMNS",
    "LINES",
}
FORBIDDEN_SKILL_ROOT_VARS = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")
HOOKS_FILE = REPO_ROOT / "dev/hooks.json"

FENCE_RE = re.compile(r"```(bash|sh|shell)\n(.*?)```", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
VAR_USE_RE = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")
# Any `$` followed by a digit. The braced arm deliberately spans the whole expansion, so a
# multi-digit index (`${10}`) and a modifier form (`${1:-x}`, `${1#foo}`) are caught too —
# both are positional references, and a narrow `\$\{[0-9]\}` let them through. The bare arm
# matches the leading index only, so `$10` reports as `$1`, which is how the shell reads it.
# The optional `[#!]` covers `${#1}` (length of a positional) and `${!1}` (indirection);
# `${#arr[@]}` is untouched because what follows the `#` there is not a digit.
POSITIONAL_PARAM_RE = re.compile(r"\$\{[#!]?[0-9][^}]*\}|\$[0-9]")
VAR_CAPTURE_RE = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=")
# A `#` opens a shell comment only at a word boundary. `${#arr[@]}` and the base prefix in
# `$(( 16#FF ))` are not comments, and cutting there blinded the arithmetic scan below.
COMMENT_RE = re.compile(r"(?:^|(?<=[\s;&|(]))#.*$")
# Quoted regions. `((` inside them delimits nothing — `grep -E '((A|B))'` is a regex, not
# arithmetic — so they are masked out before any arithmetic span is located.
QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
# What may precede a bare `(( ... ))` for it to be arithmetic rather than nested subshells:
# command position only.
ARITH_CMD_POS_RE = re.compile(r"(?:[;&|({!]|\b(?:for|if|while|until|then|do|elif|else|return|time))$")
# An arithmetic expansion surviving inside a double-quoted region.
DQUOTED_ARITH_RE = re.compile(r"\$\(\(.*?\)\)")
# Statement separators — a capture after one is still a capture (`)); COUNT=0`), which a
# `^`-anchored match alone would miss and turn into a fabricated violation downstream.
SEGMENT_RE = re.compile(r";|&&|\|\||&")
# A bare name inside arithmetic. `$`/`{` exclude the `$VAR` and `${VAR}` forms VAR_USE_RE
# already owns, so the two scans never double-report the same read.
# `#` joins the exclusions as a base prefix: the `FF` of `$(( 16#FF ))` is a literal digit
# string, not a variable.
ARITH_VAR_RE = re.compile(r"(?<![$\w{#])([A-Z_][A-Z0-9_]*)\b")
# Arithmetic assigns as well as reads. A plain `=` is a pure capture (`(( I=0; I<N; I++ ))`
# declares its own counter); `++`, `--` and `OP=` read the old value first, so they must not
# silence the read — `(( COUNT++ ))` on an unset name is PR #240's bug in another spelling.
ARITH_ASSIGN_RE = re.compile(
    r"(?<![$\w])([A-Z_][A-Z0-9_]*)\s*(\+\+|--|(?:<<|>>|[-+*/%&|^])?=(?!=))"
)
# Command substitution nested in arithmetic — `$(( $(DATE +%s) + 1 ))`. Its contents are a
# command line, not an arithmetic expression, so the bare-name scan must not read `DATE` as a
# variable. Any `$VAR` inside it is still caught by VAR_USE_RE over the whole line.
ARITH_CMDSUB_RE = re.compile(r"\$\([^()]*\)")

# Section references. `§3e`, `§ "Title"`, `§'Title'` — a bare `§Some Words` with
# neither number nor quotes is deliberately unmatched: those point at the global
# instruction layer, not at a bundled file.
SECTION_REF_RE = re.compile(r"§\s*(?:\"([^\"\n]+)\"|'([^'\n]+)'|(\d+[a-z]?)\b)")
# Arrow section pointers: `` `references/harness-invariants.md` → *Section Name* ``. The title
# must carry markdown emphasis or quotes — an unformatted `→ some words` is prose (a state
# transition, a routing label), not a cross-file pointer. Code ticks are deliberately NOT a
# title form: `` → `--all` `` is a flag, and this repo's tables are full of them.
ARROW_REF_RE = re.compile(
    r"→\s*(?:\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|\"([^\"\n]+)\"|'([^'\n]+)')"
)
# What may sit between the file mention and its arrow: closing punctuation (including the `*`
# of an emphasis-wrapped mention, as ATTRIBUTION_GAP_RE already allows), and further formatted
# elements of a pointer chain (`dev:harness-init` → `refs/x.md` → *Title*). Anything else means
# the nearest filename belongs to unrelated prose earlier in the line — the same adjacency
# reasoning ATTRIBUTION_GAP_RE applies to bundled-with attributions.
ARROW_GAP_RE = re.compile(
    r"^[`\"'”*)\]]*"
    r"(?:\s*→\s*(?:`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\"[^\"\n]+\"|'[^'\n]+')[`\"'”*)\]]*)*"
    r"\s*$"
)
# A citation may name a heading by its leading words where the rest is a parenthetical or
# subtitle: `## Layer 0: Settings-Level Enforcement` is cited as *Layer 0*. The remainder must
# start with a separator — a bare word boundary would let *Non* match
# `## Non-Interactive Gate Defaults`, which is not a citation of anything.
ANCHOR_PREFIX_SEP_RE = re.compile(r"^\s*[:(—]")
# `harness-init/SKILL.md`, `harness-init/references/sweep-template.md` — a path-qualified
# mention names the skill that owns the file, which is the only way to disambiguate a basename
# as common as SKILL.md. The leading segment is the skill; any further segments are its
# internal layout.
PATH_QUALIFIER_RE = re.compile(r"([A-Za-z0-9._-]+)/(?:[A-Za-z0-9._-]+/)*$")
# Known extensions only: a permissive `\.\w+` also matches prose like "e.g".
FILE_MENTION_RE = re.compile(r"([A-Za-z0-9._-]+\.(?:md|sh|py|json|ya?ml|toml|txt))")
SIGNAL_REF_RE = re.compile(r"\bSignals?\s+(\d+)(?:\s+and\s+(\d+))?\b")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
NUMERIC_ANCHOR_RE = re.compile(r"^(\d+[a-z]?)[.)]")

# `Signal N` is a bare reference — it names no file. The taxonomy that owns those
# numbers is located by basename, so a move within the skills tree still resolves.
SIGNAL_TAXONOMY_BASENAME = "signal-taxonomy.md"

# Bundled script invocations: `$SKILL_DIR/scripts/foo.py`, `"${SKILL_DIR}"/scripts/foo.sh`.
# The trailing name is matched loosely and filtered below — `$SKILL_DIR/scripts/...` is a
# prose placeholder, not a file.
BUNDLED_SCRIPT_RE = re.compile(r"\$\{?SKILL_DIR\}?\"?/scripts/([A-Za-z0-9._-]+)")
# Sibling-skill invocations: `$SKILL_DIR/../task-next/scripts/task_nodes.py`. Two skills in one
# plugin may share a single copy of a script rather than duplicating it; the reference is just as
# breakable as an own-skill one, so it gets the same merge-time check against the named sibling.
SIBLING_SCRIPT_RE = re.compile(
    r"\$\{?SKILL_DIR\}?\"?/\.\./([A-Za-z0-9._-]+)/scripts/([A-Za-z0-9._-]+)"
)
SCRIPT_PLACEHOLDER_NAMES = {"...", "..", "."}

# Attribution of a bundled file to its owning skill: `` (bundled with `dev:harness-curate`) ``.
# The plugin prefix is captured too — an attribution may point across plugins (dev -> prod).
BUNDLED_WITH_RE = re.compile(r"\(bundled with\s+`?([a-z0-9-]+):([a-z0-9-]+)`?\)")
# Only a filename *adjacent* to the attribution is the file being attributed. Anything but
# closing punctuation between the two means the attribution names no file of its own and the
# nearest mention belongs to unrelated prose — skills routinely name target-repo files
# (`backlog.md`, `tasks.md`, `docs/workflows.md`) that this repo does not ship.
ATTRIBUTION_GAP_RE = re.compile(r"^[`\"'*,;:\s]*$")


def find_skill_files() -> list[Path]:
    files: list[Path] = []
    for pattern in SKILL_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    return files


def find_reference_files() -> list[tuple[str, Path]]:
    """Return (skill_name, path) pairs for `references/*.md` docs split out of a SKILL.md.

    These aren't matched by SKILL_GLOBS (no frontmatter, live in a subdir) but can carry
    fenced bash moved out of a HARD_FAIL_SKILLS SKILL.md — check capture-before-use here too.
    """
    files: list[tuple[str, Path]] = []
    for pattern in REFERENCE_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            skill_name = path.parent.parent.name
            files.append((skill_name, path))
    return files


def parse_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (name, description) parsed from a SKILL.md frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, ""

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, ""

    fm_lines = lines[1:end]
    name = None
    description_parts: list[str] = []
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
            i += 1
            continue
        if line.startswith("description:"):
            rest = line.split(":", 1)[1].strip()
            if rest and rest not in (">-", ">", "|-", "|"):
                description_parts.append(rest)
            i += 1
            # Folded/block scalar: consume indented continuation lines.
            while i < len(fm_lines) and (fm_lines[i].startswith(" ") or fm_lines[i].strip() == ""):
                description_parts.append(fm_lines[i].strip())
                i += 1
            continue
        i += 1
    return name, " ".join(p for p in description_parts if p)


def _mask_quoted(line: str) -> str:
    """Blank out quoted regions, preserving offsets — for locating statement separators.

    A `;` inside either quote form is literal text, not a separator.
    """
    return QUOTED_RE.sub(lambda m: " " * len(m.group(0)), line)


def _mask_literal(line: str) -> str:
    """Blank out what the shell takes literally, preserving offsets — for locating arithmetic.

    Single quotes suppress expansion entirely. Double quotes do not: `echo "$(( N + 1 ))"`
    evaluates, so an arithmetic expansion inside them stays visible while the surrounding
    literal text is blanked.
    """

    def repl(m: re.Match) -> str:
        span = m.group(0)
        if span.startswith("'"):
            return " " * len(span)
        out = [" "] * len(span)
        for arith in DQUOTED_ARITH_RE.finditer(span):
            out[arith.start() : arith.end()] = span[arith.start() : arith.end()]
        return "".join(out)

    return QUOTED_RE.sub(repl, line)


def _arith_opens(masked: str, start: int = 0):
    """Yield the offset just past every real arithmetic `((` in `masked`."""
    i = start
    while True:
        j = masked.find("((", i)
        if j < 0:
            return
        i = j + 2
        if j > 0 and masked[j - 1] == "$":
            yield i
            continue
        before = masked[:j].rstrip()
        if not before or ARITH_CMD_POS_RE.search(before):
            yield i


def _fold_multiline_arith(block: str) -> str:
    r"""Join a newline-spanning `(( ... ))` onto one line so the line scan can see inside it.

    Quoted regions are masked first, so a `((` living in a string literal several lines above
    a `))` in another one cannot fold the real statements between them.
    """
    masked = "\n".join(_mask_quoted(line) for line in block.splitlines())
    out = list(block)
    i = 0
    for open_end in _arith_opens(masked):
        if open_end < i:
            continue
        close = masked.find("))", open_end)
        if close < 0:
            continue
        i = close + 2
        span = block[open_end:close]
        if "\n" not in span or '"' in span or "'" in span:
            continue
        for idx in range(open_end, close):
            if out[idx] == "\n":
                out[idx] = " "
    return "".join(out)


def _segments(line: str) -> list[str]:
    """Split `line` on statement separators that are not inside quotes."""
    masked = _mask_quoted(line)
    cuts = [0]
    for sep in SEGMENT_RE.finditer(masked):
        cuts.append(sep.end())
    return [line[a:b] for a, b in zip(cuts, cuts[1:] + [len(line)])]


def emit(reads, line, block_num, captured, earlier_blocks, problems) -> None:
    """Record a violation for each read with no capture in scope."""
    for var, shown in reads:
        if var in captured:
            continue
        where = earlier_blocks.get(var)
        origin = (
            f" — captured in block #{where}, which is a separate shell"
            if where is not None
            else ""
        )
        problems.append(
            f"block #{block_num}: {shown} used before capture{origin}"
            f" — line: {line.strip()!r}"
        )


def _arith_reads(line: str) -> tuple[list[str], set[str]]:
    """Return (bare reads, names the arithmetic captures) for the arithmetic spans on `line`.

    Sub-expressions are walked in evaluation order, split on `;`: `(( I=0; I<3; I++ ))`
    declares `I` before the condition reads it, so the loop header is self-contained. Within
    one sub-expression only the assignment's left-hand side is a capture — the right-hand
    side of `(( COUNT = COUNT + 1 ))` reads the old value, which is PR #240's bug again.
    """
    masked = _mask_literal(line)
    reads: list[str] = []
    captures: set[str] = set()
    scanned_to = 0
    for open_end in _arith_opens(masked):
        if open_end < scanned_to:
            continue
        close = masked.find("))", open_end)
        if close < 0:
            continue
        scanned_to = close + 2
        span = ARITH_CMDSUB_RE.sub(" ", line[open_end:close])
        declared: set[str] = set()
        for sub in span.split(";"):
            lhs_spans = []
            assigned = set()
            for assign in ARITH_ASSIGN_RE.finditer(sub):
                assigned.add(assign.group(1))
                if assign.group(2) == "=":
                    lhs_spans.append(assign.span(1))
            for use in ARITH_VAR_RE.finditer(sub):
                if any(s <= use.start() < e for s, e in lhs_spans):
                    continue
                name = use.group(1)
                if name in declared or name in SHELL_PROVIDED_VARS:
                    continue
                reads.append(name)
            declared |= assigned
            captures |= assigned
    return reads, captures


def check_capture_before_use(text: str) -> list[str]:
    """Return list of capture-before-use violation messages (empty = clean).

    Each fenced block is a fresh shell — an agent runs it as its own invocation — so
    captures never carry across a block boundary. `earlier_blocks` records where a name
    was captured previously only to name that boundary in the message: a read whose sole
    capture sits in an earlier block is still a violation, and the confusing case is the
    one where the doc *looks* like it captured the value.
    """
    problems = []
    earlier_blocks: dict[str, int] = {}
    for block_num, m in enumerate(FENCE_RE.finditer(text), start=1):
        captured = set(ALLOWLIST_VARS)
        # Comments go first: stripping after the fold would let a `#` on one line swallow the
        # operands that followed it on the next.
        stripped = "\n".join(COMMENT_RE.sub("", ln) for ln in m.group(2).splitlines())
        for line in _fold_multiline_arith(stripped).splitlines():
            arith, arith_captures = _arith_reads(line)
            reads = [(var, f"{var} (arithmetic)") for var in arith]
            # The arithmetic is graded against the state before it ran; what it declares is
            # only then in scope for the rest of the line (`for (( I=0; ... )); do echo $I`).
            emit(reads, line, block_num, captured, earlier_blocks, problems)
            captured |= arith_captures
            emit(
                [(var, f"${{{var}}}") for var in VAR_USE_RE.findall(line)],
                line,
                block_num,
                captured,
                earlier_blocks,
                problems,
            )
            for segment in _segments(line):
                cap = VAR_CAPTURE_RE.match(segment)
                if cap:
                    captured.add(cap.group(1))
                    earlier_blocks.setdefault(cap.group(1), block_num)
            for name in arith_captures:
                earlier_blocks.setdefault(name, block_num)
    return problems


def check_plugin_root_portability(text: str) -> list[str]:
    """Reject hook-only root variables from shared skill instructions.

    Scoped to fenced code blocks + inline code spans — a prose-only mention
    (e.g. migration notes) must not hard-fail CI.
    """
    code_text = "\n".join(m.group(1) for m in CODE_FENCE_RE.finditer(text))
    code_text += "\n" + "\n".join(m.group(1) for m in INLINE_CODE_RE.finditer(text))
    return [
        f"hook-only root variable {token!r} is not portable in shared skill instructions"
        for token in FORBIDDEN_SKILL_ROOT_VARS
        if re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])", code_text)
    ]


def check_positional_params(text: str) -> list[str]:
    """Reject positional parameters from skill code blocks and inline code spans.

    Observed once (PR #238): a positional inside a fenced block was substituted from the
    skill's own invocation arguments as the skill text was loaded — `awk '{s+=$1}'` arrived
    as `awk '{s+=task-review}'` under `--from task-review`, while the file on disk stayed
    correct. The substitution rule is uncharacterized, so this is deliberately wider than
    the one confirmed case: a block holding no positional cannot be corrupted by any variant
    of the behavior. See `docs/platform-specs.md` → Positional Parameters in Skill Code
    Blocks. Prose is exempt — describing the hazard must not fail CI.
    """
    code_lines = []
    for m in CODE_FENCE_RE.finditer(text):
        code_lines.extend(m.group(1).splitlines())
    code_lines.extend(m.group(1) for m in INLINE_CODE_RE.finditer(text))
    problems = []
    for line in code_lines:
        for token in POSITIONAL_PARAM_RE.findall(line):
            problems.append(
                f"positional parameter {token!r} in a code block is substituted from the "
                f"skill's invocation args at load time — use a named variable: {line.strip()!r}"
            )
    return problems


def check_bundled_script_refs(text: str, path: Path) -> list[str]:
    """Every `$SKILL_DIR/scripts/<name>` must resolve to a file the skill actually bundles.

    A skill's runtime guard can only report a missing bundled script *after* the user has
    invoked the skill. This catches the same packaging error at merge time, where it is
    still free to fix. Resolution is scoped to the owning skill — a script bundled by some
    *other* skill does not satisfy the reference.
    """
    skill_dir = skill_dir_of(path)
    problems = []

    def report(ref: str, target: Path) -> None:
        try:
            where = target.relative_to(REPO_ROOT)
        except ValueError:  # a path outside the repo (unit tests use a tempdir)
            where = target
        problems.append(f"references {ref}, but {where} does not exist")

    for name in sorted(set(BUNDLED_SCRIPT_RE.findall(text))):
        if name in SCRIPT_PLACEHOLDER_NAMES:
            continue
        target = skill_dir / "scripts" / name
        if not target.is_file():
            report(f"$SKILL_DIR/scripts/{name}", target)

    # A sibling reference resolves against `{plugin}/skills/<sibling>/scripts/<name>` — the
    # deliberate shared-copy case (`task-new` -> `task-next`), not a stray relative path.
    for sibling, name in sorted(set(SIBLING_SCRIPT_RE.findall(text))):
        if name in SCRIPT_PLACEHOLDER_NAMES or sibling in SCRIPT_PLACEHOLDER_NAMES:
            continue
        target = skill_dir.parent / sibling / "scripts" / name
        if not target.is_file():
            report(f"$SKILL_DIR/../{sibling}/scripts/{name}", target)

    return problems


def plugins_root_of(path: Path) -> Path:
    """Return the directory holding the `{plugin}/` dirs, derived from a checked asset.

    Derived from the asset rather than REPO_ROOT so the check runs unchanged against a
    tempdir fixture: `<root>/dev/skills/alpha/SKILL.md` -> `<root>`.
    """
    skill_dir = skill_dir_of(path)
    # skill_dir = <plugins_root>/<plugin>/skills/<name>
    return skill_dir.parent.parent.parent


def adjacent_file_mention(prefix: str) -> str | None:
    """Return the filename `prefix` ends on, or None if the tail is anything but punctuation.

    `prefix` is the text running up to an attribution (or a whole wrapped line). Only a
    mention the attribution butts against is the file being attributed; a mention further
    back belongs to unrelated prose.
    """
    mentions = list(FILE_MENTION_RE.finditer(prefix))
    if not mentions:
        return None
    last = mentions[-1]
    return last.group(1) if ATTRIBUTION_GAP_RE.match(prefix[last.end():]) else None


def check_bundled_with_refs(text: str, path: Path) -> list[str]:
    """Every `` `<file>` (bundled with `<plugin>:<skill>`) `` must name the file's real owner.

    A verbatim quote carries its cross-reference with it, so a pointer that was already
    stale spreads to every skill that copies the rule (PR #211). Resolution is by the file
    basename sitting *adjacent* to the attribution — immediately before it on the same
    line, else at the end of the immediately preceding line, since this repo hard-wraps
    markdown. Adjacency is what makes the mention the attributed file: an attribution that
    spells out no filename of its own is skipped rather than bound to whatever unrelated
    prose came earlier, since skills routinely name target-repo files (`backlog.md`,
    `tasks.md`, `docs/workflows.md`) this repo does not ship. An unresolvable adjacent name
    still fails closed — it can only mean a bundled asset that was deleted or renamed.
    """
    plugins_root = plugins_root_of(path)
    lines = text.splitlines()
    problems: list[str] = []

    def owners(basename: str) -> list[str]:
        """`<plugin>:<skill>` for every skill in the tree that bundles this basename."""
        found = []
        for skills_dir in sorted(plugins_root.glob("*/skills")):
            for skill in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
                if any(skill.rglob(basename)):
                    found.append(f"{skills_dir.parent.name}:{skill.name}")
        return found

    for lineno, line in enumerate(lines, start=1):
        for ref in BUNDLED_WITH_RE.finditer(line):
            plugin, skill = ref.group(1), ref.group(2)
            named = adjacent_file_mention(line[: ref.start()])
            if named is None and lineno >= 2:
                # Hard-wrapped prose: the filename can sit at the end of the line above.
                # Bounded to the *immediately* preceding line — walking back through blank
                # lines would attach a filename from an unrelated paragraph and report a
                # mismatch for an attribution that never named it.
                prev = lines[lineno - 2]
                if prev.strip():
                    named = adjacent_file_mention(prev)
            if named is None:
                continue

            skill_dir = plugins_root / plugin / "skills" / skill
            if not skill_dir.is_dir():
                problems.append(
                    f"line {lineno}: `{named}` is attributed to `{plugin}:{skill}`, "
                    "which is not a skill in this repo"
                )
                continue
            if any(skill_dir.rglob(named)):
                continue

            actual = owners(named)
            if actual:
                problems.append(
                    f"line {lineno}: `{named}` is attributed to `{plugin}:{skill}` "
                    f"but is bundled with {', '.join(f'`{a}`' for a in actual)}"
                )
            else:
                problems.append(
                    f"line {lineno}: `{named}` is attributed to `{plugin}:{skill}`, "
                    "but no skill in this repo bundles it"
                )
    return problems


def normalize_anchor(text: str) -> str:
    """Casefold an anchor/reference title so quoting and code ticks don't split a match."""
    cleaned = text.replace("`", "").replace('"', "").replace("'", "")
    return " ".join(cleaned.split()).strip(" .:;,-").casefold()


def collect_anchors(text: str) -> tuple[set[str], set[str]]:
    """Return (numeric anchors, titled anchors) a `§` reference may point at.

    Both ATX headings and `**bold**` spans count: this repo anchors some sections on a
    bold callout rather than a heading (e.g. `prod/skills/hwpx/SKILL.md` line 243).
    """
    numeric: set[str] = set()
    titles: set[str] = set()
    for raw in [m.group(1) for m in HEADING_RE.finditer(text)] + BOLD_RE.findall(text):
        stripped = raw.replace("`", "").strip()
        num = NUMERIC_ANCHOR_RE.match(stripped)
        if num:
            numeric.add(num.group(1))
        titles.add(normalize_anchor(raw))
    return numeric, titles


def skill_dir_of(path: Path) -> Path:
    """Return the `{plugin}/skills/{name}` directory owning a SKILL.md or references/*.md."""
    for parent in path.parents:
        if parent.parent.name == "skills":
            return parent
    return path.parent


def build_basename_index(paths: list[Path]) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in paths:
        index.setdefault(path.name, []).append(path)
    return index


def anchor_matches(title: str, titled_anchors: set[str]) -> bool:
    """True when `title` names one of `titled_anchors`, exactly or as a leading prefix.

    The prefix form is how this repo cites headings that carry a parenthetical or colon
    suffix — `## Spawn Prompt Contract (shared invariant)` is cited as *Spawn Prompt
    Contract*. The prefix must end at a separator or word boundary so a genuinely renamed
    heading still fails.
    """
    normalized = normalize_anchor(title)
    if normalized in titled_anchors:
        return True
    return any(
        anchor.startswith(normalized) and ANCHOR_PREFIX_SEP_RE.match(anchor[len(normalized):])
        for anchor in titled_anchors
    )


def resolve_md_target(
    name: str,
    source: Path,
    basename_index: dict[str, list[Path]],
    qualifier: str | None = None,
) -> Path | None:
    """Resolve a referenced `*.md` basename to a bundled asset, or None if it isn't one.

    None means "not ours to check" — skills routinely name target-repo files such as
    `backlog.md`, `tasks.md`, or `docs/workflows.md`, which do not exist in this repo.

    `qualifier` is the directory segment the mention was written under
    (`harness-init/SKILL.md` -> `harness-init`). Where it names a skill that bundles the
    file, it wins: without it an ambiguous basename falls through to the referrer's own
    copy and the pointer gets graded against the wrong file. `references` is excluded — it
    is a path segment inside a skill, not a skill name, and its unresolvable case is
    deliberately handled by the fail-closed branch in the callers.
    """
    candidates = basename_index.get(name, [])
    if qualifier and qualifier != "references":
        qualified = [c for c in candidates if skill_dir_of(c).name == qualifier]
        if len(qualified) == 1:
            return qualified[0]
        if qualified:
            # A skill shipping the same basename twice (say `assets/notes.md` and
            # `references/notes.md`) makes the qualifier ambiguous. Picking by index order
            # would guess, and falling through is worse still — the unqualified path
            # resolves a common basename to the *referrer's* copy. Skip, as the ambiguous
            # case below already does.
            return None
        if qualifier in {skill_dir_of(p).name for paths in basename_index.values() for p in paths}:
            # The qualifier names a real skill that does not bundle this file. Falling
            # through would resolve it to some *other* skill's copy and report the pointer
            # as clean, hiding the mis-attribution. Skip instead of guessing.
            return None
        # Otherwise the qualifier is a plain path segment (`docs/`), not a skill name —
        # resolve as if it were absent.

    # `SKILL.md` is not a unique basename, so a cross-skill reference to one resolves to the
    # referrer's own copy on the `skill_dir` probes and gets graded against the wrong anchors.
    # Only the referrer's own directory is an unambiguous read; anything else needs the
    # `<skill>/SKILL.md` qualifier above.
    ambiguous = len(candidates) > 1
    skill_dir = skill_dir_of(source)
    probes = (
        (source.parent / name,)
        if ambiguous
        else (source.parent / name, skill_dir / name, skill_dir / "references" / name)
    )
    for candidate in probes:
        if candidate.is_file():
            return None if (ambiguous and candidate == source) else candidate
    # Cross-skill reference (e.g. harness-init pointing at harness-curate's taxonomy):
    # a unique basename across all bundled assets is an unambiguous target.
    matches = basename_index.get(name, [])
    return matches[0] if len(matches) == 1 else None


def resolve_line_target(
    line: str, ref_start: int, source: Path, basename_index: dict[str, list[Path]]
) -> tuple[Path | None, str | None, int | None]:
    """Resolve the bundled `*.md` a reference at `ref_start` points into.

    Returns `(target, problem, mention_end)`. `target` and `problem` are never both set;
    both are None when the line names nothing this check owns — no file mention before the
    reference, a non-markdown target, or a target-repo file the plugin does not ship.
    `mention_end` is the offset just past the resolved filename, so callers can measure the
    gap between the mention and the reference.
    """
    mentions = [m for m in FILE_MENTION_RE.finditer(line) if m.start() < ref_start]
    if not mentions:
        # No file named before this reference. Prose continues across lines, so the owning
        # file may be paragraphs back — unresolvable without guessing. Cross-asset
        # references are the scope here; bare `§N` is left to human review.
        return None, None, None
    mention = mentions[-1]
    named = mention.group(1)
    if not named.endswith(".md"):
        # e.g. `validate-harness.sh` §11 — a script has no heading structure.
        return None, None, mention.end()

    prefix = line[: mention.start()]
    qualifier = PATH_QUALIFIER_RE.search(prefix)
    target = resolve_md_target(
        named, source, basename_index, qualifier.group(1) if qualifier else None
    )
    if target is None:
        # A `references/` path names a bundled sibling doc, so failing to resolve one
        # means it was deleted or renamed — the very drift this check exists for.
        # Fail closed there; every other unresolved name is a target-repo file
        # (`backlog.md`, `docs/workflows.md`) the plugin does not ship.
        if prefix.endswith("references/"):
            return (
                None,
                f"references/{named} is not a bundled file (deleted, renamed, or a typo)",
                mention.end(),
            )
        return None, None, mention.end()
    return target, None, mention.end()


def check_section_refs(
    text: str,
    source: Path,
    basename_index: dict[str, list[Path]],
    anchor_cache: dict[Path, tuple[set[str], set[str]]],
) -> list[str]:
    """Return messages for `§`/`Signal N` references that resolve to no anchor."""

    def anchors(path: Path) -> tuple[set[str], set[str]]:
        if path not in anchor_cache:
            anchor_cache[path] = collect_anchors(path.read_text(encoding="utf-8"))
        return anchor_cache[path]

    taxonomy_matches = basename_index.get(SIGNAL_TAXONOMY_BASENAME, [])
    taxonomy = taxonomy_matches[0] if len(taxonomy_matches) == 1 else None
    # `Signal N` is only the taxonomy's numbering inside the skills that use it. Unrelated
    # prose elsewhere (a "Signal 3" in a hwpx or persona-debate doc) must not be graded
    # against harness-curate's headings, so require the file to reach for the taxonomy.
    if taxonomy is not None and not (
        SIGNAL_TAXONOMY_BASENAME in text or skill_dir_of(source) == skill_dir_of(taxonomy)
    ):
        taxonomy = None

    problems = []
    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        for ref in SECTION_REF_RE.finditer(line):
            title = ref.group(1) or ref.group(2)
            number = ref.group(3)

            target, problem, _ = resolve_line_target(line, ref.start(), source, basename_index)
            if problem is not None:
                problems.append(f"line {lineno}: {problem}")
                continue
            if target is None:
                continue

            where = str(target.relative_to(REPO_ROOT))
            numeric_anchors, titled_anchors = anchors(target)
            if number is not None:
                if number not in numeric_anchors:
                    problems.append(f"line {lineno}: §{number} has no section {number}. in {where}")
            elif normalize_anchor(title) not in titled_anchors:
                problems.append(f'line {lineno}: § "{title}" has no matching section in {where}')

        # Arrow pointers are scanned twice: once over the line itself, and once over the line
        # joined to the one above it, keeping only matches that straddle the join. This repo
        # hard-wraps markdown, so a pointer routinely splits across the break — the same reason
        # check_bundled_with_refs reaches back exactly one line.
        scans = [(line, 0)]
        previous = lines[lineno - 2] if lineno >= 2 else ""
        if previous.strip():
            joined = previous.rstrip() + " "
            scans.append((joined + line, len(joined)))

        for scan, join_at in scans:
            for ref in ARROW_REF_RE.finditer(scan):
                if join_at and not (ref.start() < join_at <= ref.end()):
                    # Wholly inside one of the two lines — graded when that line is its own scan.
                    continue
                title = next(group for group in ref.groups() if group is not None)
                if FILE_MENTION_RE.fullmatch(title.strip()):
                    # `hwpx-format.md → editing-gotchas.md → …` is a reading order, not a pointer.
                    continue

                target, problem, mention_end = resolve_line_target(
                    scan, ref.start(), source, basename_index
                )
                if problem is not None:
                    problems.append(f"line {lineno}: {problem}")
                    continue
                if target is None:
                    continue
                if not ARROW_GAP_RE.match(scan[mention_end : ref.start()]):
                    # The filename is not adjacent to the arrow, so it belongs to unrelated
                    # prose and this arrow is a label rather than a cross-file pointer.
                    continue

                _, titled_anchors = anchors(target)
                if not anchor_matches(title, titled_anchors):
                    problems.append(
                        f'line {lineno}: → "{title}" has no matching section in '
                        f"{target.relative_to(REPO_ROOT)}"
                    )

        if taxonomy is None:
            continue
        numeric_anchors, _ = anchors(taxonomy)
        for ref in SIGNAL_REF_RE.finditer(line):
            for number in (ref.group(1), ref.group(2)):
                if number is not None and number not in numeric_anchors:
                    problems.append(
                        f"line {lineno}: Signal {number} has no section {number}. in "
                        f"{taxonomy.relative_to(REPO_ROOT)}"
                    )
    # One line can carry several references into the same unresolvable file (a `§` and an
    # arrow, or a two-hop arrow chain). Each would repeat the identical message and inflate
    # the violation count, so report each distinct message once, in the order it was found.
    return list(dict.fromkeys(problems))


def check_windows_hook_commands() -> list[str]:
    """Require an explicit PowerShell-safe override for every dev command hook."""
    try:
        data = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read {HOOKS_FILE.relative_to(REPO_ROOT)}: {exc}"]

    problems = []
    for event, groups in data.get("hooks", {}).items():
        for group_index, group in enumerate(groups):
            for hook_index, hook in enumerate(group.get("hooks", [])):
                if hook.get("type") != "command":
                    continue
                location = f"{event}[{group_index}].hooks[{hook_index}]"
                command = hook.get("commandWindows")
                if not isinstance(command, str) or not command.strip():
                    problems.append(f"{location}: commandWindows missing")
                    continue
                if "${" in command:
                    problems.append(f"{location}: commandWindows contains Bash parameter expansion")
                if "$env:PLUGIN_ROOT" not in command:
                    problems.append(f"{location}: commandWindows must use $env:PLUGIN_ROOT")
    return problems


def main() -> int:
    skill_files = find_skill_files()
    if not skill_files:
        print("SKIP: no skill files found")
        return 0

    reference_files = find_reference_files()
    basename_index = build_basename_index(skill_files + [p for _, p in reference_files])
    anchor_cache: dict[Path, tuple[set[str], set[str]]] = {}

    hard_fail = False
    windows_hook_problems = check_windows_hook_commands()
    for msg in windows_hook_problems:
        print(f"ERROR {HOOKS_FILE.relative_to(REPO_ROOT)} [commandWindows]: {msg}")
    if windows_hook_problems:
        hard_fail = True
    else:
        print(f"OK   {HOOKS_FILE.relative_to(REPO_ROOT)}: PowerShell command overrides clean")
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        name, _ = parse_frontmatter(text)
        rel = path.relative_to(REPO_ROOT)
        if not name:
            print(f"WARN {rel}: could not parse `name:` from frontmatter — skipping")
            continue

        severity = "ERROR" if name in HARD_FAIL_SKILLS else "WARN"

        portability = check_plugin_root_portability(text)
        positional = check_positional_params(text)
        capture = check_capture_before_use(text)
        section_refs = check_section_refs(text, path, basename_index, anchor_cache)
        script_refs = check_bundled_script_refs(text, path)
        with_refs = check_bundled_with_refs(text, path)

        if (not portability and not positional and not capture and not section_refs
                and not script_refs and not with_refs):
            print(
                f"OK   {rel} ({name}): plugin-root portability + positional params "
                "+ capture-before-use + section refs + bundled scripts "
                "+ bundled-with attributions clean"
            )
            continue

        for msg in portability:
            print(f"ERROR {rel} ({name}) [plugin-root-portability]: {msg}")
        for msg in positional:
            print(f"ERROR {rel} ({name}) [positional-param]: {msg}")
        for msg in capture:
            print(f"{severity} {rel} ({name}) [capture-before-use]: {msg}")
        for msg in section_refs:
            print(f"ERROR {rel} ({name}) [section-ref]: {msg}")
        for msg in script_refs:
            print(f"ERROR {rel} ({name}) [bundled-script-ref]: {msg}")
        for msg in with_refs:
            print(f"ERROR {rel} ({name}) [bundled-with-ref]: {msg}")

        if portability or positional or section_refs or script_refs or with_refs:
            hard_fail = True
        if severity == "ERROR" and capture:
            hard_fail = True

    # WARN-only: these files weren't scanned at all before (no frontmatter, glob
    # miss), so surfacing them is new visibility. Promoting straight to hard-fail
    # would retroactively block CI on pre-existing debt in untouched reference
    # docs (e.g. hwpx's $SKILL_DIR pattern) — track those via backlog, not here.
    for skill_name, path in reference_files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        portability = check_plugin_root_portability(text)
        positional = check_positional_params(text)
        capture = check_capture_before_use(text)
        section_refs = check_section_refs(text, path, basename_index, anchor_cache)
        script_refs = check_bundled_script_refs(text, path)
        with_refs = check_bundled_with_refs(text, path)

        if (not portability and not positional and not capture and not section_refs
                and not script_refs and not with_refs):
            print(
                f"OK   {rel} ({skill_name}): plugin-root portability + positional params "
                "+ capture-before-use + section refs + bundled scripts "
                "+ bundled-with attributions clean"
            )
            continue

        for msg in portability:
            print(f"ERROR {rel} ({skill_name}) [plugin-root-portability]: {msg}")
        for msg in positional:
            print(f"ERROR {rel} ({skill_name}) [positional-param]: {msg}")
        for msg in capture:
            print(f"WARN {rel} ({skill_name}) [capture-before-use]: {msg}")
        for msg in section_refs:
            print(f"ERROR {rel} ({skill_name}) [section-ref]: {msg}")
        for msg in script_refs:
            print(f"ERROR {rel} ({skill_name}) [bundled-script-ref]: {msg}")
        for msg in with_refs:
            print(f"ERROR {rel} ({skill_name}) [bundled-with-ref]: {msg}")

        if portability or positional or section_refs or script_refs or with_refs:
            hard_fail = True

    print("----")
    if hard_fail:
        print("FAIL: portability or hard-fail violations found (see ERROR lines above).")
        return 1
    print("OK: no hard-fail violations (WARN-only items are tracked separately).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
