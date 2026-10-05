# Eval fixture file. Not production code.
from flask import abort, g, request


def lookup_account(token: str):
    # Fixture stand-in for a DB lookup.
    accounts = {"t-admin": ("admin", True), "t-user": ("user", True), "t-new": ("user", False)}
    return accounts.get(token)


def load_session():
    found = lookup_account(request.headers.get("X-Auth-Token", ""))
    if found is None:
        abort(401)
    role, verified = found
    g.user = {"role": role, "verified": verified}
