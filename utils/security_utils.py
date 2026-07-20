
import hashlib
import hmac
import os


def hash_security_value(value):
    if not value:
        return None

    secret = os.environ["SECURITY_HASH_KEY"].encode()

    return hmac.new(
        secret,
        value.encode(),
        hashlib.sha256
    ).hexdigest()