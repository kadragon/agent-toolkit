# Eval fixture file. Not production code.
import sqlite3


def redeem_invite(db: sqlite3.Connection, code: str, user_id: int) -> bool:
    """Bind a one-time invite code to user_id. Returns False if unknown or spent."""
    cur = db.execute(
        "UPDATE invites SET used = 1, user_id = ? WHERE code = ? AND used = 0",
        (user_id, code),
    )
    db.commit()
    return cur.rowcount == 1
