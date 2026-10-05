# Eval fixture file. Not production code.
import sqlite3


def redeem_invite(db: sqlite3.Connection, code: str, user_id: int) -> bool:
    """Bind a one-time invite code to user_id. Returns False if unknown or spent."""
    row = db.execute("SELECT used FROM invites WHERE code = ?", (code,)).fetchone()
    if row is None or row[0]:
        return False
    db.execute(
        "UPDATE invites SET used = 1, user_id = ? WHERE code = ?",
        (user_id, code),
    )
    db.commit()
    return True
