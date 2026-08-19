#!/usr/bin/env python3
"""Regression tests for preflight.sh's per-cycle cache.

One review cycle invokes preflight.sh from ~7 separate SKILL.md blocks, each block re-running it
purely so it reads standalone. Every live run costs two hub.sh round trips plus a `git fetch`
(~2s measured in this repo). The result is now cached at
`$(git rev-parse --git-dir)/task-review-cycle-preflight.json` and served back while still valid.

The cache is keyed on the *current branch*, not on time alone: Setup runs before the cycle's
Step 0 creates the feature branch, so a Setup-era entry names the wrong `feature_branch` the
moment the branch is cut. Reusing it would hand the reviewer prompt `${FEATURE_BRANCH}=main`.
That invalidation is the case these tests exist to pin, alongside the `--no-hub` mode key, the
TTL, `--refresh`, `PREFLIGHT_CACHE=0`, and the rule that an errored probe is never cached.

Cache hits are asserted by *counting hub.sh invocations*, not by timing: a served cache makes
zero calls. The stub hub.sh is resolved by preflight.sh relative to its own directory, so every
case runs against a throwaway git repo — no network, no gh, no agy/codex assumptions.

Run: python3 dev/skills/task-review-cycle/scripts/test_preflight.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "preflight.sh"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []

# A hub.sh stub that logs one line per invocation and answers both subcommands preflight.sh
# uses. `detect` reports a clean GitHub hub so `has_errors` stays false (an errored result is
# deliberately never cached, which would mask every other case here).
STUB_HUB = """#!/usr/bin/env bash
echo "$1" >> "$(dirname "${BASH_SOURCE[0]}")/../calls.log"
case "$1" in
  detect)    echo '{"hub_type": "github", "token_present": true, "errors": []}' ;;
  repo-info) echo '{"owner_repo": "acme/widget", "default_branch": "main", "merge_strategy": {}}' ;;
  *)         echo '{}' ;;
esac
"""

# Same, but `detect` reports an error so preflight.sh emits has_errors: true.
STUB_HUB_ERR = """#!/usr/bin/env bash
echo "$1" >> "$(dirname "${BASH_SOURCE[0]}")/../calls.log"
case "$1" in
  detect)    echo '{"hub_type": "none", "token_present": false, "errors": ["gh not authenticated"]}' ;;
  repo-info) echo '{}' ;;
  *)         echo '{}' ;;
esac
"""


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def make_repo(tmp: Path, name: str, stub: str = STUB_HUB) -> Path:
    """A git repo with one commit, holding preflight.sh next to a counting hub.sh stub."""
    repo = tmp / name
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)
    shutil.copy(SCRIPT, scripts / "preflight.sh")
    hub = scripts / "hub.sh"
    hub.write_text(stub, encoding="utf-8")
    hub.chmod(0o755)
    return repo


def call_count(repo: Path) -> int:
    log = repo / "calls.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def reset_calls(repo: Path) -> None:
    log = repo / "calls.log"
    if log.exists():
        log.unlink()


def cache_file(repo: Path) -> Path:
    return repo / ".git" / "task-review-cycle-preflight.json"


def run(repo: Path, *args: str, **env_overrides) -> dict:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_overrides.items()})
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "preflight.sh"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_stdout": proc.stdout, "_stderr": proc.stderr, "_rc": proc.returncode}


def checkout(repo: Path, branch: str) -> None:
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        print("\n-- a live run writes the cache; the next run is served from it --")
        repo = make_repo(tmp, "hit")
        first = run(repo)
        check("first run probes the hub and reports the branch",
              first.get("feature_branch") == "main" and call_count(repo) == 2,
              f"got {first}, calls={call_count(repo)}")
        check("the cache file lands under the git dir", cache_file(repo).is_file())

        reset_calls(repo)
        second = run(repo)
        check("second run makes zero hub calls", call_count(repo) == 0,
              f"calls={call_count(repo)}")
        check("second run returns identical JSON", second == first,
              f"{second} != {first}")

        print("\n-- a branch change invalidates (Setup runs before Step 0 cuts the branch) --")
        reset_calls(repo)
        checkout(repo, "feat/thing")
        after = run(repo)
        check("the hub is probed again", call_count(repo) == 2, f"calls={call_count(repo)}")
        check("feature_branch follows the checkout",
              after.get("feature_branch") == "feat/thing", f"got {after}")

        reset_calls(repo)
        again = run(repo)
        check("the new branch then caches in its own right",
              call_count(repo) == 0 and again.get("feature_branch") == "feat/thing",
              f"calls={call_count(repo)}, got {again}")

        print("\n-- --no-hub is part of the key --")
        modes = make_repo(tmp, "modes")
        run(modes)
        reset_calls(modes)
        nohub = run(modes, "--no-hub")
        check("a --no-hub run does not reuse the hub-mode entry",
              nohub.get("no_hub") is True and nohub.get("hub_type") == "none",
              f"got {nohub}")
        reset_calls(modes)
        hub_again = run(modes)
        check("the hub-mode run does not reuse the --no-hub entry either",
              hub_again.get("no_hub") is False and hub_again.get("hub_type") == "github"
              and call_count(modes) == 2,
              f"got {hub_again}, calls={call_count(modes)}")

        print("\n-- --refresh forces a live run --")
        refresh = make_repo(tmp, "refresh")
        run(refresh)
        reset_calls(refresh)
        run(refresh, "--refresh")
        check("--refresh re-probes the hub", call_count(refresh) == 2,
              f"calls={call_count(refresh)}")
        reset_calls(refresh)
        run(refresh)
        check("--refresh leaves a usable cache behind", call_count(refresh) == 0,
              f"calls={call_count(refresh)}")

        print("\n-- PREFLIGHT_CACHE=0 disables read and write --")
        off = make_repo(tmp, "disabled")
        run(off, PREFLIGHT_CACHE=0)
        check("no cache file is written", not cache_file(off).exists())
        reset_calls(off)
        run(off, PREFLIGHT_CACHE=0)
        check("every run probes the hub", call_count(off) == 2, f"calls={call_count(off)}")

        print("\n-- an expired entry is not served --")
        ttl = make_repo(tmp, "ttl")
        run(ttl)
        # Backdate the entry by 30 minutes; the default TTL is 15.
        old = time.time() - 30 * 60
        os.utime(cache_file(ttl), (old, old))
        reset_calls(ttl)
        run(ttl)
        check("a stale entry falls back to a live run", call_count(ttl) == 2,
              f"calls={call_count(ttl)}")

        print("\n-- an errored probe is never cached --")
        bad = make_repo(tmp, "errored", stub=STUB_HUB_ERR)
        errored = run(bad)
        check("the error surfaces", errored.get("has_errors") is True, f"got {errored}")
        check("nothing is written", not cache_file(bad).exists())
        reset_calls(bad)
        run(bad)
        check("the failure re-surfaces on the next run", call_count(bad) == 2,
              f"calls={call_count(bad)}")

        print("\n-- a corrupt cache file degrades to a live run, not a crash --")
        corrupt = make_repo(tmp, "corrupt")
        run(corrupt)
        cache_file(corrupt).write_text("{not json", encoding="utf-8")
        reset_calls(corrupt)
        recovered = run(corrupt)
        check("preflight still returns valid JSON",
              recovered.get("feature_branch") == "main" and call_count(corrupt) == 2,
              f"got {recovered}, calls={call_count(corrupt)}")

    passed = sum(_results)
    total = len(_results)
    print(f"\n=== Results: {passed} PASS, {total - passed} FAIL ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
