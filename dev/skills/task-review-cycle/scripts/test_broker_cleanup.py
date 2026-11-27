"""Exercise review-owned and legacy broker shutdown with real detached Node processes."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BASH = os.environ.get("TEST_GIT_BASH") or shutil.which("bash") or "bash"
BROKER = r"""
import fs from 'node:fs';
import net from 'node:net';
const args = process.argv;
const pidFile = args[args.indexOf('--pid-file') + 1];
const endpoint = args[args.indexOf('--endpoint') + 1].slice(5);
const shutdown = () => {
  fs.unlinkSync(pidFile);
  fs.writeFileSync(process.env.TEST_EXIT, String(process.pid));
  process.exit(0);
};
net.createServer(socket => socket.on('data', shutdown)).listen(endpoint, () => {
  fs.writeFileSync(pidFile, String(process.pid));
});
process.on('SIGTERM', shutdown);
"""
COMPANION = r"""
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cxc-'));
const pidFile = path.join(dir, 'broker.pid');
const endpoint = process.platform === 'win32'
  ? 'pipe:' + '\\\\.\\pipe\\' + path.basename(dir)
  : 'unix:' + path.join(dir, 'broker.sock');
const child = spawn(process.execPath, [process.env.TEST_BROKER, 'serve', '--endpoint', endpoint,
  '--cwd', process.cwd(), '--pid-file', pidFile], { detached: true, stdio: 'ignore' });
child.unref();
const deadline = Date.now() + 4000;
const wait = setInterval(() => {
  if (!fs.existsSync(pidFile)) {
    if (Date.now() < deadline) return;
    process.exit(27);
  }
  fs.writeFileSync(process.env.TEST_MARKER, JSON.stringify({ pid: child.pid, pidFile }));
  clearInterval(wait);
  if (process.env.TEST_FAIL === 'yes') process.exit(9);
  console.log(JSON.stringify({ codex: { stdout: 'Review completed' } }));
}, 20);
"""


@unittest.skipUnless(shutil.which("node"), "Node is needed for the companion fixture")
class BrokerCleanupTests(unittest.TestCase):
    def test_review_owned_broker_exits_on_success_and_failure(self):
        temp = tempfile.TemporaryDirectory(prefix="rb ")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        broker = root / "app-server-broker.mjs"
        broker.write_text(BROKER, encoding="utf-8")
        companion = root / "companion.mjs"
        companion.write_text(COMPANION, encoding="utf-8")
        legacy_temp = root / "legacy"
        legacy_temp.mkdir()
        legacy_marker, legacy_exit = root / "legacy.pid.json", root / "legacy.exit"
        legacy_env = {
            **os.environ, "TEST_BROKER": str(broker), "TEST_MARKER": str(legacy_marker),
            "TEST_EXIT": str(legacy_exit), "TEST_FAIL": "no",
            "TMPDIR": str(legacy_temp), "TMP": str(legacy_temp), "TEMP": str(legacy_temp),
        }
        subprocess.run(["node", str(companion)], cwd=root, env=legacy_env,
                       capture_output=True, timeout=10, check=True)
        legacy = json.loads(legacy_marker.read_text(encoding="utf-8"))
        self.addCleanup(subprocess.run, [sys.executable, str(SCRIPTS / "broker-cleanup.py"), str(root)],
                        capture_output=True, timeout=30, check=False)
        for fails in ("no", "yes"):
            with self.subTest(fails=fails):
                marker = root / fails
                exited = root / f"{fails}.exit"
                env = {**os.environ, "TEST_BROKER": str(broker), "TEST_MARKER": str(marker),
                       "TEST_EXIT": str(exited), "TEST_FAIL": fails, "CODEX_REVIEW_RESULT_DIR": str(root / "results")}
                result = subprocess.run(
                    [BASH, str(SCRIPTS / "codex-review.sh"), "plugin", "main", str(companion)],
                    cwd=root, env=env, capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 9 if fails == "yes" else 0, result.stdout + result.stderr)
                self.assertTrue(marker.is_file(), result.stderr)
                info = json.loads(marker.read_text(encoding="utf-8"))
                self.assertEqual(exited.read_text(encoding="utf-8"), str(info["pid"]))
                pid_file = Path(info["pidFile"])
                self.assertFalse(pid_file.exists(), result.stderr)
                self.assertFalse(pid_file.parent.parent.exists(), result.stderr)
                self.assertTrue(Path(legacy["pidFile"]).exists())
        stopped = subprocess.run([sys.executable, str(SCRIPTS / "broker-cleanup.py"), str(root)],
                                 capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertEqual(legacy_exit.read_text(encoding="utf-8"), str(legacy["pid"]))


if __name__ == "__main__":
    unittest.main()
