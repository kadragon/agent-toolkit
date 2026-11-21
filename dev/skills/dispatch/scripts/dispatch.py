"""Deterministic steps of the dispatch skill.

  dispatch.py pick <repo path> [--tree]
      Print, as JSON, the candidates task-next would pick in <repo path>, from the
      task-next script bundled with this dev plugin (fast path, first = its pick).
  dispatch.py launch --cli claude|codex --model M --effort E --cwd PATH
                     [--name N] [--keep-connectors] [--no-show] [--dry-run] [MESSAGE]
      Start the child with hc run and, inside the Herdr app, keep its pane in the
      right-hand column. Prints one JSON object: name, address, parent, shown.
      Codex takes no MESSAGE: send it with hc send once the screen is clear.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CLAUDE_SETTINGS = {
    "promptSuggestionEnabled": False,
    "awaySummaryEnabled": False,
    "disableClaudeAiConnectors": True,
    "enabledPlugins": {"cc-plugin-you-should-know@builtin": False},
}


def terminal_name(raw):
    """hc names are 1-32 of a-z 0-9 - _."""
    name = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-")[:32]
    if not name:
        raise SystemExit(f"cannot build a terminal name from {raw!r}")
    return name


def child_argv(cli, model, effort, message, keep_connectors):
    if cli == "codex":
        if message:
            raise SystemExit("codex takes no first message at launch; hc send it once the screen is clear")
        return ["codex", "--no-alt-screen", "--approve-for-me", "-m", model,
                "-c", f"model_reasoning_effort={effort}"]
    if not message:
        raise SystemExit("a claude child needs its first message")
    settings = dict(CLAUDE_SETTINGS)
    if keep_connectors:
        del settings["disableClaudeAiConnectors"]
    return ["claude", "--model", model, "--effort", effort,
            "--settings", json.dumps(settings, separators=(",", ":")), message]


def hc_json(*args):
    out = subprocess.run(["hc", *args, "--json"], capture_output=True, text=True,
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
    """The tab that shows the home terminal, from the app's own layout (not from focus)."""
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


def launch(args):
    cwd = Path(args.cwd).expanduser()
    name = terminal_name(args.name or cwd.name)
    home = os.environ.get("HC_TERMINAL_ID")
    if not args.dry_run:
        taken = {t.get("name") for t in hc_json("ls")["terminals"]}
        name = free_name(name, bool(args.name), taken)
    argv = ["hc", "run", "--bg", "--json", "--outlive-parent", "--name", name, "--cwd", str(cwd),
            *(["--parent", home] if home else []),
            *child_argv(args.cli, args.model, args.effort, args.message, args.keep_connectors)]
    if args.dry_run:
        print(json.dumps({"name": name, "argv": argv}, ensure_ascii=False))
        return
    if not cwd.is_dir():
        raise SystemExit(f"no such directory: {cwd}")
    result = json.loads(subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                       check=True).stdout)
    if home and result.get("parent") != home:
        print(f"warning: parent is {result.get('parent')}, not this session {home}", file=sys.stderr)
    shown = False
    if home and not args.no_show:
        try:
            show(home, result["address"])
            shown = True
        except (subprocess.CalledProcessError, OSError, ValueError, KeyError, RuntimeError,
                StopIteration) as err:
            print(f"pane not kept: {err}", file=sys.stderr)
    print(json.dumps({"name": name, "address": result["address"], "parent": result.get("parent"),
                      "cli": args.cli, "model": args.model, "effort": args.effort, "shown": shown}))


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
    pick_parser.set_defaults(func=pick)
    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("--cli", choices=["claude", "codex"], required=True)
    launch_parser.add_argument("--model", required=True)
    launch_parser.add_argument("--effort", required=True)
    launch_parser.add_argument("--cwd", required=True)
    launch_parser.add_argument("--name")
    launch_parser.add_argument("--keep-connectors", action="store_true")
    launch_parser.add_argument("--no-show", action="store_true")
    launch_parser.add_argument("--dry-run", action="store_true")
    launch_parser.add_argument("message", nargs="?")
    launch_parser.set_defaults(func=launch)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
