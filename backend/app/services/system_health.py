"""System Health Service (``07:282-298``).

Reports the operational status of each platform component so the Command Center
can show whether the platform itself is working (``06:395-421``).

Health is tracked **in memory, not persisted**. The documented
``System Health Log`` entity (``08:291-305``) writes a row per poll to render
five status indicators - unbounded writes for no operational value, and a
single-row shape that cannot represent more than one camera. Only *transitions*
are worth recording, and those belong on the Crowd Event Timeline
(Architecture Review C13, Rejected Decision R4).

The design point here is the **probe registry**. A component's health is
answered by whoever owns that component, not by this service guessing. Phase 2
registers real probes for the camera and the AI Pipeline; until then those
components report OFFLINE, which is accurate - they are not running.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeAlias

from surgeguard_ai.contracts import ComponentType, HealthStatus

from ..core.logging import get_logger
from ..db.session import DatabaseManager
from ..schemas.system import ComponentHealth, SystemHealth

__all__ = ["HealthProbe", "SystemHealthService"]

logger = get_logger(__name__)

#: Answers the health of one component. Owned by that component's module.
HealthProbe: TypeAlias = Callable[[], Awaitable[ComponentHealth]]


class SystemHealthService:
    """Aggregates component health for the System Health panel."""

    def __init__(self, database: DatabaseManager) -> None:
        self._database = database
        self._probes: dict[ComponentType, HealthProbe] = {}

    # -- Registration -------------------------------------------------------

    def register_probe(self, component: ComponentType, probe: HealthProbe) -> None:
        """Register the health probe for a component.

        Replaces any existing probe for that component, so a module can update
        its own reporting without coordinating with this service.
        """
        self._probes[component] = probe
        logger.debug("Health probe registered", extra={"component": component.value})

    def unregister_probe(self, component: ComponentType) -> None:
        """Remove a probe. The component then reports OFFLINE."""
        self._probes.pop(component, None)

    # -- Reporting ----------------------------------------------------------

    async def check(self) -> SystemHealth:
        """Return the current health of every component.

        Never raises. A health check that fails must report a degraded platform,
        not become another failure (``04:121-127``).
        """
        checked_at = datetime.now(UTC)
        components = [
            await self._check_component(component) for component in ComponentType
        ]
        return SystemHealth(components=components, checked_at=checked_at)

    async def _check_component(self, component: ComponentType) -> ComponentHealth:
        """Resolve one component's health, preferring its registered probe."""
        probe = self._probes.get(component)
        if probe is not None:
            try:
                return await probe()
            except Exception as error:  # noqa: BLE001 - a broken probe is a warning
                logger.warning(
                    "Health probe failed",
                    exc_info=error,
                    extra={"component": component.value},
                )
                return ComponentHealth(
                    component=component,
                    status=HealthStatus.WARNING,
                    detail="Component health could not be determined.",
                )

        return await self._default_health(component)

    async def _default_health(self, component: ComponentType) -> ComponentHealth:
        """Health for components with no registered probe.

        The backend and the database can answer for themselves. Anything else
        without a probe is genuinely not running, and says so.
        """
        now = datetime.now(UTC)

        if component is ComponentType.BACKEND:
            return ComponentHealth(
                component=component,
                status=HealthStatus.HEALTHY,
                last_seen=now,
            )

        if component is ComponentType.DATABASE:
            reachable = await self._database.ping()
            return ComponentHealth(
                component=component,
                status=HealthStatus.HEALTHY if reachable else HealthStatus.OFFLINE,
                detail=None if reachable else "Database is not reachable.",
                last_seen=now if reachable else None,
            )

        if component is ComponentType.NETWORK:
            # Network health from the server's perspective is backend
            # reachability. Whether the *client* can reach the server is a
            # question only the client can answer, and the Command Center
            # answers it with its own connection state.
            return ComponentHealth(
                component=component,
                status=HealthStatus.HEALTHY,
                last_seen=now,
            )

        return ComponentHealth(
            component=component,
            status=HealthStatus.OFFLINE,
            detail="Not started.",
        )
