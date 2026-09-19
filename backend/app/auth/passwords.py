"""Password hashing.

PBKDF2-HMAC-SHA256 from the standard library, at the iteration count OWASP
recommends for it. No third-party dependency, no native build step on an
operator's Windows machine, and a format that names its own parameters so the
count can be raised later without invalidating existing accounts.

Hashing is deliberately slow - around half a second - so callers on the event
loop run it in a worker thread.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

__all__ = ["ITERATIONS", "MIN_PASSWORD_LENGTH", "hash_password", "needs_rehash", "verify_password"]

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16

#: Long enough to resist guessing without forcing rules nobody remembers.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """Return ``pbkdf2_sha256$<iterations>$<salt>$<hash>`` for a password."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Whether ``password`` matches ``encoded``. Never raises on a malformed hash."""
    try:
        algorithm, iterations_text, salt_text, hash_text = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(hash_text)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def needs_rehash(encoded: str) -> bool:
    """Whether a stored hash uses weaker parameters than the current ones."""
    try:
        algorithm, iterations_text, _, _ = encoded.split("$")
        return algorithm != ALGORITHM or int(iterations_text) < ITERATIONS
    except ValueError:
        return True
