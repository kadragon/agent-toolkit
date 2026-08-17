#!/usr/bin/env python3
"""Frontmatter validity check for shipped plugin assets (skills, agents, commands).

Guards one silent failure mode: an asset whose frontmatter Claude Code cannot read.
The loader does not error — it loads the asset with *empty metadata*, so the
`description:` that drives auto-invocation vanishes with nothing in the log. That is
what happened to `dev/skills/task-review/SKILL.md` before PR #164: an unquoted
`description:` packed `--no-hub: local only. --auto: skip confirmation.` into a plain
scalar, and a plain scalar may not contain a `: ` (colon-space) sequence.

The asset set is enumerated **by path** (`*/skills/*/SKILL.md`, `*/agents/*.md`,
`*/commands/*.md`), not by "files that happen to start with `---`". Content-gated
discovery would skip the two loudest forms of this very bug — an asset with no
frontmatter at all, and one whose `---` is preceded by a UTF-8 BOM — leaving CI green
on exactly the files it exists to catch.

Checks:

(a) Every plugin asset has a delimited frontmatter block, BOM-free, that parses as a
    YAML mapping.
(b) The keys required for that asset type are present and non-empty strings.
(c) `name:` matches the path the loader derives it from (skill directory / agent file
    stem) — the same silent-breakage class, since a rename that misses the frontmatter
    leaves the asset registered under its old name.
(d) Non-asset markdown that carries frontmatter (design docs, references) must still
    parse as YAML, but is held to no asset-specific key requirement.

Invocation-axis checks (docs/invocation.md), which hold rules that otherwise live only
in prose:

(e) Axis coherence — `disable-model-invocation: true` and a sibling
    `agents/openai.yaml` with `policy.allow_implicit_invocation: false` are present
    together or not at all. A one-sided mark locks the human out of one harness while
    the model keeps auto-selecting the skill in the other.
(f) Call graph — no skill may name a user-invoked skill to the Skill tool, whatever the
    caller's own axis. The weaker reading lets a model-invoked skill fire a destructive
    orchestrator.
(g) Notation — no residual `Skill(ns:name)` in skill prose. Sites that invoke nothing
    carry `notation-exempt: <reason>` on the line or the one above, per
    docs/conventions.md → Adjudicated Exceptions Need a Marker.

Usage: python3 scripts/ci/check_skill_frontmatter.py
Exit: 0 if every file is valid, 1 if any violation, 2 if PyYAML is unavailable.
Always prints a full report.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard, not logic
    print(
        "ERROR: PyYAML required — this check parses frontmatter with the same "
        "strictness the loader does.\n"
        "  CI:    pip install pyyaml\n"
        "  local: python3 -m venv .venv && .venv/bin/pip install pyyaml "
        "(system python3 is PEP 668 externally-managed on macOS)",
        file=sys.stderr,
    )
    sys.exit(2)

REPO_ROOT = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)

DELIMITER = "---"
BOM = "﻿"

# Asset kind -> (required keys, whether `name:` must match the path).
ASSET_RULES = {
    "skill": (["name", "description"], True),
    "agent": (["name", "description"], True),
    # Commands take their name from the filename and carry no `name:` key.
    "command": (["description"], False),
}


# --- Invocation-axis checks (docs/invocation.md) -----------------------------
#
# The axis is documented prose; these three checks are what hold it. Each mirrors one
# section of docs/invocation.md and fails with the fix, not just the violation.

# A cross-skill target, however the prose quotes it: "dev:task-grill", `dev:task-grill`,
# 'dev:task-grill', or bare. Matching only the double-quoted form would miss the
# spelling this repo actually reaches for — it backticks skill names everywhere.
TARGET_RE = re.compile(r"[\"'`]?([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)[\"'`]?")

# The retired notation. Namespace-anchored on purpose: the router-prose `Use Skill(X)` /
# `Use Skill(deploy-orchestrator)` forms carry no namespace and are not this rule's business.
NOTATION_RE = re.compile(r"Skill\([a-z][a-z0-9-]*:[a-z][a-z0-9-]*\)")

# Adjudicated exceptions, per docs/conventions.md → Adjudicated Exceptions Need a Marker.
# Anchored to a comment so prose *about* the marker does not silently become one.
NOTATION_EXEMPT_RE = re.compile(r"<!--\s*notation-exempt:\s*[^>]*-->")
CALLGRAPH_EXEMPT_RE = re.compile(r"<!--\s*call-graph-exempt:\s*[^>]*-->")
FM_EXEMPT_RE = re.compile(r"^#\s*notation-exempt:\s*\S")

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*\S*\s*$")

SIDECAR_REL = Path("agents") / "openai.yaml"


def plugin_of(rel: str) -> str:
    """The plugin namespace a repo-relative path belongs to (`dev`, `prod`, ...)."""
    return Path(rel).parts[0]


def skill_dirs(root: Path, tracked: list[Path]) -> dict[str, Path]:
    """Map `plugin:skill` -> its directory, for every `*/skills/*/SKILL.md` in the repo.

    Keyed by namespace, not bare name: `dev:x` and `prod:x` are different skills, and a
    bare-name map would silently drop one of them.
    """
    found: dict[str, Path] = {}
    for path in tracked:
        rel = str(path.relative_to(root))
        if classify(rel) == "skill":
            found[f"{plugin_of(rel)}:{Path(rel).parent.name}"] = root / Path(rel).parent
    return found


def frontmatter_mapping(path: Path) -> dict:
    """Parsed frontmatter for a file, or {} when it is absent or unusable.

    Frontmatter validity is check_file()'s job — these checks only need the values,
    and must not double-report a parse error the per-file pass already surfaced.
    """
    try:
        block, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}
    if block is None:
        return {}
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def axis_flag(value, label: str) -> tuple[bool, str | None]:
    """Read a boolean axis field strictly. Returns (locked, error).

    A quote-wrapped `"true"` is a string; the loader does not honour it, so reading it
    as merely "not locked" would let the gate confirm coherence on a skill the author
    meant to lock — in both harnesses at once. Wrong values fail rather than default.
    """
    if value is None:
        return False, None
    if not isinstance(value, bool):
        return False, (
            f"`{label}: {value!r}` is not a YAML boolean — a quote-wrapped `\"true\"` is a "
            "string and neither harness honours it. Write it unquoted, or drop the key"
        )
    return value, None


def is_user_invoked(skill_dir: Path) -> bool:
    """True when the skill's Claude Code half declares it user-invoked."""
    raw = frontmatter_mapping(skill_dir / "SKILL.md").get("disable-model-invocation")
    locked, _ = axis_flag(raw, "disable-model-invocation")
    return locked


def check_axis_coherence(name: str, skill_dir: Path) -> list[str]:
    """A skill is user-invoked in BOTH harnesses or neither (docs/invocation.md).

    Marking one and not the other is the defect this catches: the human still fires it
    by name in the marked harness while the model keeps auto-selecting it in the other.
    """
    raw_claude = frontmatter_mapping(skill_dir / "SKILL.md").get("disable-model-invocation")
    claude_locked, claude_error = axis_flag(raw_claude, "disable-model-invocation")
    if claude_error:
        return [f"skill `{name}`: {claude_error}."]

    sidecar = skill_dir / SIDECAR_REL
    codex_locked = False
    if sidecar.is_file():
        try:
            data = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            detail = str(exc).replace("\n", " ")
            return [
                f"skill `{name}`: `{SIDECAR_REL}` does not parse as YAML, so its "
                f"`policy` block cannot be read: {detail}"
            ]
        if isinstance(data, dict):
            policy = data.get("policy")
            if isinstance(policy, dict):
                raw_codex = policy.get("allow_implicit_invocation")
                permissive, codex_error = axis_flag(raw_codex, "policy.allow_implicit_invocation")
                if codex_error:
                    return [f"skill `{name}`: `{SIDECAR_REL}` {codex_error}."]
                codex_locked = raw_codex is False

    if claude_locked and not codex_locked:
        return [
            f"skill `{name}` sets `disable-model-invocation: true` but its Codex half does "
            f"not match — add `{SIDECAR_REL}` with `policy.allow_implicit_invocation: false`. "
            "A skill is user-invoked in both harnesses or neither "
            "(docs/invocation.md → Per-platform fields)."
        ]
    if codex_locked and not claude_locked:
        return [
            f"skill `{name}` sets `policy.allow_implicit_invocation: false` in "
            f"`{SIDECAR_REL}` but its `SKILL.md` does not set `disable-model-invocation: true`. "
            "A skill is user-invoked in both harnesses or neither "
            "(docs/invocation.md → Per-platform fields)."
        ]
    return []


def fence_mask(lines: list[str]) -> list[str | None]:
    """Per line: the text above the enclosing fence, or None when outside a fence.

    A fence closes only on a run at least as long as the one that opened it, so a
    4-backtick block quoting 3-backtick lines does not flip the state. Fence lines
    themselves map to None, which is why an inline ```code``` span — not a fence line
    by FENCE_RE — is still scanned for violations.
    """
    mask: list[str | None] = [None] * len(lines)
    open_run = 0
    intro: str | None = None
    for i, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if match and not open_run:
            open_run = len(match.group(1))
            intro = lines[i - 1] if i >= 1 else ""
            continue
        if match and len(match.group(1)) >= open_run:
            open_run = 0
            intro = None
            continue
        if open_run:
            mask[i] = intro if intro is not None else ""
    return mask


def check_call_graph(rel: str, text: str, user_invoked: set[str]) -> list[str]:
    """No skill may call a user-invoked skill — not a user-invoked one, not a model-invoked one.

    Deliberately indifferent to the caller's own axis: the weaker reading
    ("user-invoked may not call user-invoked") lets a model-invoked skill fire a
    destructive orchestrator. docs/invocation.md → The invariant.
    """
    problems = []
    lines = text.splitlines()
    for lineno, line in enumerate(lines, 1):
        # Report at the line carrying the target, but let the tool name sit on either
        # neighbour: a call may wrap, and the target may precede it ("invoke `dev:x`
        # with the Skill tool"). Anchoring on the target is also what keeps one call
        # from being reported twice.
        before = lines[lineno - 2] if lineno >= 2 else ""
        after = lines[lineno] if lineno < len(lines) else ""
        if "Skill tool" not in f"{before} {line} {after}":
            continue
        if CALLGRAPH_EXEMPT_RE.search(line) or CALLGRAPH_EXEMPT_RE.search(before):
            continue
        seen = set()
        # Every target on the line, not just the first: docs/invocation.md → Notation
        # sanctions `Call the Skill tool twice, for "dev:task-spec" and "dev:task-tickets"`.
        for namespace, target in TARGET_RE.findall(line):
            qualified = f"{namespace}:{target}"
            if qualified in user_invoked and qualified not in seen:
                seen.add(qualified)
                problems.append(
                    f"{rel}:{lineno} names user-invoked skill `{qualified}` to the Skill "
                    "tool. A user-invoked skill is reachable by the human and nothing else "
                    "— write it as an instruction to run it, or call the model-invoked half "
                    "instead. If this line only *describes* the rule, mark it "
                    "`<!-- call-graph-exempt: <reason> -->` (docs/invocation.md → The "
                    "invariant)."
                )
    return problems


def notation_problem(rel: str, lineno: int) -> str:
    return (
        f"{rel}:{lineno} uses the retired `Skill(ns:name)` notation. Write "
        'Call the Skill tool with "ns:name" (docs/invocation.md → Notation), or, if this '
        "site invokes nothing, mark it `<!-- notation-exempt: <reason> -->` on the line, the "
        "one above, or the line above an enclosing code fence — in frontmatter, an "
        "unindented `# notation-exempt:` line directly under the key it covers "
        "(docs/conventions.md → Adjudicated Exceptions Need a Marker)."
    )


def frontmatter_span(lines: list[str]) -> int:
    """Index of the closing `---`, or 0 when the file has no frontmatter block."""
    if not lines or lines[0].strip() != DELIMITER:
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == DELIMITER:
            return i
    return 0


def frontmatter_exempt_lines(lines: list[str]) -> set[int]:
    """1-based line numbers inside the frontmatter block that a marker covers.

    A folded scalar has no line a marker could share without leaking into the value the
    loader reads, so inside frontmatter the marker sits on its own **unindented** line
    and covers **only the key block immediately above it**. Covering the whole block
    would let one justified exemption launder an unrelated violation under another key;
    honouring an indented `#` would make the marker part of the scalar it exempts.
    """
    end = frontmatter_span(lines)
    if not end:
        return set()

    covered: set[int] = set()
    key_start = None
    for i in range(1, end):
        raw = lines[i]
        if FM_EXEMPT_RE.match(raw):
            if key_start is not None:
                covered.update(range(key_start + 1, i + 1))
            continue
        if raw[:1] not in (" ", "\t", "#", ""):
            key_start = i
    return covered


def check_notation(rel: str, text: str) -> list[str]:
    """Operative cross-skill calls use the explicit Skill-tool form, not `Skill(ns:name)`.

    A skill name dropped into prose is read as prose; naming the tool is what loads the
    target. docs/invocation.md → Notation.
    """
    problems = []
    lines = text.splitlines()
    fm_exempt_lines = frontmatter_exempt_lines(lines)
    fm_end = frontmatter_span(lines)
    fences = fence_mask(lines)

    for lineno, line in enumerate(lines, 1):
        if not NOTATION_RE.search(line):
            continue
        if lineno <= fm_end:
            # Inside frontmatter only the key-scoped rule applies. The generic
            # "line above" rule would let a marker justifying one key silently
            # exempt the next one — the marker line *is* the line above it.
            if lineno not in fm_exempt_lines:
                problems.append(notation_problem(rel, lineno))
            continue
        candidates = [line, lines[lineno - 2] if lineno >= 2 else ""]
        fence_intro = fences[lineno - 1]
        if fence_intro is not None:
            candidates.append(fence_intro)
        if any(NOTATION_EXEMPT_RE.search(c) for c in candidates):
            continue
        problems.append(notation_problem(rel, lineno))
    return problems


def check_invocation_axis(root: Path) -> tuple[list[str], bool]:
    """Run all three axis checks. Returns (report lines, failed)."""
    tracked = list_tracked_markdown(root)
    dirs = skill_dirs(root, tracked)
    user_invoked = {name for name, d in dirs.items() if is_user_invoked(d)}
    lines: list[str] = []
    failed = False

    for name in sorted(dirs):
        problems = check_axis_coherence(name, dirs[name])
        axis = "user" if name in user_invoked else "model"
        if problems:
            failed = True
            lines.extend(f"ERROR {p}" for p in problems)
        else:
            lines.append(f"OK   skill `{name}` ({axis}-invoked): both platform halves agree")

    # Scope: everything a plugin ships that an agent reads as instructions — skill
    # bundles, agent definitions, and commands. An agent file naming a user-invoked
    # skill breaks the same invariant a skill file does.
    scanned = 0
    for path in tracked:
        rel = str(path.relative_to(root))
        in_skill_bundle = any(d in path.parents for d in dirs.values())
        if not (in_skill_bundle or classify(rel) in ("agent", "command")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        problems = check_call_graph(rel, text, user_invoked) + check_notation(rel, text)
        if problems:
            failed = True
            lines.extend(f"ERROR {p}" for p in problems)

    lines.append(
        f"OK   call graph + notation: {scanned} shipped markdown files scanned "
        f"({len(user_invoked)} user-invoked skills)"
    )
    return lines, failed


def list_tracked_markdown(root: Path) -> list[Path]:
    tracked = subprocess.check_output(
        ["git", "-c", "core.quotePath=false", "ls-files", "--", "*.md"],
        text=True,
        cwd=root,
    ).splitlines()
    return sorted(root / rel for rel in tracked)


def classify(rel: str) -> str | None:
    """Return the plugin asset kind for a repo-relative path, or None if not an asset."""
    path = Path(rel)
    if path.name == "SKILL.md" and path.parent.parent.name == "skills":
        return "skill"
    if path.parent.name == "agents":
        return "agent"
    if path.parent.name == "commands":
        return "command"
    return None


def expected_name(kind: str, rel: str) -> str:
    """The name the loader derives from the path."""
    path = Path(rel)
    return path.parent.name if kind == "skill" else path.stem


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (block, error). `block` is the raw YAML between the `---` delimiters."""
    lines = text.splitlines()
    if not lines:
        return None, "file is empty — no frontmatter block"
    if lines[0].startswith(BOM):
        return None, (
            "frontmatter delimiter is preceded by a UTF-8 BOM — the loader reads "
            "`\\ufeff---`, not `---`, and drops all metadata. Rewrite the file as "
            "UTF-8 without BOM"
        )
    if lines[0].strip() != DELIMITER:
        return None, "file does not open with a `---` frontmatter delimiter"

    for i in range(1, len(lines)):
        if lines[i].strip() == DELIMITER:
            return "\n".join(lines[1:i]), ""

    return None, "frontmatter block is never closed by a `---` line"


def check_file(path: Path, root: Path | None = None) -> list[str]:
    """Return a list of violation messages for one file (empty when valid).

    A non-asset markdown file with no frontmatter is not a violation — the caller
    filters those out before reporting.
    """
    root = root if root is not None else REPO_ROOT
    rel = str(path.relative_to(root))
    kind = classify(rel)
    text = path.read_text(encoding="utf-8")

    block, error = split_frontmatter(text)
    if block is None:
        return [error]

    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ")
        return [
            "frontmatter failed to parse as YAML — the asset would load with empty "
            f"metadata: {detail}"
        ]

    if not isinstance(data, dict):
        return [f"frontmatter is not a YAML mapping (parsed as {type(data).__name__})"]

    if kind is None:
        # Non-asset markdown: parsing is the whole contract, no required keys.
        return []

    problems: list[str] = []
    required, name_must_match_path = ASSET_RULES[kind]

    for key in required:
        value = data.get(key)
        if key not in data:
            problems.append(f"missing required key `{key}:`")
        elif value is None:
            problems.append(f"`{key}:` has no value")
        elif not isinstance(value, str):
            problems.append(f"`{key}:` must be a string, got {type(value).__name__}")
        elif not value.strip():
            problems.append(f"`{key}:` is empty")

    if name_must_match_path:
        expected = expected_name(kind, rel)
        actual = data.get("name")
        if isinstance(actual, str) and actual.strip() != expected:
            problems.append(
                f"`name: {actual.strip()}` does not match the path the loader derives "
                f"it from (expected `{expected}`)"
            )

    return problems


def build_report(root: Path) -> tuple[list[str], bool, int]:
    """Return (report lines, failed, asset count) for a repository root."""
    lines: list[str] = []
    failed = False
    asset_count = 0

    for path in list_tracked_markdown(root):
        rel = str(path.relative_to(root))
        kind = classify(rel)

        if kind is None:
            # Only non-asset files that actually carry frontmatter are in scope.
            try:
                first = path.read_text(encoding="utf-8").split("\n", 1)[0]
            except (OSError, UnicodeDecodeError):
                continue
            if first.lstrip(BOM).strip() != DELIMITER:
                continue
            label = "non-asset frontmatter"
        else:
            asset_count += 1
            label = kind

        problems = check_file(path, root)
        if not problems:
            lines.append(f"OK   {rel} ({label}): frontmatter valid")
            continue
        failed = True
        for msg in problems:
            lines.append(f"ERROR {rel} ({label}): {msg}")

    return lines, failed, asset_count


def main() -> int:
    lines, failed, asset_count = build_report(REPO_ROOT)
    for line in lines:
        print(line)

    print("----")

    axis_lines, axis_failed = check_invocation_axis(REPO_ROOT)
    for line in axis_lines:
        print(line)
    failed = failed or axis_failed

    print("----")

    if asset_count == 0:
        # Fail closed: a gate that silently covers zero files is indistinguishable
        # from a passing one in the CI summary.
        print(
            "FAIL: discovery found zero plugin assets "
            "(*/skills/*/SKILL.md, */agents/*.md, */commands/*.md). "
            "Either the pathspec regressed or this is not the plugin repo."
        )
        return 1

    if failed:
        print("FAIL: see ERROR lines above.")
        print(
            "Frontmatter the loader cannot read still loads — with no description — so "
            "auto-invocation silently stops working. An invocation-axis violation is the "
            "same class: the rule stays documented while the tree stops obeying it."
        )
        return 1

    print(f"OK: {asset_count} plugin assets valid ({len(lines)} files checked); "
          "invocation axis coherent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
