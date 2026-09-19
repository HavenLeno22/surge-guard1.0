"""Database access layer.

Persistent storage only. Business rules belong in ``app.services``
(``08:495-511``).
"""

from __future__ import annotations

from .base import Base
from .mixins import TimestampMixin, UUIDPrimaryKeyMixin
from .session import DatabaseManager, get_database, get_session, session_scope

__all__ = [
    "Base",
    "DatabaseManager",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "get_database",
    "get_session",
    "session_scope",
]
