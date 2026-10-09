#!/usr/bin/env python3
"""Exercise generated/existing harnesses and size warnings through real scripts."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BASE = """# Fixture
## Docs Index
`docs/runbook.md` — build and test commands.
## Working with Existing Code
Preserve unrelated changes.
## Language Policy
Code and docs: English.
Update this file only for stable operational facts that code does not reveal.
"""


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("AGENTS.md", BASE)
        self.write("CLAUDE.md", "@AGENTS.md\n")
        self.write("docs/runbook.md", "# Runbook\nRun tests.\n")
        self.write(".agents/skills", "../.claude/skills")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def run_script(self, name="validate-harness.sh", **env):
        result = subprocess.run(
            ["bash", str(SCRIPTS / name)], cwd=self.root,
            env={**os.environ, "CONTEXT_SIZE_LIMIT": "200", **env},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.stderr, "", result.stderr)
        return result

    def test_minimal_without_optional_sections(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("WARN: 0", result.stdout)
        self.assertIn("LEVEL 1", result.stdout)

    def test_existing_non_numbered_policy_and_one_invariant(self):
        self.write("AGENTS.md", BASE + "## Golden Principles\n- Validate public input → tests.\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("WARN: 0", result.stdout)

    def test_maintenance_pointer(self):
        self.write("AGENTS.md", BASE.replace(BASE.splitlines()[-1], "Edit policy: `docs/conventions.md`."))
        self.write("docs/conventions.md", "# Instruction updates\nUpdate AGENTS.md only for stable operational guidance.\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("WARN: 0", result.stdout)

    def test_broken_reference(self):
        self.write("AGENTS.md", BASE + "Read `docs/missing.md`.\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Referenced docs/missing.md missing", result.stdout)

    def test_malformed_configuration(self):
        for path in (".claude/settings.json", ".codex/config.toml", ".codex/agents/reviewer.toml"):
            with self.subTest(path=path):
                self.write(path, "{broken = [")
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(path, result.stdout)
                (self.root / path).unlink()

    def test_configured_delegation_surfaces(self):
        surfaces = {
            ".claude/agents/reviewer.md": "---\nname: reviewer\ndescription: Review\nspine-exempt: true\n---\n",
            ".codex/agents/reviewer.toml": 'name = "reviewer"\ndescription = "Review"\n',
            ".codex/config.toml": '[agents.reviewer]\ndescription = "Review"\n',
            ".agents/skills/review/SKILL.md": "# Review orchestrator\n",
        }
        for path, content in surfaces.items():
            with self.subTest(path=path):
                if path.startswith(".agents/skills/"):
                    (self.root / ".agents/skills").unlink()
                    (self.root / ".claude/skills").mkdir(parents=True)
                    (self.root / ".agents/skills").symlink_to("../.claude/skills", target_is_directory=True)
                self.write(path, content)
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("No Delegation section", result.stdout)
                self.assertIn("no routing doc", result.stdout)
                (self.root / path).unlink()
        # Guidance can be a section pointing to an existing workflow.
        self.write(".codex/agents/reviewer.toml", 'name = "reviewer"\n')
        self.write("AGENTS.md", BASE + "## Delegation\nFollow `docs/workflows.md`.\n")
        self.write("docs/workflows.md", "# Workflow\nReview independently when authorized.\n")
        result = self.run_script()
        self.assertNotIn("No Delegation section", result.stdout)
        self.assertNotIn("no routing doc", result.stdout)

    def test_workflow_only_delegation(self):
        self.write("docs/workflows.md", "# Code\n## Delegation workflow\nDelegate to the built-in reviewer when authorized.\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("No Delegation section", result.stdout)

    def test_invalid_required_artifacts_still_fail(self):
        for path, text, diagnostic in (
            ("CLAUDE.md", "# Copied instructions\n", "not a pure"),
            (".agents/skills", "wrong target", "content is not"),
            ("backlog.md", "## Queue\n- [?] bad\n", "non-standard checkboxes"),
        ):
            with self.subTest(path=path):
                self.write(path, text)
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(diagnostic, result.stdout)
                self.write(path, "@AGENTS.md\n" if path == "CLAUDE.md" else "../.claude/skills")
                if path == "backlog.md":
                    (self.root / path).unlink()

    def test_no_heading_session_overflow(self):
        self.write("AGENTS.md", "guidance\n" * 201)
        result = self.run_script("check-context-size.sh")
        self.assertEqual(result.returncode, 0)
        self.assertIn("201 lines", result.stdout)

    def test_size_boundaries(self):
        for count in (99, 100, 101, 199, 200, 201):
            with self.subTest(count=count):
                self.write("AGENTS.md", BASE + "\n" * (count - len(BASE.splitlines())))
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(f"AGENTS.md is {count} lines", result.stdout)
                self.assertIn(f"WARN: {int(count > 100)}", result.stdout)
                self.assertEqual("strong warning" in result.stdout, count > 200)
                session = self.run_script("check-context-size.sh")
                self.assertEqual(session.returncode, 0)
                self.assertEqual(bool(session.stdout), count > 200)

    def test_session_override_and_codex_fallback(self):
        (self.root / "CLAUDE.md").unlink()
        for count in (49, 50, 51):
            self.write("AGENTS.md", BASE + "\n" * (count - len(BASE.splitlines())))
            result = self.run_script("check-context-size.sh", CONTEXT_SIZE_LIMIT="50")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(bool(result.stdout), count > 50)


if __name__ == "__main__":
    unittest.main()
