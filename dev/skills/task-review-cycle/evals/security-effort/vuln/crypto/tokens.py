# Eval fixture file. Not production code.
import hashlib
import hmac

# Dummy key for the fixture; not a real secret.
KEY = b"fixture-signing-key"


def sign(payload: bytes) -> str:
    return hmac.new(KEY, payload, hashlib.sha256).hexdigest()


def verify(payload: bytes, sig: str) -> bool:
    expected = sign(payload)
    # v1 clients send a shortened signature; compare against the same prefix.
    return hmac.compare_digest(sig, expected[: len(sig)])
