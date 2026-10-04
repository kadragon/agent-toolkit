# Eval fixture file. Not production code.
import subprocess


def ping(host: str) -> str:
    out = subprocess.run(
        ["ping", "-c1", host], capture_output=True, text=True, timeout=10
    )
    return out.stdout
