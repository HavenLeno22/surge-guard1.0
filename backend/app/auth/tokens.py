"""Session tokens.

A token is 256 bits of randomness handed to the browser once. Only its SHA-256
digest is stored, so the session table cannot be replayed into a sign-in by
anyone who reads it. A slow hash is unnecessary here, unlike for passwords: the
input is already uniformly random and far too large to guess.
"""

from __future__ import annotations

import hashlib
import secrets

__all__ = ["new_session_token", "token_digest"]

TOKEN_BYTES = 32


def new_session_token() -> str:
    """A new URL-safe session token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_digest(token: str) -> str:
    """The value stored in place of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
