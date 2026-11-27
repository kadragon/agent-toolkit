"""Exercise the scan output and status markers without GitHub credentials or network."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT = Path(__file__).with_name("fetch-alerts.sh").resolve()
GH_FIXTURE = """\
import json
import os
import subprocess
import sys

args = sys.argv[1:]
if args == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["repo", "view"]:
    print("owner repo https://github.com/owner/repo PRIVATE")
    sys.exit(0)
assert args[:3] == ["api", "--hostname", "github.com"], args
kind = "dependabot" if args[3] == "graphql" else args[3].split("/")[3]
with open(os.environ["ALERT_FIXTURE"], encoding="utf-8") as fixture:
    response = json.load(fixture)[kind]
if isinstance(response, str):
    sys.exit(response)
if "--jq" in args:
    sys.exit(subprocess.run(["jq", args[args.index("--jq") + 1]], input=json.dumps(response), text=True).returncode)
print(json.dumps(response))
"""


def dependabot(total=0, nodes=()):
    return {"data": {"repository": {"vulnerabilityAlerts": {"totalCount": total, "nodes": list(nodes)}}}}


class FetchAlertsTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "scan"
        gh = self.root / "gh"
        gh.write_text(f"#!{sys.executable}\n{GH_FIXTURE}", encoding="utf-8")
        gh.chmod(0o755)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"],
                       cwd=self.root, check=True)

    def scan(self, db=None, code=(), secret=()):
        fixture = self.root / "responses.json"
        fixture.write_text(json.dumps({"dependabot": dependabot() if db is None else db,
                                       "code-scanning": code, "secret-scanning": secret}), encoding="utf-8")
        env = dict(os.environ, PATH=f"{self.root}{os.pathsep}{os.environ['PATH']}", ALERT_FIXTURE=str(fixture))
        subprocess.run(["bash", str(SCRIPT), str(self.output)], cwd=self.root, env=env,
                       check=True, capture_output=True, text=True)

    def test_permission_and_not_found_are_unreadable(self):
        self.scan(code="gh: Resource not accessible by integration (HTTP 403)",
                  secret="gh: Not Found (HTTP 404)")
        errors = (self.output / ".fetch-errors").read_text(encoding="utf-8")
        for kind in ("code-scanning", "secret-scanning"):
            self.assertIn(f"ERROR: {kind} fetch failed", errors)
            self.assertFalse((self.output / f"{kind}.disabled").exists())

    def test_only_explicit_feature_disabled_messages_confirm_disabled(self):
        self.scan(code="gh: GitHub Advanced Security is not enabled for this repository. (HTTP 403)",
                  secret="gh: Secret scanning is disabled for this repository. (HTTP 404)")
        self.assertTrue((self.output / "code-scanning.disabled").exists())
        self.assertTrue((self.output / "secret-scanning.disabled").exists())
        self.assertFalse((self.output / ".fetch-errors").exists())

    def test_partial_scans_are_marked_per_type_and_reuse_clears_markers(self):
        code = [{"number": n} for n in range(1, 101)]
        self.scan(db=dependabot(2, [{"number": 1}]), code=code, secret=[{"number": 2, "secret": "fixture"}])
        self.assertTrue((self.output / "dependabot.truncated").exists())
        self.assertTrue((self.output / "code-scanning.truncated").exists())
        self.assertFalse((self.output / "secret-scanning.truncated").exists())
        self.assertFalse((self.output / ".fetch-errors").exists())
        self.assertEqual(json.loads((self.output / "secret-scanning.json").read_text(encoding="utf-8")), [{"number": 2}])
        self.scan()
        self.assertEqual(list(self.output.glob("*.truncated")), [])

    def test_invalid_success_responses_are_flagged_without_losing_other_types(self):
        self.scan(db={**dependabot(), "errors": [{"message": "permission denied"}]}, code={"message": "unavailable"},
                  secret=[{"number": 2}])
        errors = (self.output / ".fetch-errors").read_text(encoding="utf-8")
        self.assertIn("ERROR: dependabot response incomplete", errors)
        self.assertIn("ERROR: code-scanning returned invalid alert JSON", errors)
        self.assertNotIn("secret-scanning", errors)
        self.assertEqual(json.loads((self.output / "secret-scanning.json").read_text(encoding="utf-8")), [{"number": 2}])


if __name__ == "__main__":
    unittest.main()
