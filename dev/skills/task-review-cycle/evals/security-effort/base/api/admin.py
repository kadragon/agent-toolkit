# Eval fixture file. Not production code.
from flask import Flask

from auth.decorators import require_role
from auth.session import load_session

app = Flask(__name__)
app.before_request(load_session)


@app.post("/admin/purge")
@require_role("admin")
def purge():
    return {"purged": True}
