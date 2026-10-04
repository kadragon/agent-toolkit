# Intentional eval fixture — plants command injection. Not production code.
import subprocess


def ping(host: str) -> str:
    out = subprocess.run(
        f"ping -c1 {host}", shell=True, capture_output=True, text=True, timeout=10
    )
    return out.stdout
