"""Stop Codex companion brokers by exact workspace and, for a review, private PID-file root."""

import argparse
import ctypes
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Broker:
    pid: int
    cwd: Path
    endpoint: str
    pid_file: Path


def canonical(path):
    return Path(os.path.realpath(path))


def broker_from_args(pid, args):
    if len(args) != 9 or Path(args[0]).name.lower() not in {"node", "node.exe"}:
        return None
    if Path(args[1]).name != "app-server-broker.mjs" or args[2] != "serve":
        return None
    options = dict(zip(args[3::2], args[4::2], strict=True))
    if options.keys() != {"--endpoint", "--cwd", "--pid-file"}:
        return None
    cwd, pid_file = Path(options["--cwd"]), Path(options["--pid-file"])
    if not cwd.is_absolute() or not pid_file.is_absolute():
        return None
    if pid_file.name != "broker.pid" or not pid_file.parent.name.startswith("cxc-"):
        return None
    return Broker(pid, canonical(cwd), options["--endpoint"], canonical(pid_file))


def windows_args(command):
    from ctypes import wintypes

    split = ctypes.windll.shell32.CommandLineToArgvW
    split.restype = ctypes.POINTER(wintypes.LPWSTR)
    split.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    release = ctypes.windll.kernel32.LocalFree
    release.argtypes = [wintypes.HLOCAL]
    release.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    argv = split(command, ctypes.byref(count))
    if not argv:
        return []
    try:
        return argv[:count.value]
    finally:
        release(ctypes.cast(argv, wintypes.HLOCAL))


def output(args):
    return subprocess.check_output(args, text=True, encoding="utf-8-sig", errors="replace", timeout=8)


def process_args(pid=None):
    if os.name == "nt":
        query = "Name='node.exe'"
        if pid is not None:
            query += f" AND ProcessId={pid}"
        script = (
            "$ErrorActionPreference = 'Stop'; [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            f"Get-CimInstance Win32_Process -Filter \"{query}\" "
            "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        records = json.loads(output(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]) or "[]")
        if isinstance(records, dict):
            records = [records]
        for record in records or []:
            if record.get("CommandLine"):
                yield record["ProcessId"], windows_args(record["CommandLine"])
        return

    if sys.platform == "linux":
        entries = [Path(f"/proc/{pid}")] if pid is not None else Path("/proc").iterdir()
        for entry in entries:
            if entry.name.isdecimal():
                try:
                    args = (entry / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
                except OSError:
                    continue
                yield int(entry.name), list(map(os.fsdecode, args))
        return

    # BSD ps flattens argv. Match the companion's fixed argument order and use
    # the PID file as corroboration when argv boundaries cannot be recovered.
    selector = ["-p", str(pid)] if pid is not None else ["-ax"]
    try:
        lines = output(["ps", *selector, "-ww", "-o", "pid=,command="]).splitlines()
    except subprocess.CalledProcessError:
        if pid is None:
            raise
        return
    for line in lines:
        match = re.fullmatch(
            r"\s*(\d+) (.+?/node|node) (.+?/app-server-broker\.mjs)"
            r" serve --endpoint (.+) --cwd (.+) --pid-file (.+)", line,
        )
        if match:
            number, node, script, endpoint, cwd, pid_file = match.groups()
            try:
                if Path(pid_file).read_text(encoding="ascii").strip() != number:
                    continue
            except (OSError, UnicodeError):
                continue
            yield int(number), [node, script, "serve", "--endpoint", endpoint, "--cwd", cwd, "--pid-file", pid_file]


def brokers(pid=None):
    for number, args in process_args(pid):
        broker = broker_from_args(number, args)
        if broker is not None:
            yield broker


SHUTDOWN = r"""
const net = require('node:net');
const endpoint = process.argv[1];
let target;
if (endpoint.startsWith('unix:')) target = endpoint.slice(5);
else if (endpoint.startsWith('pipe:')) target = endpoint.slice(5);
else process.exit(1);
const socket = net.createConnection(target);
socket.setTimeout(750, () => socket.destroy());
socket.on('error', () => socket.destroy());
socket.on('connect', () => socket.write('{"id":1,"method":"broker/shutdown","params":{}}\n'));
socket.on('data', () => socket.destroy());
"""


def running(broker):
    return broker in brokers(broker.pid)


def stop(broker):
    # A PID from a stale record or from an earlier process snapshot is not authority to kill.
    if not running(broker):
        return True
    try:
        subprocess.run(["node", "-e", SHUTDOWN, broker.endpoint], capture_output=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if os.name == "nt":
        # The fresh CIM query gives the app-server time to exit after acknowledging shutdown.
        if running(broker):
            subprocess.run(["taskkill.exe", "/PID", str(broker.pid), "/T", "/F"],
                           capture_output=True, timeout=5, check=False)
        return not running(broker)

    # SIGTERM also asks the broker to close its app-server child.
    if running(broker):
        try:
            os.kill(broker.pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
    for _ in range(20):
        if not running(broker):
            return True
        time.sleep(0.05)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    roots = parser.add_mutually_exclusive_group()
    roots.add_argument("--owned-temp", type=Path)
    roots.add_argument("--fixture-root", action="store_true", help="Include immediate fixture directories")
    parser.add_argument("--list", action="store_true", help="Report matching brokers without stopping them")
    args = parser.parse_args()
    cwd = canonical(args.workspace)
    owned = canonical(args.owned_temp) if args.owned_temp is not None else None
    failed = False
    try:
        for broker in list(brokers()):
            matches = broker.cwd.parent == cwd if args.fixture_root else broker.cwd == cwd
            if not matches or (owned is not None and broker.pid_file.parent.parent != owned):
                continue
            label = f"Codex companion broker PID {broker.pid} ({broker.cwd})"
            if args.list:
                print(label)
            else:
                try:
                    stopped = stop(broker)
                except (OSError, subprocess.SubprocessError, ValueError):
                    stopped = False
                if not stopped:
                    failed = True
                    print(f"Could not stop {label}", file=sys.stderr)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"Could not inspect Codex companion brokers: {exc}", file=sys.stderr)
        failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
