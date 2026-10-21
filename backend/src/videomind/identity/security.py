import base64
import hashlib
import hmac
import secrets


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256 * 1024**2
    )
    return (
        "scrypt-v1$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        version, salt, _ = stored.split("$")
        if version != "scrypt-v1":
            return False
        return hmac.compare_digest(
            password_hash(password, base64.b64decode(salt, validate=True)), stored
        )
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
