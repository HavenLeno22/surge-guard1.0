"""SurgeGuard Backend application factory.

Composition root: the one place that knows how every component fits together.
Nothing else constructs a broadcaster, opens the database, or wires the event
bus - which is why every other module can be tested in isolation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from surgeguard_ai.contracts import ComponentType

from .api import api_router, register_exception_handlers, websocket_router
from .auth.rate_limit import LoginRateLimiter
from .auth.service import AuthService
from .cameras.manager import CameraManager
from .cameras.registry import CameraRegistry
from .cameras.topology_store import TopologyStore
from .core.config import Settings, get_settings
from .core.event_bus import get_event_bus
from .core.logging import configure_logging, get_logger
from .db.migrate import run_migrations
from .db.session import DatabaseManager
from .hardware.readings import manager_readings
from .hardware.serial_transport import PySerialTransport
from .hardware.service import HardwareAlertService
from .realtime.broadcaster import Broadcaster
from .realtime.connection_manager import ConnectionManager
from .realtime.publisher import RealtimePublisher
from .realtime.snapshot import SnapshotBuilder
from .services.history_query import HistoryQuery
from .services.history_recorder import HistoryRecorder
from .services.perception_health import build_camera_probe, build_pipeline_probe
from .services.simulation_service import SimulationService
from .services.site_service import SiteIntelligenceService
from .services.system_health import SystemHealthService
from .services.timeline_service import TimelineService
from .web import mount_frontend
from .workers.perception_factory import (
    build_allocation_config,
    build_forecast_config,
)

__all__ = ["create_app", "app"]

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start and stop long-lived components.

    Startup order matters: the database is connected before anything that might
    query it, and the broadcaster starts before any client can connect.
    Shutdown reverses that order.
    """
    settings: Settings = app.state.settings

    logger.info(
        "Starting %s v%s",
        settings.app_name,
        settings.app_version,
        extra={
            "environment": settings.environment.value,
            "analysis_fps": settings.analysis_fps,
        },
    )

    # The database this application was configured with - not the process-wide
    # default - so an application built with its own settings, as every test
    # builds one, can never write to another deployment's data.
    if settings.database_auto_migrate:
        try:
            await run_migrations(settings.database_url)
        except Exception:
            logger.exception(
                "The database schema could not be brought up to date. Check "
                "SURGEGUARD_DATABASE_URL, or run `alembic upgrade head` from backend/."
            )
            raise

    database = DatabaseManager(settings)
    database.connect()
    app.state.database = database

    # -- Operators ------------------------------------------------------------
    #
    # Accounts and sessions live in the database; the sign-in limiter lives in
    # memory, so a restart never locks out the person restarting.
    app.state.auth = AuthService(database, settings)
    app.state.login_limiter = LoginRateLimiter(
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_lockout_seconds,
    )
    if not settings.auth_enabled:
        logger.warning(
            "Sign-in is disabled (SURGEGUARD_AUTH_ENABLED=false): anyone who can reach "
            "this address can operate the platform."
        )

    app.state.event_bus = get_event_bus()

    connections = ConnectionManager()
    app.state.connections = connections

    broadcaster = Broadcaster(connections, settings)
    await broadcaster.start()
    app.state.broadcaster = broadcaster

    health = SystemHealthService(database)
    app.state.system_health = health

    timeline = TimelineService(limit=settings.timeline_limit)
    app.state.timeline = timeline

    # -- Cameras --------------------------------------------------------------
    #
    # Every camera - the primary one included - is a runtime owned by the camera
    # manager: its own perception worker and model, perception state, analysis
    # pipeline, queue and decision services and live video. The runtimes share
    # the event bus, and each one's handlers ignore other cameras' output, so an
    # analysis pipeline is never fed two crowds.
    #
    # The primary camera's services are also published under the names the
    # single-camera routes have always used, so those routes, and every client
    # of them, keep describing exactly what they described before.

    registry = CameraRegistry(
        settings.camera_registry_path,
        seeds=settings.camera_seeds,
        primary_camera_id=settings.camera_id,
    )
    topology = TopologyStore(settings.topology_path)
    manager = CameraManager(settings, app.state.event_bus, registry, topology, timeline)
    app.state.camera_manager = manager

    primary = manager.primary
    app.state.perception_state = primary.perception_state
    app.state.perception_sink = primary.sink
    app.state.zone_store = primary.zone_store
    app.state.crowd_intelligence = primary.intelligence
    app.state.queue_service = primary.queue_service
    app.state.decisions = primary.decisions
    app.state.live_stream = primary.live_stream
    app.state.perception_worker = primary.worker

    # -- Simulation Mode ----------------------------------------------------
    #
    # Runs what-if scenarios through the *production* forecast and allocation
    # engines, so a simulation is evidence about the real system rather than a
    # separate demonstration of nothing. Its state is held here, apart from
    # every live service, so simulated figures can never reach a live record.

    app.state.simulation = SimulationService(
        forecast_config=build_forecast_config(settings),
        allocation_config=build_allocation_config(settings),
    )

    # -- Realtime -----------------------------------------------------------
    #
    # The one place domain events become WebSocket messages. Services publish
    # events and never touch a socket; this subscribes and decides what reaches
    # the operator, in what shape and how often.

    publisher = RealtimePublisher(
        broadcaster,
        app.state.event_bus,
        perception_state=primary.perception_state,
        worker=primary.worker,
        assessment_min_interval_seconds=settings.ws_assessment_min_interval_seconds,
        manager=manager,
        health=health,
    )
    publisher.start()
    app.state.realtime_publisher = publisher

    # -- Site intelligence ----------------------------------------------------
    #
    # Every camera combined, once a second: a count that does not double-count
    # overlapping views, pooled queues and their forecast, the hotspot, the flow
    # map and alerts with their evidence. Built from the cameras' own analysis,
    # so it has nothing to say on a deployment where the pipeline never runs.

    site = SiteIntelligenceService(settings, manager, app.state.event_bus, timeline)
    app.state.site_intelligence = site

    # -- History ----------------------------------------------------------------
    #
    # Every camera's analysis and every site update, folded into buckets and
    # written as aggregates - never frames. Subscribed before any camera starts,
    # so the first window is recorded.
    history = HistoryRecorder(settings, database, app.state.event_bus)
    history.start()
    app.state.history_recorder = history
    app.state.history_query = HistoryQuery(database, settings)

    # -- Alert hardware -----------------------------------------------------------
    #
    # The Arduino RGB LED and buzzer follow the most urgent priority any camera's
    # Decision Engine reports: woken by each report, reconciled every second, and
    # resent as a keepalive. Created even when disabled, so the API can say so.
    hardware = HardwareAlertService(
        transport_factory=lambda: PySerialTransport(
            settings.hardware_serial_port, settings.hardware_baud_rate
        ),
        readings=lambda: manager_readings(manager),
        event_bus=app.state.event_bus,
        enabled=settings.hardware_enabled,
        keepalive_seconds=settings.hardware_keepalive_seconds,
        reconnect_seconds=settings.hardware_reconnect_seconds,
    )
    await hardware.start()
    app.state.hardware_alerts = hardware

    # Registered after the cameras exist, because a snapshot reports what each
    # pipeline is doing as well as what it has seen.
    connections.set_snapshot_provider(
        SnapshotBuilder(
            settings=settings,
            health=health,
            worker=primary.worker,
            perception=primary.perception_state,
            intelligence=primary.intelligence,
            decisions=primary.decisions,
            timeline=timeline,
            manager=manager,
            site_provider=lambda: site.latest,
        ).build
    )

    # The cameras and the AI Pipeline can now answer for themselves. Until these
    # are registered the health service reports both as OFFLINE, which was
    # accurate while nothing was running and would be a lie once something is.
    health.register_probe(ComponentType.AI_PIPELINE, build_pipeline_probe(manager))
    health.register_probe(ComponentType.CAMERA, build_camera_probe(manager))

    # Returns as soon as each camera's supervision task is scheduled. Loading
    # model weights takes seconds, and the API must answer throughout.
    await manager.start()
    if settings.pipeline_enabled:
        site.start()

    primary.decisions.record_system(
        "Monitoring session started",
        f"{settings.app_name} v{settings.app_version} in {settings.environment.value}, "
        f"{len(manager.runtimes())} camera(s) configured.",
    )

    logger.info("Startup complete")

    try:
        yield
    finally:
        logger.info("Shutting down")

        # The publisher first, so nothing is broadcast about cameras mid-stop;
        # then the cameras, which are the only thing still producing work for
        # everything below them. Stopping a camera detaches its handlers before
        # the bus drains, so a result already in flight cannot be analysed
        # against state that is about to be discarded.
        publisher.stop()
        # Before the cameras stop: the hardware is left showing NO_DATA, not the
        # last level a camera that is about to stop reported.
        await hardware.stop()
        await site.stop()
        await manager.stop()

        await broadcaster.stop()
        await app.state.event_bus.drain()
        # After the bus drains, so the last windows are in their buckets; before
        # the database closes, so those buckets can be written.
        await history.stop()
        await database.disconnect()

        logger.info("Shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Configuration override. Tests supply their own; production
            reads the environment.

    Returns:
        A configured application.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered Crowd Intelligence and Decision Support Platform. "
            "Transforms live CCTV footage into operational intelligence that "
            "helps authorities prevent crowd-related incidents."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Available to the lifespan handler, which runs before any dependency.
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(api_router)
    app.include_router(websocket_router)

    # Last, so it can never shadow an API or socket route.
    mount_frontend(app, settings.frontend_dist_dir)

    return app


#: Module-level application for ``uvicorn app.main:app``.
app = create_app()
