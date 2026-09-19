"""Component health is pushed when, and only when, it changes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from surgeguard_ai.contracts import ComponentType, HealthStatus

from app.core.event_bus import EventBus
from app.realtime.envelope import WSEventType
from app.realtime.publisher import RealtimePublisher
from app.schemas.system import ComponentHealth, SystemHealth
from app.services.perception_state import PerceptionStateService


class FakeBroadcaster:
    def __init__(self) -> None:
        self.sent: list[tuple[WSEventType, dict[str, Any], str | None]] = []

    @property
    def client_count(self) -> int:
        return 1

    async def publish(
        self, event_type: WSEventType, data: dict[str, Any], camera_id: str | None = None
    ) -> None:
        self.sent.append((event_type, data, camera_id))


class ChangingHealth:
    """Healthy for two checks, then the camera goes offline and stays offline."""

    def __init__(self) -> None:
        self.checks = 0

    async def check(self) -> SystemHealth:
        self.checks += 1
        camera = HealthStatus.HEALTHY if self.checks <= 2 else HealthStatus.OFFLINE
        return SystemHealth(
            components=[
                ComponentHealth(component=ComponentType.CAMERA, status=camera),
                ComponentHealth(component=ComponentType.DATABASE, status=HealthStatus.HEALTHY),
            ],
            checked_at=datetime.now(UTC),
        )


class FakeWorker:
    camera_id = "cam-01"


async def test_health_is_pushed_once_per_change() -> None:
    broadcaster = FakeBroadcaster()
    health = ChangingHealth()
    publisher = RealtimePublisher(
        broadcaster,  # type: ignore[arg-type]
        EventBus(),
        perception_state=PerceptionStateService(),
        worker=FakeWorker(),  # type: ignore[arg-type]
        health=health,  # type: ignore[arg-type]
        health_interval_seconds=0.01,
    )
    publisher.start()
    try:
        for _ in range(200):
            if health.checks >= 6:
                break
            await asyncio.sleep(0.01)
    finally:
        publisher.stop()

    pushes = [data for event, data, _ in broadcaster.sent if event is WSEventType.HEALTH_UPDATED]
    assert len(pushes) == 2  # the first state, then the camera going offline
    assert pushes[1]["components"][0]["status"] == "OFFLINE"
