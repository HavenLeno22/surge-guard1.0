"""The backend's Queue Intelligence surface.

A thin read-and-configure layer over two things that already exist: the latest
:class:`~surgeguard_ai.contracts.analysis.AnalysisResult` held by
:class:`~app.services.crowd_intelligence.CrowdIntelligenceService`, and the
:class:`~surgeguard_ai.queue.QueueAnalyzer` inside the analysis pipeline.

It holds no measurements of its own. That is deliberate: a second copy of the
queue state would be a second thing to keep in step with the first, and the
whole point of routing everything through one ``AnalysisResult`` is that the
measurement, the forecast and the recommendation on screen always describe the
same frame.

What it does own is the *operator's* side of the configuration - counter
allocation and zones - because those are inputs to the pipeline rather than
outputs from it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from surgeguard_ai.contracts import (
    AnalysisResult,
    CameraZone,
    ForecastReport,
    ImagePoint,
    ImagePolygon,
    QueueReport,
    ResourcePlanReport,
)
from surgeguard_ai.pipeline import AnalysisPipeline
from surgeguard_ai.queue import CounterSettings

from ..core.logging import get_logger
from ..schemas.queue import (
    CounterSettingsWrite,
    CounterStateRead,
    ZonePointWrite,
    ZoneWrite,
)
from .crowd_intelligence import CrowdIntelligenceService
from .zone_store import ZoneStore

__all__ = ["QueueService", "zone_from_write", "zone_to_write"]

logger = get_logger(__name__)


class QueueService:
    """Reads Queue Intelligence output and accepts operator configuration."""

    def __init__(
        self,
        intelligence: CrowdIntelligenceService,
        zones: ZoneStore,
        pipeline: AnalysisPipeline | None,
        *,
        camera_id: str,
        default_service_rate_per_min: float = 2.0,
    ) -> None:
        self._intelligence = intelligence
        self._zones = zones
        self._pipeline = pipeline
        self._camera_id = camera_id
        self._default_rate = default_service_rate_per_min
        self._zones_changed_since_build = False

    # -- Availability -------------------------------------------------------

    @property
    def camera_id(self) -> str:
        """The camera these zones and queues belong to."""
        return self._camera_id

    @property
    def enabled(self) -> bool:
        """Whether Queue Intelligence is running at all."""
        return self._analyzer is not None

    @property
    def _analyzer(self):
        return self._pipeline.queue_analyzer if self._pipeline is not None else None

    @property
    def requires_restart(self) -> bool:
        """Whether the running pipeline is measuring against stale zones.

        Zones are read when the analyser is constructed, so a zone saved after
        that point is on disk but not yet in effect. Reporting this is what
        stops an operator wondering why the zone they just drew is not being
        measured.
        """
        return self._zones_changed_since_build

    # -- Reading ------------------------------------------------------------

    @property
    def latest(self) -> AnalysisResult | None:
        return self._intelligence.latest

    def age_seconds(self, result: AnalysisResult) -> float:
        """How old an analysis is, in seconds, never negative."""
        return max(0.0, (datetime.now(UTC) - result.frame_ts).total_seconds())

    def current(self) -> QueueReport | None:
        """Measured queue state, or ``None`` when nothing has been analysed."""
        result = self.latest
        return result.queue if result is not None else None

    def prediction(self) -> ForecastReport | None:
        """Queue forecasts, or ``None`` when none have been produced."""
        result = self.latest
        return result.forecast if result is not None else None

    def recommendations(self) -> ResourcePlanReport | None:
        """Counter allocation plans, or ``None`` when none have been produced."""
        result = self.latest
        return result.resources if result is not None else None

    # -- Counters -----------------------------------------------------------

    def counters(self) -> tuple[CounterStateRead, ...]:
        """Current counter allocation for every queue zone.

        Rates come from the live measurement when one exists, falling back to
        the operator's configured assumption - so the figure shown is the one
        actually being used in the wait calculation, not a separate copy that
        could disagree with it.
        """
        analyzer = self._analyzer
        if analyzer is None:
            return ()

        report = self.current()
        names = {queue.zone_id: queue for queue in (report.queues if report else ())}

        states = []
        for zone_id in analyzer.queue_zone_ids:
            settings = analyzer.counters_for(zone_id)
            measured = names.get(zone_id)

            rate = (
                measured.capacity.service_rate_per_counter_per_min
                if measured is not None
                else settings.configured_rate_per_min
            )
            states.append(
                CounterStateRead(
                    zone_id=zone_id,
                    zone_name=measured.zone_name if measured else zone_id,
                    total_counters=settings.total_counters,
                    active_counters=settings.active_counters,
                    service_rate_per_min=rate,
                    idle_counters=max(
                        0, settings.total_counters - settings.active_counters
                    ),
                )
            )
        return tuple(states)

    def set_counters(self, zone_id: str, write: CounterSettingsWrite) -> bool:
        """Apply an operator's counter allocation. Returns False for an unknown zone.

        Takes effect on the next analysis window. The measured service rate then
        follows reality on its own, which is how the platform detects that a
        newly opened counter is not actually serving anybody.
        """
        analyzer = self._analyzer
        if analyzer is None or zone_id not in analyzer.queue_zone_ids:
            return False

        existing = analyzer.counters_for(zone_id)
        rate = write.service_rate_per_min or existing.configured_rate_per_min

        analyzer.set_counters(
            zone_id,
            CounterSettings(
                total_counters=write.total_counters,
                active_counters=write.active_counters,
                configured_rate_per_min=rate,
            ),
        )
        logger.info(
            "Counter allocation updated",
            extra={
                "zone_id": zone_id,
                "total_counters": write.total_counters,
                "active_counters": write.active_counters,
            },
        )
        return True

    # -- Zones --------------------------------------------------------------

    def zones(self) -> tuple[ZoneWrite, ...]:
        """The camera's current zone set, as the API represents it."""
        return tuple(zone_to_write(zone) for zone in self._zones.zones)

    def save_zones(self, zones: tuple[ZoneWrite, ...]) -> tuple[ZoneWrite, ...]:
        """Replace the camera's zone set and persist it."""
        saved = self._zones.save(tuple(zone_from_write(zone) for zone in zones))
        self._zones_changed_since_build = True
        logger.info(
            "Camera zones replaced; pipeline rebuild required for them to take "
            "effect",
            extra={"zone_count": len(saved)},
        )
        return tuple(zone_to_write(zone) for zone in saved)

    def mark_zones_applied(self) -> None:
        """Note that the pipeline has been rebuilt against the current zones."""
        self._zones_changed_since_build = False

    def rebind(self, pipeline: AnalysisPipeline | None) -> None:
        """Point at a newly built analysis pipeline after a zone change."""
        self._pipeline = pipeline
        self.mark_zones_applied()


def zone_to_write(zone: CameraZone) -> ZoneWrite:
    """A stored zone in the shape the API publishes."""
    return ZoneWrite(
        zone_id=zone.zone_id,
        name=zone.name,
        zone_type=zone.zone_type,
        width_m=zone.width_m,
        polygon=tuple(
            ZonePointWrite(x=point.x, y=point.y) for point in zone.polygon.points
        ),
    )


def zone_from_write(zone: ZoneWrite) -> CameraZone:
    """An operator-drawn zone in the shape the AI Pipeline consumes."""
    return CameraZone(
        zone_id=zone.zone_id,
        name=zone.name,
        zone_type=zone.zone_type,
        width_m=zone.width_m,
        polygon=ImagePolygon(
            points=tuple(ImagePoint(x=p.x, y=p.y) for p in zone.polygon)
        ),
    )
