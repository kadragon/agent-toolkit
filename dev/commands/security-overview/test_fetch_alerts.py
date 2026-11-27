"""Exercise the scan output and status markers without GitHub credentials or network."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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
    assert args[2] == "https://github.com/owner/repo.git", args
    print("owner repo https://github.com/owner/repo PRIVATE")
    sys.exit(0)
assert args[:3] == ["api", "--hostname", "github.com"], args
kind = "dependabot" if args[3] == "graphql" else args[3].split("/")[3]
with open(os.environ["ALERT_FIXTURE"], encoding="utf-8") as fixture:
    response = json.load(fixture)[kind]
if isinstance(response, dict) and "fixture_stderr" in response:
    if "fixture_exit" in response:
        print(json.dumps(response["payload"]), end="", flush=True)
        print(response["fixture_stderr"], file=sys.stderr)
        sys.exit(response["fixture_exit"])
    print(response["fixture_stderr"], file=sys.stderr)
    response = response["payload"]
if isinstance(response, str):
    sys.exit(response)
if "--jq" in args:
    sys.exit(subprocess.run(["jq", args[args.index("--jq") + 1]], input=json.dumps(response), text=True).returncode)
print(json.dumps(response))
"""


def dependabot(total=0, nodes=()):
    return {"data": {"repository": {"vulnerabilityAlerts": {"totalCount": total, "nodes": list(nodes)}}}}


def fixture_git_env():
    selectors = subprocess.check_output(["git", "rev-parse", "--local-env-vars"], text=True).splitlines()
    return {name: value for name, value in os.environ.items() if name not in selectors}


class FetchAlertsTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "scan"
        gh = self.root / "gh"
        gh.write_text(f"#!{sys.executable}\n{GH_FIXTURE}", encoding="utf-8")
        gh.chmod(0o755)
        self.env = fixture_git_env()
        subprocess.run(["git", "init", "-q", str(self.root)], env=self.env, check=True)
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"],
                       cwd=self.root, env=self.env, check=True)

    def scan(self, db=None, code=(), secret=(), *, trace=False):
        fixture = self.root / "responses.json"
        fixture.write_text(json.dumps({"dependabot": dependabot() if db is None else db,
                                       "code-scanning": code, "secret-scanning": secret}), encoding="utf-8")
        env = dict(self.env, PATH=f"{self.root}{os.pathsep}{self.env['PATH']}", ALERT_FIXTURE=str(fixture))
        options = ["-x"] if trace else []
        return subprocess.run(["bash", *options, str(SCRIPT), str(self.output)], cwd=self.root, env=env,
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

    def test_invalid_secret_response_is_flagged_before_redaction(self):
        self.scan(secret={})
        errors = self.output / ".fetch-errors"
        self.assertTrue(errors.exists(), "a successful non-array response must mark the scan failed")
        self.assertIn("ERROR: secret-scanning returned invalid alert JSON", errors.read_text(encoding="utf-8"))

    def test_secret_is_redacted_before_shell_trace(self):
        result = self.scan(secret=[{"number": 7, "secret": "fixture-trace-secret"}], trace=True)
        self.assertIn("+ fetch_rest_alerts secret-scanning", result.stderr)
        self.assertNotIn("fixture-trace-secret", result.stderr)
        self.assertEqual(json.loads((self.output / "secret-scanning.json").read_text(encoding="utf-8")), [{"number": 7}])

    def test_rest_diagnostics_do_not_contaminate_alert_json(self):
        self.scan(code={"payload": [{"number": 1}], "fixture_stderr": "gh: notice"})
        self.assertEqual(json.loads((self.output / "code-scanning.json").read_text(encoding="utf-8")), [{"number": 1}])
        self.assertFalse((self.output / ".fetch-errors").exists())

    def test_disabled_rest_diagnostic_with_error_body(self):
        self.scan(code={"payload": {"message": "disabled"}, "fixture_exit": 1, "fixture_stderr":
                        "gh: Code scanning is not enabled for this repository. (HTTP 403)"})
        self.assertTrue((self.output / "code-scanning.disabled").exists())
        self.assertFalse((self.output / ".fetch-errors").exists())


class FixtureIsolationTest(unittest.TestCase):
    def test_inherited_git_selectors_do_not_redirect_fixture(self):
        with TemporaryDirectory() as unrelated:
            env = fixture_git_env()
            subprocess.run(["git", "init", "-q", unrelated], env=env, check=True)
            git_dir = str(Path(unrelated) / ".git")
            fixture = FetchAlertsTest()
            self.addCleanup(fixture.doCleanups)
            with patch.dict(os.environ, GIT_DIR=git_dir, GIT_WORK_TREE=unrelated):
                fixture.setUp()
                remotes = subprocess.check_output(["git", "--git-dir", git_dir, "remote"], env=env, text=True)
                self.assertEqual(remotes.strip(), "")
                fixture.scan()
            self.assertEqual((fixture.output / "repo.txt").read_text(encoding="utf-8").strip(),
                             "owner/repo https://github.com/owner/repo")


if __name__ == "__main__":
    unittest.main()
