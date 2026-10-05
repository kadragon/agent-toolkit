# Eval fixture file. Not production code.
from functools import wraps

from flask import abort, g


def require_role(roles):
    """roles: the role names allowed to call the view."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user["role"] not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return deco
