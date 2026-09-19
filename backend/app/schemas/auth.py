"""Authentication and operator account schemas."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from ..models.auth import UserRole

__all__ = [
    "AuthStatusRead",
    "LoginWrite",
    "PasswordChangeWrite",
    "ProfileWrite",
    "SessionRead",
    "SetupWrite",
    "UserCreateWrite",
    "UserRead",
    "UserUpdateWrite",
]

#: Deliberately permissive: an operator account on a local network may well be
#: ``ops@control-room``. The check is that it is shaped like an address, not
#: that a mail server exists for it.
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}$")


def _normalise_email(value: str) -> str:
    candidate = value.strip().lower()
    if not _EMAIL.fullmatch(candidate):
        raise ValueError("Enter an email address such as ops@venue.org")
    return candidate


def _normalise_name(value: str) -> str:
    candidate = " ".join(value.split())
    if not candidate:
        raise ValueError("Enter a name")
    return candidate


_PASSWORD = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class UserRead(BaseModel):
    """An operator account as the interface shows it. Never carries the hash."""

    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class AuthStatusRead(BaseModel):
    """What the interface needs before it can decide which screen to show."""

    model_config = ConfigDict(extra="forbid")

    auth_enabled: bool = Field(
        description="False when the deployment opens without sign-in, as the prototype did."
    )
    setup_required: bool = Field(
        description="True until the first administrator account has been created."
    )
    user: UserRead | None = Field(
        default=None, description="The signed-in operator, when the request carries a session."
    )


class SetupWrite(BaseModel):
    """The first administrator account on a new deployment."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    display_name: str = Field(max_length=80)
    password: str = _PASSWORD

    _email = field_validator("email")(_normalise_email)
    _name = field_validator("display_name")(_normalise_name)


class LoginWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        # Normalised but not format-checked: a malformed address simply matches
        # no account, and says so the same way a wrong password does.
        return value.strip().lower()


class ProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(max_length=80)

    _name = field_validator("display_name")(_normalise_name)


class PasswordChangeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = _PASSWORD


class SessionRead(BaseModel):
    """One browser signed in as the current operator."""

    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None = None
    ip_address: str | None = None
    current: bool = Field(description="Whether this is the session making the request.")


class UserCreateWrite(BaseModel):
    """An account an administrator creates for another operator."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    display_name: str = Field(max_length=80)
    password: str = _PASSWORD
    role: UserRole = UserRole.OPERATOR

    _email = field_validator("email")(_normalise_email)
    _name = field_validator("display_name")(_normalise_name)


class UserUpdateWrite(BaseModel):
    """An administrator's change to an account. Absent fields are left as they are."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=80)
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _normalise_name(value)
