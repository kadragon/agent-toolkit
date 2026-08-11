#!/usr/bin/env python3
"""Regression tests for codex-review.sh's stale-state prune and per-workspace lock.

The behavior under test exists because of a Windows-only failure mode in the openai-codex
plugin: the shared app-server broker is spawned as a child of whichever companion first needed
it, and every teardown path there runs `taskkill /PID x /T /F`. Killing any companion therefore
takes the shared broker down with it, and the next review reuses metadata pointing at a dead
process — job records frozen at `running`, a `broker.json` naming a dead PID — then dies mid-turn
with no JSON on stdout ("payload status: unparsed"). The prune clears that metadata before each
run; the lock stops two cycles from racing into it.

Covered: dead-PID job records are rewritten and mirrored into state.json, live and already-finished
records are left byte-identical, a dead broker record takes its `cxc-*` session dir with it, a live
one survives, an unreadable liveness probe counts as alive, another workspace's directory is never
touched, and the lock skips with status 75 for a live owner while reclaiming a stale one.

None of the cases reach the companion: both the lock and the prune run before it is launched, so
the stub path is deliberately non-existent and the resulting non-zero exit is expected.

Run: python3 dev/skills/task-review/scripts/test_codex_review.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "codex-review.sh"

# A PID that cannot be live: above the 32-bit ceiling Linux and Windows both cap at.
DEAD_PID = 4294967290
EX_LOCKED = 75

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def bash_path(path) -> str:
    """`C:\\x\\y` → `/c/x/y`. The script consumes these as globs, which backslashes break."""
    text = str(path)
    if os.name == "nt" and len(text) > 1 and text[1] == ":":
        return "/" + text[0].lower() + text[2:].replace("\\", "/")
    return text


class LiveShell:
    """A live process whose PID is in the same space `kill -0` reads from inside the script.

    `os.getpid()` cannot stand in for this on Git Bash: a Python PID is a native Windows PID,
    while the script's `kill -0` sees MSYS PIDs. `exec sleep` keeps the shell's own `$$` as the
    surviving process, so the reported PID stays valid for the lifetime of the fixture.
    """

    def __enter__(self):
        # The PID goes through a file, not a pipe: `exec` never returns, so anything bash buffered
        # on stdout would sit there unflushed and a pipe read would block forever. A redirect is
        # flushed when the `echo` completes, which is before the `exec`.
        handle, raw = tempfile.mkstemp(prefix="codex-review-live-")
        os.close(handle)
        self.pid_file = Path(raw)
        self.proc = subprocess.Popen(["bash", "-c", f'echo $$ > "{bash_path(self.pid_file)}"; exec sleep 300'])
        deadline = time.time() + 30
        while time.time() < deadline:
            text = self.pid_file.read_text(encoding="utf-8").strip()
            if text:
                self.pid = int(text)
                return self
            time.sleep(0.05)
        raise RuntimeError("live-shell fixture never reported its PID")

    def __exit__(self, *_):
        self.proc.kill()
        self.proc.wait(timeout=10)
        self.pid_file.unlink(missing_ok=True)


def check(name, condition, detail=""):
    label = PASS if condition else FAIL
    print(f"  {label}  {name}" + (f"\n       {detail}" if detail and not condition else ""))
    _results.append(condition)


def job(job_id, status, pid):
    return {"id": job_id, "title": "Codex Review", "status": status, "phase": status, "pid": pid}


def make_workspace(
    state_root: Path, slug: str, jobs: list, broker_pid=None, session_dir=None, suffix="0123456789abcdef"
):
    """A companion state directory: jobs/, the state.json index, optionally broker.json."""
    ws = state_root / f"{slug}-{suffix}"
    (ws / "jobs").mkdir(parents=True)
    for record in jobs:
        (ws / "jobs" / f"{record['id']}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    index = {"version": 1, "config": {}, "jobs": [dict(r) for r in jobs]}
    (ws / "state.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    if broker_pid is not None:
        broker = {"endpoint": "unix:/tmp/broker.sock", "pid": broker_pid}
        if session_dir is not None:
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "broker.log").write_text("", encoding="utf-8")
            broker["sessionDir"] = str(session_dir)
        (ws / "broker.json").write_text(json.dumps(broker, indent=2), encoding="utf-8")
    return ws


def make_repo(tmp: Path, name: str) -> Path:
    """A git repo whose toplevel basename is the workspace slug the script derives."""
    repo = tmp / name
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    shutil.copy(SCRIPT, repo / "scripts" / "codex-review.sh")
    return repo


def run(repo: Path, tmp: Path, platform="posix", companion="/nonexistent/companion.mjs", **env_overrides):
    env = dict(os.environ)
    env.update(
        {
            "CODEX_REVIEW_PLATFORM": platform,
            "CODEX_REVIEW_STATE_ROOTS": bash_path(tmp / "state"),
            "CODEX_REVIEW_LOCK_ROOT": bash_path(tmp / "locks"),
        }
    )
    env.update({k: str(v) for k, v in env_overrides.items()})
    return subprocess.run(
        ["bash", str(repo / "scripts" / "codex-review.sh"), "plugin", "main", companion],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def case_prunes_dead_job(tmp: Path, _live: int):
    print("\ndead-PID job record")
    repo = make_repo(tmp, "wsprune")
    ws = make_workspace(tmp / "state", "wsprune", [job("review-dead", "running", DEAD_PID)])
    run(repo, tmp)
    record = read(ws / "jobs" / "review-dead.json")
    check("status rewritten to failed", record["status"] == "failed", str(record))
    check("phase rewritten to failed", record["phase"] == "failed", str(record))
    check("pid cleared", record["pid"] is None, str(record))
    check("errorMessage recorded", "Orphaned" in record.get("errorMessage", ""), str(record))
    index = read(ws / "state.json")
    check("state.json entry mirrored", index["jobs"][0]["status"] == "failed", str(index))


def case_keeps_live_and_finished(tmp: Path, live: int):
    print("\nlive and already-finished job records")
    repo = make_repo(tmp, "wskeep")
    ws = make_workspace(
        tmp / "state",
        "wskeep",
        [job("review-live", "running", live), job("review-done", "completed", DEAD_PID)],
    )
    before = {p.name: p.read_bytes() for p in (ws / "jobs").glob("*.json")}
    run(repo, tmp)
    after = {p.name: p.read_bytes() for p in (ws / "jobs").glob("*.json")}
    check("live running record byte-identical", before["review-live.json"] == after["review-live.json"])
    check("completed record byte-identical", before["review-done.json"] == after["review-done.json"])


def case_broker_dead(tmp: Path, _live: int):
    print("\ndead broker record")
    repo = make_repo(tmp, "wsbroker")
    session = tmp / "cxc-abc123"
    ws = make_workspace(tmp / "state", "wsbroker", [], broker_pid=DEAD_PID, session_dir=session)
    run(repo, tmp)
    check("broker.json deleted", not (ws / "broker.json").exists())
    check("cxc-* session dir removed", not session.exists())


def case_broker_alive(tmp: Path, live: int):
    print("\nlive broker record")
    repo = make_repo(tmp, "wsbrokerlive")
    session = tmp / "cxc-live01"
    ws = make_workspace(tmp / "state", "wsbrokerlive", [], broker_pid=live, session_dir=session)
    run(repo, tmp)
    check("broker.json kept", (ws / "broker.json").exists())
    check("session dir kept", session.exists())


def case_foreign_session_dir_kept(tmp: Path, _live: int):
    print("\nbroker record naming a non-plugin directory")
    repo = make_repo(tmp, "wsforeign")
    session = tmp / "not-a-broker-dir"
    ws = make_workspace(tmp / "state", "wsforeign", [], broker_pid=DEAD_PID, session_dir=session)
    run(repo, tmp)
    check("broker.json deleted", not (ws / "broker.json").exists())
    check("directory outside the cxc-* naming left alone", session.exists())


def case_unreadable_probe_counts_alive(tmp: Path, _live: int):
    print("\nliveness probe that cannot answer")
    repo = make_repo(tmp, "wsprobe")
    ws = make_workspace(tmp / "state", "wsprobe", [job("review-dead", "running", DEAD_PID)])
    before = (ws / "jobs" / "review-dead.json").read_bytes()
    # `windows` selects the tasklist probe, which does not exist on this runner.
    run(repo, tmp, platform="windows")
    check(
        "record left untouched when the probe is missing",
        (ws / "jobs" / "review-dead.json").read_bytes() == before,
    )


def case_other_workspace_untouched(tmp: Path, _live: int):
    print("\nanother workspace's state directory")
    repo = make_repo(tmp, "wsmine")
    mine = make_workspace(tmp / "state", "wsmine", [job("review-dead", "running", DEAD_PID)])
    other = make_workspace(tmp / "state", "wstheirs", [job("review-other", "running", DEAD_PID)])
    # `wsmine-extra` is a *different* repo whose directory `wsmine-extra-<hash>` the
    # `wsmine-*` glob also matches. Prefix is not identity — this is the case a plain glob loses.
    sibling = make_workspace(
        tmp / "state", "wsmine-extra", [job("review-sibling", "running", DEAD_PID)], suffix="fedcba9876543210"
    )
    # A directory under the same prefix whose suffix is not the companion's 16 hex digits.
    foreign = make_workspace(
        tmp / "state", "wsmine", [job("review-foreign", "running", DEAD_PID)], suffix="notahash"
    )
    before = {
        "other": (other / "jobs" / "review-other.json").read_bytes(),
        "sibling": (sibling / "jobs" / "review-sibling.json").read_bytes(),
        "foreign": (foreign / "jobs" / "review-foreign.json").read_bytes(),
    }
    run(repo, tmp)
    check(
        "unrelated workspace record byte-identical",
        (other / "jobs" / "review-other.json").read_bytes() == before["other"],
    )
    check(
        "prefix-colliding workspace record byte-identical",
        (sibling / "jobs" / "review-sibling.json").read_bytes() == before["sibling"],
    )
    check(
        "directory whose suffix is not a 16-hex hash left alone",
        (foreign / "jobs" / "review-foreign.json").read_bytes() == before["foreign"],
    )
    check(
        "own workspace still pruned",
        read(mine / "jobs" / "review-dead.json")["status"] == "failed",
    )


def case_lock(tmp: Path, live: int):
    print("\nper-workspace lock")
    repo = make_repo(tmp, "wslock")
    make_workspace(tmp / "state", "wslock", [])
    lock_dir = tmp / "locks" / "codex-review-wslock.lock"

    proc = run(repo, tmp)
    check("lock released on exit", not lock_dir.exists(), f"rc={proc.returncode}")

    lock_dir.mkdir(parents=True)
    (lock_dir / "pid").write_text(f"{live}\n", encoding="utf-8")
    proc = run(repo, tmp)
    check("live owner → exit 75", proc.returncode == EX_LOCKED, f"rc={proc.returncode} {proc.stderr}")
    check("live owner → reported on stderr", "already running" in proc.stderr, proc.stderr)
    check("live owner → lock left with its owner", (lock_dir / "pid").exists())

    (lock_dir / "pid").write_text(f"{DEAD_PID}\n", encoding="utf-8")
    proc = run(repo, tmp)
    check("stale owner → reclaimed", "reclaimed stale codex review lock" in proc.stderr, proc.stderr)
    check("stale owner → not skipped", proc.returncode != EX_LOCKED, f"rc={proc.returncode}")


def case_malformed_state_is_survivable(tmp: Path, _live: int):
    print("\nmalformed job record")
    repo = make_repo(tmp, "wsmalformed")
    ws = make_workspace(tmp / "state", "wsmalformed", [job("review-dead", "running", DEAD_PID)])
    (ws / "jobs" / "broken.json").write_text("{not json", encoding="utf-8")
    proc = run(repo, tmp)
    record = read(ws / "jobs" / "review-dead.json")
    check("sweep continues past the malformed record", record["status"] == "failed", str(record))
    check("script still reached the companion launch", "companion" in proc.stderr.lower(), proc.stderr)


def main():
    if not shutil.which("jq"):
        print("jq is required for these tests", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as raw, LiveShell() as shell:
        tmp = Path(raw)
        for case in (
            case_prunes_dead_job,
            case_keeps_live_and_finished,
            case_broker_dead,
            case_broker_alive,
            case_foreign_session_dir_kept,
            case_unreadable_probe_counts_alive,
            case_other_workspace_untouched,
            case_lock,
            case_malformed_state_is_survivable,
        ):
            case(tmp, shell.pid)
    failed = _results.count(False)
    print(f"\n{len(_results) - failed}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
