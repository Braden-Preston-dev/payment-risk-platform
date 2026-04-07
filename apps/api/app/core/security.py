import hashlib
import secrets

def generate_api_key() -> str:
    """Generates a secure random API key."""
    return secrets.token_urlsafe(32)

def hash_api_key(api_key: str) -> str:
    """Hashes the API key using SHA-256."""
    return hashlib.sha256(api_key.encode()).hexdigest()

def verify_api_key(api_key: str, key_hash: str) -> bool:
    """Verifies that the provided API key matches the stored hash."""
    return secrets.compare_digest(hash_api_key(api_key), key_hash)

def get_api_key_prefix(api_key: str) -> str:
    """Returns the prefix (first 8 characters) of the API key."""
    return api_key[:8]