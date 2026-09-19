"""FastAPI dependency injection.

Every shared resource a route needs is resolved here, so handlers declare what
they need and never construct it. That is what makes a handler testable: a test
overrides the dependency instead of standing up the real component.

Long-lived components (the broadcaster, the health service) are created once at
startup and held on ``app.state``. This module reads them from the request
rather than holding module-level references, so tests that build a second
application do not collide with the first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from ..cameras.manager import CameraManager
from ..core.config import Settings, get_settings
from ..core.event_bus import EventBus, get_event_bus
from ..db.session import DatabaseManager, get_database
from ..hardware.service import HardwareAlertService
from ..realtime.broadcaster import Broadcaster
from ..realtime.connection_manager import ConnectionManager
from ..services.crowd_intelligence import CrowdIntelligenceService
from ..services.decision_service import DecisionService
from ..services.perception_state import PerceptionStateService
from ..services.queue_service import QueueService
from ..services.simulation_service import SimulationService
from ..services.site_service import SiteIntelligenceService
from ..services.system_health import SystemHealthService
from ..services.timeline_service import TimelineService
from ..streaming import LiveStreamService
from ..workers.perception_worker import PerceptionWorker

__all__ = [
    "SettingsDep",
    "SessionDep",
    "DatabaseDep",
    "EventBusDep",
    "BroadcasterDep",
    "CameraManagerDep",
    "HardwareAlertsDep",
    "ConnectionManagerDep",
    "CrowdIntelligenceDep",
    "DecisionServiceDep",
    "LiveStreamDep",
    "PerceptionStateDep",
    "PerceptionWorkerDep",
    "QueueServiceDep",
    "SimulationServiceDep",
    "SiteIntelligenceDep",
    "SystemHealthDep",
    "TimelineServiceDep",
]


def _from_state(connection: HTTPConnection, attribute: str) -> object:
    """Read a startup-created component from application state.

    Takes :class:`HTTPConnection` rather than ``Request``. It is the common base
    of both ``Request`` and ``WebSocket``, so one dependency serves REST handlers
    and the Command Center socket alike - a ``Request`` annotation cannot be
    resolved for a WebSocket route.
    """
    component = getattr(connection.app.state, attribute, None)
    if component is None:
        raise RuntimeError(
            f"Application state is missing {attribute!r}. "
            "This component is created during startup; the application was not "
            "initialised through its lifespan."
        )
    return component


def get_app_settings(connection: HTTPConnection) -> Settings:
    """The settings this application was built with.

    Read from application state rather than the process-wide cache, so an
    application built with its own settings - every test builds one - is
    answered with those settings and not whatever the environment holds.
    """
    settings = getattr(connection.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


def get_app_database(connection: HTTPConnection) -> DatabaseManager:
    """The database this application connected to at startup."""
    database = getattr(connection.app.state, "database", None)
    return database if isinstance(database, DatabaseManager) else get_database()


async def get_app_session(connection: HTTPConnection) -> AsyncIterator[AsyncSession]:
    """A request-scoped session on the application's own database.

    Committed when the handler returns normally, rolled back if it raises.
    """
    async with get_app_database(connection).session() as session:
        yield session


def get_broadcaster(connection: HTTPConnection) -> Broadcaster:
    """Return the application's broadcaster."""
    return _from_state(connection, "broadcaster")  # type: ignore[return-value]


def get_connection_manager(connection: HTTPConnection) -> ConnectionManager:
    """Return the application's WebSocket connection manager."""
    return _from_state(connection, "connections")  # type: ignore[return-value]


def get_system_health_service(connection: HTTPConnection) -> SystemHealthService:
    """Return the application's system health service."""
    return _from_state(connection, "system_health")  # type: ignore[return-value]


def get_perception_state(connection: HTTPConnection) -> PerceptionStateService:
    """Return the application's perception state.

    Present even when the pipeline is disabled - it simply reports that nothing
    has been received, which is what a caller needs to know.
    """
    return _from_state(connection, "perception_state")  # type: ignore[return-value]


def get_crowd_intelligence(connection: HTTPConnection) -> CrowdIntelligenceService:
    """Return the application's crowd intelligence service.

    Present even when crowd analysis is disabled - it then reports that nothing
    has been assessed and says why, which is what a caller needs in order to
    distinguish a disabled analyser from a starting one.
    """
    return _from_state(connection, "crowd_intelligence")  # type: ignore[return-value]


def get_decision_service(connection: HTTPConnection) -> DecisionService:
    """Return the application's decision service.

    Present even when the Operational Decision Engine is disabled - it then
    reports that no guidance exists, which is what a caller needs in order to
    distinguish a disabled engine from a quiet one.
    """
    return _from_state(connection, "decisions")  # type: ignore[return-value]


def get_live_stream(connection: HTTPConnection) -> LiveStreamService:
    """Return the application's live video stream."""
    return _from_state(connection, "live_stream")  # type: ignore[return-value]


def get_timeline_service(connection: HTTPConnection) -> TimelineService:
    """Return the application's Crowd Event Timeline."""
    return _from_state(connection, "timeline")  # type: ignore[return-value]


def get_queue_service(connection: HTTPConnection) -> QueueService:
    """Return the application's Queue Intelligence service.

    Present even when Queue Intelligence is disabled - it then reports that
    it is not running and says why, which is what a caller needs in order to
    distinguish a disabled analyser from an unconfigured camera.
    """
    return _from_state(connection, "queue_service")  # type: ignore[return-value]


def get_simulation_service(connection: HTTPConnection) -> SimulationService:
    """Return the application's simulation service.

    Held separately from every live service, so a simulated surge can never
    reach a record the platform presents as observed.
    """
    return _from_state(connection, "simulation")  # type: ignore[return-value]


def get_camera_manager(connection: HTTPConnection) -> CameraManager:
    """Return the application's camera manager - every camera, the primary included."""
    return _from_state(connection, "camera_manager")  # type: ignore[return-value]


def get_hardware_alerts(connection: HTTPConnection) -> HardwareAlertService:
    """Return the service driving the alert hardware (present even when disabled)."""
    return _from_state(connection, "hardware_alerts")  # type: ignore[return-value]


def get_site_intelligence(connection: HTTPConnection) -> SiteIntelligenceService:
    """Return the service combining every camera into site intelligence."""
    return _from_state(connection, "site_intelligence")  # type: ignore[return-value]


def get_perception_worker(connection: HTTPConnection) -> PerceptionWorker:
    """Return the application's perception worker.

    Injected rather than reached for so that a route can be tested against a
    worker in any state without a camera or a GPU present.
    """
    return _from_state(connection, "perception_worker")  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Annotated aliases
#
# Handlers declare `settings: SettingsDep` rather than repeating
# `Depends(get_settings)` at every call site.
# ---------------------------------------------------------------------------

SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_app_session)]
DatabaseDep = Annotated[DatabaseManager, Depends(get_app_database)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
BroadcasterDep = Annotated[Broadcaster, Depends(get_broadcaster)]
ConnectionManagerDep = Annotated[ConnectionManager, Depends(get_connection_manager)]
SystemHealthDep = Annotated[SystemHealthService, Depends(get_system_health_service)]
PerceptionStateDep = Annotated[PerceptionStateService, Depends(get_perception_state)]
PerceptionWorkerDep = Annotated[PerceptionWorker, Depends(get_perception_worker)]
CameraManagerDep = Annotated[CameraManager, Depends(get_camera_manager)]
HardwareAlertsDep = Annotated[HardwareAlertService, Depends(get_hardware_alerts)]
CrowdIntelligenceDep = Annotated[
    CrowdIntelligenceService, Depends(get_crowd_intelligence)
]
DecisionServiceDep = Annotated[DecisionService, Depends(get_decision_service)]
TimelineServiceDep = Annotated[TimelineService, Depends(get_timeline_service)]
LiveStreamDep = Annotated[LiveStreamService, Depends(get_live_stream)]
QueueServiceDep = Annotated[QueueService, Depends(get_queue_service)]
SimulationServiceDep = Annotated[SimulationService, Depends(get_simulation_service)]
SiteIntelligenceDep = Annotated[SiteIntelligenceService, Depends(get_site_intelligence)]
