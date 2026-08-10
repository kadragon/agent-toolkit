#!/usr/bin/env python3
"""Harness ratchet checks for shipped plugin skills (dev/, prod/).

Three independent checks, run over every `{plugin}/skills/*/SKILL.md`:

(a) Plugin-root portability — shared skill instructions and references must not
    depend on hook-only plugin root variables to locate bundled files.

(b) Capture-before-use — every `$VAR` / `${VAR}` (uppercase) referenced
    inside a fenced ```bash/```sh code block must have a `VAR=` capture
    earlier in the *same* block. Platform env vars (HOME, PATH) are allowlisted.

(c) Section references - every `§N` / `§ "Title"` pointer that names a bundled
    `*.md` on the same line, plus every bare `Signal N`, must resolve to a real
    anchor in the target. PR #181 renumbered the signal taxonomy 8 -> 7 and
    shipped 5 orphaned references that only human review caught; this check is
    the mechanical replacement. Scope is deliberately cross-asset: a `§N` with no
    file named on its line (the owning file may be paragraphs back) is skipped
    rather than guessed at. A `references/`-qualified name that resolves to
    nothing fails closed — that path can only mean a bundled sibling doc, so an
    unresolvable one was deleted or renamed.

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

Scope note: plugin-root portability, section-reference, bundled-script and
bundled-with violations are unconditional errors.
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
REFERENCE_GLOBS = [
    "dev/skills/*/references/*.md",
    "prod/skills/*/references/*.md",
]

# Skills fixed in the skill-review-findings sprint — violations here block CI.
# All other skills are warn-only until brought into compliance separately.
HARD_FAIL_SKILLS = {"harness-init", "task-next", "hwpx", "task-review"}

ALLOWLIST_VARS = {"HOME", "PATH"}
FORBIDDEN_SKILL_ROOT_VARS = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")
HOOKS_FILE = REPO_ROOT / "dev/hooks.json"

FENCE_RE = re.compile(r"```(bash|sh|shell)\n(.*?)```", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
VAR_USE_RE = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")
VAR_CAPTURE_RE = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=")

# Section references. `§3e`, `§ "Title"`, `§'Title'` — a bare `§Some Words` with
# neither number nor quotes is deliberately unmatched: those point at the global
# instruction layer, not at a bundled file.
SECTION_REF_RE = re.compile(r"§\s*(?:\"([^\"\n]+)\"|'([^'\n]+)'|(\d+[a-z]?)\b)")
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


def check_capture_before_use(text: str) -> list[str]:
    """Return list of capture-before-use violation messages (empty = clean)."""
    problems = []
    for block_num, m in enumerate(FENCE_RE.finditer(text), start=1):
        captured = set(ALLOWLIST_VARS)
        block_lines = m.group(2).splitlines()
        for line in block_lines:
            # Ignore full-line and inline comments — commented-out $VAR is not a use.
            line = line.split("#", 1)[0]
            for var in VAR_USE_RE.findall(line):
                if var not in captured:
                    problems.append(
                        f"block #{block_num}: ${{{var}}} used before capture — line: {line.strip()!r}"
                    )
            cap = VAR_CAPTURE_RE.match(line)
            if cap:
                captured.add(cap.group(1))
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


def check_bundled_with_refs(text: str, path: Path) -> list[str]:
    """Every `` `<file>` (bundled with `<plugin>:<skill>`) `` must name the file's real owner.

    A verbatim quote carries its cross-reference with it, so a pointer that was already
    stale spreads to every skill that copies the rule (PR #211). Resolution is by the
    file basename named just before the attribution — same line, else the nearest
    preceding non-blank line, since this repo hard-wraps markdown. An attribution with no
    filename anywhere in reach is skipped rather than guessed at.
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
            mentions = [m.group(1) for m in FILE_MENTION_RE.finditer(line[: ref.start()])]
            if not mentions and lineno >= 2:
                # Hard-wrapped prose: the filename can sit at the end of the line above.
                # Bounded to the *immediately* preceding line — walking back through blank
                # lines would attach a filename from an unrelated paragraph and report a
                # mismatch for an attribution that never named it.
                prev = lines[lineno - 2]
                if prev.strip():
                    mentions = [m.group(1) for m in FILE_MENTION_RE.finditer(prev)]
            if not mentions:
                continue
            named = mentions[-1]

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


def resolve_md_target(
    name: str, source: Path, basename_index: dict[str, list[Path]]
) -> Path | None:
    """Resolve a referenced `*.md` basename to a bundled asset, or None if it isn't one.

    None means "not ours to check" — skills routinely name target-repo files such as
    `backlog.md`, `tasks.md`, or `docs/workflows.md`, which do not exist in this repo.
    """
    # `SKILL.md` is not a unique basename, so a cross-skill reference to one would resolve
    # to the referrer itself on the first probe and be graded against the wrong anchors.
    ambiguous = len(basename_index.get(name, [])) > 1
    skill_dir = skill_dir_of(source)
    for candidate in (source.parent / name, skill_dir / name, skill_dir / "references" / name):
        if candidate.is_file():
            return None if (ambiguous and candidate == source) else candidate
    # Cross-skill reference (e.g. harness-init pointing at harness-curate's taxonomy):
    # a unique basename across all bundled assets is an unambiguous target.
    matches = basename_index.get(name, [])
    return matches[0] if len(matches) == 1 else None


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
    for lineno, line in enumerate(text.splitlines(), start=1):
        for ref in SECTION_REF_RE.finditer(line):
            title = ref.group(1) or ref.group(2)
            number = ref.group(3)

            mentions = [m for m in FILE_MENTION_RE.finditer(line) if m.start() < ref.start()]
            if not mentions:
                # No file named on this line. Prose continues across lines, so the owning
                # file may be paragraphs back — unresolvable without guessing. Cross-asset
                # references are the scope here; bare `§N` is left to human review.
                continue
            named = mentions[-1].group(1)
            if not named.endswith(".md"):
                # e.g. `validate-harness.sh` §11 — a script has no heading structure.
                continue
            target = resolve_md_target(named, source, basename_index)
            if target is None:
                # A `references/` path names a bundled sibling doc, so failing to resolve one
                # means it was deleted or renamed — the very drift this check exists for.
                # Fail closed there; every other unresolved name is a target-repo file
                # (`backlog.md`, `docs/workflows.md`) the plugin does not ship.
                if line[: mentions[-1].start()].endswith("references/"):
                    problems.append(
                        f"line {lineno}: references/{named} is not a bundled file "
                        "(deleted, renamed, or a typo)"
                    )
                continue

            where = str(target.relative_to(REPO_ROOT))
            numeric_anchors, titled_anchors = anchors(target)
            if number is not None:
                if number not in numeric_anchors:
                    problems.append(f"line {lineno}: §{number} has no section {number}. in {where}")
            elif normalize_anchor(title) not in titled_anchors:
                problems.append(f'line {lineno}: § "{title}" has no matching section in {where}')

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
    return problems


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
        capture = check_capture_before_use(text)
        section_refs = check_section_refs(text, path, basename_index, anchor_cache)
        script_refs = check_bundled_script_refs(text, path)
        with_refs = check_bundled_with_refs(text, path)

        if not portability and not capture and not section_refs and not script_refs and not with_refs:
            print(
                f"OK   {rel} ({name}): plugin-root portability + capture-before-use "
                "+ section refs + bundled scripts + bundled-with attributions clean"
            )
            continue

        for msg in portability:
            print(f"ERROR {rel} ({name}) [plugin-root-portability]: {msg}")
        for msg in capture:
            print(f"{severity} {rel} ({name}) [capture-before-use]: {msg}")
        for msg in section_refs:
            print(f"ERROR {rel} ({name}) [section-ref]: {msg}")
        for msg in script_refs:
            print(f"ERROR {rel} ({name}) [bundled-script-ref]: {msg}")
        for msg in with_refs:
            print(f"ERROR {rel} ({name}) [bundled-with-ref]: {msg}")

        if portability or section_refs or script_refs or with_refs:
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
        capture = check_capture_before_use(text)
        section_refs = check_section_refs(text, path, basename_index, anchor_cache)
        script_refs = check_bundled_script_refs(text, path)
        with_refs = check_bundled_with_refs(text, path)

        if not portability and not capture and not section_refs and not script_refs and not with_refs:
            print(
                f"OK   {rel} ({skill_name}): plugin-root portability + capture-before-use "
                "+ section refs + bundled scripts + bundled-with attributions clean"
            )
            continue

        for msg in portability:
            print(f"ERROR {rel} ({skill_name}) [plugin-root-portability]: {msg}")
        for msg in capture:
            print(f"WARN {rel} ({skill_name}) [capture-before-use]: {msg}")
        for msg in section_refs:
            print(f"ERROR {rel} ({skill_name}) [section-ref]: {msg}")
        for msg in script_refs:
            print(f"ERROR {rel} ({skill_name}) [bundled-script-ref]: {msg}")
        for msg in with_refs:
            print(f"ERROR {rel} ({skill_name}) [bundled-with-ref]: {msg}")

        if portability or section_refs or script_refs or with_refs:
            hard_fail = True

    print("----")
    if hard_fail:
        print("FAIL: portability or hard-fail violations found (see ERROR lines above).")
        return 1
    print("OK: no hard-fail violations (WARN-only items are tracked separately).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
