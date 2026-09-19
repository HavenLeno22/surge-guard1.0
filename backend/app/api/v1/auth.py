"""Sign-in, sign-out and the signed-in operator's own account.

``/status`` is public and always answers: it is how the interface decides
whether to show first-run setup, the sign-in page or the Command Center. Every
other route here either creates a session or acts on the session making the
request.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ...auth.dependencies import (
    AuthServiceDep,
    OperatorDep,
    OptionalPrincipalDep,
    Principal,
)
from ...auth.service import SessionSnapshot, UserSnapshot
from ...core.config import Settings
from ...core.exceptions import (
    ConflictError,
    InvalidCredentialsError,
    TooManyAttemptsError,
    UnauthorizedError,
)
from ...core.logging import get_logger
from ...schemas.auth import (
    AuthStatusRead,
    LoginWrite,
    PasswordChangeWrite,
    ProfileWrite,
    SessionRead,
    SetupWrite,
    UserRead,
)
from ...schemas.common import ApiResponse
from ..deps import ConnectionManagerDep, SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


def to_user_read(user: UserSnapshot) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _session_read(session: SessionSnapshot, current_id: str | None) -> SessionRead:
    return SessionRead(
        id=session.id,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        expires_at=session.expires_at,
        user_agent=session.user_agent,
        ip_address=session.ip_address,
        current=session.id == current_id,
    )


def _client_address(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=int(settings.session_ttl_hours * 3600),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _require_enabled(settings: Settings) -> None:
    if not settings.auth_enabled:
        raise ConflictError(
            "Sign-in is switched off on this deployment (SURGEGUARD_AUTH_ENABLED=false)."
        )


@router.get(
    "/status",
    response_model=ApiResponse[AuthStatusRead],
    summary="Whether sign-in is required, set up, and who is signed in",
)
async def get_auth_status(
    settings: SettingsDep, principal: OptionalPrincipalDep, request: Request
) -> ApiResponse[AuthStatusRead]:
    if not settings.auth_enabled:
        return ApiResponse.ok(
            AuthStatusRead(auth_enabled=False, setup_required=False, user=None),
            message="Sign-in is not required on this deployment.",
        )

    auth = request.app.state.auth
    setup_required = await auth.setup_required()
    user = await auth.get_user(principal.user_id) if principal and principal.user_id else None
    return ApiResponse.ok(
        AuthStatusRead(
            auth_enabled=True,
            setup_required=setup_required,
            user=to_user_read(user) if user is not None else None,
        ),
        message="Sign-in status retrieved.",
    )


@router.post(
    "/setup",
    response_model=ApiResponse[UserRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create the first administrator account",
)
async def complete_setup(
    body: SetupWrite,
    request: Request,
    response: Response,
    settings: SettingsDep,
    auth: AuthServiceDep,
) -> ApiResponse[UserRead]:
    """Only while the deployment has no account at all; 409 afterwards."""
    _require_enabled(settings)
    user = await auth.create_first_admin(
        email=body.email, display_name=body.display_name, password=body.password
    )
    token = await auth.start_session(
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_address(request),
    )
    _set_session_cookie(response, settings, token)
    return ApiResponse.ok(
        to_user_read(user), message="Administrator account created. You are signed in."
    )


@router.post("/login", response_model=ApiResponse[UserRead], summary="Sign in")
async def login(
    body: LoginWrite,
    request: Request,
    response: Response,
    settings: SettingsDep,
    auth: AuthServiceDep,
) -> ApiResponse[UserRead]:
    _require_enabled(settings)
    limiter = request.app.state.login_limiter
    key = f"{_client_address(request) or '-'}|{body.email}"

    wait = limiter.check(key)
    if wait is not None:
        raise TooManyAttemptsError(wait)

    try:
        user = await auth.authenticate(body.email, body.password)
    except InvalidCredentialsError:
        limiter.record_failure(key)
        logger.info("Sign-in failed", extra={"client": _client_address(request)})
        raise

    limiter.reset(key)
    token = await auth.start_session(
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_address(request),
    )
    _set_session_cookie(response, settings, token)
    logger.info("Operator signed in", extra={"user_id": user.id})
    return ApiResponse.ok(to_user_read(user), message=f"Signed in as {user.display_name}.")


@router.post("/logout", response_model=ApiResponse[None], summary="Sign out")
async def logout(
    request: Request,
    response: Response,
    settings: SettingsDep,
    connections: ConnectionManagerDep,
) -> ApiResponse[None]:
    """Always succeeds - signing out twice is not an error worth showing anyone."""
    token = request.cookies.get(settings.session_cookie_name)
    if token and settings.auth_enabled:
        session_id = await request.app.state.auth.revoke_token(token)
        if session_id is not None:
            await connections.disconnect_session(session_id)
    _clear_session_cookie(response, settings)
    return ApiResponse.ok(None, message="Signed out.")


@router.get("/me", response_model=ApiResponse[UserRead], summary="The signed-in operator")
async def get_me(principal: OperatorDep, auth: AuthServiceDep) -> ApiResponse[UserRead]:
    user = await _own_account(principal, auth)
    return ApiResponse.ok(to_user_read(user), message="Operator account retrieved.")


@router.patch("/me", response_model=ApiResponse[UserRead], summary="Update your name")
async def update_me(
    body: ProfileWrite, principal: OperatorDep, auth: AuthServiceDep
) -> ApiResponse[UserRead]:
    user_id = _own_id(principal)
    user = await auth.update_profile(user_id, display_name=body.display_name)
    return ApiResponse.ok(to_user_read(user), message="Name updated.")


@router.post(
    "/me/password",
    response_model=ApiResponse[None],
    summary="Change your password and sign out everywhere else",
)
async def change_password(
    body: PasswordChangeWrite,
    principal: OperatorDep,
    auth: AuthServiceDep,
    connections: ConnectionManagerDep,
) -> ApiResponse[None]:
    user_id = _own_id(principal)
    others = await auth.list_sessions(user_id)
    revoked = await auth.change_password(
        user_id,
        current_password=body.current_password,
        new_password=body.new_password,
        keep_session_id=principal.session_id,
    )
    for session in others:
        if session.id != principal.session_id:
            await connections.disconnect_session(session.id)
    detail = f" {revoked} other session(s) signed out." if revoked else ""
    return ApiResponse.ok(None, message=f"Password changed.{detail}")


@router.get(
    "/sessions",
    response_model=ApiResponse[list[SessionRead]],
    summary="Where you are signed in",
)
async def list_sessions(
    principal: OperatorDep, auth: AuthServiceDep
) -> ApiResponse[list[SessionRead]]:
    sessions = await auth.list_sessions(_own_id(principal))
    return ApiResponse.ok(
        [_session_read(session, principal.session_id) for session in sessions],
        message="Active sessions retrieved.",
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=ApiResponse[None],
    summary="Sign out one of your sessions",
)
async def revoke_session(
    session_id: str,
    principal: OperatorDep,
    auth: AuthServiceDep,
    connections: ConnectionManagerDep,
) -> ApiResponse[None]:
    await auth.revoke_session(session_id, user_id=_own_id(principal))
    await connections.disconnect_session(session_id)
    return ApiResponse.ok(None, message="Session signed out.")


def _own_id(principal: Principal) -> str:
    if principal.user_id is None:
        raise ConflictError(
            "There is no operator account to change: sign-in is switched off on this deployment."
        )
    return principal.user_id


async def _own_account(principal: Principal, auth: AuthServiceDep) -> UserSnapshot:
    user = await auth.get_user(_own_id(principal))
    if user is None:
        raise UnauthorizedError()
    return user
