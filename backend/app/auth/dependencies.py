"""Who is making a request, and whether they may.

Resolved from the session cookie on every REST request, video stream and the
Command Center socket. With authentication disabled on a deployment, every
request is treated as the configured default operator with full rights - which
is exactly how the platform behaved before sign-in existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from ..core.config import Settings, get_settings
from ..core.constants import DEFAULT_OPERATOR_NAME
from ..core.exceptions import ForbiddenError, ServiceUnavailableError, UnauthorizedError
from ..models.auth import UserRole
from .service import AuthContext, AuthService

__all__ = [
    "AdminDep",
    "AuthServiceDep",
    "OperatorDep",
    "OptionalPrincipalDep",
    "Principal",
    "get_auth_service",
    "optional_principal",
    "require_admin",
    "require_operator",
]


@dataclass(frozen=True, slots=True)
class Principal:
    """The operator a request acts for."""

    user_id: str | None
    email: str | None
    display_name: str
    role: UserRole
    session_id: str | None
    authenticated: bool

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    @classmethod
    def of(cls, context: AuthContext) -> Principal:
        return cls(
            user_id=context.user.id,
            email=context.user.email,
            display_name=context.user.display_name,
            role=context.user.role,
            session_id=context.session_id,
            authenticated=True,
        )


#: Every request, on a deployment with sign-in switched off.
UNAUTHENTICATED_OPERATOR = Principal(
    user_id=None,
    email=None,
    display_name=DEFAULT_OPERATOR_NAME,
    role=UserRole.ADMIN,
    session_id=None,
    authenticated=False,
)


def _settings_of(connection: HTTPConnection) -> Settings:
    # Read directly rather than through app.api.deps: routes import this module,
    # and the api package importing its routes must not become a cycle.
    settings = getattr(connection.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


def get_auth_service(connection: HTTPConnection) -> AuthService:
    service = getattr(connection.app.state, "auth", None)
    if not isinstance(service, AuthService):
        raise ServiceUnavailableError("Operator accounts are not available yet.")
    return service


async def optional_principal(connection: HTTPConnection) -> Principal | None:
    """The signed-in operator, or ``None`` when there is no valid session."""
    settings = _settings_of(connection)
    if not settings.auth_enabled:
        return UNAUTHENTICATED_OPERATOR

    token = connection.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    context = await get_auth_service(connection).resolve_token(token)
    return Principal.of(context) if context is not None else None


async def require_operator(
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Principal:
    """Any signed-in operator."""
    if principal is None:
        raise UnauthorizedError()
    return principal


async def require_admin(
    principal: Annotated[Principal, Depends(require_operator)],
) -> Principal:
    """A signed-in administrator."""
    if not principal.is_admin:
        raise ForbiddenError()
    return principal


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
OptionalPrincipalDep = Annotated[Principal | None, Depends(optional_principal)]
OperatorDep = Annotated[Principal, Depends(require_operator)]
AdminDep = Annotated[Principal, Depends(require_admin)]
