import hashlib
import hmac
import secrets

from app.core.config import settings


def generate_api_key() -> str:
    """Generates a secure random API key."""
    return f"prp_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """Return a lookup-safe digest keyed with the server-side pepper."""
    return hmac.new(
        settings.API_PEPPER.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """Verifies that the provided API key matches the stored hash."""
    return secrets.compare_digest(hash_api_key(api_key), key_hash)


def get_api_key_prefix(api_key: str) -> str:
    """Returns the prefix (first 8 characters) of the API key."""
    return api_key[:8]


def generate_webhook_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


def sign_webhook(secret: str, timestamp: int, body: bytes) -> str:
    signed_payload = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"
