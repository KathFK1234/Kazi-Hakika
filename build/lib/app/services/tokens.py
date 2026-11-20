import hashlib
import secrets


def new_token() -> str:
    """256 bits from the OS CSPRNG, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Tokens are high-entropy, so a fast hash is enough; only hashes are stored."""
    return hashlib.sha256(token.encode()).hexdigest()
