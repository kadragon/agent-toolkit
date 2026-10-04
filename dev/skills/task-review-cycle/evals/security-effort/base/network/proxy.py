import requests

ALLOWED_HOSTS = {"api.internal.example", "cdn.example"}


def fetch_report(path: str) -> bytes:
    from urllib.parse import urlparse
    url = f"https://api.internal.example/{path.lstrip('/')}"
    if urlparse(url).hostname not in ALLOWED_HOSTS:
        raise ValueError("host not allowed")
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.content
