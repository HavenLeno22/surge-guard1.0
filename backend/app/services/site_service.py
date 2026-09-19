"""Site intelligence, kept current - every camera combined, once a second.

Per-camera analysis arrives at each camera's own frame rate. The site view does
not need to: combining a dozen figures across cameras many times a second would
only multiply work and WebSocket traffic, while an operator reads the site
picture on a scale of seconds. So a steady loop gathers each camera's latest
state and hands it to :class:`~surgeguard_ai.site.SiteIntelligence`.

**Alerts on the timeline.** Site alerts are conditions, re-evaluated every
update. The timeline records their *transitions* - raised, resolved - and only
once a condition has persisted for a few seconds, so a hotspot score hovering on
a threshold does not write a line a second. Site entries are recorded against
the site rather than a camera, so a camera reconnecting (which clears that
camera's timeline entries) never erases the record of its own outage.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from surgeguard_ai.contracts import (
    Severity,
    SiteAlert,
    SiteCamera,
    SiteReport,
    SiteTopology,
    TimelineEntryType,
)
from surgeguard_ai.site import CameraObservation, SiteIntelligence, SiteIntelligenceConfig

from ..cameras.manager import CameraManager
from ..cameras.runtime import CameraRuntime
from ..core.config import Settings
from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from ..workers.perception_factory import build_allocation_config, build_forecast_config
from .timeline_service import TimelineService
from .zone_store import ZoneStoreError

__all__ = ["SITE_TIMELINE_ID", "SiteIntelligenceService"]

logger = get_logger(__name__)

#: The timeline "camera" site-level entries are recorded against.
SITE_TIMELINE_ID = "site"


@dataclass(slots=True)
class _TrackedAlert:
    alert: SiteAlert
    first_seen: datetime
    last_seen: datetime
    recorded: bool = False


class SiteIntelligenceService:
    """Owns site intelligence for the running cameras."""

    def __init__(
        self,
        settings: Settings,
        manager: CameraManager,
        event_bus: EventBus,
        timeline: TimelineService,
        *,
        raise_after_seconds: float = 3.0,
        resolve_after_seconds: float = 10.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Args:
            settings: Configuration - update cadence, observation age, and the
                forecast and allocation settings every camera uses.
            manager: The cameras to combine.
            event_bus: Where each report is announced.
            timeline: Where alert transitions are recorded.
            raise_after_seconds: How long an alert must persist before it is
                written to the timeline.
            resolve_after_seconds: How long it must be gone before its
                resolution is written.
            clock: Source of "now", for tests.
        """
        self._settings = settings
        self._manager = manager
        self._event_bus = event_bus
        self._timeline = timeline
        self._raise_after = raise_after_seconds
        self._resolve_after = resolve_after_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

        allocation = build_allocation_config(settings)
        self._intelligence = SiteIntelligence(
            SiteIntelligenceConfig(
                max_observation_age_seconds=settings.site_max_observation_age_seconds,
                # The allocator marks plans provisional below this; an alert
                # resting on rates that young would be just as provisional.
                min_rate_observation_seconds=allocation.min_observation_seconds,
            ),
            forecast_config=build_forecast_config(settings),
            allocation_config=allocation,
        )
        self._latest: SiteReport | None = None
        self._alerts: dict[str, _TrackedAlert] = {}
        self._task: asyncio.Task[None] | None = None
        self._failures = 0

    # -- Reading ------------------------------------------------------------

    @property
    def latest(self) -> SiteReport | None:
        """The most recent report, or ``None`` before the first update."""
        return self._latest

    @property
    def failures(self) -> int:
        return self._failures

    def topology(self) -> SiteTopology:
        """The site as configured: every camera, and every zone link."""
        return SiteTopology(
            cameras=tuple(_site_camera(runtime) for runtime in self._manager.runtimes()),
            links=self._manager.topology.links,
        )

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="site-intelligence")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        interval = self._settings.site_update_interval_seconds
        while True:
            try:
                self.update_once()
            except Exception as error:  # noqa: BLE001 - the loop must outlive one bad update
                self._failures += 1
                logger.exception("Site intelligence update failed", exc_info=error)
            await asyncio.sleep(interval)

    # -- The update ---------------------------------------------------------

    def update_once(self) -> SiteReport:
        """Combine every camera's current state into a report, and announce it."""
        now = self._clock()
        observations = [self._observe(runtime, now) for runtime in self._manager.runtimes()]
        report = self._intelligence.update(self.topology(), observations, now)
        self._latest = report
        self._record_transitions(report, now)
        self._event_bus.dispatch(DomainEvent.SITE_UPDATED, report)
        return report

    def _observe(self, runtime: CameraRuntime, now: datetime) -> CameraObservation:
        status = runtime.snapshot(now=now)
        analysis = runtime.intelligence.snapshot(now=now)
        try:
            zones = runtime.zone_store.zones
        except ZoneStoreError:
            zones = ()
        return CameraObservation(
            camera_id=runtime.camera_id,
            status=status.status,
            status_detail=status.detail,
            analysis=analysis.result if analysis is not None else None,
            analysis_age_seconds=analysis.age_seconds if analysis is not None else None,
            zones=zones,
        )

    # -- Timeline -----------------------------------------------------------

    def _record_transitions(self, report: SiteReport, now: datetime) -> None:
        current = {alert.alert_id: alert for alert in report.alerts}

        for alert_id, alert in current.items():
            tracked = self._alerts.get(alert_id)
            if tracked is None:
                tracked = self._alerts[alert_id] = _TrackedAlert(alert, now, now)
            tracked.alert = alert
            tracked.last_seen = now
            persisted = (now - tracked.first_seen).total_seconds()
            if not tracked.recorded and persisted >= self._raise_after:
                tracked.recorded = True
                self._append(
                    entry_type=TimelineEntryType.ALERT,
                    severity=alert.severity,
                    title=alert.title,
                    detail=_detail(alert),
                )

        for alert_id in [alert_id for alert_id in self._alerts if alert_id not in current]:
            tracked = self._alerts[alert_id]
            if not tracked.recorded:
                # Never persisted long enough to be recorded; forget the flicker.
                del self._alerts[alert_id]
                continue
            if (now - tracked.last_seen).total_seconds() >= self._resolve_after:
                del self._alerts[alert_id]
                self._append(
                    entry_type=TimelineEntryType.STATUS_CHANGE,
                    severity=Severity.INFO,
                    title=f"Resolved - {tracked.alert.title}",
                    detail="The condition has not been measured for "
                    f"{self._resolve_after:.0f} seconds.",
                )

    def _append(
        self, *, entry_type: TimelineEntryType, severity: Severity, title: str, detail: str | None
    ) -> None:
        entry = self._timeline.append(
            entry_type=entry_type,
            severity=severity,
            title=title,
            detail=detail,
            camera_id=SITE_TIMELINE_ID,
        )
        self._event_bus.dispatch(DomainEvent.TIMELINE_ENTRY_ADDED, entry)


def _site_camera(runtime: CameraRuntime) -> SiteCamera:
    definition = runtime.definition
    return SiteCamera(
        camera_id=definition.camera_id,
        name=definition.name,
        role=definition.role,
        # A camera with no declared area watches an area of its own, so its
        # count adds to the others rather than being merged with any of them.
        coverage_area=definition.coverage_area or definition.camera_id,
        enabled=definition.enabled,
    )


def _detail(alert: SiteAlert) -> str:
    if not alert.evidence:
        return alert.explanation
    return f"{alert.explanation} Evidence: {'; '.join(alert.evidence)}."
