"""Queue Intelligence - measuring what a service queue is doing.

Consumes a :class:`~surgeguard_ai.contracts.perception.PerceptionResult` and the
camera's configured zones, and produces a
:class:`~surgeguard_ai.contracts.queue.QueueReport`: for each QUEUE zone, how
many people are in it, whether it is genuinely a queue, how fast people join and
are served, and how long a joiner should expect to wait.

This stage sits beside crowd analysis rather than after it. Both consume the
same perception output and neither depends on the other, which is what allows
Queue Intelligence to be added without disturbing the Crowd Stability Index
(Rule 2).

**What this stage will not do.** It will not claim to understand intent. A
person standing in a line and a person standing near a line look the same to a
detector, and no amount of post-processing changes that. What it does instead is
measure four properties a queue demonstrably has - linear arrangement, regular
spacing, coherent heading, orientation toward a counter - report the weighted
result with a confidence, and decline to classify when the evidence is thin.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

from ..contracts.camera import CameraConfig, CameraZone
from ..contracts.enums import QueueFormation, RateSource, ZoneType
from ..contracts.geometry import ImagePoint
from ..contracts.perception import PerceptionResult, Track
from ..contracts.queue import (
    FlowRates,
    QueueGeometry,
    QueueMetrics,
    QueueReport,
    ServiceCapacity,
    WaitEstimate,
)
from ._spatial import (
    PrincipalAxis,
    axis_alignment,
    heading_coherence,
    point_in_polygon,
    polygon_centroid,
    principal_axis,
    spacing_along_axis,
    spacing_regularity,
)
from .config import QueueAnalysisConfig
from .zone_flow import ZoneFlowTracker

__all__ = ["CounterSettings", "QueueAnalyzer"]

logger = logging.getLogger(__name__)


class CounterSettings:
    """Operator-configured service resources for one queue zone.

    The platform cannot see how many ticket windows a hall has, nor which of
    them are staffed. That is operator knowledge, supplied here and updated
    whenever it changes. The per-counter service *rate*, by contrast, is
    measured from observed departures as soon as there are enough of them - the
    configured figure is a starting assumption, not a permanent one.
    """

    __slots__ = ("total_counters", "active_counters", "configured_rate_per_min")

    def __init__(
        self,
        total_counters: int = 1,
        active_counters: int = 1,
        configured_rate_per_min: float = 2.0,
    ) -> None:
        if total_counters < 0:
            raise ValueError("total_counters cannot be negative")
        if active_counters < 0:
            raise ValueError("active_counters cannot be negative")
        if active_counters > total_counters:
            raise ValueError(
                f"active_counters ({active_counters}) cannot exceed "
                f"total_counters ({total_counters})"
            )
        if configured_rate_per_min <= 0:
            raise ValueError("configured_rate_per_min must be positive")

        self.total_counters = total_counters
        self.active_counters = active_counters
        self.configured_rate_per_min = configured_rate_per_min


class QueueAnalyzer:
    """Measures every configured queue zone on one camera.

    Stateful across frames: arrival and service rates are counts of transitions,
    which only exist relative to what was seen before. One instance follows one
    camera for the life of a source session.
    """

    def __init__(
        self,
        camera: CameraConfig,
        config: QueueAnalysisConfig | None = None,
        *,
        counters: Mapping[str, CounterSettings] | None = None,
    ) -> None:
        self._camera = camera
        self._config = config or QueueAnalysisConfig()
        self._counters: dict[str, CounterSettings] = dict(counters or {})

        self._queue_zones = camera.zones_of_type(ZoneType.QUEUE)
        self._counter_zones = camera.zones_of_type(ZoneType.COUNTER)

        self._flow: dict[str, ZoneFlowTracker] = {
            zone.zone_id: ZoneFlowTracker(
                window_seconds=self._config.flow_window_seconds,
                service_end_fraction=self._config.service_end_fraction,
                max_dwell_seconds=self._config.max_dwell_seconds,
            )
            for zone in self._queue_zones
        }

        if not self._queue_zones:
            logger.info(
                "No QUEUE zone configured for camera %s - Queue Intelligence has "
                "nothing to measure until one is defined",
                camera.camera_id,
            )

    # -- Operator configuration --------------------------------------------

    def set_counters(self, zone_id: str, settings: CounterSettings) -> None:
        """Update the service resources attached to a queue zone.

        Called when an operator opens or closes a counter. Takes effect on the
        next analysis window; the *measured* service rate then follows reality
        on its own, which is how the platform detects that a newly opened
        counter is not actually serving anyone.
        """
        self._counters[zone_id] = settings

    def counters_for(self, zone_id: str) -> CounterSettings:
        """Current counter settings for a zone, defaulted if never configured."""
        return self._counters.get(
            zone_id,
            CounterSettings(
                total_counters=1,
                active_counters=1,
                configured_rate_per_min=self._config.default_service_rate_per_min,
            ),
        )

    # -- Analysis -----------------------------------------------------------

    def analyze(self, perception: PerceptionResult) -> QueueReport:
        """Measure every queue zone for one frame."""
        if not self._queue_zones:
            return QueueReport(
                frame_seq=perception.frame_seq,
                frame_ts=perception.frame_ts,
                queues=(),
                unconfigured=True,
            )

        queues = tuple(
            self._analyze_zone(zone, perception) for zone in self._queue_zones
        )
        return QueueReport(
            frame_seq=perception.frame_seq,
            frame_ts=perception.frame_ts,
            queues=queues,
            unconfigured=False,
        )

    def _analyze_zone(
        self, zone: CameraZone, perception: PerceptionResult
    ) -> QueueMetrics:
        frame_ts = perception.frame_ts
        tracks = perception.tracking.tracks

        inside = tuple(
            track for track in tracks if point_in_polygon(track.foot_point, zone.polygon)
        )
        # Geometry uses only tracks old enough to trust; the headcount uses every
        # person actually seen. Filtering the count too would under-report a
        # queue that is filling quickly, which is precisely when it matters.
        settled = tuple(
            track
            for track in inside
            if track.age_frames >= self._config.min_track_age_frames
        )

        axis = principal_axis([track.foot_point for track in settled])
        counter_zone = self._nearest_counter(axis, zone)
        geometry = self._measure_geometry(settled, axis, counter_zone)
        formation, confidence, basis = self._classify(
            len(inside), geometry, counter_zone
        )

        service_end, extent = self._service_end(axis, counter_zone)
        tracker = self._flow[zone.zone_id]
        tracker.observe(
            frame_ts,
            {track.track_id: track.foot_point for track in settled},
            service_end=service_end,
            queue_extent_px=extent,
        )

        flow = self._measure_flow(tracker)
        capacity = self._measure_capacity(zone.zone_id, tracker, flow)
        wait = self._estimate_wait(len(inside), capacity, tracker, confidence)
        mean_dwell, max_dwell = tracker.dwell_seconds(frame_ts)

        return QueueMetrics(
            zone_id=zone.zone_id,
            zone_name=zone.name,
            frame_seq=perception.frame_seq,
            frame_ts=frame_ts,
            person_count=len(inside),
            formation=formation,
            formation_confidence=confidence,
            formation_basis=basis,
            geometry=geometry,
            flow=flow,
            capacity=capacity,
            wait=wait,
            mean_dwell_seconds=mean_dwell,
            max_dwell_seconds=max_dwell,
        )

    # -- Geometry -----------------------------------------------------------

    def _nearest_counter(
        self, axis: PrincipalAxis | None, queue_zone: CameraZone
    ) -> CameraZone | None:
        """The COUNTER zone this queue most plausibly serves.

        Nearest to the queue's centre, or to the queue zone's own centroid when
        there are too few people to have an axis. Returns ``None`` when no
        counter zone is configured - counter alignment is then simply
        unavailable, exactly as an unconfigured EXIT zone makes egress
        congestion unavailable rather than zero.
        """
        if not self._counter_zones:
            return None

        if axis is not None:
            origin = ImagePoint(x=axis.centre[0], y=axis.centre[1])
        else:
            origin = polygon_centroid(queue_zone.polygon)

        def distance(zone: CameraZone) -> float:
            centre = polygon_centroid(zone.polygon)
            return (centre.x - origin.x) ** 2 + (centre.y - origin.y) ** 2

        return min(self._counter_zones, key=distance)

    def _measure_geometry(
        self,
        tracks: tuple[Track, ...],
        axis: PrincipalAxis | None,
        counter_zone: CameraZone | None,
    ) -> QueueGeometry:
        if axis is None:
            return QueueGeometry(sample_size=len(tracks))

        points = [track.foot_point for track in tracks]
        gaps = spacing_along_axis(points, axis)
        regularity = spacing_regularity(gaps)
        mean_gap = sum(gaps) / len(gaps) if gaps else None

        coherence = heading_coherence(
            [
                (track.velocity_image.dx, track.velocity_image.dy)
                for track in tracks
                if track.velocity_image is not None
            ]
        )

        alignment = None
        if counter_zone is not None:
            alignment = axis_alignment(axis, polygon_centroid(counter_zone.polygon))

        return QueueGeometry(
            sample_size=len(tracks),
            linearity=axis.linearity,
            spacing_regularity=regularity,
            heading_coherence=coherence,
            counter_alignment=alignment,
            mean_spacing_px=mean_gap,
            mean_spacing_m=None,  # Requires calibration; Phase G.
            major_axis_deg=axis.angle_deg,
        )

    # -- Classification -----------------------------------------------------

    def _classify(
        self,
        person_count: int,
        geometry: QueueGeometry,
        counter_zone: CameraZone | None,
    ) -> tuple[QueueFormation, float, tuple[str, ...]]:
        """Decide whether this zone holds a queue, and say why.

        The score is a weighted mean over whichever of the four structural
        signals could be measured, with the weights of the unavailable ones
        renormalised away - the same treatment the Crowd Stability Index gives an
        unavailable indicator, and for the same reason: scoring a missing signal
        as zero would read as evidence against a queue when it is no evidence at
        all.
        """
        config = self._config

        if person_count <= config.sparse_threshold:
            return (
                QueueFormation.SPARSE,
                1.0,
                (
                    f"{person_count} "
                    f"{'person' if person_count == 1 else 'people'} in zone - "
                    f"below the {config.sparse_threshold}-person floor for "
                    "structure to be meaningful",
                ),
            )

        components: list[tuple[str, float | None, float, str]] = [
            ("linearity", geometry.linearity, config.linearity_weight, "arranged linearly"),
            (
                "spacing",
                geometry.spacing_regularity,
                config.spacing_weight,
                "evenly spaced",
            ),
            (
                "heading",
                geometry.heading_coherence,
                config.heading_weight,
                "moving coherently",
            ),
            (
                "counter",
                geometry.counter_alignment,
                config.counter_weight,
                f"oriented toward {counter_zone.name}" if counter_zone else "oriented toward counter",
            ),
        ]

        available = [(n, v, w, label) for n, v, w, label in components if v is not None]
        if not available:
            return (
                QueueFormation.UNDETERMINED,
                0.0,
                ("No structural measurement available - too few settled tracks",),
            )

        total_weight = sum(w for _, _, w, _ in available)
        score = sum(v * w for _, v, w, _ in available) / total_weight

        basis = tuple(
            f"{label} ({value:.2f})"
            for _, value, _, label in sorted(
                available, key=lambda item: (item[1] or 0.0) * item[2], reverse=True
            )
        )

        # Coverage discounts confidence when signals were missing: a score built
        # on one of four measurements is not as trustworthy as one built on all
        # four, whatever its value.
        coverage = total_weight

        if score >= config.queue_threshold:
            formation = QueueFormation.QUEUE
            margin = (score - config.queue_threshold) / max(
                1e-6, 1.0 - config.queue_threshold
            )
        elif score <= config.crowd_threshold:
            formation = QueueFormation.GENERAL_CROWD
            margin = (config.crowd_threshold - score) / max(1e-6, config.crowd_threshold)
        else:
            formation = QueueFormation.UNDETERMINED
            margin = 0.0

        confidence = max(0.0, min(1.0, coverage * (0.5 + 0.5 * margin)))
        return formation, confidence, basis

    # -- Flow and capacity --------------------------------------------------

    def _service_end(
        self, axis: PrincipalAxis | None, counter_zone: CameraZone | None
    ) -> tuple[ImagePoint | None, float | None]:
        """Where the queue is served, and how long the queue is.

        The queue's axis has two ends; the service end is whichever lies nearer
        the counter. Extent is taken as four standard deviations along the major
        axis - the span containing essentially the whole line.
        """
        if axis is None or counter_zone is None:
            return None, None

        cx, cy = axis.centre
        dx, dy = axis.direction
        half = 2.0 * axis.major_sigma

        end_a = ImagePoint(x=cx + dx * half, y=cy + dy * half)
        end_b = ImagePoint(x=cx - dx * half, y=cy - dy * half)

        counter_centre = polygon_centroid(counter_zone.polygon)

        def squared_distance(point: ImagePoint) -> float:
            return (point.x - counter_centre.x) ** 2 + (point.y - counter_centre.y) ** 2

        service_end = end_a if squared_distance(end_a) <= squared_distance(end_b) else end_b
        return service_end, 2.0 * half

    def _measure_flow(self, tracker: ZoneFlowTracker) -> FlowRates:
        arrivals, served, abandoned = tracker.counts()
        arrival_rate, service_rate, abandonment_rate = tracker.rates()
        observed = tracker.observation_seconds

        if observed >= self._config.min_flow_observation_seconds and served > 0:
            source = RateSource.MEASURED
        elif served > 0:
            source = RateSource.BLENDED
        else:
            source = RateSource.CONFIGURED

        return FlowRates(
            window_seconds=self._config.flow_window_seconds,
            arrivals=arrivals,
            departures_served=served,
            departures_abandoned=abandoned,
            arrival_rate_per_min=arrival_rate,
            service_rate_per_min=service_rate,
            abandonment_rate_per_min=abandonment_rate,
            rate_source=source,
            observation_seconds=observed,
        )

    def _measure_capacity(
        self, zone_id: str, tracker: ZoneFlowTracker, flow: FlowRates
    ) -> ServiceCapacity:
        """Combine operator counter settings with the observed service rate.

        The per-counter rate is the measured throughput divided across the
        counters actually open. Until enough departures have been observed it is
        blended toward the configured figure in proportion to how far through
        the observation window the platform is - so the number moves smoothly
        from assumption to measurement instead of jumping.
        """
        settings = self.counters_for(zone_id)
        configured = settings.configured_rate_per_min

        if settings.active_counters <= 0 or flow.departures_served == 0:
            return ServiceCapacity(
                total_counters=settings.total_counters,
                active_counters=settings.active_counters,
                service_rate_per_counter_per_min=configured,
                rate_source=RateSource.CONFIGURED,
            )

        measured = flow.service_rate_per_min / settings.active_counters

        if flow.rate_source is RateSource.MEASURED:
            rate, source = measured, RateSource.MEASURED
        else:
            maturity = min(
                1.0,
                tracker.observation_seconds
                / max(1e-6, self._config.min_flow_observation_seconds),
            )
            rate = maturity * measured + (1.0 - maturity) * configured
            source = RateSource.BLENDED

        return ServiceCapacity(
            total_counters=settings.total_counters,
            active_counters=settings.active_counters,
            service_rate_per_counter_per_min=max(
                self._config.min_service_rate_per_min, rate
            ),
            rate_source=source,
        )

    def _estimate_wait(
        self,
        queue_length: int,
        capacity: ServiceCapacity,
        tracker: ZoneFlowTracker,
        formation_confidence: float,
    ) -> WaitEstimate:
        """Little's Law, with its assumptions attached."""
        effective = capacity.effective_service_rate_per_min

        minutes: float | None
        if queue_length == 0:
            minutes = 0.0
        elif effective < self._config.min_service_rate_per_min:
            # Nothing is draining. Reporting an enormous number here would look
            # like a measurement of a very long wait; it is an absence of one.
            minutes = None
        else:
            minutes = queue_length / effective

        assumptions: list[str] = []
        if capacity.rate_source is RateSource.MEASURED:
            assumptions.append(
                f"service rate measured over "
                f"{tracker.observation_seconds / 60.0:.1f} min of observation"
            )
        elif capacity.rate_source is RateSource.BLENDED:
            assumptions.append(
                "service rate partly measured, partly assumed - observation still short"
            )
        else:
            assumptions.append(
                f"service rate assumed at "
                f"{capacity.service_rate_per_counter_per_min:.1f}/min per counter "
                "- no departures observed yet"
            )

        assumptions.append(
            f"assumes all {capacity.active_counters} active "
            f"{'counter' if capacity.active_counters == 1 else 'counters'} stay open"
        )
        assumptions.append("assumes arrivals are served in order")

        observation_factor = min(
            1.0,
            tracker.observation_seconds
            / max(1e-6, self._config.min_flow_observation_seconds),
        )
        source_factor = {
            RateSource.MEASURED: 1.0,
            RateSource.BLENDED: 0.7,
            RateSource.CONFIGURED: 0.4,
        }[capacity.rate_source]

        confidence = observation_factor * source_factor * max(0.1, formation_confidence)

        return WaitEstimate(
            minutes=minutes,
            queue_length=queue_length,
            effective_service_rate_per_min=effective,
            rate_source=capacity.rate_source,
            assumptions=tuple(assumptions),
            confidence=max(0.0, min(1.0, confidence)),
        )

    # -- Introspection ------------------------------------------------------

    @property
    def queue_zone_ids(self) -> tuple[str, ...]:
        """Zone ids this analyser is measuring."""
        return tuple(zone.zone_id for zone in self._queue_zones)

    def observation_seconds(self, zone_id: str) -> float:
        """How long one zone has been observed. Zero for an unknown zone."""
        tracker = self._flow.get(zone_id)
        return tracker.observation_seconds if tracker else 0.0
