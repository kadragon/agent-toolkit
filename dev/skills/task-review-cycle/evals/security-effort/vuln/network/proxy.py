# Eval fixture file. Not production code.
import requests


def fetch_report(user_url: str) -> bytes:
    resp = requests.get(user_url, timeout=10)
    resp.raise_for_status()
    return resp.content
