#!/usr/bin/env python3
"""Regression tests for ci-wait.sh's consecutive-failure (rework) cap.

The behavior under test is edge #8/C3: "hard-stop after 3 CI failures" existed only as
prose, so the orchestrator had to remember the count across separate script invocations —
exactly the kind of tally a fresh context loses. The cap now lives in the script and is
reported as `reason: "rework-cap"`.

Covered: the counter increments across invocations, trips at the 3rd real failure, resets
on either kind of pass (`success` and no-CI-configured), and is NOT incremented by a timeout
or a ci-status error. The timing constants are env-overridable purely so the timeout and
no-checks-grace branches are reachable here without editing the script.

Also covered: the opening fast-poll window. `harness-check` finishes in 13-22s, so a single
20s cadence discovers a pass up to a full interval late; the script polls at
CI_WAIT_FAST_POLL_INTERVAL for the first CI_WAIT_FAST_POLL_SECS and then falls back.

These cases count stub invocations rather than asserting on wall-clock gaps, which removes
flake from the *gap* between polls but not from the deadline itself: the status call precedes
the deadline check, so per-iteration overhead (a forked hub.sh, two jq calls, two `date`
calls) can trip the deadline one poll early. Each budget below is therefore set well above the
minimum that satisfies its assertion, so several slow iterations cannot red the gate.

ci-wait.sh resolves hub.sh relative to its own directory, so each case runs against a
stub hub.sh in a throwaway git repo — no network, no gh.

Run: python3 dev/skills/task-review-cycle/scripts/test_ci_wait.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ci-wait.sh"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def make_repo(tmp: Path, status: str, name: str = "") -> Path:
    """A git repo holding ci-wait.sh next to a hub.sh stub that always reports `status`.

    `name` overrides the directory, so two repos can share a status.
    """
    repo = tmp / (name or status.replace(" ", "_"))
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    shutil.copy(SCRIPT, scripts / "ci-wait.sh")
    stub = scripts / "hub.sh"
    stub.write_text(f'#!/usr/bin/env bash\necho \'{{"status": "{status}"}}\'\n', encoding="utf-8")
    stub.chmod(0o755)
    return repo


def make_counting_repo(tmp: Path, name: str) -> Path:
    """Like make_repo("pending"), but the stub records one line per invocation.

    Counting calls is what makes the cadence observable without timing assertions: over a
    fixed window, a tighter interval is simply more calls.
    """
    repo = tmp / name
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    shutil.copy(SCRIPT, scripts / "ci-wait.sh")
    stub = scripts / "hub.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'echo x >> "$(dirname "${BASH_SOURCE[0]}")/../calls.log"\n'
        "echo '{\"status\": \"pending\"}'\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return repo


def call_count(repo: Path) -> int:
    log = repo / "calls.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def run(repo: Path, pr: str = "7", timeout: int = 30, **env_overrides) -> dict:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_overrides.items()})
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "ci-wait.sh"), pr],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_stdout": proc.stdout, "_stderr": proc.stderr, "_rc": proc.returncode}


def strike_file(repo: Path, pr: str = "7") -> Path:
    return repo / ".git" / f"task-review-ci-strikes-{pr}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        print("\n-- the cap trips on the 3rd consecutive real failure --")
        repo = make_repo(tmp, "failure")
        first = run(repo)
        check("1st failure reports no reason and failures=1",
              first.get("passed") is False
              and "reason" not in first
              and first.get("failures") == 1, f"got {first}")

        second = run(repo)
        check("2nd failure still has no reason, failures=2",
              "reason" not in second and second.get("failures") == 2, f"got {second}")

        third = run(repo)
        check("3rd failure reports reason=rework-cap",
              third.get("reason") == "rework-cap"
              and third.get("failures") == 3
              and third.get("max_failures") == 3, f"got {third}")

        fourth = run(repo)
        check("it stays tripped on further failures",
              fourth.get("reason") == "rework-cap" and fourth.get("failures") == 4,
              f"got {fourth}")

        print("\n-- the opening window polls fast, then falls back --")
        fast = make_counting_repo(tmp, "fast_window")
        run(fast, CI_WAIT_TIMEOUT_SECS=6, CI_WAIT_POLL_INTERVAL=30,
            CI_WAIT_FAST_POLL_INTERVAL=1, CI_WAIT_FAST_POLL_SECS=10)
        check("a 1s opening cadence polls every second inside a 6s budget",
              call_count(fast) >= 4, f"got {call_count(fast)} calls, expected >= 4")

        slow = make_counting_repo(tmp, "slow_fallback")
        run(slow, CI_WAIT_TIMEOUT_SECS=2, CI_WAIT_POLL_INTERVAL=3,
            CI_WAIT_FAST_POLL_INTERVAL=1, CI_WAIT_FAST_POLL_SECS=0)
        # The status call precedes the deadline check, so a 3s sleep over a 2s budget still
        # costs one more poll: t=0 and t=3. The fast cadence would have polled at t=0,1,2, so
        # an upper bound alone discriminates — and it stays true if a slow first iteration
        # burns the whole budget and the run ends at one call.
        check("a zero-length opening window falls straight back to POLL_INTERVAL",
              call_count(slow) <= 2, f"got {call_count(slow)} calls, expected <= 2")

        clamped = make_counting_repo(tmp, "explicit_override")
        run(clamped, CI_WAIT_TIMEOUT_SECS=4, CI_WAIT_POLL_INTERVAL=1)
        check("an explicit POLL_INTERVAL below the 5s fast default is not slowed by it",
              call_count(clamped) >= 3, f"got {call_count(clamped)} calls, expected >= 3")

        floored = make_counting_repo(tmp, "zero_interval")
        run(floored, CI_WAIT_TIMEOUT_SECS=4, CI_WAIT_POLL_INTERVAL=0,
            CI_WAIT_FAST_POLL_INTERVAL=0)
        check("a zero fast interval is floored instead of busy-looping",
              call_count(floored) <= 2, f"got {call_count(floored)} calls, expected <= 2")

        # The slow path had the same hole for longer: the numeric guard accepts 0, so
        # CI_WAIT_POLL_INTERVAL=0 turned the long tail into `sleep 0`. A zero-length opening
        # window forces the fallback branch on the very first iteration, so this exercises
        # POLL_INTERVAL alone — the fast interval never runs.
        # Killed rather than waited out. The floor is hardcoded at 20s, so once it works the
        # very first sleep outlasts any budget worth setting — letting the run finish would
        # add 20s to every suite invocation to observe a single call. Pre-fix the same window
        # is a `sleep 0` busy loop, and the call count over a fixed 4s discriminates the two
        # without either side having to terminate.
        slow_floored = make_counting_repo(tmp, "zero_slow_interval")
        try:
            run(slow_floored, timeout=4, CI_WAIT_POLL_INTERVAL=0, CI_WAIT_FAST_POLL_SECS=0)
        except subprocess.TimeoutExpired:
            pass
        check("a zero POLL_INTERVAL is floored instead of busy-looping the long tail",
              call_count(slow_floored) <= 3, f"got {call_count(slow_floored)} calls, expected <= 3")

        print("\n-- a pass clears the counter --")
        passing = make_repo(tmp, "success")
        strike_file(passing).write_text("2\n", encoding="utf-8")
        result = run(passing)
        check("a passing run reports passed=true", result.get("passed") is True, f"got {result}")
        check("and deletes the strike file", not strike_file(passing).exists())

        print("\n-- non-rework outcomes never increment --")
        errored = make_repo(tmp, "bogus-status")
        strike_file(errored).write_text("1\n", encoding="utf-8")
        result = run(errored)
        check("a ci-status error is reported as its own reason",
              result.get("passed") is False
              and result.get("reason", "").startswith("ci-status returned"), f"got {result}")
        check("and leaves the counter untouched",
              strike_file(errored).read_text().strip() == "1")

        timed_out = make_repo(tmp, "pending")
        strike_file(timed_out).write_text("2\n", encoding="utf-8")
        result = run(timed_out, CI_WAIT_TIMEOUT_SECS=1, CI_WAIT_POLL_INTERVAL=1)
        check("a timeout is reported as reason=timeout",
              result.get("passed") is False and result.get("reason") == "timeout", f"got {result}")
        check("and leaves the counter untouched",
              strike_file(timed_out).read_text().strip() == "2")

        print("\n-- a no-CI repo counts as a pass and clears the counter --")
        no_ci = make_repo(tmp, "none")
        strike_file(no_ci).write_text("2\n", encoding="utf-8")
        result = run(no_ci, CI_WAIT_NO_CHECKS_GRACE_SECS=0)
        check("no CI checks reports passed=true",
              result.get("passed") is True
              and result.get("reason") == "no CI checks found", f"got {result}")
        check("and clears the strike file like a real pass",
              not strike_file(no_ci).exists())

        print("\n-- a repo WITH CI configured never passes on an unregistered check set --")
        configured = make_repo(tmp, "none", name="none_configured")
        (configured / ".github" / "workflows").mkdir(parents=True)
        (configured / ".github" / "workflows" / "ci.yml").write_text("on: pull_request\n", encoding="utf-8")
        strike_file(configured).write_text("2\n", encoding="utf-8")
        result = run(configured, CI_WAIT_NO_CHECKS_GRACE_SECS=0,
                     CI_WAIT_CONFIGURED_GRACE_SECS=1, CI_WAIT_POLL_INTERVAL=1)
        check("checks that never register report passed=false",
              result.get("passed") is False
              and result.get("reason") == "checks-never-registered", f"got {result}")
        check("and leave the strike counter untouched — it is not rework",
              strike_file(configured).exists()
              and strike_file(configured).read_text().strip() == "2")

        print("\n-- a Forgejo/Gitea workflow directory counts as CI configured too --")
        forgejo = make_repo(tmp, "none", name="none_forgejo")
        (forgejo / ".forgejo" / "workflows").mkdir(parents=True)
        (forgejo / ".forgejo" / "workflows" / "ci.yaml").write_text("on: pull_request\n", encoding="utf-8")
        result = run(forgejo, CI_WAIT_NO_CHECKS_GRACE_SECS=0,
                     CI_WAIT_CONFIGURED_GRACE_SECS=1, CI_WAIT_POLL_INTERVAL=1)
        check("a .forgejo/workflows entry blocks the no-CI pass",
              result.get("passed") is False
              and result.get("reason") == "checks-never-registered", f"got {result}")

        print("\n-- a push-only workflow does not make CI 'configured' for a PR --")
        push_only = make_repo(tmp, "none", name="none_push_only")
        (push_only / ".github" / "workflows").mkdir(parents=True)
        (push_only / ".github" / "workflows" / "deploy.yml").write_text(
            "on:\n  push:\n    branches: [main]\n", encoding="utf-8")
        result = run(push_only, CI_WAIT_NO_CHECKS_GRACE_SECS=0, CI_WAIT_POLL_INTERVAL=1)
        check("a workflow with no PR trigger still passes as no-CI",
              result.get("passed") is True
              and result.get("reason") == "no CI checks found", f"got {result}")

        print("\n-- a non-YAML file in the workflows dir does not make CI 'configured' --")
        keep_only = make_repo(tmp, "none", name="none_gitkeep")
        (keep_only / ".github" / "workflows").mkdir(parents=True)
        (keep_only / ".github" / "workflows" / ".gitkeep").write_text("", encoding="utf-8")
        (keep_only / ".github" / "workflows" / "README.md").write_text(
            "workflows run on pull_request\n", encoding="utf-8")
        result = run(keep_only, CI_WAIT_NO_CHECKS_GRACE_SECS=0, CI_WAIT_POLL_INTERVAL=1)
        check("a .gitkeep/README leftover still passes as no-CI",
              result.get("passed") is True
              and result.get("reason") == "no CI checks found", f"got {result}")

        print("\n-- a symlinked workflow file counts as CI configured --")
        linked = make_repo(tmp, "none", name="none_symlink")
        (linked / ".github" / "workflows").mkdir(parents=True)
        (linked / "shared-ci.yml").write_text("on: pull_request\n", encoding="utf-8")
        (linked / ".github" / "workflows" / "ci.yml").symlink_to(linked / "shared-ci.yml")
        result = run(linked, CI_WAIT_NO_CHECKS_GRACE_SECS=0,
                     CI_WAIT_CONFIGURED_GRACE_SECS=1, CI_WAIT_POLL_INTERVAL=1)
        check("a symlinked workflow blocks the no-CI pass",
              result.get("passed") is False
              and result.get("reason") == "checks-never-registered", f"got {result}")

        print("\n-- a zero configured-grace override falls back to the default --")
        zero_grace = make_repo(tmp, "none", name="none_zero_grace")
        (zero_grace / ".github" / "workflows").mkdir(parents=True)
        (zero_grace / ".github" / "workflows" / "ci.yml").write_text("on: pull_request\n", encoding="utf-8")
        result = run(zero_grace, CI_WAIT_NO_CHECKS_GRACE_SECS=0,
                     CI_WAIT_CONFIGURED_GRACE_SECS=0, CI_WAIT_TIMEOUT_SECS=1,
                     CI_WAIT_POLL_INTERVAL=1)
        check("a zero grace does not report checks-never-registered on the first poll",
              result.get("passed") is False and result.get("reason") == "timeout", f"got {result}")

        print("\n-- an empty workflow directory is not CI configured --")
        empty_dir = make_repo(tmp, "none", name="none_empty_workflows")
        (empty_dir / ".github" / "workflows").mkdir(parents=True)
        result = run(empty_dir, CI_WAIT_NO_CHECKS_GRACE_SECS=0, CI_WAIT_POLL_INTERVAL=1)
        check("an empty workflows dir still passes as no-CI",
              result.get("passed") is True
              and result.get("reason") == "no CI checks found", f"got {result}")

        print("\n-- a garbage configured-grace override falls back, it does not kill the script --")
        garbage = make_repo(tmp, "none", name="none_garbage_grace")
        (garbage / ".github" / "workflows").mkdir(parents=True)
        (garbage / ".github" / "workflows" / "ci.yml").write_text("on: pull_request\n", encoding="utf-8")
        result = run(garbage, CI_WAIT_NO_CHECKS_GRACE_SECS=0,
                     CI_WAIT_CONFIGURED_GRACE_SECS="abc", CI_WAIT_TIMEOUT_SECS=1,
                     CI_WAIT_POLL_INTERVAL=1)
        check("a non-numeric grace keeps the default and still emits JSON",
              result.get("passed") is False
              and result.get("reason") in ("timeout", "checks-never-registered"), f"got {result}")

        print("\n-- a garbage cap override falls back to 3, it does not kill the script --")
        capped = make_repo(tmp, "failure0")
        (capped / "scripts" / "hub.sh").write_text(
            '#!/usr/bin/env bash\necho \'{"status": "failure"}\'\n', encoding="utf-8")
        run(capped, CI_WAIT_MAX_STRIKES="abc")
        run(capped, CI_WAIT_MAX_STRIKES="abc")
        result = run(capped, CI_WAIT_MAX_STRIKES="abc")
        check("a non-numeric CI_WAIT_MAX_STRIKES still trips at the default 3",
              result.get("reason") == "rework-cap" and result.get("max_failures") == 3,
              f"got {result}")

        print("\n-- per-PR isolation --")
        repo2 = make_repo(tmp, "failure2")
        # `failure2` is not a status ci-wait.sh knows; rebuild the stub as a real failure.
        (repo2 / "scripts" / "hub.sh").write_text(
            '#!/usr/bin/env bash\necho \'{"status": "failure"}\'\n', encoding="utf-8")
        run(repo2, pr="7")
        run(repo2, pr="7")
        other = run(repo2, pr="8")
        check("a different PR starts its own count",
              other.get("failures") == 1 and "reason" not in other, f"got {other}")

        print("\n-- a corrupt strike file degrades to zero, not a crash --")
        corrupt = make_repo(tmp, "failure3")
        (corrupt / "scripts" / "hub.sh").write_text(
            '#!/usr/bin/env bash\necho \'{"status": "failure"}\'\n', encoding="utf-8")
        strike_file(corrupt).write_text("not-a-number\n", encoding="utf-8")
        result = run(corrupt)
        check("a non-numeric counter restarts at 1",
              result.get("failures") == 1, f"got {result}")

        print("\n-- a stale head's status is pending, not an answer --")
        # Right after a push the hub can still describe the previous commit: PR #362 struck one
        # real failure twice that way. Each stub answers for `first` once, then for HEAD.
        def sha_repo(name, first_status, first_sha, then_status):
            repo = make_repo(tmp, "pending", name=name)
            commit = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                      "--allow-empty", "-m"]
            subprocess.run(commit + ["previous"], cwd=repo, check=True)
            previous = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                                      capture_output=True, text=True).stdout.strip()
            subprocess.run(commit + ["head"], cwd=repo, check=True)
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                                  capture_output=True, text=True).stdout.strip()
            first = previous if first_sha == "previous" else first_sha
            (repo / "scripts" / "hub.sh").write_text(
                "#!/usr/bin/env bash\n"
                'log="$(dirname "${BASH_SOURCE[0]}")/../calls.log"\n'
                'echo x >> "$log"\n'
                'if [ "$(wc -l < "$log")" -le 1 ]; then\n'
                f"  echo '{{\"status\": \"{first_status}\", \"head_sha\": \"{first}\"}}'\n"
                "else\n"
                f"  echo '{{\"status\": \"{then_status}\", \"head_sha\": \"{head}\"}}'\n"
                "fi\n",
                encoding="utf-8")
            return repo

        stale = sha_repo("stale_failure", "failure", "previous", "success")
        result = run(stale, CI_WAIT_POLL_INTERVAL=1)
        check("a stale-SHA failure then a head-SHA success passes",
              result.get("passed") is True and call_count(stale) == 2, f"got {result}")
        check("the stale-SHA failure leaves no strike file",
              not strike_file(stale).exists())

        stale_green = sha_repo("stale_success", "success", "previous", "failure")
        result = run(stale_green, CI_WAIT_POLL_INTERVAL=1)
        check("a stale-SHA success is not a pass; the head's failure is struck once",
              result.get("passed") is False and result.get("failures") == 1
              and call_count(stale_green) == 2, f"got {result}")

        foreign = sha_repo("foreign_sha", "failure", "1" * 40, "success")
        result = run(foreign, CI_WAIT_POLL_INTERVAL=1)
        check("a SHA this checkout lacks (a bot's commit) is answered, not waited out",
              result.get("failures") == 1 and call_count(foreign) == 1, f"got {result}")

        print("\n-- the real hub.sh reports the head SHA its GitHub checks describe --")
        hub_repo = tmp / "hub_github"
        hub_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=hub_repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:o/r.git"],
                       cwd=hub_repo, check=True)
        bindir = tmp / "gh_bin"
        bindir.mkdir()
        # `pr view` answers with the snapshot in $GH_VIEW (unset → the call fails); `pr checks`
        # always reports a stale failure, so reading it instead of the snapshot shows up red.
        (bindir / "gh").write_text(
            "#!/usr/bin/env bash\n"
            'case "$1 $2" in\n'
            '  "pr view") [ -n "${GH_VIEW:-}" ] || exit 1; printf \'%s\' "$GH_VIEW"; exit 0 ;;\n'
            "  \"pr checks\") echo '[{\"bucket\": \"fail\"}]'; exit 1 ;;\n"
            "esac\n"
            "exit 1\n",
            encoding="utf-8")
        (bindir / "gh").chmod(0o755)

        def hub_status(rollup):
            view = None if rollup is None else json.dumps(
                {"headRefOid": "a" * 40, "statusCheckRollup": rollup})
            env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}")
            env.pop("GH_VIEW", None)
            if view is not None:
                env["GH_VIEW"] = view
            proc = subprocess.run(
                ["bash", str(SCRIPT.parent / "hub.sh"), "ci-status", "7"], cwd=hub_repo,
                capture_output=True, text=True, timeout=30, env=env)
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                return {"_stdout": proc.stdout, "_stderr": proc.stderr}

        def run_ctx(conclusion, status="COMPLETED", name="test", started="2026-01-01T00:00:00Z"):
            return {"__typename": "CheckRun", "name": name, "workflowName": "ci",
                    "status": status, "conclusion": conclusion, "startedAt": started}

        status = hub_status([run_ctx("FAILURE")])
        check("ci-status carries headRefOid as head_sha",
              status.get("status") == "failure" and status.get("head_sha") == "a" * 40,
              f"got {status}")
        status = hub_status([run_ctx("", status="IN_PROGRESS")])
        check("checks come from the same snapshot as the head, not a second request",
              status.get("status") == "pending" and status.get("head_sha") == "a" * 40,
              f"got {status}")
        status = hub_status([run_ctx("FAILURE", started="2026-01-01T00:00:00Z"),
                             run_ctx("SUCCESS", started="2026-01-01T00:05:00Z")])
        check("a rerun supersedes the older failure of the same check",
              status.get("status") == "success" and status.get("checks") == 1, f"got {status}")
        status = hub_status([run_ctx("SUCCESS"), run_ctx("SKIPPED", name="lint"),
                             {"__typename": "StatusContext", "context": "ext", "state": "SUCCESS"}])
        check("skipped checks and status contexts count as passing",
              status.get("status") == "success" and status.get("checks") == 3, f"got {status}")
        status = hub_status([run_ctx("CANCELLED"),
                             {"__typename": "StatusContext", "context": "ext", "state": "PENDING"}])
        check("a pending status context outranks a cancelled check",
              status.get("status") == "pending", f"got {status}")
        status = hub_status([{"__typename": "StatusContext", "context": "ext", "state": "ERROR"}])
        check("an errored status context is a failure", status.get("status") == "failure",
              f"got {status}")
        status = hub_status([])
        check("an empty rollup reports none with the head",
              status.get("status") == "none" and status.get("head_sha") == "a" * 40,
              f"got {status}")
        status = hub_status(None)
        check("a failed view reports none without a head",
              status.get("status") == "none" and "head_sha" not in status, f"got {status}")

    print("\n-- the default deadline fires inside the Bash tool's 600s ceiling --")
    # The orchestrator runs ci-wait.sh in the foreground; a deadline past 600s is killed first and
    # returns no JSON, so the `timeout` branch never reaches the caller. The last sleep and one
    # status call can land after the deadline, so both must fit under the ceiling too.
    source = SCRIPT.read_text(encoding="utf-8")
    deadline = int(re.search(r'CI_WAIT_TIMEOUT_SECS:-(\d+)', source).group(1))
    poll = int(re.search(r'CI_WAIT_POLL_INTERVAL:-(\d+)', source).group(1))
    check("default deadline + one poll + call margin stays under 600s",
          deadline + poll + 30 <= 600, f"deadline={deadline} poll={poll}")

    passed = sum(_results)
    total = len(_results)
    print(f"\n=== Results: {passed} PASS, {total - passed} FAIL ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
