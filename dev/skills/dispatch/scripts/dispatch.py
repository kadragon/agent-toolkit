"""Deterministic steps of the dispatch skill.

  dispatch.py pick <repo path> [--tree] [--full-scan]
      Print task-next's candidate snapshot as JSON, using the bundled selector.
      Default: fast path. --full-scan uses the batch and unattended ordering.
  dispatch.py launch --cli claude|codex --model M --effort E --cwd PATH
                     --work-kind queue|new|standalone --request REQUEST --unit UNIT --git-limits LIMITS
                     [--name N] [--parent T] [--task TASK] [--keep-connectors]
                     [--no-show] [--dry-run] [MESSAGE]
      Start the child with hc run and, inside the Herdr app, keep its pane in the
      right-hand column. Prints one JSON object: name, address, parent, shown.
      Codex takes --task or a later send with --run. Claude takes MESSAGE.
  dispatch.py send [--run RECEIPT] [--continue] ADDRESS MESSAGE
      Send to a clear Codex composer. A receipt allows startup turn 1 or phase reuse.
  dispatch.py collect RECEIPT [--close]
      Read the result and status without reading the screen. Close a completed child.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

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
WARNING_FOOTER = re.compile(r"⚠\ufe0f?\s*\d+\s+warnings?\s*·\s*f2 to view\b", re.IGNORECASE)
PASTED_CONTENT = re.compile(r"\[Pasted Content \d+ chars\](?: #\d+)?")
HERDR_MESSAGE = re.compile(r'^<hc\s+from="[^"]+"(?:\s+[\w-]+="[^"]*")*>\s*(.*?)\s*</hc>$', re.DOTALL)
CODEX_STATUS_LINE = re.compile(r"^ {2,}(?:gpt-\S+|(?:← for agents · )?\? for shortcuts\b)", re.IGNORECASE)
SCREEN_POLL_SECONDS = 0.25
RESULT_STATES = {"done", "ready", "blocked", "merged"}
RESULT_LIMIT = 8192
TASK_COMMANDS = {"claude": ("/dev:task-next", "/dev:task-new"), "codex": ("$task-next", "$task-new")}


def terminal_name(raw):
    """hc names are 1-32 of a-z 0-9 - _."""
    name = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-")[:32]
    if not name:
        raise SystemExit(f"cannot build a terminal name from {raw!r}")
    return name


def child_argv(cli, model, effort, message, keep_connectors, result=None):
    if cli == "codex":
        if message:
            raise SystemExit("codex takes no first message at launch; use dispatch.py send")
        # Herdr requires foreground Codex so commands execute inside its terminal.
        return ["codex", "--no-daemon", "--no-alt-screen", "--approve-for-me", "-m", model,
                "-c", f"model_reasoning_effort={effort}"]
    if not message:
        raise SystemExit("a claude child needs its first message")
    settings = dict(CLAUDE_SETTINGS)
    if keep_connectors:
        del settings["disableClaudeAiConnectors"]
    report = ["--append-system-prompt", report_instruction(result)] if result else []
    return ["claude", "--model", model, "--effort", effort,
            "--settings", json.dumps(settings, separators=(",", ":")), *report, message]


def report_instruction(result):
    return (f"Write progress at phase boundaries and the final report as UTF-8 JSON to {result} "
            "(write a temporary sibling, then rename over it). Fields: status (done, ready, "
            "blocked, or merged), phase, summary (at most three lines), and optional worktree, "
            "contract, head, pr, ci, evidence, tokens (measured totals only), or review_retries. "
            "Write ready when pausing before the merge, and merged only after confirming the merge. "
            "Use file paths for details. Do not send reports by hc send.")


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_run(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
    for key in ("address", "parent", "created_ms"):
        if terminal.get(key) != run[key]:
            raise SystemExit(f"terminal identity changed: {run['address']}")


def read_result(path):
    result_path = path.with_name("result.json")
    try:
        with result_path.open("rb") as data:
            raw = data.read(RESULT_LIMIT + 1)
            written = os.fstat(data.fileno()).st_mtime_ns
        if len(raw) > RESULT_LIMIT:
            raise ValueError("result exceeds 8 KiB")
        result = json.loads(raw.decode("utf-8-sig"))
        if (not isinstance(result, dict) or not isinstance(result.get("status"), str)
                or result["status"] not in RESULT_STATES
                or not isinstance(result.get("phase"), str)
                or not isinstance(result.get("summary"), str)
                or len(result["summary"].splitlines()) > 3):
            raise ValueError("invalid status, phase, or summary")
        return result, written
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot read dispatch result {result_path}: {error}") from None


def hc_json(*args):
    out = subprocess.run(["hc", args[0], "--json", *args[1:]], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    return json.loads(out)


def tallest(panes):
    """The pane to split: most rows; ties go to the earliest created, which halving keeps topmost."""
    return min(panes, key=lambda t: (-t.get("rows", 0), t.get("created_ms", 0)))["address"]


def app(*args):
    out = subprocess.run(["herdr-app", *args], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    return json.loads(out)


def home_tab(home):
    for space in app("ls")["spaces"]:
        for tab in space["tabs"]:
            if any(t["terminal"] == home for t in tab["terminals"]):
                return tab
    raise RuntimeError(f"home terminal {home} is in no tab")


def show(home, child):
    """Home stays left; children stack in one column on the right of home's own tab.

    terminal.keep places beside whatever pane has focus, and focus is one per window, so the
    person (or another home session in another space) can move it. Every step is checked
    against home's tab and the person's focus is put back.
    """
    for _ in range(40):  # the app lists a terminal hc just started a moment later
        tab = home_tab(home)
        entry = next(t for t in tab["terminals"] if t["terminal"] == home)
        if child in entry.get("sub_agents", []):
            break
        time.sleep(0.25)
    else:
        raise RuntimeError(f"the app never listed {child} under {home}")
    mine = {t["address"] for t in hc_json("ls")["terminals"]
            if t.get("parent") == home and t.get("state") == "live" and t["address"] != child}
    panes = {t["terminal"]: t["pane"] for t in tab["terminals"] if t["terminal"] in mine}
    if panes:
        target, place = tallest([hc_json("get", a) for a in panes]), "down"
        target_pane = panes[target]
    else:
        place = "right"
        target_pane = entry["pane"]
    before = app("status").get("focused_pane")
    try:
        app("do", "pane.focus", "--pane", target_pane)
        if app("status").get("focused_pane") != target_pane:
            raise RuntimeError("focus moved before the pane was kept")
        app("do", "terminal.keep", "--terminal", child, "--place", place)
        if not any(t["terminal"] == child for t in home_tab(home)["terminals"]):
            app("do", "terminal.park", "--terminal", child)
            raise RuntimeError("the pane opened outside home's tab and was parked again")
    finally:
        if before:
            subprocess.run(["herdr-app", "do", "pane.focus", "--pane", before], capture_output=True)


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


def first_prompt(cli, message, handoff):
    if not message.strip():
        raise SystemExit("first message is empty")
    commands = TASK_COMMANDS[cli]
    if handoff["work_kind"] != "standalone" and message.split(maxsplit=1)[0] not in commands:
        print(f"warning: {handoff['work_kind']} work should start with {' or '.join(commands)}; "
              "this first message may skip the task cycle", file=sys.stderr)
    return (f"{message}\n\nHandoff metadata:\n"
            "Task-cycle mode and flags come exclusively from the invocation above.\n"
            "<dispatch-handoff>\n"
            f"- Original user request (verbatim): {handoff['request']}\n"
            f"- Assigned unit: {handoff['unit']}\n"
            f"- Git limits: {handoff['git_limits']}\n"
            "</dispatch-handoff>")


def launch(args):
    cwd = Path(args.cwd).expanduser()
    name = terminal_name(args.name or cwd.name)
    if args.task is not None and (args.cli != "codex" or args.message is not None):
        raise SystemExit("--task is for Codex only; Claude takes its task as MESSAGE")
    handoff = {key: getattr(args, key) for key in ("request", "unit", "git_limits", "work_kind")}
    for key in ("request", "unit", "git_limits"):
        if not handoff[key].strip():
            raise SystemExit(f"--{key.replace('_', '-')} must not be blank")
    message = args.message
    if args.cli == "claude" and message is not None:
        message = first_prompt(args.cli, message, handoff)
    if args.task is not None and not args.task.strip():
        raise SystemExit("first message is empty")
    home = args.parent or os.environ.get("HC_TERMINAL_ID")
    result_path = None
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
    argv = ["hc", "run", "--bg", "--json", "--no-notify", "--outlive-parent",
            "--name", name, "--cwd", str(cwd), *(["--parent", home] if home else ["--no-parent"]),
            *child_argv(args.cli, args.model, args.effort, message, args.keep_connectors, result_path)]
    if args.dry_run:
        preview = {"name": name, "argv": argv}
        if args.task is not None:
            preview["task"] = first_prompt(args.cli, args.task, handoff)
        print(json.dumps(preview, ensure_ascii=False))
        return
    result = json.loads(subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                       check=True).stdout)
    address = result["address"]
    terminal = hc_json("get", address)
    run = {"name": name, "address": address, "parent": home,
           "created_ms": terminal["created_ms"], "cli": args.cli, "model": args.model,
           "effort": args.effort, "sent": args.cli == "claude", "screen_reads": 0}
    receipt = result_path.with_name("run.json")
    write_json(receipt, {**run, "handoff": handoff} if args.cli == "codex" else run)
    if terminal.get("parent") != home:
        print(json.dumps({**run, "shown": False, "run": str(receipt), "result": str(result_path)}), flush=True)
        detail = ("Claude may have received its launch prompt; inspect before retrying"
                  if args.cli == "claude" else "task withheld")
        raise SystemExit(f"{address}: parent changed at launch; {detail}")
    shown = False
    if home and not args.no_show:
        try:
            show(home, result["address"])
            shown = True
        except (subprocess.CalledProcessError, OSError, ValueError, KeyError, RuntimeError,
                StopIteration) as err:
            print(f"pane not kept: {err}", file=sys.stderr)
    print(json.dumps({**run, "shown": shown, "run": str(receipt), "result": str(result_path)}), flush=True)
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


def codex_screen(text, *, sent_message=None):
    lines = [line.rstrip() for line in text.rstrip().splitlines()]
    # Codex indents continued lines of the submitted prompt in its transcript.
    hook_lines = lines if sent_message is not None else (line.lstrip() for line in lines)
    if any(HOOK_BLOCKER.match(line) for line in hook_lines):
        return "hooks"
    if lines and WARNING_FOOTER.search(lines[-1]):
        return "warning"

    # A transcript prompt can appear above output while the actual composer is hidden.
    for index in reversed(range(len(lines))):
        line = lines[index].lstrip()
        if line.startswith(("•", "■", "─ Worked for")):
            break
        if line.startswith("›"):
            prompt = line[1:].strip()
            if prompt in ("", "Ask Codex to do anything"):
                return "ready"
            if PASTED_CONTENT.fullmatch(prompt):
                return "paste"
            if sent_message is not None:
                # Codex leaves a blank row between the composer and its status line.
                body_end = next((row for row in reversed(range(index + 1, len(lines) - 1))
                                 if not lines[row] and CODEX_STATUS_LINE.match(lines[row + 1])), len(lines))
                if matches_sent_message((prompt, *lines[index + 1:body_end]), sent_message):
                    return "paste"
            break
    return "waiting"


def read_codex_screen(address, *, sent_message=None):
    screen = hc_json("read", "--lines", "0", address)
    if not screen["complete"] or screen["how"] != "screen":
        return "waiting"
    return codex_screen(screen["text"], sent_message=sent_message)


def startup_composer(text):
    """Herdr may count initial Codex startup as turn 1 before any prompt."""
    prompts = [line.strip() for line in text.splitlines() if line.lstrip().startswith("›")]
    return ("OpenAI Codex (v" in text and len(prompts) == 1
            and prompts[0] in {"›", "› Ask Codex to do anything"}
            and not any(line.lstrip().startswith(("•", "■")) for line in text.splitlines()))


def send(args):
    run_file = getattr(args, "run", None)
    run_path = Path(run_file).resolve() if run_file else None
    with lock_run(run_path) if run_path else nullcontext():
        send_task(args, run_path)


def send_task(args, run_path):
    address = args.address
    if not args.message.strip():
        raise SystemExit("first message is empty")
    run = None
    continuation = getattr(args, "continuation", False)
    if run_path:
        run = load_run(run_path)
        if run["cli"] != "codex" or run["address"] != address:
            raise SystemExit("receipt is for another terminal or CLI")
        if run["sent"] == "unconfirmed":
            result, written = read_result(run_path)
            if not result or written == run.get("previous_result"):
                raise SystemExit("previous delivery is unconfirmed; inspect the child's composer before resuming")
            verify_terminal(run, hc_json("get", address))
            run["sent"] = True
            write_json(run_path, run)
        if run["sent"] != continuation:
            raise SystemExit("use --continue only after the first task is confirmed")
    elif continuation:
        raise SystemExit("--continue requires --run")
    message = args.message
    if run_path:
        if not continuation:
            if "handoff" in run:
                message = first_prompt("codex", message, run["handoff"])
            else:
                print("warning: legacy receipt has no handoff metadata; include the original request, "
                      "assigned unit, and Git limits in the first message", file=sys.stderr)
        message += "\n\n" + report_instruction(run_path.with_name("result.json"))
    sent_message = message.strip()
    screen_reads = 0
    attempted_send = False
    try:
        deadline = time.monotonic() + 30
        while True:
            screen_reads += 1
            screen = read_codex_screen(address)
            if screen == "hooks":
                raise SystemExit(f"{address}: task withheld; inspect the Codex hook status with /hooks")
            if screen == "warning":
                raise SystemExit(f"{address}: task withheld; inspect the Codex warning with F2")
            if screen == "ready":
                terminal = hc_json("get", address)
                if run:
                    verify_terminal(run, terminal)
                status = (terminal.get("status") or {}).get("state")
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
                raise SystemExit(f"{address}: task withheld; no clear Codex input line (check dialogs or drafts)")
            time.sleep(SCREEN_POLL_SECONDS)

        # Herdr can report that no turn started even after it pasted the message.
        if run:
            if run["parent"]:
                os.environ["HC_TERMINAL_ID"] = run["parent"]
            _, run["previous_result"] = read_result(run_path)
            if status == "done":
                current = hc_json("get", address)
                verify_terminal(run, current)
                if (current["turn"] != terminal["turn"] or
                        (current.get("status") or {}).get("state") != "done"):
                    raise SystemExit(f"{address}: task withheld; the child started another turn")
            run["sent"] = "unconfirmed"
            write_json(run_path, run)
        else:
            print("warning: no dispatch receipt. Use --run to carry handoff metadata", file=sys.stderr)
        attempted_send = True
        guard = ["--if", "idle"] if status == "idle" else []
        hc_json("send", *guard, "--", address, message)

        deadline = time.monotonic() + 5
        previous_idle_paste = False
        retried_enter = False
        while True:
            screen_reads += 1
            screen = read_codex_screen(address, sent_message=sent_message)
            if screen == "hooks":
                raise SystemExit(f"{address}: Codex reported a hook problem after the send; inspect before continuing")
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
            if screen == "ready" and (status == "working" or completed):
                if run:
                    run["sent"] = True
                    run["screen_reads"] += screen_reads
                    write_json(run_path, run)
                print(json.dumps({"address": address, "submitted": True, "screen_reads": screen_reads}))
                return
            if screen == "warning":
                raise SystemExit(f"{address}: Codex showed a warning after the send; inspect before continuing")
            idle_paste = (status == "idle" or (continuation and status == "done")) and screen == "paste"
            if idle_paste and previous_idle_paste and not retried_enter:
                hc_json("keys", address, "enter")
                retried_enter = True
            if time.monotonic() >= deadline:
                raise SystemExit(f"{address}: could not confirm submission; inspect the input before retrying")
            previous_idle_paste = idle_paste
            time.sleep(SCREEN_POLL_SECONDS)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as err:
        reason = ("Herdr could not confirm delivery; inspect the screen before retrying" if attempted_send
                  else "task withheld; Herdr could not read Codex readiness")
        raise SystemExit(f"{address}: {reason} ({type(err).__name__})") from None


def collect(args):
    path = Path(args.run).resolve()
    with lock_run(path) if args.close else nullcontext():
        collect_result(path, args.close)


def collect_result(path, close):
    run = load_run(path)
    result, written = read_result(path)
    if written == run.get("previous_result"):
        result = None
    terminal = hc_json("get", run["address"])
    verify_terminal(run, terminal)
    status = (terminal.get("status") or {}).get("state")
    finished = terminal["state"] == "finished"
    if close:
        if not result or result["status"] not in {"done", "merged"} or not (finished or status == "done"):
            raise SystemExit("terminal has no final result or is still running; left intact")
        if not finished:
            hc_json("kill", run["address"])
        hc_json("rm", run["address"])
    print(json.dumps({"address": run["address"], "status": status, "state": terminal["state"],
                      "result": result, "closed": close, "screen_reads": run["screen_reads"]},
                     ensure_ascii=False))


def pick(args):
    skills = Path(__file__).resolve().parents[2]
    script = skills / "task-next" / "scripts" / "backlog_candidates.py"
    repo = Path(args.repo).expanduser()
    if not (repo / "backlog.md").exists() and not args.tree:
        raise SystemExit(f"{repo} has no backlog.md: no queue")
    cmd = [sys.executable, "-I", "-X", "utf8", str(script), "--tasks", "tasks.md",
           "--backlog", "backlog.md", "--json"]
    if args.tree:
        cmd += ["--ref", "origin/HEAD"]
    if args.full_scan:
        cmd.append("--full-scan")
    done = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if done.returncode:
        raise SystemExit(done.stderr.strip() or done.stdout.strip())
    sys.stderr.write(done.stderr)
    print(done.stdout.strip())


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
    launch_parser.add_argument("--git-limits", required=True, help="verbatim Git limits")
    launch_parser.add_argument("--name")
    launch_parser.add_argument("--parent")
    launch_parser.add_argument("--task", help="send the first Codex task after launch")
    launch_parser.add_argument("--keep-connectors", action="store_true")
    launch_parser.add_argument("--no-show", action="store_true")
    launch_parser.add_argument("--dry-run", action="store_true")
    launch_parser.add_argument("message", nargs="?")
    launch_parser.set_defaults(func=launch)
    send_parser = sub.add_parser("send")
    send_parser.add_argument("address")
    send_parser.add_argument("message")
    send_parser.add_argument("--run")
    send_parser.add_argument("--continue", dest="continuation", action="store_true")
    send_parser.set_defaults(func=send)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("run")
    collect_parser.add_argument("--close", action="store_true")
    collect_parser.set_defaults(func=collect)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
