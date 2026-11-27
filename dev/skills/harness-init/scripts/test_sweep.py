#!/usr/bin/env python3
"""Exercise the bundled sweep template with findings from an adapted lint check."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SWEEP = Path(__file__).with_name("sweep.sh")
LINT_MARKER = "# Parse lint output and add to FINDINGS if issues found"
LINT_FINDING = "[lint] Fixture lint finding"
SECURITY_FINDING = "[security] Fixture security finding"


class SweepTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tools").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "docs/runbook.md").write_text("# Runbook\n", encoding="utf-8")
        self.backlog = self.root / "backlog.md"
        self.backlog.write_text("# Queue\n", encoding="utf-8")
        self.backend = self.root / "queue_backend.py"
        self.backend.write_text('print(\'{"edit_file":"backlog.md"}\')\n', encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def sweep(self, *args, finding=None):
        template = SWEEP.read_text(encoding="utf-8")
        self.assertIn(LINT_MARKER, template)
        if finding is not None:
            template = template.replace(LINT_MARKER, f'FINDINGS+=("{finding}")')
        script = self.root / "tools/sweep.sh"
        script.write_text(template, encoding="utf-8")
        return subprocess.run(
            ["bash", str(script), *args],
            cwd=self.root,
            env={**os.environ, "AGENT_QUEUE_BACKEND_SCRIPT": str(self.backend)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_quick_reports_adapted_lint_findings_without_persisting(self):
        result = self.sweep("--quick", finding=LINT_FINDING)
        self.assertIn(LINT_FINDING, result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Doc drift", result.stdout)
        self.assertEqual(self.backlog.read_text(encoding="utf-8"), "# Queue\n")

    def test_quick_without_findings_is_clean(self):
        result = self.sweep("--quick")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Sweep clean", result.stdout)
        self.assertNotIn("Doc drift", result.stdout)

    def test_quick_keeps_security_details_out_of_unattended_output(self):
        result = self.sweep("--quick", finding=SECURITY_FINDING)
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 finding(s)", result.stdout)
        self.assertNotIn(SECURITY_FINDING, result.stdout + result.stderr)
        self.assertEqual(self.backlog.read_text(encoding="utf-8"), "# Queue\n")

    def test_full_scan_still_persists_findings(self):
        result = self.sweep(finding=LINT_FINDING)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Doc drift", result.stdout)
        self.assertIn(LINT_FINDING, result.stdout)
        self.assertIn(f"- [ ] {LINT_FINDING}", self.backlog.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
