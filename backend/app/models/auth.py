"""Operator accounts and their sign-in sessions.

An account is who an operator is; a session is one browser signed in as them.
Keeping the two apart is what lets an operator see every place they are signed
in, sign one of them out, and change their password without being thrown out of
the console they changed it from.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from ..db.types import UTCDateTime

__all__ = ["UserAccount", "UserRole", "UserSession"]


class UserRole(StrEnum):
    """What an operator may change.

    Two roles, because a control room has two kinds of person: the operators who
    run a shift, and whoever is responsible for how the platform is set up.
    Watching, counters, retries and simulations are an operator's work; adding
    cameras, drawing zones, linking the site and managing accounts are an
    administrator's.
    """

    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One operator.

    Never deleted, only deactivated: the timeline attributes actions to the
    person who took them, and that record must outlive their account.
    """

    __table_args__ = (CheckConstraint("role IN ('ADMIN', 'OPERATOR')", name="role"),)

    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    """Stored lowercased, so an operator signing in as Ops@Venue.org finds their account."""

    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=UserRole.OPERATOR.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class UserSession(UUIDPrimaryKeyMixin, Base):
    """One signed-in browser.

    The browser holds a random token; only its SHA-256 digest is stored here, so
    a copy of this table does not let anyone sign in.
    """

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
