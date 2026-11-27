"""Read one result over the Codex app server's stdio transport."""

import io
import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path


class AppServerError(ValueError):
    pass


def request(binary, home, method, params, *, timeout, cwd=None, experimental=False):
    home = home.resolve()
    env = {**os.environ, "CODEX_HOME": str(home)}
    with subprocess.Popen([binary, "app-server"], cwd=cwd, env=env, bufsize=0, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          start_new_session=os.name != "nt") as process:
        incoming = queue.Queue()
        deadline = time.monotonic() + timeout

        def read():
            try:
                # Only the reader owns this buffer, so cleanup can close the raw pipe independently.
                for line in io.BufferedReader(process.stdout):
                    incoming.put(line)
            except (OSError, ValueError):
                pass
            finally:
                incoming.put(None)

        def send(message):
            process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
            process.stdin.flush()

        def receive(request_id):
            while (remaining := deadline - time.monotonic()) > 0:
                line = incoming.get(timeout=remaining)
                if line is None:
                    raise AppServerError("Codex app server closed before replying")
                message = json.loads(line)
                if isinstance(message, dict) and message.get("id") == request_id:
                    if "error" in message or "result" not in message:
                        rejected = "initialize" if request_id == 1 else method
                        raise AppServerError(f"Codex app server rejected {rejected}")
                    return message["result"]
            raise AppServerError("Codex app server timed out")

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "dispatch", "version": "1"},
                "capabilities": {"experimentalApi": experimental},
            }})
            initialized = receive(1)
            actual_home = initialized.get("codexHome") if isinstance(initialized, dict) else None
            if not isinstance(actual_home, str) or Path(actual_home).resolve() != home:
                raise AppServerError("Codex app server loaded a different home")
            send({"method": "initialized"})
            send({"id": 2, "method": method, "params": params})
            return receive(2)
        except queue.Empty:
            raise AppServerError("Codex app server timed out") from None
        finally:
            # The executable can be a shim that starts the real app server as its child.
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
