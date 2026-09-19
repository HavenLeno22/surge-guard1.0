"""Column types shared by every model."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

__all__ = ["UTCDateTime"]


class UTCDateTime(TypeDecorator[datetime]):
    """A timestamp that is always timezone-aware UTC on both sides of the database.

    ``DateTime(timezone=True)`` is not enough on SQLite, which has no timezone
    storage: an aware value goes in and a *naive* one comes back, and the first
    comparison against ``datetime.now(UTC)`` raises. Every timestamp in the
    platform is UTC, so this stores UTC and hands UTC back.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime refuses a naive datetime; attach a timezone first")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
