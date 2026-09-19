"""Shared pytest fixtures for the SurgeGuard backend test suite."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from surgeguard_ai.contracts import (
    BoundingBox,
    Detection,
    DetectionResult,
    PerceptionResult,
    SourceMode,
    Track,
    TrackingResult,
)

from app.core.config import Environment, Settings
from app.core.event_bus import EventBus
from app.main import create_app
from app.services.perception_state import PerceptionStateService


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Test configuration using a throwaway database.

    Each test gets its own SQLite file under pytest's temporary directory, so
    tests cannot see each other's data and none of them touch the development
    database.

    The perception pipeline is **disabled**. The backend must be testable
    without a camera, a GPU or model weights - and a suite that silently
    required them would pass on one machine and hang on every other. Worker
    behaviour is tested against doubles instead.
    """
    return Settings(
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        log_level="WARNING",
        ws_heartbeat_seconds=3600.0,  # effectively disabled during tests
        pipeline_enabled=False,
        # Operator camera edits and zone links go to the test's own directory,
        # never to the repository's data/ - a test adding a camera must not
        # leave one behind for the next run, or for a real deployment.
        camera_registry_path=tmp_path / "cameras.json",
        topology_path=tmp_path / "topology.json",
        zones_dir=tmp_path / "zones",
        # The API alone: a built interface in the working tree must not change
        # what these tests see.
        frontend_dist_dir=tmp_path / "no-frontend",
        # These tests are about the platform's behaviour, not about who may use
        # it; sign-in has its own suite, built on `auth_settings`.
        auth_enabled=False,
        auth_password_iterations=1_000,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """An application instance built with test settings.

    Note this does not run the lifespan - use :func:`client` for anything
    needing startup-created components.
    """
    return create_app(settings)


@pytest.fixture
def auth_settings(settings: Settings) -> Settings:
    """Test settings with operator sign-in switched on, as a deployment has it."""
    return settings.model_copy(update={"auth_enabled": True})


@pytest.fixture
def auth_app(auth_settings: Settings) -> FastAPI:
    return create_app(auth_settings)


@pytest.fixture
async def auth_client(auth_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client against an application that requires sign-in.

    Keeps cookies between requests, as a browser does, so a test signs in once
    and is then signed in.
    """
    from asgi_lifespan import LifespanManager  # noqa: PLC0415 - optional dependency

    async with LifespanManager(auth_app):
        transport = ASGITransport(app=auth_app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client with the application's lifespan run.

    Requests go straight to the ASGI application; no socket is opened and no
    port is bound.
    """
    from asgi_lifespan import LifespanManager  # noqa: PLC0415 - optional dependency

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
def event_bus() -> Iterator[EventBus]:
    """A fresh event bus, cleared after the test."""
    bus = EventBus()
    yield bus
    bus.clear()


@pytest.fixture
def perception_state() -> PerceptionStateService:
    """An empty perception state."""
    return PerceptionStateService()


def make_perception_result(
    *,
    frame_seq: int = 0,
    person_count: int = 2,
    camera_id: str = "cam-01",
    source_mode: SourceMode = SourceMode.LIVE,
    frame_ts: datetime | None = None,
    degraded: bool = False,
    inference_ms: float | None = 12.5,
    achieved_fps: float = 20.0,
) -> PerceptionResult:
    """Build a perception result of the shape the AI Pipeline emits.

    Constructed by hand rather than by running the pipeline: these tests are
    about what the backend does with a result, and running a model to obtain one
    would make them slow, hardware-dependent and no more truthful.
    """
    timestamp = frame_ts or datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    detections = tuple(
        Detection(
            bbox=BoundingBox(x1=index * 50.0, y1=100.0, x2=index * 50.0 + 40.0, y2=300.0),
            confidence=0.9,
        )
        for index in range(person_count)
    )
    tracks = tuple(
        Track(
            track_id=index + 1,
            bbox=detection.bbox,
            confidence=detection.confidence,
            age_frames=frame_seq + 1,
            foot_point=detection.bbox.foot_point,
        )
        for index, detection in enumerate(detections)
    )

    return PerceptionResult(
        camera_id=camera_id,
        source_mode=source_mode,
        frame_seq=frame_seq,
        frame_ts=timestamp,
        produced_at=timestamp,
        person_count=person_count,
        detections=DetectionResult(
            frame_seq=frame_seq,
            frame_ts=timestamp,
            detections=detections,
            inference_ms=inference_ms,
        ),
        tracking=TrackingResult(
            frame_seq=frame_seq,
            frame_ts=timestamp,
            tracks=tracks,
        ),
        inference_ms=inference_ms,
        processing_ms=(inference_ms or 0.0) + 2.0,
        achieved_fps=achieved_fps,
        degraded=degraded,
        degraded_reason="Detection unavailable: synthetic" if degraded else None,
    )
