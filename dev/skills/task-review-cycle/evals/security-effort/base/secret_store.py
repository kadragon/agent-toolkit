import logging
import os

log = logging.getLogger(__name__)

SECRET_KEY = os.environ["SECRET_KEY"]


def sign(payload: bytes) -> bytes:
    import hmac
    return hmac.new(SECRET_KEY.encode(), payload, "sha256").digest()
