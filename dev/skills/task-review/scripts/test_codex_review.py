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
touched, the lock skips with status 75 for a live owner while reclaiming a stale one, and an empty
or unparseable companion payload gets one retry after the broker record is pruned.

Most state and lock cases do not reach the companion: the lock and prune run before it is launched,
so the stub path is deliberately non-existent and the resulting non-zero exit is expected. The
sequenced companion cases exercise the retry and bounded-diagnostic paths directly.

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

# Deliberately retain the pre-fix form so the compatibility fixture below proves that its
# assertion actually detects the macOS Bash 3.2 parse failure.
BROKEN_PLATFORM_SELECTOR = '''CODEX_REVIEW_PLATFORM="${CODEX_REVIEW_PLATFORM:-$(
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*) printf 'windows' ;;
    *) printf 'posix' ;;
  esac
)}"'''


def bash_path(path) -> str:
    """`C:\\x\\y` → `/c/x/y`. The script consumes these as globs, which backslashes break."""
    text = str(path)
    if os.name == "nt" and len(text) > 1 and text[1] == ":":
        return "/" + text[0].lower() + text[2:].replace("\\", "/")
    return text


def selector_probe(selector_block: str) -> str:
    """Run only the selector in a shell that reproduces Bash 3.2's parse behavior."""
    return f'''set -eu
unset CODEX_REVIEW_PLATFORM
{selector_block}
printf '%s\\n' "$CODEX_REVIEW_PLATFORM"
'''


def selector_compat_shell() -> str | None:
    """Find an optional local shell that rejects the broken selector like macOS Bash 3.2."""
    candidates = ["/bin/bash", shutil.which("bash")]
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        proc = subprocess.run(
            [candidate, "-c", selector_probe(BROKEN_PLATFORM_SELECTOR)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "syntax error" in proc.stderr:
            return candidate
    return None


def platform_selector_block() -> str | None:
    """Extract the shipped selector so the compatibility fixture tests the real source."""
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.find('if [ -z "${CODEX_REVIEW_PLATFORM:-}" ]; then')
    if start < 0:
        return None
    end = source.find("\nfi", start)
    if end < 0:
        return None
    return source[start : end + len("\nfi")]


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
            "CODEX_REVIEW_STATE_ROOTS": bash_path(tmp / "state"),
            "CODEX_REVIEW_LOCK_ROOT": bash_path(tmp / "locks"),
            # The fixture tree stands in for the OS temp root, so session-dir deletion is decided
            # against a path this test controls rather than the runner's real %TEMP%.
            "CODEX_REVIEW_TEMP_ROOTS": bash_path(tmp),
        }
    )
    if platform is None:
        env.pop("CODEX_REVIEW_PLATFORM", None)
    else:
        env["CODEX_REVIEW_PLATFORM"] = platform
    env.update({k: str(v) for k, v in env_overrides.items()})
    return subprocess.run(
        ["bash", str(repo / "scripts" / "codex-review.sh"), "plugin", "main", companion],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def make_sequenced_companion(tmp: Path, name: str, outputs: list[str], broker_path: Path | None = None):
    """Write a deterministic companion stub that emits one output per invocation."""
    script = tmp / f"{name}.mjs"
    calls = tmp / f"{name}.calls"
    script.write_text(
        "import fs from 'node:fs';\n"
        f"const calls = {json.dumps(str(calls))};\n"
        f"const outputs = {json.dumps(outputs)};\n"
        f"const broker = {json.dumps(str(broker_path) if broker_path else '')};\n"
        "const count = (fs.existsSync(calls) ? Number(fs.readFileSync(calls, 'utf8')) : 0) + 1;\n"
        "fs.writeFileSync(calls, String(count));\n"
        "if (count === 1 && broker) {\n"
        "  fs.writeFileSync(broker, JSON.stringify({pid: 4294967290}));\n"
        "}\n"
        "process.stdout.write(outputs[Math.min(count - 1, outputs.length - 1)] ?? '');\n",
        encoding="utf-8",
    )
    return script, calls


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def lock_dir_for(repo: Path, tmp: Path) -> Path:
    """The lock path the script derives: slug + a cksum of the canonical workspace path."""
    # Mirror the script's own derivation, canonicalization included — computing it any other way
    # would key the fixture to a path the script never looks at, and every lock check would pass
    # vacuously by taking a fresh lock.
    key = subprocess.run(
        [
            "bash",
            "-c",
            'top=$(git rev-parse --show-toplevel); root=$(cd "$top" && pwd -P); '
            "printf '%s' \"$root\" | cksum | tr -d ' \\t'",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return tmp / "locks" / f"codex-review-{repo.name}-{key}.lock"


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


def case_null_pid_is_no_evidence(tmp: Path, _live: int):
    """`pid: null` is absence of evidence, not evidence of death.

    Both `broker-lifecycle.mjs` and `codex-companion.mjs` write `child.pid ?? null`, so a null PID
    record can belong to a live broker. Deleting its endpoint would break every other client on the
    workspace — the exact failure this whole change exists to stop.
    """
    print("\nrecords carrying no PID")
    repo = make_repo(tmp, "wsnullpid")
    session = tmp / "cxc-nullpid"
    ws = make_workspace(
        tmp / "state", "wsnullpid", [job("review-nopid", "running", None)], broker_pid=None, session_dir=session
    )
    # `make_workspace` only writes broker.json when a pid is passed, so write the null-pid one here.
    session.mkdir(parents=True, exist_ok=True)
    (ws / "broker.json").write_text(
        json.dumps({"endpoint": "unix:/tmp/b.sock", "pid": None, "sessionDir": str(session)}, indent=2),
        encoding="utf-8",
    )
    before = (ws / "jobs" / "review-nopid.json").read_bytes()
    run(repo, tmp)
    check("null-pid job record untouched", (ws / "jobs" / "review-nopid.json").read_bytes() == before)
    check("null-pid broker.json kept", (ws / "broker.json").exists())
    check("its session dir kept", session.exists())


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


def case_windows_probe_flag_form(tmp: Path, _live: int):
    """The tasklist flag form is load-bearing and its failure mode is silent.

    `MSYS2_ARG_CONV_EXCL='*'` turns MSYS path conversion off, so the flags must be plain `/NH`.
    Passing `//NH` — the form that survives conversion when it is ON — makes real tasklist exit
    non-zero, which the fail-safe reads as "alive", disabling the prune entirely on Windows. The
    stub reproduces that rejection, so the regression is caught on a Linux runner.
    """
    print("\nwindows probe flag form")
    repo = make_repo(tmp, "wsflags")
    ws = make_workspace(tmp / "state", "wsflags", [job("review-dead", "running", DEAD_PID)])
    stub_dir = tmp / "stub-bin"
    stub_dir.mkdir(exist_ok=True)
    argv_log = tmp / "tasklist-argv.txt"
    (stub_dir / "tasklist").write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{bash_path(argv_log)}"\n'
        'for arg in "$@"; do\n'
        '  case "$arg" in\n'
        # Real tasklist rejects an unconverted `//NH` outright.
        '    //*) echo "ERROR: Invalid argument/option - \'$arg\'." >&2; exit 1 ;;\n'
        "  esac\n"
        "done\n"
        # No process matches this fixture's PID: the not-found reply carries no image name.
        'echo "INFO: No tasks are running which match the specified criteria."\n',
        encoding="utf-8",
    )
    (stub_dir / "tasklist").chmod(0o755)
    env_path = f"{bash_path(stub_dir)}{os.pathsep}{os.environ['PATH']}"
    run(repo, tmp, platform="windows", PATH=env_path)
    logged = argv_log.read_text(encoding="utf-8") if argv_log.exists() else ""
    check("tasklist was invoked", bool(logged.strip()), repr(logged))
    check("flags passed as /NH, not //NH", "//" not in logged, repr(logged))
    check(
        "dead record pruned through the windows probe",
        read(ws / "jobs" / "review-dead.json")["status"] == "failed",
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


def case_session_dir_outside_temp(tmp: Path, _live: int):
    """A `cxc-` name is not evidence of being a plugin-created temp dir.

    `createBrokerSessionDir` is `mkdtempSync(join(os.tmpdir(), "cxc-"))`, so a `sessionDir` that
    names `cxc-cache` inside a project tree is either corrupt or someone else's data — recursively
    deleting it on the strength of the name alone is the worst thing this prune could do.
    """
    print("\nsession dir outside every temp root")
    repo = make_repo(tmp, "wsoutside")
    outside = tmp / "not-temp" / "cxc-cache"
    ws = make_workspace(tmp / "state", "wsoutside", [], broker_pid=DEAD_PID, session_dir=outside)
    proc = run(repo, tmp, CODEX_REVIEW_TEMP_ROOTS=bash_path(tmp / "state"))
    check("broker.json still deleted", not (ws / "broker.json").exists())
    check("dir outside the temp roots kept", outside.exists())
    check("kept dir reported", "outside every temp root" in proc.stderr, proc.stderr[-400:])


def case_ambiguous_workspace_skipped(tmp: Path, _live: int):
    """Two checkouts sharing a basename cannot be told apart from the shell, so neither is touched.

    The directory suffix is `sha256(canonical native path)[:16]` over the path Node canonicalizes —
    on Windows that carries the on-disk casing, which git and bash do not report — so there is no
    way here to decide which of two same-basename directories belongs to this checkout.
    """
    print("\nambiguous same-basename workspaces")
    repo = make_repo(tmp, "wsdupe")
    a = make_workspace(tmp / "state", "wsdupe", [job("review-a", "running", DEAD_PID)])
    b = make_workspace(
        tmp / "state", "wsdupe", [job("review-b", "running", DEAD_PID)], suffix="fedcba9876543210"
    )
    before = ((a / "jobs" / "review-a.json").read_bytes(), (b / "jobs" / "review-b.json").read_bytes())
    proc = run(repo, tmp)
    check("first candidate untouched", (a / "jobs" / "review-a.json").read_bytes() == before[0])
    check("second candidate untouched", (b / "jobs" / "review-b.json").read_bytes() == before[1])
    check("ambiguity reported", "cannot identify this workspace" in proc.stderr, proc.stderr[-400:])


def case_default_platform_selector(tmp: Path, _live: int):
    """The platform selector must execute when no override is provided.

    macOS ships Bash 3.2, which rejects the old case-inside-command-substitution form at runtime.
    The existing cases override CODEX_REVIEW_PLATFORM, so this path needs an explicit regression.
    The source-level guards keep the regression red on Linux CI; the selector-only compatibility
    fixture additionally runs the real shipped block where a Bash 3.2-era shell is available.
    """
    print("\ndefault platform selector")
    repo = make_repo(tmp, "wsdefaultselector")
    companion, calls = make_sequenced_companion(
        tmp,
        "default-platform-selector",
        ['{"codex":{"status":0,"stdout":"review via default selector"}}'],
    )
    proc = run(repo, tmp, platform=None, companion=bash_path(companion))
    check("default selector reaches companion", proc.returncode == 0, proc.stderr[-400:])
    check("default selector emits no shell syntax error", "syntax error" not in proc.stderr, proc.stderr[-400:])
    check("default selector emits review", proc.stdout.strip() == "review via default selector", proc.stdout)
    check("default selector invokes companion once", calls.read_text(encoding="utf-8") == "1")

    selector_source = SCRIPT.read_text(encoding="utf-8")
    selector = platform_selector_block()
    check("selector has explicit compatibility guard", selector is not None)
    check(
        "selector avoids nested fallback expansion",
        "${CODEX_REVIEW_PLATFORM:-$(" not in selector_source,
        selector_source,
    )
    if selector is None:
        return

    compat_shell = selector_compat_shell()
    if compat_shell is None:
        print("  SKIP  Bash 3.2 runtime fixture unavailable; source guard remains active")
        return

    fixed = subprocess.run(
        [compat_shell, "-c", selector_probe(selector)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    broken = subprocess.run(
        [compat_shell, "-c", selector_probe(BROKEN_PLATFORM_SELECTOR)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    check("broken selector rejected by compatibility fixture", "syntax error" in broken.stderr, broken.stderr[-400:])
    check("fixed selector accepted by compatibility fixture", "syntax error" not in fixed.stderr, fixed.stderr[-400:])
    check("fixed selector resolves a platform", fixed.stdout.strip() in {"posix", "windows"}, fixed.stdout)


def case_empty_payload_retries_after_prune(tmp: Path, _live: int):
    print("\nempty companion payload retries")
    repo = make_repo(tmp, "wsretry")
    ws = make_workspace(tmp / "state", "wsretry", [])
    broker = ws / "broker.json"
    companion, calls = make_sequenced_companion(
        tmp,
        "empty-payload",
        ["", '{"codex":{"status":0,"stdout":"review after retry"}}'],
        broker,
    )
    proc = run(
        repo,
        tmp,
        companion=bash_path(companion),
        CODEX_REVIEW_TEST_CALLS=str(calls),
        CODEX_REVIEW_TEST_BROKER=str(broker),
    )
    check("empty payload → retry succeeds", proc.returncode == 0, proc.stderr)
    check("companion called exactly twice", calls.read_text(encoding="utf-8") == "2")
    check("broker record pruned before retry", not broker.exists())
    check("retry warning emitted once", proc.stderr.count("retrying once") == 1, proc.stderr)
    check("retry review text emitted", proc.stdout.strip() == "review after retry", proc.stdout)


def case_empty_json_stdout_retries_after_prune(tmp: Path, _live: int):
    print("\nvalid JSON with missing stdout retries")
    repo = make_repo(tmp, "wsemptyjson")
    ws = make_workspace(tmp / "state", "wsemptyjson", [])
    broker = ws / "broker.json"
    companion, calls = make_sequenced_companion(
        tmp,
        "empty-json-stdout",
        ['{"codex":{"status":0}}', '{"codex":{"status":0,"stdout":"review after retry"}}'],
        broker,
    )
    proc = run(repo, tmp, companion=bash_path(companion))
    check("missing stdout → retry succeeds", proc.returncode == 0, proc.stderr)
    check("missing stdout companion called exactly twice", calls.read_text(encoding="utf-8") == "2")
    check("missing stdout broker record pruned before retry", not broker.exists())
    check("missing stdout retry warning emitted once", proc.stderr.count("retrying once") == 1, proc.stderr)
    check("missing stdout retry review text emitted", proc.stdout.strip() == "review after retry", proc.stdout)


def case_empty_json_stdout_retries_then_fails(tmp: Path, _live: int):
    print("\nvalid JSON with empty stdout retries then fails")
    repo = make_repo(tmp, "wsemptyjsonfail")
    ws = make_workspace(tmp / "state", "wsemptyjsonfail", [])
    broker = ws / "broker.json"
    companion, calls = make_sequenced_companion(
        tmp,
        "empty-json-stdout-fail",
        [
            '{"codex":{"status":0,"stdout":""}}',
            '{"codex":{"status":0,"stdout":""}}',
        ],
        broker,
    )
    proc = run(repo, tmp, companion=bash_path(companion))
    check("second empty stdout payload → exit 1", proc.returncode == 1, proc.stderr)
    check("empty stdout companion called exactly twice", calls.read_text(encoding="utf-8") == "2")
    check("empty stdout broker record pruned before retry", not broker.exists())
    check("empty stdout retry warning emitted once", proc.stderr.count("retrying once") == 1, proc.stderr)
    check("empty stdout current payload status diagnostic kept", "payload status: 0" in proc.stderr, proc.stderr)
    check(
        "empty stdout bounded payload diagnostic kept",
        "companion stdout (last 2000 bytes; full payload:" in proc.stderr,
        proc.stderr,
    )


def case_unparseable_payload_retries_then_fails(tmp: Path, _live: int):
    print("\nunparseable companion payload retries then fails")
    repo = make_repo(tmp, "wsretryfail")
    ws = make_workspace(tmp / "state", "wsretryfail", [])
    broker = ws / "broker.json"
    companion, calls = make_sequenced_companion(
        tmp,
        "unparseable-payload",
        ["not-json", "still-not-json"],
        broker,
    )
    proc = run(
        repo,
        tmp,
        companion=bash_path(companion),
        CODEX_REVIEW_TEST_CALLS=str(calls),
        CODEX_REVIEW_TEST_BROKER=str(broker),
    )
    check("second unparseable payload → exit 1", proc.returncode == 1, proc.stderr)
    check("failed companion called exactly twice", calls.read_text(encoding="utf-8") == "2")
    check("retry warning emitted once", proc.stderr.count("retrying once") == 1, proc.stderr)
    check("current payload status diagnostic kept", "payload status: unparsed" in proc.stderr, proc.stderr)
    check("current bounded payload diagnostic kept", "still-not-json" in proc.stderr, proc.stderr)


def case_lock(tmp: Path, live: int):
    print("\nper-workspace lock")
    repo = make_repo(tmp, "wslock")
    make_workspace(tmp / "state", "wslock", [])
    lock_dir = lock_dir_for(repo, tmp)

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
            case_null_pid_is_no_evidence,
            case_foreign_session_dir_kept,
            case_unreadable_probe_counts_alive,
            case_windows_probe_flag_form,
            case_other_workspace_untouched,
            case_session_dir_outside_temp,
            case_ambiguous_workspace_skipped,
            case_default_platform_selector,
            case_empty_payload_retries_after_prune,
            case_empty_json_stdout_retries_after_prune,
            case_empty_json_stdout_retries_then_fails,
            case_unparseable_payload_retries_then_fails,
            case_lock,
            case_malformed_state_is_survivable,
        ):
            case(tmp, shell.pid)
    failed = _results.count(False)
    print(f"\n{len(_results) - failed}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
