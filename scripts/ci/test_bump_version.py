#!/usr/bin/env python3
"""Regression tests for scripts/bump-version.sh.

Failure mode this locks down: on a CRLF checkout (Windows `core.autocrlf`), the
`--skill` path used to leave SKILL.md untouched while still printing a success
line, because its substitution anchored on `$` and the line ends `...\r`. The
plugin manifests bumped fine, so the silent no-op only surfaced later in review.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bump-version.sh"

MANIFEST = '{{\n  "name": "dev",\n  "version": "{version}"\n}}\n'
SKILL_MD = "---\nname: {skill}\ndescription: test\nversion: {version}\n---\n\n# Test\n"

FAILURES = []


def check(condition, message):
    if not condition:
        FAILURES.append(message)
    return condition


def make_repo(root, newline, skill_version="1.2.3", plugin_version="4.5.6"):
    """Build a minimal plugin tree whose text files use the given line ending."""
    for platform in (".claude-plugin", ".codex-plugin"):
        path = root / "dev" / platform / "plugin.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path, MANIFEST.format(version=plugin_version), newline)

    skill_md = root / "dev" / "skills" / "demo" / "SKILL.md"
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    write(skill_md, SKILL_MD.format(skill="demo", version=skill_version), newline)

    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT, scripts_dir / "bump-version.sh")
    return scripts_dir / "bump-version.sh"


def write(path, text, newline):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace("\n", newline))


def read(path):
    return path.read_text(encoding="utf-8")


def run(script, *args):
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def version_of(path, prefix):
    """First line starting with prefix, trailing CR and whitespace stripped."""
    for line in read(path).splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip('",')
    return None


def test_skill_bump(newline, label):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = make_repo(root, newline)
        result = run(script, "dev", "patch", "--skill", "demo", "minor")

        check(result.returncode == 0, f"[{label}] exit {result.returncode}: {result.stderr}")

        skill_md = root / "dev" / "skills" / "demo" / "SKILL.md"
        check(
            version_of(skill_md, "version:") == "1.3.0",
            f"[{label}] SKILL.md not bumped: {version_of(skill_md, 'version:')!r} (want '1.3.0')",
        )
        for platform in (".claude-plugin", ".codex-plugin"):
            manifest = root / "dev" / platform / "plugin.json"
            check(
                version_of(manifest, '  "version": ') == "4.5.7",
                f"[{label}] {platform} not bumped: {version_of(manifest, '  \"version\": ')!r}",
            )

        raw = open(skill_md, encoding="utf-8", newline="").read()
        check(
            ("\r\n" in raw) == (newline == "\r\n"),
            f"[{label}] line endings not preserved",
        )


def main():
    test_skill_bump("\n", "LF")
    test_skill_bump("\r\n", "CRLF")

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL {failure}")
        return 1
    print("PASS scripts/bump-version.sh (LF + CRLF skill bump, no silent no-op)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
