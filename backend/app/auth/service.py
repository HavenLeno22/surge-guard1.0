"""Operator accounts and sign-in sessions.

The one place that reads or writes accounts and sessions. Routes express intent
("sign this operator in", "revoke that session"); this module owns what that
means - hashing off the event loop, storing only token digests, never leaving a
deployment without an administrator, and revoking every other session when a
password changes.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..core.config import Settings
from ..core.exceptions import (
    AccountDisabledError,
    ConflictError,
    InvalidCredentialsError,
    NotFoundError,
    SetupCompleteError,
)
from ..core.logging import get_logger
from ..db.session import DatabaseManager
from ..models.auth import UserAccount, UserRole, UserSession
from .passwords import hash_password, verify_password
from .tokens import new_session_token, token_digest

__all__ = ["AuthContext", "AuthService", "SessionSnapshot", "UserSnapshot"]

logger = get_logger(__name__)

#: How often a session's ``last_seen_at`` is written. Every request would be a
#: write per poll for a timestamp nobody needs to the second.
_LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=60)

#: How long a resolved session is trusted without asking the database again.
#: Short, because a revoked session must stop working promptly.
_RESOLVE_CACHE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class UserSnapshot:
    """An account, detached from any database session."""

    id: str
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, account: UserAccount) -> UserSnapshot:
        return cls(
            id=account.id,
            email=account.email,
            display_name=account.display_name,
            role=UserRole(account.role),
            is_active=account.is_active,
            last_login_at=account.last_login_at,
            created_at=account.created_at,
        )


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_address: str | None

    @classmethod
    def of(cls, session: UserSession) -> SessionSnapshot:
        return cls(
            id=session.id,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            user_agent=session.user_agent,
            ip_address=session.ip_address,
        )


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Who a request is from."""

    user: UserSnapshot
    session_id: str


class AuthService:
    """Accounts, passwords and sessions."""

    def __init__(self, database: DatabaseManager, settings: Settings) -> None:
        self._database = database
        self._settings = settings
        self._setup_lock = asyncio.Lock()
        self._resolved: dict[str, tuple[float, AuthContext]] = {}
        # A real hash to verify against when an email matches no account, so a
        # failed sign-in takes the same time whether or not the account exists.
        # Built on first use, off the event loop, rather than slowing startup.
        self._decoy_hash: str | None = None

    @property
    def session_ttl(self) -> timedelta:
        return timedelta(hours=self._settings.session_ttl_hours)

    # -- Hashing (off the event loop) ---------------------------------------

    async def _hash(self, password: str) -> str:
        return await asyncio.to_thread(
            hash_password, password, iterations=self._settings.auth_password_iterations
        )

    @staticmethod
    async def _verify(password: str, encoded: str) -> bool:
        return await asyncio.to_thread(verify_password, password, encoded)

    # -- Setup ----------------------------------------------------------------

    async def user_count(self) -> int:
        async with self._database.session() as session:
            result = await session.execute(select(func.count()).select_from(UserAccount))
            return int(result.scalar_one())

    async def setup_required(self) -> bool:
        return await self.user_count() == 0

    async def create_first_admin(
        self, *, email: str, display_name: str, password: str
    ) -> UserSnapshot:
        """Create the deployment's first account, as an administrator.

        Serialised, and re-checked inside the lock, so two browsers completing
        setup at the same moment cannot both create one.
        """
        password_hash = await self._hash(password)
        async with self._setup_lock:
            if not await self.setup_required():
                raise SetupCompleteError()
            async with self._database.session() as session:
                account = UserAccount(
                    email=email,
                    display_name=display_name,
                    password_hash=password_hash,
                    role=UserRole.ADMIN.value,
                    is_active=True,
                )
                session.add(account)
                await session.flush()
                snapshot = UserSnapshot.of(account)
        logger.info("First administrator account created", extra={"user_id": snapshot.id})
        return snapshot

    # -- Signing in -----------------------------------------------------------

    async def authenticate(self, email: str, password: str) -> UserSnapshot:
        """Check credentials. Raises rather than returning ``None``.

        Raises:
            InvalidCredentialsError: No account has this email, or the password
                is wrong. One error for both.
            AccountDisabledError: The password was right for a deactivated
                account. Only said after the password is proven, so it confirms
                nothing to someone guessing.
        """
        async with self._database.session() as session:
            account = await session.scalar(select(UserAccount).where(UserAccount.email == email))
            snapshot = UserSnapshot.of(account) if account is not None else None
            encoded = account.password_hash if account is not None else None

        if encoded is None:
            if self._decoy_hash is None:
                self._decoy_hash = await self._hash("surgeguard-decoy-password")
            encoded = self._decoy_hash

        if not await self._verify(password, encoded) or snapshot is None:
            raise InvalidCredentialsError()
        if not snapshot.is_active:
            raise AccountDisabledError()
        return snapshot

    async def start_session(
        self, user_id: str, *, user_agent: str | None, ip_address: str | None
    ) -> str:
        """Open a session and return its token - the only time the token exists in full."""
        token = new_session_token()
        now = datetime.now(UTC)
        async with self._database.session() as session:
            session.add(
                UserSession(
                    user_id=user_id,
                    token_hash=token_digest(token),
                    created_at=now,
                    expires_at=now + self.session_ttl,
                    last_seen_at=now,
                    user_agent=(user_agent or "")[:255] or None,
                    ip_address=(ip_address or "")[:45] or None,
                )
            )
            await session.execute(
                update(UserAccount).where(UserAccount.id == user_id).values(last_login_at=now)
            )
        return token

    async def resolve_token(self, token: str) -> AuthContext | None:
        """The operator a session token belongs to, or ``None``.

        ``None`` for an unknown, expired or revoked session, and for a
        deactivated account - all of which mean "sign in again".
        """
        digest = token_digest(token)
        cached = self._resolved.get(digest)
        if cached is not None and time.monotonic() - cached[0] < _RESOLVE_CACHE_SECONDS:
            return cached[1]

        now = datetime.now(UTC)
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(UserSession, UserAccount)
                    .join(UserAccount, UserAccount.id == UserSession.user_id)
                    .where(UserSession.token_hash == digest)
                )
            ).first()
            if row is None:
                self._resolved.pop(digest, None)
                return None
            user_session, account = row
            if (
                user_session.revoked_at is not None
                or user_session.expires_at <= now
                or not account.is_active
            ):
                self._resolved.pop(digest, None)
                return None
            if now - user_session.last_seen_at >= _LAST_SEEN_WRITE_INTERVAL:
                user_session.last_seen_at = now
            context = AuthContext(user=UserSnapshot.of(account), session_id=user_session.id)

        self._resolved[digest] = (time.monotonic(), context)
        return context

    # -- Sessions -------------------------------------------------------------

    async def revoke_token(self, token: str) -> str | None:
        """Sign out the session a token belongs to. Returns its id, if it existed."""
        digest = token_digest(token)
        self._resolved.pop(digest, None)
        async with self._database.session() as session:
            user_session = await session.scalar(
                select(UserSession).where(UserSession.token_hash == digest)
            )
            if user_session is None:
                return None
            if user_session.revoked_at is None:
                user_session.revoked_at = datetime.now(UTC)
            return user_session.id

    async def revoke_session(self, session_id: str, *, user_id: str) -> None:
        """Sign out one of an operator's own sessions.

        Raises:
            NotFoundError: No active session with that id belongs to this operator.
        """
        async with self._database.session() as session:
            user_session = await session.scalar(
                select(UserSession).where(
                    UserSession.id == session_id,
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                )
            )
            if user_session is None:
                raise NotFoundError("That session is not signed in.")
            user_session.revoked_at = datetime.now(UTC)
        self._resolved.clear()

    async def list_sessions(self, user_id: str) -> list[SessionSnapshot]:
        """An operator's active sessions, most recently used first."""
        now = datetime.now(UTC)
        async with self._database.session() as session:
            rows = await session.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
                .order_by(UserSession.last_seen_at.desc())
            )
            return [SessionSnapshot.of(row) for row in rows]

    # -- The operator's own account ---------------------------------------------

    async def get_user(self, user_id: str) -> UserSnapshot | None:
        async with self._database.session() as session:
            account = await session.get(UserAccount, user_id)
            return UserSnapshot.of(account) if account is not None else None

    async def update_profile(self, user_id: str, *, display_name: str) -> UserSnapshot:
        async with self._database.session() as session:
            account = await session.get(UserAccount, user_id)
            if account is None:
                raise NotFoundError("That operator account no longer exists.")
            account.display_name = display_name
            await session.flush()
            snapshot = UserSnapshot.of(account)
        self._resolved.clear()
        return snapshot

    async def change_password(
        self,
        user_id: str,
        *,
        current_password: str,
        new_password: str,
        keep_session_id: str | None,
    ) -> int:
        """Replace a password and sign out every other session.

        Returns:
            How many other sessions were signed out.

        Raises:
            InvalidCredentialsError: The current password is wrong.
        """
        async with self._database.session() as session:
            account = await session.get(UserAccount, user_id)
            if account is None:
                raise NotFoundError("That operator account no longer exists.")
            encoded = account.password_hash
        if not await self._verify(current_password, encoded):
            raise InvalidCredentialsError("The current password is not correct.")

        new_hash = await self._hash(new_password)
        now = datetime.now(UTC)
        async with self._database.session() as session:
            await session.execute(
                update(UserAccount).where(UserAccount.id == user_id).values(password_hash=new_hash)
            )
            statement = update(UserSession).where(
                UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
            )
            if keep_session_id is not None:
                statement = statement.where(UserSession.id != keep_session_id)
            result = await session.execute(statement.values(revoked_at=now))
        self._resolved.clear()
        return int(result.rowcount or 0)

    # -- Administration ---------------------------------------------------------

    async def list_users(self) -> list[UserSnapshot]:
        async with self._database.session() as session:
            rows = await session.scalars(
                select(UserAccount).order_by(UserAccount.created_at.asc())
            )
            return [UserSnapshot.of(row) for row in rows]

    async def create_user(
        self, *, email: str, display_name: str, password: str, role: UserRole
    ) -> UserSnapshot:
        password_hash = await self._hash(password)
        try:
            async with self._database.session() as session:
                account = UserAccount(
                    email=email,
                    display_name=display_name,
                    password_hash=password_hash,
                    role=role.value,
                    is_active=True,
                )
                session.add(account)
                await session.flush()
                snapshot = UserSnapshot.of(account)
        except IntegrityError as error:
            raise ConflictError(f"An operator account already uses {email}.") from error
        logger.info(
            "Operator account created", extra={"user_id": snapshot.id, "role": role.value}
        )
        return snapshot

    async def update_user(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> UserSnapshot:
        """Apply an administrator's change to an account.

        Raises:
            NotFoundError: No such account.
            ConflictError: The change would leave no active administrator - a
                deployment nobody can administer can only be recovered by hand.
        """
        async with self._database.session() as session:
            account = await session.get(UserAccount, user_id)
            if account is None:
                raise NotFoundError("That operator account does not exist.")

            removes_admin = account.role == UserRole.ADMIN.value and account.is_active and (
                (role is not None and role is not UserRole.ADMIN) or is_active is False
            )
            if removes_admin:
                active_admins = await session.scalar(
                    select(func.count())
                    .select_from(UserAccount)
                    .where(
                        UserAccount.role == UserRole.ADMIN.value,
                        UserAccount.is_active.is_(True),
                    )
                )
                if int(active_admins or 0) <= 1:
                    raise ConflictError(
                        "At least one active administrator must remain. Make another "
                        "operator an administrator first."
                    )

            if display_name is not None:
                account.display_name = display_name
            if role is not None:
                account.role = role.value
            if is_active is not None:
                account.is_active = is_active
                if not is_active:
                    await session.execute(
                        update(UserSession)
                        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
                        .values(revoked_at=datetime.now(UTC))
                    )
            await session.flush()
            snapshot = UserSnapshot.of(account)
        self._resolved.clear()
        return snapshot
