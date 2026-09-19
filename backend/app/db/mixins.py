"""Reusable model mixins.

Every entity needs an identifier and audit timestamps. Declaring them once here
keeps the eventual models free of repetition (Rule 9).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from .types import UTCDateTime

__all__ = ["UUIDPrimaryKeyMixin", "TimestampMixin"]


def _new_uuid() -> str:
    """Generate a primary key.

    UUIDs rather than autoincrementing integers because Crowd Events, Alerts and
    Operational Intelligence Reports are created by the analysis path and
    referenced in real-time messages before any transaction commits. An
    identifier that exists only after a database round trip cannot be broadcast
    with the event that created it.

    Stored as a 36-character string: portable across SQLite and PostgreSQL, and
    readable in logs.
    """
    return str(uuid.uuid4())


class UUIDPrimaryKeyMixin:
    """Adds a UUID string primary key named ``id``."""

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at``, both timezone-aware UTC.

    Timestamps are server-side defaults so a row is never written without them,
    regardless of which code path created it.
    """

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )
