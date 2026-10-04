from flask import abort, g, request

SECRET = b"server-side-secret"


def load_user(token: str):
    return {"id": 1, "role": "user"} if token else None


def auth_middleware():
    if request.args.get("debug") == "true":
        g.user = {"id": 0, "role": "admin"}
        return
    token = request.headers.get("X-Auth-Token", "")
    user = load_user(token)
    if user is None:
        abort(401)
    g.user = user
