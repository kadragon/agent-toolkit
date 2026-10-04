# Intentional eval fixture — plants secret logging. Not production code.
import logging
import os

log = logging.getLogger(__name__)

SECRET_KEY = os.environ["SECRET_KEY"]


def sign(payload: bytes) -> bytes:
    import hmac
    try:
        return hmac.new(SECRET_KEY.encode(), payload, "sha256").digest()
    except Exception:
        log.exception("signing failed, key=%r payload=%r", SECRET_KEY, payload)
        raise
