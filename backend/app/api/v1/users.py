"""Operator account administration. Administrators only.

Accounts are deactivated rather than deleted, so every timeline entry keeps the
name of the operator who caused it.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from ...auth.dependencies import AdminDep, AuthServiceDep
from ...core.exceptions import ConflictError
from ...schemas.auth import UserCreateWrite, UserRead, UserUpdateWrite
from ...schemas.common import ApiResponse
from ..deps import ConnectionManagerDep
from .auth import to_user_read

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=ApiResponse[list[UserRead]], summary="Every operator account")
async def list_users(_: AdminDep, auth: AuthServiceDep) -> ApiResponse[list[UserRead]]:
    users = await auth.list_users()
    return ApiResponse.ok([to_user_read(user) for user in users], message="Operators retrieved.")


@router.post(
    "",
    response_model=ApiResponse[UserRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create an operator account",
)
async def create_user(
    body: UserCreateWrite, _: AdminDep, auth: AuthServiceDep
) -> ApiResponse[UserRead]:
    user = await auth.create_user(
        email=body.email, display_name=body.display_name, password=body.password, role=body.role
    )
    return ApiResponse.ok(to_user_read(user), message=f"Account created for {user.display_name}.")


@router.patch(
    "/{user_id}", response_model=ApiResponse[UserRead], summary="Change an operator account"
)
async def update_user(
    user_id: str,
    body: UserUpdateWrite,
    admin: AdminDep,
    auth: AuthServiceDep,
    connections: ConnectionManagerDep,
) -> ApiResponse[UserRead]:
    if user_id == admin.user_id and body.is_active is False:
        raise ConflictError("You cannot deactivate your own account.")

    sessions = await auth.list_sessions(user_id) if body.is_active is False else []
    user = await auth.update_user(
        user_id, display_name=body.display_name, role=body.role, is_active=body.is_active
    )
    for session in sessions:
        await connections.disconnect_session(session.id)
    return ApiResponse.ok(to_user_read(user), message=f"{user.display_name} updated.")
