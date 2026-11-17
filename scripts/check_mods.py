#!/usr/bin/env python3
"""Local gate for mods/: `claude plugin validate` + `claude plugin test`, failing on TS errors.

`claude plugin validate ./mods` reports TypeScript errors as warnings and still exits 0 with
"Validation passed with warnings", so the gate fails on every `error TS` it prints, test files
included, naming the `Validating hooks: <path>` section each sits under. PR #398 shipped a
TS2741 in `mods/hooks/status-band/register.tsx` past the old count-the-warnings habit.

Local only: CI does not install `claude`, so only the `--test` parser self-test runs there.

Usage:
  python3 scripts/check_mods.py [mods-dir]   # default ./mods
  python3 scripts/check_mods.py --test       # parser self-test, no `claude` needed
"""

from __future__ import annotations

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

    reasons = verdict(validate_rc, validate_output, test_rc)
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

    total = len(cases) + len(verdict_cases)
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
