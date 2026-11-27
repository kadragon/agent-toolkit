"""Deterministic steps of the dispatch skill.

  dispatch.py pick <repo path> [--tree] [--full-scan]
      Print task-next's candidate snapshot as JSON, using the bundled selector.
      Default: fast path. --full-scan uses the batch and unattended ordering.
  dispatch.py launch --cli claude|codex --model M --effort E --cwd PATH
                     --work-kind queue|new|standalone --request REQUEST --unit UNIT
                     [--git-limits LIMITS] [--no-git-writes]
                     [--review-transfer-approval APPROVAL]
                     [--name N] [--title TEXT] [--parent T] [--task TASK] [--trust-hooks] [--keep-connectors]
                     [--dry-run] [MESSAGE]
      Start a background child with hc run --bg. Prints launch and receipt details as JSON.
      --title becomes the hc label title=TEXT and, without --name, the source of the name.
      Codex takes --task or a later send with --run. Claude takes MESSAGE.
      --trust-hooks bypasses persisted hook trust for this Codex launch only.
      A Codex family (luna, terra, sol, any case) resolves to its newest listed slug in
      $CODEX_HOME/models_cache.json; a full slug passes through. fable and astra are refused.
  dispatch.py send [--run RECEIPT] [--continue | --resend] ADDRESS MESSAGE
      Send to a clear Codex composer. A receipt allows startup, phase reuse, or recovery.
  dispatch.py report-review RESULT
      Read a Codex pre-merge report from stdin and atomically write ready or blocked.
  dispatch.py collect RECEIPT [--stall-minutes N] [--close [--force]]
      Read the result, status and any stop reason. Close an owned child.
      A Codex child whose hooks fail, or whose launch-time kadragon plugin version directory
      was removed, reports stop_reason hooks_broken; any plugin version change warns on stderr.
  dispatch.py pin --repo PATH --commit SHA --codex PATH
      Create an isolated Codex wave. Launch idle children with launch --wave WAVE.
  dispatch.py release WAVE
      Release the private home and verified snapshot after all registered children close.
  dispatch.py wait RUN [RUN ...] [--until OUTCOMES] [--timeout SECONDS]
      Print one brief line per child and another only when its displayed state changes.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext, suppress
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pinned_wave  # noqa: E402

CLAUDE_SETTINGS = {
    "promptSuggestionEnabled": False,
    "awaySummaryEnabled": False,
    "disableClaudeAiConnectors": True,
    "enabledPlugins": {"cc-plugin-you-should-know@builtin": False},
}
HOOK_BLOCKER = re.compile(
    r"^(?:[•└⚠]\ufe0f?\s*)?(?:(?:\d+\s+)?hooks? needs? review|"
    r"hook (?:failed|stopped)|blocked by hook|(?:plugin contents changed;\s*)?hook approval required)\b",
    re.IGNORECASE)
# Codex can show this cause on its own or as a detail of a hook failure.
PLUGIN_HOOK_FAILURE = re.compile(
    r"^(?:[•└⚠]\ufe0f?[ \t]*|(?:•[ \t]*)?hook failed\b[^\n]*?"
    r"(?:[ \t]+|\n(?:[ \t]+[│├└][^\n]*\n)*[ \t]*[└├][ \t]*))?"
    r"plugin contents changed;\s*hook approval required\b",
    re.IGNORECASE | re.MULTILINE)
# A hook failure event, not a prompt or command output that quotes the phrase.
CODEX_HOOK_FAILED = re.compile(r"^• Hook failed\b[^\n]*\n[ \t]*└", re.MULTILINE)
WARNING_FOOTER = re.compile(r"⚠\ufe0f?\s*(\d+)\s+warnings?\s*·\s*f2 to view\b", re.IGNORECASE)
HOOK_BYPASS_NOTICE = ("`--dangerously-bypass-hook-trust` is enabled. "
                      "Enabled hooks may run without review for this invocation.")
WARNING_VIEW_TITLE = re.compile(r"Warnings · \d+ of \d+ · .+")
WARNING_VIEW_FOOTER = re.compile(
    r"k keep & next · esc dismiss & close(?: · \S+ copy)?(?: · \S+ warning)?", re.IGNORECASE)
PASTED_CONTENT = re.compile(r"\[Pasted Content \d+ chars\](?: #\d+)?")
HERDR_MESSAGE = re.compile(r'^<hc\s+from="[^"]+"(?:\s+[\w-]+="[^"]*")*>\s*(.*?)\s*</hc>$', re.DOTALL)
CODEX_STATUS_LINE = re.compile(
    r"^ {2,}(?:gpt-\S+|(?:~|…|[a-z]:)?[/\\]\S)",
    re.IGNORECASE,
)
CODEX_SHORTCUT_LINE = re.compile(r"^ {2,}(?:← for agents · )?\? for shortcuts\b", re.IGNORECASE)
CODEX_OUTPUT_MARKERS = ("•", "■", "─ Worked for")
USAGE_NOTICE = re.compile(
    r"(?:you(?:'ve|’ve| have)? (?:hit|reached) (?:your|the) (?:chatgpt )?(?:usage )?limit\b|"
    r"(?:(?:individual )?quota|usage limit|rate limit) (?:reached|exceeded)\b)", re.IGNORECASE)
FILTER_NOTICE = re.compile(r"This content can['’]t be shown\.?", re.IGNORECASE)
POLICY_ERROR = re.compile(r"API Error:.*\busage policy\b", re.IGNORECASE)
STOP_USAGE = "Usage limit reached"
STOP_FILTER = "Stopped by a safety or usage-policy filter"
STOP_HOOKS = "hooks_broken"
PLUGIN_MARKETPLACE = "kadragon"
STALL_MINUTES = 30
SCREEN_POLL_SECONDS = 0.25
POST_SEND_SETTLE_SECONDS = 2
CLOSE_WAIT_SECONDS = 10
LAUNCH_LOOKUP_SECONDS = 30
DRAFT_CLEARS = 5
DRAFT_CLEAR_SETTLE_SECONDS = 1
LOST_SETTLE_SECONDS = 2
RESULT_STATES = {"done", "ready", "blocked", "merged", "working"}
RESULT_LIMIT = 8192
WAIT_DEFAULT = ("ready", "blocked", "merged", "idle", "stop")
WAIT_OUTCOMES = (*WAIT_DEFAULT, "done")
WAIT_POLL_SECONDS = 2
WAIT_TIMEOUT_SECONDS = 1800
TASK_COMMANDS = {"claude": ("/dev:task-next", "/dev:task-new"), "codex": ("$task-next", "$task-new")}
BANNED_MODELS = ("fable", "astra")
CODEX_FAMILIES = ("luna", "terra", "sol")
CODEX_SLUG = re.compile(r"gpt-(\d+(?:\.\d+)*)-([a-z]+)")
QUOTA_SCRIPT = Path(__file__).resolve().with_name("quota.py")
QUOTA_TIMEOUT_SECONDS = 10
EXPIRING_PASS_EXCEPTIONS = ("production DB", "deploy")
BIAS_EXCEPTIONS = ("unknown-cause debugging", "open grill/spec", "security", "auth", "data migration",
                   *EXPIRING_PASS_EXCEPTIONS)


def terminal_name(raw):
    """hc names are 1-32 of a-z 0-9 - _."""
    name = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-")[:32]
    if not name:
        raise SystemExit(f"cannot build a terminal name from {raw!r}")
    return name


def child_name(repo, title):
    base = terminal_name(repo)
    slug = re.sub(r"[^a-z0-9_-]+", "-", (title or "").lower()).strip("-_")
    if not slug:
        return base
    return f"{base}-{slug}"[:32].rstrip("-")


def child_argv(cli, model, effort, message, keep_connectors, result=None, *, trust_hooks=False):
    if cli == "codex":
        if message:
            raise SystemExit("codex takes no first message at launch; use dispatch.py send")
        # Herdr requires foreground Codex so commands execute inside its terminal.
        argv = ["codex", "--no-daemon", "--no-alt-screen", "--approve-for-me", "-m", model,
                "-c", f"model_reasoning_effort={effort}"]
        if trust_hooks:
            argv.append("--dangerously-bypass-hook-trust")
        return argv
    if not message:
        raise SystemExit("a claude child needs its first message")
    settings = dict(CLAUDE_SETTINGS)
    if keep_connectors:
        del settings["disableClaudeAiConnectors"]
    report = ["--append-system-prompt", report_instruction(result)] if result else []
    return ["claude", "--model", model, "--effort", effort,
            "--settings", json.dumps(settings, separators=(",", ":")), *report, message]


def refuse_banned_model(model):
    words = re.split(r"[^a-z0-9]+", model.lower())
    banned = next((name for name in BANNED_MODELS if name in words), None)
    if banned:
        raise SystemExit(f"model {model!r} is a {banned} model; dispatch never launches {' or '.join(BANNED_MODELS)}")


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_models_cache():
    return codex_home() / "models_cache.json"


def plugin_cache():
    return codex_home() / "plugins" / "cache" / PLUGIN_MARKETPLACE


def installed_plugin_versions():
    """Return {plugin: newest installed version} from the Codex plugin cache."""
    versions = {}
    try:
        plugins = sorted(entry for entry in plugin_cache().iterdir() if entry.is_dir())
    except OSError:
        return versions
    for plugin in plugins:
        try:
            names = [entry.name for entry in plugin.iterdir() if entry.is_dir()]
        except OSError:
            continue
        if names:
            versions[plugin.name] = max(names, key=lambda name: ([int(n) for n in re.findall(r"\d+", name)], name))
    return versions


def plugin_drift(run):
    """Compare the plugin versions recorded at launch with the installed ones."""
    started = run.get("plugin_versions")
    if not isinstance(started, dict) or not started:
        return [], []
    current = installed_plugin_versions()
    changed = [f"{plugin} {version} -> {current.get(plugin, 'missing')}"
               for plugin, version in sorted(started.items()) if current.get(plugin) != version]
    removed = [plugin for plugin, version in sorted(started.items())
               if not (plugin_cache() / plugin / version).is_dir()]
    return changed, removed


def resolve_codex_model(model):
    family = model.lower()
    if family not in CODEX_FAMILIES:
        return model
    cache = codex_models_cache()
    try:
        entries = json.loads(cache.read_text(encoding="utf-8"))["models"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"cannot resolve Codex family {family!r}: unreadable models cache {cache} ({error}); "
                         "start Codex once to refresh it, or pass a full model slug") from None
    versions = []
    for entry in entries if isinstance(entries, list) else ():
        if not isinstance(entry, dict) or entry.get("visibility") != "list" or entry.get("upgrade"):
            continue
        slug = entry.get("slug")
        match = CODEX_SLUG.fullmatch(slug) if isinstance(slug, str) else None
        if match and match[2] == family:
            versions.append((tuple(int(part) for part in match[1].split(".")), slug))
    if not versions:
        raise SystemExit(f"no listed, non-retiring gpt-<version>-{family} model in {cache}; "
                         "pass a full model slug")
    return max(versions)[1]


def report_instruction(result, *, require_review_sources=False):
    instruction = (f"Write progress at phase boundaries and the final report as UTF-8 JSON to {result} "
            "(write a temporary sibling, then rename over it). Fields: status (working, done, ready, "
            "blocked, or merged), phase, summary (at most three lines), and optional worktree, "
            "contract, head, pr, ci, evidence, tokens (measured totals only), review_retries, "
            "or review_sendbacks (per the task-review-cycle consolidation guide). "
            "Use working for interim reports. Write ready when pausing before the merge, and merged only after confirming the merge. "
            "Use file paths for details. Do not send reports by hc send.")
    if require_review_sources:
        instruction += (
            " For a pre-merge report, include review_sources with claude, agy and codex outcomes. "
            "Use complete only for a completed independent result you consolidated, "
            "or give the reason the source is missing. "
            "An incomplete required review blocks a merge and must report blocked with the reviewer and reason. "
            f'Pass the candidate JSON to the bundled dispatch.py report-review "{result}" on stdin '
            "when available. Report ready only after the required independent reviews and CI pass. "
            "Keep the review outcomes in any later PR completion report."
        )
    return instruction


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_run(path):
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(run, dict) or not isinstance(run.get("address"), str):
            raise ValueError("expected a Herdr terminal receipt")
        return run
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot read dispatch receipt {path}: {error}") from None


@contextmanager
def lock_run(path):
    with path.with_suffix(".lock").open("a+b") as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SystemExit(f"cannot lock dispatch receipt {path}: {error}") from None
        yield


def verify_terminal(run, terminal):
    if run.get("created_ms") is None:
        # hc get failed at launch: adopt the terminal at this address only if hc created it with
        # the launch's name, under the same parent, no earlier than the launch started.
        created = terminal.get("created_ms")
        if (any(terminal.get(key) != run[key] for key in ("address", "parent", "name"))
                or not isinstance(created, int) or created < run.get("launched_ms", float("inf"))):
            raise SystemExit(f"terminal identity unconfirmed: {run['address']}; inspect it by hand")
        run["created_ms"] = created
    for key in ("address", "parent", "created_ms"):
        if terminal.get(key) != run[key]:
            raise SystemExit(f"terminal identity changed: {run['address']}")


def confirm_launch_identity(path, run, locked, *, timeout=None):
    """Write the identity adopted after a failed launch lookup, so later checks are exact."""
    if run.get("created_ms") is not None:
        return
    verify_terminal(run, hc_json("get", run["address"], **({"timeout": timeout} if timeout else {})))
    if locked:
        write_json(path, run)
        return
    try:
        with lock_run(path):
            saved = load_run(path)
            if saved.get("created_ms") is None:
                write_json(path, {**saved, "created_ms": run["created_ms"]})
    except SystemExit:
        pass  # another dispatch command holds the receipt; the next check adopts again


def validate_result(result):
    if (not isinstance(result, dict) or not isinstance(result.get("status"), str)
            or result["status"] not in RESULT_STATES
            or not isinstance(result.get("phase"), str)
            or not isinstance(result.get("summary"), str)
            or len(result["summary"].splitlines()) > 3):
        raise ValueError("invalid status, phase, or summary")


def gate_required_reviews(result):
    status = result["status"]
    if status not in {"ready", "merged"} and not (status == "done" and result.get("pr")):
        return result
    sources = result.get("review_sources")
    if not isinstance(sources, dict):
        sources = {}
    missing = []
    for reviewer in ("claude", "agy", "codex"):
        outcome = sources.get(reviewer)
        if outcome == "complete":
            continue
        reason = " ".join(outcome.split())[:160] if isinstance(outcome, str) else ""
        missing.append(f"{reviewer}: {reason or 'no completed result'}")
    if missing:
        return {**result, "status": "blocked", "phase": "review-sources", "summary": "\n".join(missing)}
    return result


def report_review(args):
    path = Path(args.result)
    if path.name != "result.json":
        raise SystemExit("report-review expects the assigned result.json path")
    try:
        raw = sys.stdin.buffer.read(RESULT_LIMIT + 1)
        if len(raw) > RESULT_LIMIT:
            raise ValueError("result exceeds 8 KiB")
        result = json.loads(raw.decode("utf-8-sig"))
        validate_result(result)
        if result["status"] not in {"ready", "blocked"}:
            raise ValueError("report-review expects a ready or blocked report")
        result = gate_required_reviews(result)
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > RESULT_LIMIT:
            raise ValueError("result exceeds 8 KiB")
        write_json(path, result)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot write dispatch result {path}: {error}") from None


def read_result(path):
    result_path = path.with_name("result.json")
    try:
        with result_path.open("rb") as data:
            raw = data.read(RESULT_LIMIT + 1)
            written = os.fstat(data.fileno()).st_mtime_ns
        if len(raw) > RESULT_LIMIT:
            raise ValueError("result exceeds 8 KiB")
        result = json.loads(raw.decode("utf-8-sig"))
        if isinstance(result, dict) and "status" not in result:
            result = {"status": "working", **result}
        validate_result(result)
        return result, written
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot read dispatch result {result_path}: {error}") from None


def hc_json(*args, timeout=None):
    out = subprocess.run(["hc", args[0], "--json", *args[1:]], capture_output=True, text=True,
                         encoding="utf-8", check=True, timeout=timeout).stdout
    return json.loads(out)


def hc_rpc(method, params, timeout):
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n"
    out = subprocess.run(["hc", "connect"], input=request, capture_output=True, text=True,
                         encoding="utf-8", timeout=timeout, check=True).stdout
    for line in out.splitlines():
        if line.strip() and (reply := json.loads(line)).get("id") == 1:
            return reply
    raise ValueError(f"Herdr returned no reply to {method}")


def free_name(base, explicit, taken):
    """Names are global to hc, shared with every other home session's children."""
    if base not in taken:
        return base
    if explicit:
        raise SystemExit(f"terminal name {base!r} is taken by a live terminal")
    n = 2
    while f"{base[:29]}-{n}" in taken:
        n += 1
    return f"{base[:29]}-{n}"


def configured_handoff_lines(launch_dir, cwd):
    home = launch_dir
    if not (home / "repos" / "handoff.json").exists():
        for directory in (launch_dir, *launch_dir.parents):
            git_path = directory / ".git"
            if git_path.is_file() or (git_path / "HEAD").is_file():
                home = directory
                break
    config = home / "repos" / "handoff.json"
    try:
        prefixes = json.loads(config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{config}: {exc}") from exc
    if not isinstance(prefixes, dict):
        raise SystemExit(f"{config}: expected an object mapping path prefixes to lists of lines")

    target = (launch_dir / cwd).resolve()
    extra_lines = []
    for prefix, lines in prefixes.items():
        if not prefix.strip():
            raise SystemExit(f"{config}: path prefixes must be nonblank")
        if not isinstance(lines, list) or any(
            not isinstance(line, str) or not line.strip() or line.splitlines() != [line] or "\0" in line
            for line in lines
        ):
            raise SystemExit(f"{config}: {prefix!r} must map to a list of nonblank single lines")
        try:
            prefix_path = (home / Path(prefix).expanduser()).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit(f"{config}: invalid path prefix {prefix!r}: {exc}") from exc
        if target.is_relative_to(prefix_path):
            extra_lines.extend(lines)
    return extra_lines


def first_prompt(cli, message, handoff):
    if not message.strip():
        raise SystemExit("first message is empty")
    commands = TASK_COMMANDS[cli]
    if handoff["work_kind"] != "standalone" and message.split(maxsplit=1)[0] not in commands:
        print(f"warning: {handoff['work_kind']} work should start with {' or '.join(commands)}; "
              "this first message may skip the task cycle", file=sys.stderr)
    fields = {"Original user request (verbatim)": handoff["request"],
              "Assigned unit": handoff["unit"],
              "Git limits": handoff["git_limits"]}
    if "additional_git_limits" in handoff:
        fields["Additional Git limits (verbatim)"] = handoff["additional_git_limits"]
    if "review_transfer_approval" in handoff:
        fields["Review transfer approval (verbatim)"] = handoff["review_transfer_approval"]
    prompt = (f"{message}\n\nHandoff metadata (JSON):\n"
              "Task-cycle mode and flags come exclusively from the invocation above.\n"
              "<dispatch-handoff>\n"
              f"{json.dumps(fields, ensure_ascii=False, indent=2)}\n"
              "</dispatch-handoff>")
    invocation, *body = message.lstrip().splitlines()
    if (handoff["work_kind"] == "queue" and invocation.split()[:2] == [commands[0], "--tree"]
            and any(line.startswith("Dispatch mode: parallel-worktree") for line in body)):
        prompt += (
            "\n\nRead the installed task-next SKILL.md sections listed in Phase index as each phase starts. "
            "Locate Markdown headings outside code fences with rg -n '^#{2,3} ' and read the current ranges. "
            "For the worktree, see references/tree.md → --tree mode and references/cycle.md → Branch "
            "(including Worktree cycle). After implementation, follow cycle.md → Version bump, Cleanup, "
            "and Validation evidence, then Step 4 and cycle.md → Hand off into task-review-cycle → Caller gate."
        )
    extra_lines = handoff.get("extra_lines")
    if extra_lines:
        if cli == "codex":
            extra_lines = [
                f"> {line}" if (line.lstrip().startswith(("›", *CODEX_OUTPUT_MARKERS))
                                 or HOOK_BLOCKER.match(line.lstrip())) else line
                for line in extra_lines
            ]
        prompt += "\n\n" + "\n".join(extra_lines)
    return prompt


def warn_linked_worktree(cwd):
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return
    paths = result.stdout.splitlines()
    if len(paths) == 2 and Path(paths[0]).resolve() != Path(paths[1]).resolve():
        print(f"warning: {cwd} is inside a linked worktree; the child can keep it open on Windows. "
              "Launch from the main checkout and add --tree to the task invocation.", file=sys.stderr)


def normalized_title(title):
    if title is not None:
        title = " ".join(title.split())
        if not title:
            raise SystemExit("--title must not be blank")
    return title


def launch_handoff(args, cwd):
    handoff = {key: getattr(args, key) for key in ("request", "unit", "git_limits", "work_kind")}
    for key in ("request", "unit"):
        if not handoff[key].strip():
            raise SystemExit(f"--{key.replace('_', '-')} must not be blank")
    limits = " ".join((args.git_limits or "").casefold().split())
    no_authority = limits in {"", "not specified", "unknown", "implementation-only"}
    if getattr(args, "no_git_writes", False):
        if limits in {"none", "no-push", "pr-only"}:
            raise SystemExit("--no-git-writes conflicts with --git-limits that describe a Git grant")
        handoff["git_limits"] = "implementation-only"
        if not no_authority:
            handoff["additional_git_limits"] = args.git_limits
    elif handoff["work_kind"] in {"queue", "new"} and no_authority:
        raise SystemExit("--git-limits must carry a verified user grant; "
                         "use --no-git-writes for implementation-only work")
    elif not limits:
        raise SystemExit("--git-limits must not be blank")
    approval = getattr(args, "review_transfer_approval", None)
    if approval is not None:
        if not approval.strip():
            raise SystemExit("--review-transfer-approval must not be blank")
        handoff["review_transfer_approval"] = approval
    extra_lines = configured_handoff_lines(Path.cwd(), cwd)
    if extra_lines:
        handoff["extra_lines"] = extra_lines
    return handoff


def read_quota_snapshot():
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", str(QUOTA_SCRIPT)], capture_output=True, text=True,
            encoding="utf-8", check=True, timeout=QUOTA_TIMEOUT_SECONDS,
        )
        snapshot = json.loads(result.stdout)
        if (snapshot["bias"] not in ("none", "claude", "codex", "both-hot")
                or snapshot["effective_bias"] not in ("none", "claude", "codex")
                or not isinstance(snapshot["prefer_expiring_passes"], bool)
                or any(snapshot[cli]["state"] not in ("unknown", "ok", "hot", "critical")
                       for cli in ("claude", "codex"))):
            raise ValueError("unexpected quota output")
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, RecursionError) as error:
        print(f"warning: quota check unavailable; proceeding without quota gates ({error})", file=sys.stderr)
        return None
    for cli in ("claude", "codex"):
        if snapshot[cli]["state"] == "unknown":
            print(f"warning: {cli} quota snapshot is unavailable", file=sys.stderr)
    return snapshot


def launch_quota(args, model):
    snapshot = read_quota_snapshot()
    pinned = getattr(args, "user_pinned", False)
    approved = getattr(args, "approve_critical", False)
    reason = getattr(args, "bias_exception", None)
    audit = {"bias": snapshot["bias"] if snapshot else None, "quota_snapshot": snapshot}
    if pinned:
        audit["user_pin_reason"] = "CLI, model or effort explicitly selected by the user"
    if approved:
        audit["critical_approved"] = True
    if reason is not None:
        audit["bias_exception"] = reason
    if snapshot is None:
        return audit

    quota = snapshot[args.cli]
    if quota.get("raw_state", quota["state"]) == "critical" and not approved:
        raise SystemExit(f"{args.cli} quota is critical; --approve-critical requires explicit user approval")
    preferred = snapshot["effective_bias"]
    if pinned or quota["state"] == "unknown" or preferred in ("none", args.cli):
        return audit

    words = set(re.split(r"[^a-z0-9]+", model.lower()))
    strong = snapshot["prefer_expiring_passes"]
    if args.cli == "claude":
        top = "opus" in words and not words.intersection(("haiku", "sonnet"))
    else:
        top = ("sol" in words and not words.intersection(("luna", "terra"))
               and args.effort.lower() in ("xhigh", "max", "ultra"))
        if top and not strong:
            return audit
    if not top:
        raise SystemExit(f"quota bias {preferred} refuses {args.cli} {model}/{args.effort}; "
                         "use the preferred CLI or --user-pinned for an explicit user choice")

    allowed = EXPIRING_PASS_EXCEPTIONS if strong else BIAS_EXCEPTIONS
    category = (reason or "").partition(":")[0].strip().casefold()
    if category not in {item.casefold() for item in allowed}:
        raise SystemExit(f"quota bias {preferred} requires --bias-exception with one of: {', '.join(allowed)}")
    return audit


PIN_ERRORS = (pinned_wave.PinError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def pin(args):
    try:
        path, wave = pinned_wave.prepare(Path(args.repo).resolve(), args.commit, args.codex)
    except PIN_ERRORS as error:
        raise SystemExit(f"cannot pin Codex wave: {error}; see shared-cache readiness") from None
    print(json.dumps({"wave": str(path), "home": str(path.parent / "home"), "codex": wave["binary"],
                      "commit": wave["commit"], "versions": wave["versions"]}, ensure_ascii=False))


def release(args):
    try:
        path = pinned_wave.wave_path(args.wave)
        with lock_run(path):
            wave = pinned_wave.read_wave(path)
            for receipt in wave["children"]:
                child = load_run(Path(receipt))
                if child.get("wave") != str(path) or not child.get("closed_reason"):
                    raise pinned_wave.PinError(f"wave child must be closed first: {receipt}")
            write_json(path, {**wave, "released": True})
        pinned_wave.remove(path.parent)
    except PIN_ERRORS as error:
        raise SystemExit(f"cannot release Codex wave: {error}") from None
    print(json.dumps({"wave": str(path), "released": True}, ensure_ascii=False))


def launch(args):
    wave_arg = getattr(args, "wave", None)
    if wave_arg is None:
        launch_child(args)
        return
    if args.cli != "codex" or getattr(args, "trust_hooks", False) or args.task is not None:
        raise SystemExit("--wave requires an idle Codex launch and forbids --trust-hooks")
    try:
        path = pinned_wave.wave_path(wave_arg)
        if not path.is_file():
            raise pinned_wave.PinError("wave receipt is missing")
    except PIN_ERRORS as error:
        raise SystemExit(f"pinned launch withheld: {error}; see shared-cache readiness") from None
    with lock_run(path):
        try:
            wave = pinned_wave.read_wave(path)
            if wave.get("released"):
                raise pinned_wave.PinError("wave has been released")
            pinned_wave.ensure_shared_guards_are_preserved(codex_home())
            pinned_wave.verify_herdr()
            trusted = pinned_wave.verify(path, wave, Path(args.cwd).expanduser().resolve(strict=True))
        except PIN_ERRORS as error:
            raise SystemExit(f"pinned launch withheld: {error}; see shared-cache readiness") from None
        launch_child(args, path, wave, trusted)


def launch_child(args, wave_path=None, wave=None, pinned_startup=None):
    cwd = Path(args.cwd).expanduser()
    title = normalized_title(getattr(args, "title", None))
    name = terminal_name(args.name) if args.name else child_name(cwd.name, title)
    if args.task is not None and (args.cli != "codex" or args.message is not None):
        raise SystemExit("--task is for Codex only; Claude takes its task as MESSAGE")
    trust_hooks = getattr(args, "trust_hooks", False)
    if trust_hooks and args.cli != "codex":
        raise SystemExit("--trust-hooks is only supported for Herdr Codex launches")
    refuse_banned_model(args.model)
    model = resolve_codex_model(args.model) if args.cli == "codex" else args.model
    resolved = {"model": model, **({"model_family": args.model} if model != args.model else {})}
    handoff = launch_handoff(args, cwd)
    message = args.message
    if args.cli == "claude" and message is not None:
        message = first_prompt(args.cli, message, handoff)
    if args.task is not None and not args.task.strip():
        raise SystemExit("first message is empty")
    quota = launch_quota(args, model)
    home = args.parent or os.environ.get("HC_TERMINAL_ID") or None
    result_path = None
    child = None
    if wave:
        codex_args = child_argv(args.cli, model, args.effort, message, args.keep_connectors)
        child = [wave["binary"], *codex_args[1:]]
    if not args.dry_run:
        terminals = hc_json("ls")["terminals"]
        if home:
            owner = next((t for t in terminals if t["address"] == home and t["state"] == "live"), None)
            if owner is None:
                raise SystemExit(f"parent {home} is not live; pass --parent with this session's address")
            owner = hc_json("get", home)
            if owner.get("address") != home or owner.get("state") != "live":
                raise SystemExit(f"parent {home} is no longer live")
            parent_dir = (owner.get("foreground") or {}).get("cwd") or owner.get("cwd")
            if not parent_dir or Path(parent_dir).resolve() != Path.cwd().resolve():
                raise SystemExit(f"parent {home} is outside this directory; run launch from the home session directory")
        taken = {t.get("name") for t in terminals if t["state"] == "live"}
        name = free_name(name, bool(args.name), taken)
        if not cwd.is_dir():
            raise SystemExit(f"no such directory: {cwd}")
        result_path = Path(tempfile.mkdtemp(prefix="dispatch-")) / "result.json"
    warn_linked_worktree(cwd)
    if child is None:
        child = child_argv(args.cli, model, args.effort, message, args.keep_connectors, result_path,
                           trust_hooks=trust_hooks)
    labels = {"title": title} if title else {}
    if wave:
        labels[pinned_wave.WAVE_LABEL] = wave["market"]
        params = {"argv": child, "cwd": str(cwd.resolve()), "name": name, "parent": home,
                  "no_parent": home is None, "no_notify": True, "outlive_parent": True, "labels": labels,
                  "env": {"CODEX_HOME": str(wave_path.parent / "home"), "CLAUDE_PLUGIN_ROOT": "",
                          "PYTHONDONTWRITEBYTECODE": "1"}}
        argv = ["hc", "connect"]
    else:
        argv = ["hc", "run", "--bg", "--json", "--no-notify", "--outlive-parent",
                "--name", name, "--cwd", str(cwd), *(["--label", f"title={title}"] if title else []),
                *(["--parent", home] if home else ["--no-parent"]), *child]
    if args.dry_run:
        preview = {"name": name, **resolved, **quota, "argv": argv}
        if wave:
            preview["terminal_run"] = params
        if title:
            preview["title"] = title
        if args.task is not None:
            preview["task"] = first_prompt(args.cli, args.task, handoff)
        print(json.dumps(preview, ensure_ascii=False))
        return
    receipt = result_path.with_name("run.json")
    if wave:
        wave["children"].append(str(receipt))
        try:
            write_json(wave_path, wave)
        except OSError as error:
            raise SystemExit(f"pinned launch withheld; could not register child: {error}") from None
    versions = installed_plugin_versions() if args.cli == "codex" and not wave else {}
    launched_ms = time.time_ns() // 1_000_000 - 1000  # slack for clock rounding between processes
    try:
        if wave:
            reply = hc_rpc("terminal.run", params, LAUNCH_LOOKUP_SECONDS)
        else:
            stdout = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", check=True,
                                    timeout=LAUNCH_LOOKUP_SECONDS).stdout
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"hc run failed ({error}); a child may be running, so do not retry the launch. "
                         f"Find terminal {name!r} with hc ls"
                         + (f"; wave reference retained for {receipt}" if wave else "")) from None
    try:
        if wave:
            error = reply.get("error") or {}
            kind = (error.get("data") or {}).get("kind")
            if kind in {"name_taken", "spawn_failed", "invalid_params"} or error.get("code") in {-32601, -32602}:
                wave["children"].remove(str(receipt))
                try:
                    write_json(wave_path, wave)
                    receipt.parent.rmdir()
                except OSError as cleanup_error:
                    raise SystemExit(f"Herdr rejected the launch and started no child. "
                                     f"Could not clear reservation {receipt}: {cleanup_error}") from None
                raise SystemExit(f"Herdr rejected the pinned launch: {kind or error.get('code')}: "
                                 f"{error.get('message', '')}")
            address = reply["result"]["address"]
        else:
            address = json.loads(stdout)["address"]
        if not isinstance(address, str) or not address:
            raise ValueError("invalid terminal address")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise SystemExit(f"hc run printed no terminal address ({error}); a child may be running, so do not "
                         f"retry the launch. Find terminal {name!r} with hc ls."
                         + (f" Wave reference retained for {receipt}" if wave else f" Output: {stdout[:200]!r}")) from None
    try:
        terminal, lookup_error = hc_json("get", address, timeout=LAUNCH_LOOKUP_SECONDS), None
        if not isinstance(terminal, dict) or not isinstance(terminal.get("created_ms"), int):
            raise ValueError("no created_ms in hc get output")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        terminal, lookup_error = {}, error
    run = {"name": name, "address": address, "parent": home,
           "created_ms": terminal.get("created_ms"), "cli": args.cli, **resolved,
           "effort": args.effort, "sent": args.cli == "claude", "screen_reads": 0, **quota}
    if trust_hooks:
        run["trust_hooks"] = True
    if lookup_error is not None:
        run["launched_ms"] = launched_ms
    if wave:
        run.update(wave=str(wave_path), wave_trusted_at_start=pinned_startup, cwd=str(cwd.resolve()))
    elif versions:
        run["plugin_versions"] = versions
    if title:
        run["title"] = title
    if args.cli == "codex" and handoff["work_kind"] != "standalone":
        run["require_review_sources"] = True
    try:
        write_json(receipt, {**run, "handoff": handoff} if args.cli == "codex" else run)
    except OSError as error:
        raise SystemExit(f"{address}: the child may be running, but the launch receipt could not be "
                         f"written to {receipt}: {error}. Inspect the terminal before retrying.") from None
    print(json.dumps({**run, "run": str(receipt), "result": str(result_path)}, ensure_ascii=False), flush=True)
    if lookup_error is not None:
        detail = ("do not retry the launch: Claude may already hold its launch prompt"
                  if args.cli == "claude" else
                  f"task withheld: deliver it with send --run {receipt} once hc get answers")
        raise SystemExit(f"{address}: launched, but hc get failed ({lookup_error}); {detail}. "
                         "Later dispatch commands confirm the terminal identity from the receipt")
    if terminal.get("parent") != home:
        detail = ("Claude may have received its launch prompt; inspect before retrying"
                  if args.cli == "claude" else "task withheld")
        raise SystemExit(f"{address}: parent changed at launch; {detail}")
    if args.task:
        send(SimpleNamespace(address=address, message=args.task, run=receipt))


def matches_sent_message(rows, message):
    visible = "\n".join(row.strip() for row in rows).strip()
    envelope = HERDR_MESSAGE.fullmatch(visible)
    if envelope:
        visible = envelope[1]

    # Codex wraps composer rows at the terminal width.
    for row in visible.splitlines():
        if not message.startswith(row):
            return False
        message = message[len(row):].lstrip()
    return not message


def transcript_echoed(text, message):
    """Look for the complete message in the last prompt above the clear composer."""
    lines = text.splitlines()
    prompts = [i for i, line in enumerate(lines) if line.startswith("›")]
    if len(prompts) < 2:
        return False
    last_prompt, composer = prompts[-2:]
    end = next((i for i in range(last_prompt + 1, composer)
                if lines[i].startswith(CODEX_OUTPUT_MARKERS)), composer)
    rows = (lines[last_prompt].lstrip()[1:], *lines[last_prompt + 1:end])
    return matches_sent_message(rows, message)


def footer_boundary(lines, composer, *, placeholder=False):
    match_hint = CODEX_SHORTCUT_LINE.match if placeholder else CODEX_SHORTCUT_LINE.fullmatch
    if (len(lines) >= composer + 4 and not lines[-3] and match_hint(lines[-1])
            and (CODEX_STATUS_LINE.match(lines[-2]) or (placeholder and lines[-2].startswith("  ")))):
        return len(lines) - 3

    # A visible placeholder distinguishes arbitrary footer text from an indented draft.
    if len(lines) >= composer + 3 and not lines[-2]:
        footer = lines[-1]
        if (CODEX_STATUS_LINE.match(footer) or CODEX_SHORTCUT_LINE.match(footer)
                or (placeholder and footer.startswith("  "))):
            return len(lines) - 2
    return None


def codex_hook_rows(lines):
    in_prompt = False
    previous_blank = False
    for line in lines:
        if line.startswith("›"):
            in_prompt = True
        elif line and not line.startswith("  "):
            in_prompt = False
        if not in_prompt or previous_blank:
            yield line.lstrip()
        previous_blank = not line


def codex_screen(text, *, sent_message=None):
    lines = [line.rstrip() for line in text.rstrip().splitlines()]
    hook_lines = lines if sent_message is not None else codex_hook_rows(lines)
    if any(HOOK_BLOCKER.match(line) for line in hook_lines):
        return "hooks"
    if lines and WARNING_FOOTER.search(lines[-1]):
        return "warning"

    # A transcript prompt can appear above output while the actual composer is hidden.
    indented_marker = False
    for index in reversed(range(len(lines))):
        row = lines[index]
        line = row.lstrip()
        if line.startswith(("›", *CODEX_OUTPUT_MARKERS)) and row != line:
            indented_marker = True
            continue
        if row.startswith(CODEX_OUTPUT_MARKERS):
            break
        if row.startswith("›"):
            prompt = row[1:].strip()
            placeholder = prompt == "Ask Codex to do anything"
            status_row = footer_boundary(lines, index, placeholder=placeholder)
            if status_row is not None and WARNING_FOOTER.search(lines[status_row + 1]):
                return "warning"
            if PASTED_CONTENT.fullmatch(prompt):
                return "collapsed"
            body = (prompt, *lines[index + 1:status_row])
            if (not prompt or placeholder) and not any(row.strip() for row in body[1:]):
                return "ready"
            if sent_message is not None and matches_sent_message(body, sent_message):
                return "paste"
            if not indented_marker and status_row is not None:
                return "draft"
            break
    return "waiting"


def composer_draft(text):
    lines = [line.rstrip() for line in text.rstrip().splitlines()]
    index = max(i for i, line in enumerate(lines) if line.lstrip().startswith("›"))
    status_row = footer_boundary(lines, index)
    return "\n".join([lines[index].lstrip()[1:].strip(),
                      *(line.strip() for line in lines[index + 1:status_row])]).strip()


def read_codex_screen(address, *, sent_message=None, with_text=False):
    screen = hc_json("read", "--lines", "0", address)
    text = screen.get("text", "") if screen["how"] == "screen" else ""
    if not screen["complete"] or screen["how"] != "screen":
        state = "waiting"
    else:
        state = codex_screen(text, sent_message=sent_message)
        if (sent_message is None and state == "waiting"
                and any(WARNING_VIEW_TITLE.fullmatch(line.strip()) for line in text.splitlines())):
            state = "warning-view"
    return (state, text) if with_text else state


def print_screen_tail(address, text, run):
    rows = [line.strip() for line in text.splitlines() if line.strip()][-6:]
    if rows:
        if run:
            verify_terminal(run, hc_json("get", address))
        print(f"{address}: last Codex screen rows:", file=sys.stderr)
        for row in rows:
            trimmed = row[:160] + "…" if len(row) > 160 else row
            print(f"  {trimmed!r}", file=sys.stderr)


def startup_composer(text, *, draft=False):
    """Herdr may count initial Codex startup as turn 1 before any prompt."""
    prompts = [line.strip() for line in text.splitlines() if line.lstrip().startswith("›")]
    return ("OpenAI Codex (v" in text and len(prompts) == 1
            and (draft or prompts[0] in {"›", "› Ask Codex to do anything"})
            and not any(line.lstrip().startswith(("•", "■")) for line in text.splitlines()))


def is_hook_bypass_notice(text):
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    title = "Warnings · 1 of 1 · Startup"
    if rows.count(title) != 1:
        return False
    body = rows[rows.index(title) + 1:]
    if body and WARNING_VIEW_FOOTER.fullmatch(body[-1]):
        body.pop()
    return " ".join(body) == HOOK_BYPASS_NOTICE


def send(args):
    run_file = getattr(args, "run", None)
    run_path = Path(run_file).resolve() if run_file else None
    with lock_run(run_path) if run_path else nullcontext():
        send_task(args, run_path)


def verify_pinned_delivery(run, terminal):
    labels = terminal.get("labels") or {}
    if not run or not run.get("wave"):
        if pinned_wave.WAVE_LABEL in labels:
            raise SystemExit("pinned task withheld; supply its launch receipt with --run")
        return
    try:
        path = pinned_wave.wave_path(run["wave"])
        wave = pinned_wave.read_wave(path)
        argv = (terminal.get("foreground") or {}).get("argv") or []
        if (wave.get("released") or labels.get(pinned_wave.WAVE_LABEL) != wave["market"]
                or not argv or not Path(argv[0]).is_absolute() or Path(argv[0]).resolve() != Path(wave["binary"])
                or "--no-daemon" not in argv or "--dangerously-bypass-hook-trust" in argv
                or (terminal.get("status") or {}).get("app") != "codex"):
            raise pinned_wave.PinError("Herdr could not confirm the isolated Codex process")
        if run.get("wave_trusted_at_start") is not True:
            raise pinned_wave.PinError("review each required hook natively, then close and relaunch this idle child")
        pinned_wave.ensure_shared_guards_are_preserved(codex_home())
        if not pinned_wave.verify(path, wave, Path(run["cwd"])):
            raise pinned_wave.PinError("required Codex hooks lack native trust")
    except PIN_ERRORS as error:
        raise SystemExit(f"{run['address']}: pinned task withheld; {error}") from None


def require_shared_guard(run):
    versions = installed_plugin_versions()
    started = (run or {}).get("plugin_versions") or {}
    dev = versions.get("dev")
    if not dev or ("guard" in versions and (not started or "guard" in started)):
        return
    manifest = plugin_cache() / "dev" / dev / pinned_wave.MANIFEST
    try:
        installed = pinned_wave.read_json(manifest)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as error:
        raise SystemExit(f"task withheld; can't read the installed dev plugin manifest: {error}") from None
    if "hooks" not in installed:
        raise SystemExit("task withheld; install guard@kadragon, restart the idle Codex child, and review its hooks")


def verify_delivery_turn(run, terminal):
    verify_pinned_delivery(run, terminal)
    if not run or not run.get("wave"):
        require_shared_guard(run)
    else:
        current = hc_json("get", run["address"])
        verify_terminal(run, current)
        if current["state"] != "live" or any(current.get(key) != terminal.get(key)
                                             for key in ("turn", "status", "foreground")):
            raise SystemExit(f"{run['address']}: pinned task withheld; the terminal changed during verification")


def send_task(args, run_path):
    address = args.address
    if not args.message.strip():
        raise SystemExit("first message is empty")
    run = None
    continuation = getattr(args, "continuation", False)
    resend = getattr(args, "resend", False)
    if resend and not run_path:
        raise SystemExit("--resend requires --run")
    screen_reads = 0
    if run_path:
        run = load_run(run_path)
        if run["cli"] != "codex" or run["address"] != address:
            raise SystemExit("receipt is for another terminal or CLI")
        confirm_launch_identity(run_path, run, locked=True)
        if resend:
            if run["sent"] != "unconfirmed":
                raise SystemExit("--resend requires an unconfirmed delivery")
        elif run["sent"] == "unconfirmed":
            result, written = read_result(run_path)
            terminal = hc_json("get", address)
            verify_terminal(run, terminal)
            state = (terminal.get("status") or {}).get("state")
            started = run.get("send_acknowledged", True) and (
                state == "working" or (state == "done" and "sent_turn" in run and terminal["turn"] > run["sent_turn"])
            )
            if started:
                snapshot = hc_json("read", "--lines", "0", address)
                started = (snapshot["complete"] and snapshot["how"] == "screen"
                           and codex_screen(snapshot["text"]) == "ready"
                           and not startup_composer(snapshot["text"]))
            if not started and (not result or written == run.get("previous_result")):
                raise SystemExit("previous delivery is unconfirmed; inspect the child's composer before resuming")
            run["sent"] = True
            write_json(run_path, run)
        if not resend and run["sent"] != continuation:
            raise SystemExit("use --continue only after the first task is confirmed")
    elif continuation:
        raise SystemExit("--continue requires --run")
    attempted_send = False
    stray_draft = None
    clears = 0
    last_clear = None
    warning_turn = None
    warning_withheld = f"{address}: task withheld; inspect the Codex warning with F2"
    dismissed_bypass_notice = False
    try:
        deadline = time.monotonic() + 30
        while True:
            screen_reads += 1
            screen, text = read_codex_screen(address, with_text=True)
            if resend and screen != "ready":
                if screen == "waiting":
                    print_screen_tail(address, text, run)
                raise SystemExit(f"{address}: resend withheld; the Codex composer is not clear")
            if screen == "hooks":
                raise SystemExit(f"{address}: task withheld; inspect the Codex hook status with /hooks")
            if screen in {"warning", "warning-view"}:
                if (not run or run.get("wave") or run.get("trust_hooks") is not True or run["sent"] is not False
                        or dismissed_bypass_notice):
                    raise SystemExit(warning_withheld)
                if screen == "warning-view":
                    if not is_hook_bypass_notice(text):
                        raise SystemExit(warning_withheld)
                    terminal = hc_json("get", address)
                    verify_terminal(run, terminal)
                    # Herdr can report working while the local warning viewer owns the input.
                    turn = terminal["turn"]
                    if (terminal["state"] != "live" or turn not in (0, 1)
                            or (warning_turn is not None and turn != warning_turn)):
                        raise SystemExit(warning_withheld)
                    hc_json("keys", address, "esc")
                    warning_turn = None
                    dismissed_bypass_notice = True
                    time.sleep(SCREEN_POLL_SECONDS)
                    continue
                footer = "\n".join(text.rstrip().splitlines()[-2:])
                if WARNING_FOOTER.findall(footer) != ["1"]:
                    raise SystemExit(warning_withheld)
                if warning_turn is None:
                    terminal = hc_json("get", address)
                    verify_terminal(run, terminal)
                    turn = terminal["turn"]
                    if (terminal["state"] != "live" or (terminal.get("status") or {}).get("state") != "idle"
                            or not (turn == 0 or (turn == 1 and startup_composer(text)))):
                        raise SystemExit(warning_withheld)
                    hc_json("keys", address, "f2")
                    warning_turn = turn
            if warning_turn is not None:
                if time.monotonic() >= deadline:
                    raise SystemExit(warning_withheld)
                time.sleep(SCREEN_POLL_SECONDS)
                continue
            if screen == "draft":
                draft = composer_draft(text)
                stray_draft = stray_draft or draft
                if not run or continuation:
                    raise SystemExit(f"{address}: task withheld; the Codex composer holds a draft: {draft!r}")
                terminal = hc_json("get", address)
                verify_terminal(run, terminal)
                unstarted = terminal["turn"] == 0 or (terminal["turn"] == 1 and startup_composer(text, draft=True))
                if not unstarted:
                    raise SystemExit(f"{address}: first task withheld; this child already started a turn")
                settled = last_clear is None or time.monotonic() - last_clear >= DRAFT_CLEAR_SETTLE_SECONDS
                if (terminal.get("status") or {}).get("state") == "idle" and settled:
                    if clears >= DRAFT_CLEARS:
                        raise SystemExit(f"{address}: task withheld; the Codex composer still holds a draft: {draft!r}")
                    hc_json("keys", address, "ctrl+u")
                    clears += 1
                    last_clear = time.monotonic()
            if screen == "ready" and stray_draft is not None:
                print(f"warning: cleared a stray draft from the composer: {stray_draft!r}", file=sys.stderr)
                stray_draft = None
            if screen == "ready":
                terminal = hc_json("get", address)
                if run:
                    verify_terminal(run, terminal)
                if dismissed_bypass_notice and terminal["state"] != "live":
                    raise SystemExit(f"{address}: task withheld; Codex exited after closing the warning")
                status = (terminal.get("status") or {}).get("state")
                if resend:
                    sent_turn = run.get("sent_turn")
                    if terminal["turn"] != sent_turn:
                        raise SystemExit(f"{address}: resend withheld; the recorded turn no longer matches")
                    if "sent_continuation" in run:
                        continuation = run["sent_continuation"]
                    elif sent_turn == 1 and not startup_composer(text):
                        raise SystemExit(f"{address}: resend withheld; the first task phase is ambiguous in this legacy receipt")
                    else:
                        continuation = sent_turn > 1
                    if terminal["state"] != "live" or not (status == "idle" or (continuation and status == "done")):
                        raise SystemExit(f"{address}: resend withheld; the Codex terminal is not idle or on the same completed turn")
                    break
                initial = terminal["turn"] == 0
                if not initial and not continuation:
                    if run and terminal["turn"] == 1:
                        screen_reads += 1
                        snapshot = hc_json("read", "--lines", "0", address)
                        initial = (snapshot["complete"] and snapshot["how"] == "screen"
                                   and startup_composer(snapshot["text"]))
                    if not initial:
                        raise SystemExit(f"{address}: first task withheld; this child already started a turn")
                if status == "idle" or (continuation and status == "done"):
                    break
            if time.monotonic() >= deadline:
                if screen == "waiting":
                    print_screen_tail(address, text, run)
                raise SystemExit(f"{address}: task withheld; no clear Codex input line (check dialogs or drafts)")
            time.sleep(SCREEN_POLL_SECONDS)

        verify_delivery_turn(run, terminal)
        message = args.message
        if run:
            if not continuation:
                if "handoff" in run:
                    message = first_prompt("codex", message, run["handoff"])
                else:
                    print("warning: legacy receipt has no handoff metadata; include the original request, "
                          "assigned unit, and Git limits in the first message", file=sys.stderr)
            message += "\n\n" + report_instruction(
                run_path.with_name("result.json"),
                require_review_sources=run.get("require_review_sources", False),
            )
        sent_message = message.strip()
        echoed_before = transcript_echoed(text, sent_message)
        if resend and echoed_before:
            raise SystemExit(f"{address}: resend withheld; this message already appears in the Codex transcript")
        sent_turn = terminal["turn"]
        # Herdr can report that no turn started even after it pasted the message.
        if run:
            if run["parent"]:
                os.environ["HC_TERMINAL_ID"] = run["parent"]
            result, written = read_result(run_path)
            if resend and result and written != run.get("previous_result"):
                raise SystemExit("the previous delivery already produced a result; use --continue for the next phase")
            run["previous_result"] = written
            if status == "done":
                current = hc_json("get", address)
                verify_terminal(run, current)
                if (current["turn"] != terminal["turn"] or
                        (current.get("status") or {}).get("state") != "done"):
                    raise SystemExit(f"{address}: task withheld; the child started another turn")
            run["sent"] = "unconfirmed"
            run["sent_turn"] = sent_turn
            run["sent_continuation"] = continuation
            run["send_acknowledged"] = False
            write_json(run_path, run)
        else:
            print("warning: no dispatch receipt. Use --run to carry handoff metadata", file=sys.stderr)
        attempted_send = True
        guard = ["--if", "idle"] if status == "idle" else []

        def post_send_screen(*, message=sent_message, approval_only=False):
            nonlocal screen_reads
            screen_reads += 1
            screen, text = read_codex_screen(address, sent_message=message, with_text=True)
            if screen == "hooks":
                if PLUGIN_HOOK_FAILURE.search(text):
                    raise SystemExit(f"{address}: Codex blocked after the send: plugin contents changed; "
                                     "hook approval required. Stop this child and review hooks at restart.")
                if not approval_only:
                    raise SystemExit(f"{address}: Codex reported a hook problem after the send; inspect before continuing")
            if screen == "warning" and not approval_only:
                raise SystemExit(f"{address}: Codex showed a warning after the send; inspect before continuing")
            return screen, text

        def confirmed(send_failed):
            """Return (submitted, saw_trace)."""
            deadline = time.monotonic() + 5
            previous_idle_paste = False
            retried_enter = False
            saw_trace = False
            while True:
                screen, text = post_send_screen()
                terminal = hc_json("get", address)
                if run:
                    verify_terminal(run, terminal)
                status = (terminal.get("status") or {}).get("state")
                if status == "blocked":
                    raise SystemExit(f"{address}: Codex blocked after the send; inspect the screen before continuing")
                completed = False
                if run and status == "done" and screen == "ready":
                    result, written = read_result(run_path)
                    completed = bool(result and written != run["previous_result"])
                if screen == "ready":
                    delivered = not send_failed or retried_enter or (
                        not echoed_before and transcript_echoed(text, sent_message)
                    )
                    if completed or (status == "working" and delivered):
                        break
                saw_trace = saw_trace or screen in ("paste", "collapsed", "draft") or status == "working"
                # A collapsed paste shows no text. Trust it only when Herdr confirmed typing the message.
                matches_paste = screen == "paste" or (screen == "collapsed" and not send_failed)
                idle_paste = (status == "idle" or (continuation and status == "done")) and matches_paste
                if idle_paste and previous_idle_paste and not retried_enter:
                    if run and run.get("wave"):
                        verify_delivery_turn(run, terminal)
                    hc_json("keys", address, "enter")
                    retried_enter = saw_trace = True
                if time.monotonic() >= deadline:
                    return False, saw_trace
                previous_idle_paste = idle_paste
                time.sleep(SCREEN_POLL_SECONDS)

            # Herdr can see the turn start before Codex renders a hook failure.
            settle_until = time.monotonic() + POST_SEND_SETTLE_SECONDS
            while True:
                remaining = max(0, settle_until - time.monotonic())
                time.sleep(min(SCREEN_POLL_SECONDS, remaining))
                post_send_screen(approval_only=True)
                if time.monotonic() >= settle_until:
                    return True, True

        first_line = sent_message.splitlines()[0].strip()

        def lost():
            deadline = time.monotonic() + LOST_SETTLE_SECONDS
            while True:
                screen, text = post_send_screen(message=None)
                current = hc_json("get", address)
                if run:
                    verify_terminal(run, current)
                state = (current.get("status") or {}).get("state")
                echoed = any(line.lstrip().startswith("›") and first_line in line for line in text.splitlines())
                if (screen != "ready" or echoed or current["turn"] != sent_turn
                        or not (state == "idle" or (continuation and state == "done"))):
                    return False
                if time.monotonic() >= deadline:
                    return True
                time.sleep(SCREEN_POLL_SECONDS)

        for attempt in range(2):
            if attempt:
                if run and run.get("wave"):
                    verify_delivery_turn(run, terminal)
                if run and run["send_acknowledged"]:
                    run["send_acknowledged"] = False
                    write_json(run_path, run)
                print("warning: the submission left no trace; sending it once more", file=sys.stderr)
            send_error = None
            try:
                hc_json("send", *guard, "--", address, message)
            except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as error:
                send_error = error
            else:
                if run:
                    run["send_acknowledged"] = True
                    write_json(run_path, run)
            submitted, saw_trace = confirmed(send_error is not None)
            if not submitted and (attempt or saw_trace or not lost()):
                if send_error is not None:
                    raise send_error
                raise SystemExit(f"{address}: could not confirm submission; inspect the input before retrying")
            if submitted:
                if run:
                    run["sent"] = True
                    run["screen_reads"] += screen_reads
                    write_json(run_path, run)
                print(json.dumps({"address": address, "submitted": True, "screen_reads": screen_reads}))
                return
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as err:
        reason = ("Herdr could not confirm delivery; inspect the screen before retrying" if attempted_send
                  else "task withheld; Herdr could not read Codex readiness")
        raise SystemExit(f"{address}: {reason} ({type(err).__name__})") from None


def collect(args):
    path = Path(args.run).resolve()
    force = getattr(args, "force", False)
    if force and not args.close:
        raise SystemExit("--force requires --close")
    with lock_run(path) if args.close else nullcontext():
        report = collect_result(path, args.close, force, getattr(args, "stall_minutes", STALL_MINUTES),
                                warn_drift=not getattr(args, "brief", False))
    print(brief_report(report) if getattr(args, "brief", False) else json.dumps(report, ensure_ascii=False))


def watch_stop_reason(report):
    return report["stop_reason"] or ("plugin_drift" if report.get("plugin_drift") else None)


def brief_report(report):
    result = report["result"] or {}

    def field(value):
        lines = str(value).splitlines() if value is not None else []
        return lines[0].strip() if lines else ""

    status = result.get("status")
    if not status or (status == "done" and report["status"] == "working"):
        status = "finished" if report["state"] == "finished" else report["status"]
    return " · ".join((report["address"], *(field(value) or "-" for value in (
        status, result.get("phase"), result.get("summary"), result.get("pr"), watch_stop_reason(report),
    ))))


def reached_outcome(report, outcomes):
    result = report["result"] or {}
    reported = result.get("status")
    stopped = report["state"] == "finished" or report["status"] in {"idle", "done"}
    return ((reported in outcomes and (reported != "done" or stopped))
            or ("idle" in outcomes and report["status"] == "idle")
            or ("stop" in outcomes and (watch_stop_reason(report) or report["state"] == "finished")))


def remaining_wait(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired("dispatch wait", 0)
    return remaining


def herdr_error_kind(error):
    try:
        return json.loads(error.stderr)["error"]["kind"]
    except (TypeError, ValueError, KeyError):
        return None


def wait(args):
    pending = list(dict.fromkeys(Path(receipt).resolve() for receipt in args.runs))
    deadline = time.monotonic() + args.timeout
    previous = {}
    try:
        while pending:
            next_pending = []
            working = None
            for path in pending:
                report = collect_result(path, False, False, args.stall_minutes, warn_drift=False, deadline=deadline)
                line = brief_report(report)
                if previous.get(path) != line:
                    print(line, flush=True)
                    previous[path] = line
                if not reached_outcome(report, args.until):
                    next_pending.append(path)
                    if working is None and report["state"] == "live" and report["status"] == "working":
                        working = report["address"]
            pending = next_pending
            if not pending:
                return
            interval = min(WAIT_POLL_SECONDS, remaining_wait(deadline))
            next_poll = time.monotonic() + interval
            if working and interval > 1:
                with suppress(subprocess.TimeoutExpired):
                    reply = hc_rpc("terminal.wait", {"terminal": working, "timeout": 1, "caller": None}, interval)
                    error = reply.get("error")
                    if error and (error.get("data") or {}).get("kind") != "not_found":
                        raise SystemExit(f"Herdr wait failed: {error.get('message', 'unknown error')}")
                    result = reply.get("result") or {}
                    if result.get("reason") == "message":
                        raise SystemExit(f"Herdr wait interrupted by message from {result.get('from', 'unknown sender')}")
            if (delay := next_poll - time.monotonic()) > 0:
                time.sleep(delay)
    except subprocess.TimeoutExpired:
        raise SystemExit("dispatch wait timed out") from None
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"dispatch wait could not read Herdr: {error}") from None


def wait_for_terminal_exit(run):
    address = run["address"]
    deadline = time.monotonic() + CLOSE_WAIT_SECONDS
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            terminal = hc_json("get", address, timeout=remaining)
        except subprocess.TimeoutExpired:
            break
        verify_terminal(run, terminal)
        if terminal["state"] == "finished":
            return
        time.sleep(min(SCREEN_POLL_SECONDS, max(0, deadline - time.monotonic())))
    raise SystemExit(f"{address}: terminal did not reach state: finished within {CLOSE_WAIT_SECONDS}s; receipt left open")


def notice_reason(line):
    if USAGE_NOTICE.match(line):
        return STOP_USAGE
    if FILTER_NOTICE.fullmatch(line) or POLICY_ERROR.match(line):
        return STOP_FILTER
    return None


def screen_stop_reason(snapshot, cli):
    if snapshot.get("how") != "screen":
        return None
    lines = [line.rstrip() for line in snapshot["text"].rstrip().splitlines()]
    if cli == "codex":
        # A warning footer or an older hook notice can mask the composer classification.
        for index in reversed(range(len(lines))):
            row = lines[index]
            if row.startswith((*CODEX_OUTPUT_MARKERS, "ⓘ", "ℹ")):
                break
            if row.startswith("›"):
                prompt = row[1:].strip()
                if (prompt in {"", "Ask Codex to do anything"} or PASTED_CONTENT.fullmatch(prompt)
                        or footer_boundary(lines, index) is not None):
                    lines = lines[:index]
                break
    else:
        composer = next((i for i in reversed(range(len(lines))) if lines[i].strip() == "❯"), None)
        if composer is not None:
            lines = lines[:composer]
    for row in reversed(lines):
        if row.startswith(("›", "❯")):
            break
        line = row.lstrip()
        notice = line.lstrip("ⓘℹ■⚠⎿•\ufe0f ")
        if line != row and not (cli == "claude" and line.startswith("⎿") and not FILTER_NOTICE.fullmatch(notice)):
            continue
        if reason := notice_reason(notice):
            return reason
    return None


def last_commit_ms(cwd):
    if not cwd:
        return 0
    try:
        commit = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "HEAD", "--"], cwd=cwd, capture_output=True,
            text=True, check=True, timeout=2, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        )
        return int(commit.stdout) * 1000
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def child_stop_reason(terminal, run, result, written, stall_minutes, drift=((), ()), *, deadline=None):
    """Return a one-line diagnosis and the number of extra screen reads."""
    changed, removed = drift
    facts = terminal.get("status") or {}
    state = facts.get("state")
    if terminal["state"] == "finished":
        if terminal.get("exit_code") not in (None, 0) or terminal.get("signal"):
            return "Child exited with an error", 0
        return None, 0
    notice = notice_reason(facts.get("msg") or "")
    if notice:
        return notice, 0
    if state == "blocked" and facts.get("kind") in {"permission", "question", "auth"}:
        return "Waiting for a dialog", 0
    status = result["status"] if result else None
    if status in {"done", "merged"} and state == "done":
        return None, 0
    # The child's hooks point into a plugin version directory a marketplace update deleted.
    if removed:
        return STOP_HOOKS, 0

    stale = False
    track_idle = state in {"idle", "done"} and status not in {"ready", "blocked"}
    if run.get("sent") and (state == "working" or track_idle) and terminal.get("status_ms") is not None:
        cutoff_ms = time.time_ns() // 1_000_000 - stall_minutes * 60_000
        # Herdr timestamps the current status; a new turn re-enters working.
        if max(terminal["status_ms"], (written or 0) // 1_000_000) <= cutoff_ms:
            worktree = (result or {}).get("worktree")
            cwd = ((worktree if isinstance(worktree, str) else None)
                   or (terminal.get("foreground") or {}).get("cwd") or terminal.get("cwd"))
            stale = last_commit_ms(cwd) <= cutoff_ms
    if not stale and not changed and state not in {"blocked", "error", "idle", "done"}:
        return None, 0
    try:
        timeout = min(2, remaining_wait(deadline)) if deadline is not None else 2
        snapshot = hc_json("read", "--lines", "0", run["address"], timeout=timeout)
        notice = screen_stop_reason(snapshot, run["cli"])
    except (OSError, ValueError, subprocess.SubprocessError):
        snapshot, notice = {}, None
    if notice:
        return notice, 1
    if (run["cli"] == "codex" and snapshot.get("how") == "screen"
            and CODEX_HOOK_FAILED.search(snapshot.get("text") or "")):
        return STOP_HOOKS, 1
    if state == "blocked":
        return "Waiting for a dialog", 1
    if state == "error":
        return "Child stopped on an error", 1
    if stale:
        return f"No new turn or commit for {stall_minutes} minutes", 1
    return None, 1


def repeated_review_categories(result):
    if not result or result["status"] != "blocked" or result["phase"] == "review-sources":
        return []
    history = result.get("review_sendbacks")
    if not isinstance(history, list) or len(history) < 2:
        return []
    earlier, later = history[-2:]
    for verdict in (earlier, later):
        if (not isinstance(verdict, dict) or not isinstance(verdict.get("change"), str)
                or not verdict["change"].strip() or type(verdict.get("round")) is not int
                or verdict["round"] < 1 or not isinstance(verdict.get("categories"), list)
                or any(not isinstance(category, str) or not category.strip() for category in verdict["categories"])):
            return []
    if earlier["change"] != later["change"] or earlier["round"] + 1 != later["round"]:
        return []
    return sorted(set(earlier["categories"]).intersection(later["categories"]))


def collect_result(path, close, force, stall_minutes, *, warn_drift=True, deadline=None):
    run = load_run(path)
    try:
        result, written = read_result(path)
    except SystemExit as error:
        if not force:
            raise
        print(error, file=sys.stderr)
        result, written = None, None
    if written == run.get("previous_result"):
        result, written = None, None
    if result and run.get("require_review_sources"):
        result = gate_required_reviews(result)
    timeout = remaining_wait(deadline) if deadline is not None else None
    if deadline is not None and run.get("closed_reason"):
        return {"address": run["address"], "status": None, "state": "finished", "result": result,
                "stop_reason": None}
    try:
        confirm_launch_identity(path, run, locked=close, timeout=timeout)
        terminal = hc_json("get", run["address"], **({"timeout": remaining_wait(deadline)} if timeout else {}))
    except subprocess.CalledProcessError as error:
        if deadline is not None and herdr_error_kind(error) == "not_found":
            return {"address": run["address"], "status": None, "state": "finished", "result": result,
                    "stop_reason": "Herdr terminal no longer exists"}
        raise
    verify_terminal(run, terminal)
    status = (terminal.get("status") or {}).get("state")
    finished = terminal["state"] == "finished"
    closed = {}
    reason, reads = None, 0
    changed, removed = [], []
    if run["cli"] == "codex" and not finished:
        if run.get("wave"):
            try:
                wave_path = pinned_wave.wave_path(run["wave"])
                wave = pinned_wave.read_wave(wave_path)
                pinned_wave.verify_files(wave_path, wave, check_binary=False)
            except PIN_ERRORS as error:
                changed = removed = [f"pinned wave unverifiable: {error}"]
        else:
            changed, removed = plugin_drift(run)
    if changed and warn_drift:
        print(f"{run['address']}: Codex plugin changed since launch ({', '.join(changed)}); "
              "stop the child before its next Git write", file=sys.stderr)
    if close:
        final = bool(result) and result["status"] in {"done", "merged"} and status == "done"
        if not (force or finished or final):
            raise SystemExit("terminal has no final result or is still running; left intact")
        if not finished:
            hc_json("kill", run["address"])
            wait_for_terminal_exit(run)
        hc_json("rm", run["address"])
        closed_reason = "forced" if force else ("finished" if finished else "final_result")
        closed = {"closed_reason": closed_reason}
        write_json(path, {**run, **closed})
    else:
        reason, reads = child_stop_reason(terminal, run, result, written, stall_minutes, (changed, removed),
                                          deadline=deadline)
    return {"address": run["address"], "status": status, "state": terminal["state"],
                      "result": result, "stop_reason": reason,
                      "scope_decision_categories": repeated_review_categories(result), "closed": close,
                      "screen_reads": run["screen_reads"], "collect_screen_reads": reads,
                      **({"plugin_drift": changed} if changed else {}), **closed}


def warn_stale_local_base(repo):
    remote_prefix = "refs/remotes/origin/"
    git = ["git", "-C", str(repo)]
    options = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": {**os.environ, "GIT_NO_LAZY_FETCH": "1"},
    }
    try:
        base = subprocess.run([*git, "branch", "--show-current"], **options, check=True).stdout.strip()
        if not base:
            return
        remote = f"{remote_prefix}{base}"
        default = subprocess.run(
            [*git, "symbolic-ref", "--quiet", f"{remote_prefix}HEAD"], **options,
        ).stdout.strip()
        if default and default != remote:
            return
        if not default and base not in ("main", "master"):
            return
        result = subprocess.run(
            [*git, "rev-list", "--count", f"refs/heads/{base}..{remote}", "--"],
            **options, check=True,
        )
        behind = int(result.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return
    if behind:
        commits = "commit" if behind == 1 else "commits"
        print(f"warning: {base} is {behind} {commits} behind origin/{base}. "
              "The local backlog may be stale. Update the local base or use pick --tree.", file=sys.stderr)


QUEUE_BACKEND = Path(__file__).resolve().parents[2] / "task-next" / "scripts" / "queue_backend.py"
FILE_QUEUE_REF = re.compile(r"^(tasks\.md|backlog\.md):(\d+)$")


def queue_op(op, request):
    """Run one `queue_backend.py` op; its stderr diagnostics pass through, a failure exits."""
    done = subprocess.run([sys.executable, "-I", "-X", "utf8", str(QUEUE_BACKEND), op],
                          input=json.dumps(request), capture_output=True, text=True, encoding="utf-8")
    if done.returncode:
        raise SystemExit(done.stderr.strip() or f"queue_backend.py {op} exited {done.returncode}")
    sys.stderr.write(done.stderr)
    return json.loads(done.stdout)


def heading_kind(repo, source, line, rev):
    """`h1`/`h2`/`h3` of a file-queue candidate, read from the same commit `list` read."""
    if source == "tasks.md":
        return "h1"
    if rev:
        done = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:./backlog.md"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if done.returncode:
            raise SystemExit(f"cannot read backlog.md at {rev}: {done.stderr.strip()}")
        text = done.stdout
    else:
        text = (repo / "backlog.md").read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    heading = lines[line - 1] if 0 < line <= len(lines) else ""
    level = len(heading) - len(heading.lstrip("#"))
    if level not in (2, 3):
        raise SystemExit(f"backlog.md:{line} is no longer an h2/h3 heading; the queue changed while listing, retry")
    return f"h{level}"


def pick_entry(repo, candidate, rev):
    """One `list` candidate in the shape `backlog_candidates.py --json --counts` prints."""
    counts = candidate["counts"]
    tail = {"open": counts["open"], "deferred": counts["deferred"], "blocked": counts["blocked"]}
    match = FILE_QUEUE_REF.match(candidate["ref"])
    if match:
        source, line = match.group(1), int(match.group(2))
        return {"source": source, "kind": heading_kind(repo, source, line, rev), "title": candidate["title"],
                "line": line, "items": None if source == "tasks.md" else len(candidate["items"]), **tail}
    return {"source": "issues", "kind": "issue", "ref": candidate["ref"], "url": candidate.get("url", ""),
            "title": candidate["title"], "line": None, "items": len(candidate["items"]), **tail}


def pick(args):
    repo = Path(args.repo).expanduser().resolve()
    request = {"contract": 1, "repo": str(repo)}
    if not (repo / "backlog.md").exists() and not args.tree:
        if queue_op("describe", request)["backend"] == "backlog":
            raise SystemExit(f"{repo} has no backlog.md: no queue")
    elif not args.tree:
        warn_stale_local_base(repo)
    listed = queue_op("list", {**request, "full_scan": args.full_scan, "parked": False,
                               **({"ref": "origin/HEAD"} if args.tree else {})})
    for warning in listed.get("warnings", []):
        print(warning, file=sys.stderr)
    if "rev" not in listed and (repo / "tasks.md").exists():  # only the file backend reports `rev`
        print("warning: tasks.md exists, but this repo's queue backend does not list its sprint blocks; "
              "check tasks.md by hand before picking", file=sys.stderr)
    for claim in listed.get("claimed", []):
        if not FILE_QUEUE_REF.match(claim["ref"]):  # the file queue already reports its claims as warnings
            print(f"{claim['ref']} claimed by {claim['by']}", file=sys.stderr)
    entries = [pick_entry(repo, c, listed.get("rev")) for c in listed["candidates"]]
    print(json.dumps(entries, ensure_ascii=False))


def main(argv):
    parser = argparse.ArgumentParser(prog="dispatch.py")
    sub = parser.add_subparsers(dest="command", required=True)
    pick_parser = sub.add_parser("pick")
    pick_parser.add_argument("repo")
    pick_parser.add_argument("--tree", action="store_true")
    pick_parser.add_argument("--full-scan", action="store_true")
    pick_parser.set_defaults(func=pick)
    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("--cli", choices=["claude", "codex"], required=True)
    launch_parser.add_argument("--model", required=True)
    launch_parser.add_argument("--effort", required=True)
    launch_parser.add_argument("--cwd", required=True)
    launch_parser.add_argument("--work-kind", choices=["queue", "new", "standalone"], required=True)
    launch_parser.add_argument("--request", required=True, help="verbatim original user request")
    launch_parser.add_argument("--unit", required=True, help="assigned unit")
    launch_parser.add_argument("--git-limits", help="verbatim Git grant and limits (required unless --no-git-writes)")
    launch_parser.add_argument("--no-git-writes", action="store_true", help="hand off implementation-only work")
    launch_parser.add_argument("--review-transfer-approval", help="verbatim user grant for reviewer data transfer")
    launch_parser.add_argument("--name")
    launch_parser.add_argument("--title", help="short task title; hc label title=TEXT, and the name source without --name")
    launch_parser.add_argument("--parent")
    launch_parser.add_argument("--task", help="send the first Codex task after launch")
    launch_parser.add_argument("--trust-hooks", action="store_true",
                               help="bypass persisted hook trust for this Herdr Codex launch (explicit authorization)")
    launch_parser.add_argument("--wave", help="verified Codex wave receipt from dispatch pin")
    launch_parser.add_argument("--keep-connectors", action="store_true")
    launch_parser.add_argument("--dry-run", action="store_true")
    launch_parser.add_argument("message", nargs="?")
    launch_parser.set_defaults(func=launch)
    pin_parser = sub.add_parser("pin", help="create a verified private Codex wave from an agent-toolkit commit")
    pin_parser.add_argument("--repo", required=True)
    pin_parser.add_argument("--commit", required=True)
    pin_parser.add_argument("--codex", required=True, help="absolute path to the native Codex executable")
    pin_parser.set_defaults(func=pin)
    release_parser = sub.add_parser("release", help="remove a verified Codex wave after closing its children")
    release_parser.add_argument("wave")
    release_parser.set_defaults(func=release)
    send_parser = sub.add_parser("send")
    send_parser.add_argument("address")
    send_parser.add_argument("message")
    send_parser.add_argument("--run")
    delivery = send_parser.add_mutually_exclusive_group()
    delivery.add_argument("--continue", dest="continuation", action="store_true")
    delivery.add_argument("--resend", action="store_true", help="retry an unconfirmed delivery to a clear idle composer")
    send_parser.set_defaults(func=send)
    report_parser = sub.add_parser("report-review", help="write a gated pre-merge review result")
    report_parser.add_argument("result")
    report_parser.set_defaults(func=report_review)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("run")
    collect_parser.add_argument("--stall-minutes", type=int, default=STALL_MINUTES)
    collect_parser.add_argument("--close", action="store_true")
    collect_parser.add_argument("--force", action="store_true", help="close even when the owned child has no final result")
    collect_parser.add_argument("--brief", action="store_true", help="one line with the child report and stop reason")
    collect_parser.set_defaults(func=collect)
    wait_parser = sub.add_parser("wait", help="watch receipts until each reaches a selected outcome")
    wait_parser.add_argument("runs", nargs="+")
    wait_parser.add_argument("--until", default=",".join(WAIT_DEFAULT),
                             help=f"comma-separated outcomes (default: {','.join(WAIT_DEFAULT)})")
    wait_parser.add_argument("--timeout", type=int, default=WAIT_TIMEOUT_SECONDS, metavar="SECONDS")
    wait_parser.add_argument("--stall-minutes", type=int, default=STALL_MINUTES)
    wait_parser.set_defaults(func=wait)
    launch_parser.add_argument("--bias-exception", help="routing exception category, optionally followed by ': detail'")
    launch_parser.add_argument("--user-pinned", action="store_true",
                               help="the user explicitly selected this CLI, model or effort")
    launch_parser.add_argument("--approve-critical", action="store_true",
                               help="the user explicitly approved use of a critical CLI")
    args = parser.parse_args(argv)
    if args.command == "wait":
        args.until = set(args.until.split(","))
        if not args.until <= set(WAIT_OUTCOMES):
            wait_parser.error("--until must be a comma-separated list of " + ", ".join(WAIT_OUTCOMES))
        if args.timeout < 1 or args.stall_minutes < 1:
            wait_parser.error("--timeout and --stall-minutes must be positive")
    if args.command == "collect" and args.stall_minutes < 1:
        collect_parser.error("--stall-minutes must be positive")
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
