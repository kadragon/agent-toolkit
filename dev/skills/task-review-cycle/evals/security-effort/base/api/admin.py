# Eval fixture file. Not production code.
from auth.decorators import require_role
from auth.session import load_session
from flask import Flask

app = Flask(__name__)
app.before_request(load_session)


@app.post("/admin/purge")
@require_role("admin")
def purge():
    return {"purged": True}
