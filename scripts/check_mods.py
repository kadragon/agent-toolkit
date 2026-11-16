#!/usr/bin/env python3
"""Local gate for mods/: `claude plugin validate` + `claude plugin test`, failing on TS errors.

`claude plugin validate ./mods` reports TypeScript errors as warnings and still exits 0 with
"Validation passed with warnings". The mods test files carry known TS warnings, so the gate
cannot fail on every `error TS`; it fails on one printed under a shipped (non-`*.test.ts(x)`)
file's `Validating hooks: <path>` section. PR #398 shipped a TS2741 in
`mods/hooks/status-band/register.tsx` past the old count-the-warnings habit.

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
TEST_FILE_RE = re.compile(r"\.test\.tsx?$")


def shipped_ts_errors(output: str) -> tuple[list[str], int]:
    """Return (`path: error line` for each TS error outside a test file, hooks section count).

    A TS error before any section header has no file to exempt it, so it counts as shipped.
    """
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
        if TS_ERROR_RE.search(line) and not TEST_FILE_RE.search(path):
            errors.append(f"{path}: {line.strip()}")
    return errors, sections


def run(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def main(mods_dir: str) -> int:
    if shutil.which("claude") is None:
        print("check_mods: `claude` CLI not found on PATH", file=sys.stderr)
        return 2

    rc, output = run(["claude", "plugin", "validate", mods_dir])
    print(output, end="")
    errors, sections = shipped_ts_errors(output)
    failed = False
    if rc != 0:
        print(f"check_mods: validate exited {rc}", file=sys.stderr)
        failed = True
    if sections == 0:
        print("check_mods: validate printed no `Validating hooks:` section", file=sys.stderr)
        failed = True
    for err in errors:
        print(f"check_mods: TS error in shipped file — {err}", file=sys.stderr)
    failed = failed or bool(errors)

    rc, output = run(["claude", "plugin", "test", mods_dir])
    print(output, end="")
    if rc != 0:
        print(f"check_mods: test exited {rc}", file=sys.stderr)
        failed = True

    print("check_mods: FAIL" if failed else "check_mods: OK", file=sys.stderr)
    return 1 if failed else 0


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
        ("test-file errors only", manifest + hooks_json + test_tsx + test_ts + tail, 0, 3),
        ("shipped tsx error", manifest + hooks_json + test_tsx + shipped + tail, 1, 3),
        # A shipped section *before* a test section: the exemption must not leak backward.
        ("shipped then test", manifest + shipped + test_tsx + tail, 1, 2),
        # A test section followed by a shipped file: the exemption must not leak forward.
        ("test then shipped", test_tsx + shipped, 1, 2),
        ("error before any section", "  ❯ error TS1005: ';' expected.\n" + hooks_json, 1, 1),
        ("error under manifest section", manifest + "  ❯ error TS2304: x\n" + hooks_json, 1, 1),
        ("no hooks sections", manifest + tail, 0, 0),
        ("ts-ish word without code", hooks_json + "  ❯ no error TSX here\n", 0, 1),
    ]
    failures = 0
    for name, output, want_errors, want_sections in cases:
        errors, sections = shipped_ts_errors(output)
        if len(errors) != want_errors or sections != want_sections:
            failures += 1
            print(
                f"FAIL {name}: errors={errors!r} sections={sections} "
                f"(want {want_errors} errors, {want_sections} sections)",
                file=sys.stderr,
            )
    print(f"check_mods selftest: {len(cases) - failures}/{len(cases)} passed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--test"]:
        sys.exit(selftest())
    if len(args) > 1 or (args and args[0].startswith("-")):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(args[0] if args else "./mods"))
