#!/usr/bin/env python3
"""Test the shipped guard bundle independently of the dev plugin."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "guard"
DEV = ROOT / "dev"
MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")


class GuardPluginTests(unittest.TestCase):
    def test_explicit_dev_checks_match_the_hook_runtime(self):
        pairs = [
            ("commit-guard/guard.py", "task-review-cycle/guard.py"),
            ("memory-guard/guard.py", "harness-capture/guard.py"),
        ]
        pairs.extend(
            (f"session-start/{name}", f"harness-init/scripts/{name}")
            for name in ("sync-claude-md.sh", "symlink-guard.sh", "check-context-size.sh")
        )
        pairs.extend(
            (f"session-start/{name}", f"harness-curate/scripts/{name}")
            for name in ("curate_due.py", "session_paths.py")
        )
        for hook, skill in pairs:
            with self.subTest(hook=hook):
                self.assertEqual((GUARD / "hooks" / hook).read_bytes(),
                                 (DEV / "skills" / skill).read_bytes())

    def test_session_start_runs_from_a_guard_only_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "installed guard"
            shutil.copytree(GUARD, bundle)
            project = root / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("Guidance\n", encoding="utf-8")
            codex = root / "codex"
            sessions = codex / "sessions"
            sessions.mkdir(parents=True)
            for i in range(10):
                (sessions / f"rollout-{i}.jsonl").write_text(
                    json.dumps({"type": "session_meta", "payload": {"cwd": str(project)}}) + "\n",
                    encoding="utf-8",
                )
            env = {**os.environ, "CLAUDE_MD_SYNC_URL": "", "CLAUDE_CONFIG_DIR": str(root / "claude"),
                   "CLAUDE_PLUGIN_ROOT": str(bundle), "PLUGIN_ROOT": str(bundle), "CODEX_HOME": str(codex)}
            result = subprocess.run(["bash", str(bundle / "hooks/session-start/run.sh")], cwd=project,
                                    env=env, capture_output=True, text=True, encoding="utf-8", check=True)
            self.assertEqual((project / "CLAUDE.md").read_text(encoding="utf-8").strip(), "@AGENTS.md")
            self.assertIn("HARNESS-CURATE DUE:", result.stdout)
            self.assertTrue((project / ".agents/.maintenance-stamp").is_file())
            second = subprocess.run(result.args, cwd=project, env=env, capture_output=True,
                                    text=True, encoding="utf-8", check=True)
            self.assertEqual(second.stdout, "")

    def test_dev_only_release_leaves_the_guard_bundle_byte_identical(self):
        def bundle_bytes(root):
            return {path.relative_to(root).as_posix(): path.read_bytes()
                    for path in root.rglob("*") if path.is_file()}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(GUARD, root / "guard")
            before = bundle_bytes(root / "guard")
            self.assertTrue(all(
                (name == "hooks.json" or name.startswith("hooks/") or name in MANIFESTS) and not Path(name).name.startswith("test_")
                for name in before
            ))
            for manifest in MANIFESTS:
                src = DEV / manifest
                dst = root / "dev" / manifest
                dst.parent.mkdir(parents=True)
                shutil.copyfile(src, dst)
                self.assertNotIn("hooks", json.loads(src.read_text(encoding="utf-8")))
            skill = root / "dev/skills/dispatch/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# Updated dev skill\n", encoding="utf-8")
            script = root / "scripts/bump-version.sh"
            script.parent.mkdir()
            shutil.copyfile(ROOT / "scripts/bump-version.sh", script)
            subprocess.run(["bash", str(script), "dev", "patch"], capture_output=True, check=True)
            for manifest in MANIFESTS:
                self.assertNotEqual((root / "dev" / manifest).read_bytes(), (DEV / manifest).read_bytes())
            self.assertEqual(bundle_bytes(root / "guard"), before)


if __name__ == "__main__":
    unittest.main()
