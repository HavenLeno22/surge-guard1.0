"""System information and health endpoints.

``GET /api/v1/system-health`` is documented at ``09:166-170``. The remaining
routes here are operational: they let a deployment confirm what it is running
and whether it is alive.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status

from ...auth.dependencies import OperatorDep, require_operator
from ...core.constants import API_V1_PREFIX
from ...schemas.common import ApiResponse
from ...schemas.system import SystemHealth, SystemInfo
from ..deps import DatabaseDep, SettingsDep, SystemHealthDep

router = APIRouter(tags=["system"])


@router.get(
    "/system-health",
    response_model=ApiResponse[SystemHealth],
    summary="Retrieve current platform health",
    dependencies=[Depends(require_operator)],
)
async def get_system_health(health_service: SystemHealthDep) -> ApiResponse[SystemHealth]:
    """Return the operational status of every platform component.

    Always returns 200, even when components are unhealthy. Degraded components
    are data for the Command Center to display, not a failed request - the panel
    exists precisely to show that something is wrong (``06:395-421``).
    """
    health = await health_service.check()
    return ApiResponse.ok(data=health, message="System health retrieved")


@router.get(
    "/system-info",
    response_model=ApiResponse[SystemInfo],
    summary="Retrieve platform identity and configuration",
)
async def get_system_info(settings: SettingsDep, principal: OperatorDep) -> ApiResponse[SystemInfo]:
    """Return platform identity and key configuration.

    Shown on the Welcome screen (``06:498-525``) and used to confirm which build
    and configuration a demonstration is running. ``operator_name`` is the
    signed-in operator; with sign-in switched off it is the configured default,
    exactly as before.
    """
    info = SystemInfo(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment.value,
        api_version=API_V1_PREFIX,
        analysis_fps=settings.analysis_fps,
        server_time=datetime.now(UTC),
        operator_name=principal.display_name,
        camera_id=settings.camera_id,
        camera_name=settings.camera_name,
        camera_location=settings.camera_location,
    )
    return ApiResponse.ok(data=info, message="System information retrieved")


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def liveness() -> dict[str, str]:
    """Whether the process is running.

    Deliberately checks nothing else: a liveness probe that fails when a
    dependency is down causes the process to be restarted for a problem a
    restart cannot fix.
    """
    return {"status": "alive"}


@router.get(
    "/health/ready",
    summary="Readiness probe",
)
async def readiness(database: DatabaseDep) -> dict[str, object]:
    """Whether the platform is ready to serve requests.

    Unlike liveness, this does check dependencies - a process that cannot reach
    its database should not receive traffic.
    """
    database_ready = await database.ping()
    return {
        "status": "ready" if database_ready else "degraded",
        "database": database_ready,
    }
