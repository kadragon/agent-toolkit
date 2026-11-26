#!/usr/bin/env python3
"""Local gate for mods/: `claude plugin validate` + `claude plugin test`, failing on TS errors.

`claude plugin validate ./mods` reports TypeScript errors as warnings and still exits 0 with
"Validation passed with warnings", so the gate fails on every `error TS` it prints, test files
included, naming the `Validating hooks: <path>` section each sits under. PR #398 shipped a
TS2741 in `mods/hooks/status-band/register.tsx` past the old count-the-warnings habit.

It also fails when a large hook file's SECTION MAP comment drifts from its top-level functions,
and when a pure module (`count.ts`) imports from `claude-code`: those files run and test without
the engine's `$`, and a type import would tie them to it again.

Local only: CI does not install `claude`, so only the `--test` self-test runs there; it checks
the parser, the shipped SECTION MAPs and the pure modules' imports.

Usage:
  python3 scripts/check_mods.py [mods-dir]   # default ./mods
  python3 scripts/check_mods.py --test       # parser + SECTION MAP self-test, no `claude` needed
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

SECTION_RE = re.compile(r"^Validating [^:]+: (?P<path>.+?)\s*$")
TS_ERROR_RE = re.compile(r"\berror TS\d+:")


def ts_errors(output: str) -> tuple[list[str], int]:
    """Return (`path: error line` for each TS error, hooks section count)."""
    errors: list[str] = []
    sections = 0
    path = "<no section>"
    for line in output.splitlines():
        header = SECTION_RE.match(line)
        if header:
            path = header.group("path")
            if line.startswith("Validating hooks:"):
                sections += 1
            continue
        if TS_ERROR_RE.search(line):
            errors.append(f"{path}: {line.strip()}")
    return errors, sections


SECTION_MAP_MARKER = "// ---- SECTION MAP ----"
SECTION_MAP_FILES = ("hooks/status-band/register.tsx",)
TOP_FUNCTION_RE = re.compile(r"^(?:export )?(?:async )?function\*? (\w+)")
TOP_ARROW_RE = re.compile(r"^(?:export )?const (\w+)(?::[^=]+)? = (?:async )?\(")


def section_map_drift(src: str) -> list[str]:
    """Return how a file's SECTION MAP comment differs from its top-level functions.

    Agents grep the map and read one range; a function it omits, or a stale name it keeps,
    sends them back to reading the whole file.
    """
    lines = src.splitlines()
    defs = set()
    for line in lines:
        match = TOP_FUNCTION_RE.match(line) or TOP_ARROW_RE.match(line)
        if match:
            defs.add(match.group(1))
    if SECTION_MAP_MARKER not in lines:
        return ["no SECTION MAP block"]
    mapped = set()
    for line in lines[lines.index(SECTION_MAP_MARKER) + 1 :]:
        if not line.startswith("//"):
            break
        if line.startswith("//   ") and ":" in line:
            mapped |= {n.strip() for n in line.split(":", 1)[1].split(",") if n.strip()}
    reasons = []
    if defs - mapped:
        reasons.append(f"SECTION MAP misses {sorted(defs - mapped)}")
    if mapped - defs:
        reasons.append(f"SECTION MAP keeps stale {sorted(mapped - defs)}")
    return reasons


def section_map_reasons(mods_dir: str) -> list[str]:
    reasons = []
    for rel in SECTION_MAP_FILES:
        with open(f"{mods_dir}/{rel}", encoding="utf-8") as handle:
            reasons.extend(f"{rel}: {r}" for r in section_map_drift(handle.read()))
    return reasons


PURE_MODULES = ("hooks/status-band/count.ts",)
ENGINE_IMPORT_RE = re.compile(
    r"""^(?:import\b(?:[^'";=`/]*?\bfrom)?|export\s+(?:type\s+)?(?:\*(?:\s+as\s+\w+)?|\{[^}]*\})\s*from)"""
    r"""\s*['"]claude-code(?:/[^'"]*)?['"]""",
    re.MULTILINE,
)


def engine_imports(src: str) -> list[str]:
    return [" ".join(match.group(0).split()) for match in ENGINE_IMPORT_RE.finditer(src)]


def pure_module_reasons(mods_dir: str) -> list[str]:
    reasons = []
    for rel in PURE_MODULES:
        with open(f"{mods_dir}/{rel}", encoding="utf-8") as handle:
            reasons.extend(f"{rel}: imports from claude-code ({i})" for i in engine_imports(handle.read()))
    return reasons


def run(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def verdict(validate_rc: int, validate_output: str, test_rc: int) -> list[str]:
    """Return every failure reason; an empty list means the gate passes."""
    reasons: list[str] = []
    if validate_rc != 0:
        reasons.append(f"validate exited {validate_rc}")
    errors, sections = ts_errors(validate_output)
    if sections == 0:
        reasons.append("validate printed no `Validating hooks:` section")
    reasons.extend(f"TS error — {err}" for err in errors)
    if test_rc != 0:
        reasons.append(f"test exited {test_rc}")
    return reasons


def main(mods_dir: str) -> int:
    if shutil.which("claude") is None:
        print("check_mods: `claude` CLI not found on PATH", file=sys.stderr)
        return 2

    validate_rc, validate_output = run(["claude", "plugin", "validate", mods_dir])
    print(validate_output, end="")
    test_rc, test_output = run(["claude", "plugin", "test", mods_dir])
    print(test_output, end="")

    reasons = (
        verdict(validate_rc, validate_output, test_rc)
        + section_map_reasons(mods_dir)
        + pure_module_reasons(mods_dir)
    )
    for reason in reasons:
        print(f"check_mods: {reason}", file=sys.stderr)
    print("check_mods: FAIL" if reasons else "check_mods: OK", file=sys.stderr)
    return 1 if reasons else 0


def selftest() -> int:
    hooks_json = "Validating hooks: /r/mods/hooks/hooks.json\n\n  ❯ ./register.ts hooks: session.start\n"
    test_tsx = (
        "Validating hooks: /r/mods/hooks/pr-recap/register.test.tsx\n\n"
        "⚠ Found 1 warnings:\n\n"
        "  ❯ line 167, column 51: error TS2304: Cannot find name 'setTimeout'.\n"
    )
    test_ts = "Validating hooks: /r/mods/hooks/x/a.test.ts\n  ❯ line 1, column 1: error TS2304: x\n"
    shipped = (
        "Validating hooks: /r/mods/hooks/status-band/register.tsx\n\n"
        "  ❯ line 29, column 7: error TS2322: Type 'number' is not assignable to type 'string'.\n"
    )
    manifest = "Validating plugin manifest: /r/mods/.claude-plugin/plugin.json\n"
    tail = "\n✔ Validation passed with warnings\n"

    cases = [
        # Test files are gated like shipped ones: no path is exempt.
        ("test-file errors count", manifest + hooks_json + test_tsx + test_ts + tail, 2, 3),
        ("shipped tsx error", manifest + hooks_json + shipped + tail, 1, 2),
        ("test and shipped errors", manifest + test_tsx + shipped + tail, 2, 2),
        ("error before any section", "  ❯ error TS1005: ';' expected.\n" + hooks_json, 1, 1),
        ("error under manifest section", manifest + "  ❯ error TS2304: x\n" + hooks_json, 1, 1),
        ("no hooks sections", manifest + tail, 0, 0),
        ("ts-ish word without code", hooks_json + "  ❯ no error TSX here\n", 0, 1),
    ]
    failures = 0
    for name, output, want_errors, want_sections in cases:
        errors, sections = ts_errors(output)
        if len(errors) != want_errors or sections != want_sections:
            failures += 1
            print(
                f"FAIL {name}: errors={errors!r} sections={sections} "
                f"(want {want_errors} errors, {want_sections} sections)",
                file=sys.stderr,
            )

    # verdict(): every failure reason from main(), including the exit codes.
    clean = manifest + hooks_json + tail
    verdict_cases = [
        ("clean run passes", (0, clean, 0), 0),
        ("validate nonzero exit", (1, clean, 0), 1),
        ("test nonzero exit", (0, clean, 1), 1),
        ("no hooks sections", (0, manifest + tail, 0), 1),
        ("shipped TS error", (0, manifest + shipped + tail, 0), 1),
        ("test-file TS error", (0, manifest + hooks_json + test_tsx + tail, 0), 1),
        ("every failure reported", (3, manifest + shipped + tail, 4), 3),
    ]
    for name, call, want in verdict_cases:
        reasons = verdict(*call)
        if len(reasons) != want:
            failures += 1
            print(f"FAIL verdict {name}: reasons={reasons!r} (want {want})", file=sys.stderr)

    # section_map_drift(): synthetic files, then the shipped ones (this runs in CI).
    mapped = "// ---- SECTION MAP ----\n//   all: a, b\n\n"
    map_cases = [
        ("map matches", mapped + "function a() {}\nexport const b = (x: number): void => {}\n", 0),
        ("map misses async def", mapped + "function a() {}\nconst b = () => 1\nasync function c() {}\n", 1),
        ("map keeps stale name", mapped + "function a() {}\n", 1),
        ("no map block", "function a() {}\n", 1),
        ("non-arrow const ignored", mapped + "function a() {}\nconst b = () => 1\nconst c = atom(1)\n", 0),
        ("typed arrow export", mapped + "function a() {}\nexport const b: T = (on) => {}\n", 0),
        ("indented def ignored", mapped + "function a() {}\nconst b = () => 1\n  function c() {}\n", 0),
    ]
    for name, src, want in map_cases:
        drift = section_map_drift(src)
        if len(drift) != want:
            failures += 1
            print(f"FAIL section map {name}: {drift!r} (want {want})", file=sys.stderr)
    mods_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mods")
    shipped_drift = section_map_reasons(mods_dir)
    if shipped_drift:
        failures += 1
        print(f"FAIL shipped section maps: {shipped_drift!r}", file=sys.stderr)

    import_cases = [
        ("value import", "import { atom } from 'claude-code'\n", 1),
        ("type import", "import type { Elements } from 'claude-code'\n", 1),
        ("subpath import", 'import { test } from "claude-code/testing"\n', 1),
        ("multi-line import", "import {\n  atom,\n  update,\n} from 'claude-code'\n", 1),
        ("bare import", "import 'claude-code'\n", 1),
        ("re-export", "export type { Register } from 'claude-code'\n", 1),
        ("local import", "import type { StatusBand } from '../../types'\n", 0),
        ("similar package", "import { x } from 'claude-code-extras'\n", 0),
        ("comment mention", "// import { atom } from 'claude-code'\nconst a = 1\n", 0),
        ("indented mention", "const s = `\n  import x from 'claude-code'\n`\n", 0),
        ("export before a comment", "export const a = 1\n// import { atom } from 'claude-code'\n", 0),
        ("export before a template", "export const s = `\n  import x from 'claude-code'\n`\n", 0),
        ("star re-export", "export * from 'claude-code'\n", 1),
    ]
    for name, src, want in import_cases:
        found = engine_imports(src)
        if len(found) != want:
            failures += 1
            print(f"FAIL engine import {name}: {found!r} (want {want})", file=sys.stderr)
    shipped_pure = pure_module_reasons(mods_dir)
    if shipped_pure:
        failures += 1
        print(f"FAIL shipped pure modules: {shipped_pure!r}", file=sys.stderr)

    total = len(cases) + len(verdict_cases) + len(map_cases) + len(import_cases) + 2
    print(f"check_mods selftest: {total - failures}/{total} passed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--test"]:
        sys.exit(selftest())
    if len(args) > 1 or (args and args[0].startswith("-")):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(args[0] if args else "./mods"))
