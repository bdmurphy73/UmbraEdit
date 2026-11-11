"""
UmbraStore - Authentication
===========================

Token generation and verification using SHA-256 with random salt.
Tokens are stored as "salt:hash" in the database.
"""  # noqa

from __future__ import annotations

import hashlib
import secrets


def generateToken() -> str:
    """Generate a random bearer token (43 chars, URL-safe base64 without padding)."""
    return secrets.token_urlsafe(32)


def hashToken(token: str, salt: str | None = None) -> str:
    """Hash a bearer token with SHA-256 and a random salt.

    Returns "salt:hash" where salt is 16 hex chars and hash is 64 hex chars.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + token).encode("utf-8")).hexdigest()
    return f"{salt}:{h}"


def verifyToken(token: str, storedHash: str) -> bool:
    """Verify a bearer token against a stored "salt:hash" value."""
    try:
        salt, h = storedHash.split(":", 1)
    except ValueError:
        return False
    expected = hashlib.sha256((salt + token).encode("utf-8")).hexdigest()
    return secrets.compare_digest(h, expected)
