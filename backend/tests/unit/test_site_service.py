"""Site alerts on the timeline - transitions only, and only once they persist."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from surgeguard_ai.contracts import (
    CameraConnectionStatus,
    CameraRole,
    Severity,
    TimelineEntryType,
)

from app.cameras.definitions import CameraDefinition, CameraOrigin, UrlSource
from app.core.config import Settings
from app.core.event_bus import EventBus
from app.services.site_service import SITE_TIMELINE_ID, SiteIntelligenceService
from app.services.timeline_service import TimelineService

START = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


class _Camera:
    """Just enough of a camera runtime for the site service to observe."""

    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.enabled = True
        self.status = CameraConnectionStatus.OFFLINE
        self.intelligence = SimpleNamespace(snapshot=lambda now=None: None)
        self.zone_store = SimpleNamespace(zones=())

    @property
    def definition(self) -> CameraDefinition:
        return CameraDefinition(
            camera_id=self.camera_id,
            name="Team Camera",
            location="",
            role=CameraRole.QUEUE,
            stream_url="http://192.0.2.10:4747/video",
            url_source=UrlSource.ENVIRONMENT,
            demo_video_path=None,
            enabled=self.enabled,
            coverage_area=None,
            origin=CameraOrigin.ENVIRONMENT,
            is_primary=False,
            order=2,
        )

    def snapshot(self, *, now: datetime | None = None) -> SimpleNamespace:
        return SimpleNamespace(status=self.status, detail="No frame for 22s.")


class _Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _service(settings: Settings, camera: _Camera, clock: _Clock, timeline: TimelineService):
    manager = SimpleNamespace(
        runtimes=lambda: (camera,),
        topology=SimpleNamespace(links=()),
    )
    return SiteIntelligenceService(
        settings,
        manager,  # type: ignore[arg-type]
        EventBus(),
        timeline,
        raise_after_seconds=3.0,
        resolve_after_seconds=10.0,
        clock=clock,
    )


def test_an_alert_is_recorded_once_it_has_persisted(settings: Settings) -> None:
    camera, clock, timeline = _Camera("cam-02"), _Clock(), TimelineService()
    service = _service(settings, camera, clock, timeline)

    report = service.update_once()
    assert {alert.alert_id for alert in report.alerts} == {
        "camera-offline:cam-02",
        "degraded-coverage",
    }
    assert timeline.total == 0  # not yet persisted

    for _ in range(3):
        clock.advance(1.0)
        service.update_once()

    titles = [entry.title for entry in timeline.entries()]
    assert "CAM-02 offline" in titles
    assert "Global analysis degraded - CAM-02 offline" in titles
    assert all(entry.entry_type is TimelineEntryType.ALERT for entry in timeline.entries())
    assert all(entry.camera_id == SITE_TIMELINE_ID for entry in timeline.entries())

    # Still true a second later: nothing new is written.
    clock.advance(1.0)
    service.update_once()
    assert timeline.total == 2


def test_a_flickering_alert_is_never_recorded(settings: Settings) -> None:
    camera, clock, timeline = _Camera("cam-02"), _Clock(), TimelineService()
    service = _service(settings, camera, clock, timeline)

    for _ in range(5):
        camera.status = CameraConnectionStatus.OFFLINE
        service.update_once()
        clock.advance(1.0)
        camera.enabled = False  # the condition disappears
        service.update_once()
        clock.advance(1.0)
        camera.enabled = True

    assert timeline.total == 0


def test_a_resolution_is_recorded_once_the_condition_has_stayed_away(settings: Settings) -> None:
    camera, clock, timeline = _Camera("cam-02"), _Clock(), TimelineService()
    service = _service(settings, camera, clock, timeline)
    for _ in range(4):
        service.update_once()
        clock.advance(1.0)
    assert timeline.total == 2

    camera.enabled = False
    service.update_once()
    clock.advance(5.0)
    service.update_once()
    assert timeline.total == 2  # not gone long enough

    clock.advance(6.0)
    service.update_once()

    resolved = [entry for entry in timeline.entries() if entry.title.startswith("Resolved - ")]
    assert len(resolved) == 2
    assert all(entry.severity is Severity.INFO for entry in resolved)
