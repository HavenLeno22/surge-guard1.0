"""System status and health schemas.

Backs the System Health panel (``06:872-896``) and the platform liveness probe.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import ComponentType, HealthStatus

__all__ = ["ComponentHealth", "SystemHealth", "SystemInfo"]


class ComponentHealth(BaseModel):
    """Health of one platform component."""

    model_config = ConfigDict(extra="forbid")

    component: ComponentType
    status: HealthStatus
    detail: str | None = Field(
        default=None,
        description="Why the component is not healthy, in operator-readable terms.",
    )
    last_seen: datetime | None = Field(
        default=None,
        description="When this component last reported. Used to detect silence.",
    )


class SystemHealth(BaseModel):
    """Health of every platform component (``07:282-298``)."""

    model_config = ConfigDict(extra="forbid")

    components: list[ComponentHealth]
    checked_at: datetime

    @property
    def is_healthy(self) -> bool:
        """Whether every component is healthy.

        Note that this is not the same as the platform being usable: graceful
        degradation means an unhealthy component leaves the rest operating
        (``04:121-127``).
        """
        return all(c.status is HealthStatus.HEALTHY for c in self.components)


class SystemInfo(BaseModel):
    """Platform identity and configuration summary.

    Displayed on the Welcome screen (``06:498-525``), used to confirm which
    build a demonstration is running, and the source of the identity the
    Command Center header and footer display.

    That last part matters more than it sounds. Those values were previously
    hardcoded in the interface *and* declared in backend configuration, with
    the frontend claiming in a comment to be sourced from the backend while
    actually carrying its own copy. One deployment-configured value with two
    definitions is a value that will eventually disagree with itself on screen.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    environment: str
    api_version: str = Field(description="API prefix in use, e.g. '/api/v1'.")
    analysis_fps: float = Field(description="Target AI analysis rate.")
    server_time: datetime

    operator_name: str = Field(
        description=(
            "The operator the Command Center is running for. The prototype "
            "opens directly into the Command Center without authentication "
            "(``07:429-433``), so this is configuration rather than a session - "
            "but it is configuration with exactly one definition."
        )
    )
    camera_id: str = Field(description="The camera this deployment watches.")
    camera_name: str
    camera_location: str = Field(
        description="Operator-facing location, e.g. 'Platform 3'."
    )
