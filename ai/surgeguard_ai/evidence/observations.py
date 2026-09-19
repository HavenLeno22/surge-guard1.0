"""The individual observations the Evidence Engine can make.

One function per thing the platform is able to notice. Each reads measurements
that already exist - crowd metrics and the Crowd Stability Index breakdown -
and either returns an :class:`~surgeguard_ai.contracts.evidence.EvidenceItem`
or returns ``None`` because there is nothing to report.

**Nothing here measures anything.** Every number an observation cites was
computed once, upstream, for the index. That is what keeps evidence and the
index two views of one measurement instead of two calculations free to
disagree - and it is why an operator can trust that "movement slowing" and a
falling CSI are the same fact stated twice, not two independent claims.

Composition, prioritisation and filtering are the engine's job, not these
functions'. Each answers only "is this true right now, and how do I say it?".
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.enums import EvidenceType, Severity, StabilityIndicator, ZoneType
from ..contracts.evidence import EvidenceItem, SupportingMetric
from ..contracts.stability import IndicatorReading, StabilityAssessment
from .config import EvidenceConfig

__all__ = ["ObservationContext", "OBSERVERS", "observe_conditions_nominal"]


@dataclass(frozen=True, slots=True)
class ObservationContext:
    """Everything an observer is allowed to look at for one window."""

    crowd: CrowdMetrics
    stability: StabilityAssessment
    camera: CameraConfig
    config: EvidenceConfig

    def reading(self, indicator: StabilityIndicator) -> IndicatorReading | None:
        """An indicator's reading, or ``None`` when it could not be measured.

        An unavailable indicator yields no observation at all. Reporting
        "movement is normal" because movement could not be measured would be
        the most dangerous kind of false reassurance this platform can produce.
        """
        for reading in self.stability.breakdown.readings:
            if reading.indicator is indicator and reading.available:
                return reading
        return None

    def pressure(self, indicator: StabilityIndicator) -> float | None:
        """An indicator's instability pressure, or ``None`` when unmeasured."""
        reading = self.reading(indicator)
        return reading.pressure if reading is not None else None

    @property
    def density_unit(self) -> str:
        """The unit peak density is in, so it is never displayed without one.

        ``rel`` rather than ``rel.``: these strings are interpolated into
        sentences as well as shown beside a figure, and a unit carrying its own
        full stop produces "9.0 rel.." in the first case.
        """
        return "p/m2" if self.crowd.is_metric else "rel"


# ---------------------------------------------------------------------------
# Observers
# ---------------------------------------------------------------------------


def observe_congestion(context: ObservationContext) -> EvidenceItem | None:
    """Congestion forming - the most crowded part of the view is compressing."""
    reading = context.reading(StabilityIndicator.DENSITY_PRESSURE)
    if reading is None or reading.pressure is None:
        return None
    if reading.pressure < context.config.congestion_pressure:
        return None

    where = _peak_region(context.crowd)
    density = reading.raw_value or 0.0

    return _build(
        context,
        evidence_type=EvidenceType.CONGESTION_FORMING,
        indicator=StabilityIndicator.DENSITY_PRESSURE,
        pressure=reading.pressure,
        threshold=context.config.congestion_pressure,
        headline=f"Congestion forming in the {where}" if where else "Congestion forming",
        detail=(
            f"Peak crowd density is {density:.1f} {context.density_unit}"
            + (f", concentrated in the {where} of the camera view." if where else ".")
        ),
        metrics=(
            SupportingMetric(label="Peak density", value=density, unit=context.density_unit),
            SupportingMetric(
                label="Mean density", value=context.crowd.density_mean, unit=context.density_unit
            ),
            SupportingMetric(
                label="People in view", value=float(context.crowd.person_count), unit=""
            ),
        ),
    )


def observe_occupancy_trend(context: ObservationContext) -> EvidenceItem | None:
    """Occupancy increasing, or the crowd dispersing.

    One observer for both directions because they are one measurement read
    twice. Splitting them would invite the two halves to drift onto different
    thresholds and report both at once around zero.
    """
    reading = context.reading(StabilityIndicator.RATE_OF_CHANGE)
    if reading is None or reading.raw_value is None:
        return None

    density = context.crowd.density_max
    if density < context.config.min_density_for_rate:
        # A nearly empty view produces huge fractional changes from one person
        # walking into it. Arithmetically correct, operationally noise.
        return None

    relative_rate = reading.raw_value / density
    if abs(relative_rate) < context.config.relative_rate_per_second:
        return None

    rising = relative_rate > 0
    percent_per_minute = abs(relative_rate) * 60.0 * 100.0
    metrics = (
        SupportingMetric(
            label="Peak density",
            value=density,
            unit=context.density_unit,
        ),
        SupportingMetric(
            label="Rate of change",
            value=percent_per_minute if rising else -percent_per_minute,
            unit="%/min",
        ),
    )

    if rising:
        return _build(
            context,
            evidence_type=EvidenceType.OCCUPANCY_INCREASING,
            indicator=StabilityIndicator.RATE_OF_CHANGE,
            pressure=reading.pressure or 0.0,
            threshold=0.0,
            headline="Occupancy increasing",
            detail=(
                f"Peak crowd density is rising at about {percent_per_minute:.0f}% per "
                f"minute, currently {density:.1f} {context.density_unit}."
            ),
            metrics=metrics,
        )

    return _build(
        context,
        evidence_type=EvidenceType.CROWD_DISPERSING,
        indicator=StabilityIndicator.RATE_OF_CHANGE,
        # A thinning crowd carries no instability pressure by construction, so
        # this always reports as information rather than as a warning.
        pressure=0.0,
        threshold=0.0,
        headline="Crowd dispersing",
        detail=(
            f"Peak crowd density is falling at about {percent_per_minute:.0f}% per "
            f"minute, currently {density:.1f} {context.density_unit}."
        ),
        metrics=metrics,
    )


def observe_movement_slowing(context: ObservationContext) -> EvidenceItem | None:
    """Movement slowing - the crowd is moving below its own normal."""
    reading = context.reading(StabilityIndicator.MOTION_SUPPRESSION)
    if reading is None or reading.pressure is None or reading.raw_value is None:
        return None
    if reading.pressure < context.config.movement_slowing_pressure:
        return None

    return _build(
        context,
        evidence_type=EvidenceType.MOVEMENT_SLOWING,
        indicator=StabilityIndicator.MOTION_SUPPRESSION,
        pressure=reading.pressure,
        threshold=context.config.movement_slowing_pressure,
        headline="Movement slowing",
        detail=(
            f"Median walking speed is {(1.0 - reading.raw_value) * 100:.0f}% below "
            "the recent baseline for this camera."
        ),
        metrics=_speed_metrics(context),
    )


def observe_stationary_cluster(context: ObservationContext) -> EvidenceItem | None:
    """A stationary cluster - people packed together and largely not moving.

    Requires both suppressed movement *and* raised density. Either alone is
    ordinary: a quiet platform is still, and a busy one moving freely is dense.
    Together they describe a crowd that has stopped being able to move, which
    is the condition worth naming.
    """
    motion = context.pressure(StabilityIndicator.MOTION_SUPPRESSION)
    density_reading = context.reading(StabilityIndicator.DENSITY_PRESSURE)
    if motion is None or density_reading is None or density_reading.pressure is None:
        return None
    if motion < context.config.stationary_motion_pressure:
        return None
    if density_reading.pressure < context.config.stationary_density_pressure:
        return None

    where = _peak_region(context.crowd)
    return _build(
        context,
        evidence_type=EvidenceType.STATIONARY_CLUSTER,
        indicator=StabilityIndicator.MOTION_SUPPRESSION,
        pressure=max(motion, density_reading.pressure),
        threshold=context.config.stationary_motion_pressure,
        headline=(
            f"Stationary cluster in the {where}" if where else "Stationary cluster identified"
        ),
        detail=(
            f"A dense group has largely stopped moving at "
            f"{(density_reading.raw_value or 0.0):.1f} {context.density_unit}"
            + (f" in the {where} of the camera view." if where else ".")
        ),
        metrics=(
            *_speed_metrics(context),
            SupportingMetric(
                label="Peak density",
                value=density_reading.raw_value or 0.0,
                unit=context.density_unit,
            ),
        ),
    )


def observe_flow_conflict(context: ObservationContext) -> EvidenceItem | None:
    """Flow becoming unstable - part of the crowd is moving against the majority."""
    reading = context.reading(StabilityIndicator.FLOW_CONFLICT)
    if reading is None or reading.pressure is None or reading.raw_value is None:
        return None
    if reading.pressure < context.config.flow_conflict_pressure:
        return None

    return _build(
        context,
        evidence_type=EvidenceType.FLOW_CONFLICT,
        indicator=StabilityIndicator.FLOW_CONFLICT,
        pressure=reading.pressure,
        threshold=context.config.flow_conflict_pressure,
        headline="Opposing movement detected",
        detail=(
            f"{reading.raw_value * 100:.0f}% of moving people are travelling against "
            "the main direction of the crowd."
        ),
        metrics=(
            SupportingMetric(
                label="Opposing movement", value=reading.raw_value * 100.0, unit="%"
            ),
            SupportingMetric(
                label="Main direction",
                value=context.crowd.flow.dominant_heading_deg or 0.0,
                unit="deg",
            ),
        ),
    )


def observe_egress_congestion(context: ObservationContext) -> EvidenceItem | None:
    """An exit approaching its capacity.

    The only observation permitted to name infrastructure, and only because an
    operator has configured that exit as a zone. The platform never names a
    gate it has not been told about (Architecture Review C26).
    """
    reading = context.reading(StabilityIndicator.EGRESS_CONGESTION)
    if reading is None or reading.pressure is None or reading.raw_value is None:
        return None
    if reading.pressure < context.config.egress_pressure:
        return None

    zone_id, zone_name = _worst_exit(context)
    location = f" at {zone_name}" if zone_name else ""

    return _build(
        context,
        evidence_type=EvidenceType.EGRESS_CONGESTION,
        indicator=StabilityIndicator.EGRESS_CONGESTION,
        pressure=reading.pressure,
        threshold=context.config.egress_pressure,
        headline=f"Exit congestion{location}",
        detail=(
            f"Occupancy{location} is at {reading.raw_value * 100:.0f}% of its "
            "nominal capacity."
        ),
        metrics=(
            SupportingMetric(
                label="Exit occupancy", value=reading.raw_value * 100.0, unit="% of capacity"
            ),
        ),
        zone_id=zone_id,
    )


def observe_conditions_nominal(context: ObservationContext) -> EvidenceItem:
    """No abnormal behaviour observed.

    Produced unconditionally and used by the engine only when nothing else
    survived filtering. A calm scene should say so: "nothing is wrong" and "the
    platform has nothing to say" are indistinguishable on an empty panel, and
    only one of them is reassuring.
    """
    measured = tuple(
        reading.indicator for reading in context.stability.breakdown.available_readings
    )
    return _build(
        context,
        evidence_type=EvidenceType.CONDITIONS_NOMINAL,
        indicator=None,
        pressure=0.0,
        threshold=0.0,
        headline="No abnormal behaviour",
        detail=(
            f"{len(measured)} of 5 stability indicators are being measured and none "
            f"has crossed its reporting threshold. Crowd Stability Index is "
            f"{context.stability.csi_smoothed:.0f}."
        ),
        metrics=(
            SupportingMetric(
                label="Crowd Stability Index",
                value=context.stability.csi_smoothed,
                unit="",
            ),
            SupportingMetric(
                label="People in view", value=float(context.crowd.person_count), unit=""
            ),
        ),
    )


#: Every observer that reports an abnormal condition, in no significant order -
#: ranking happens after the fact, from measured contribution rather than from
#: the order they happen to be listed in here.
OBSERVERS = (
    observe_congestion,
    observe_occupancy_trend,
    observe_movement_slowing,
    observe_stationary_cluster,
    observe_flow_conflict,
    observe_egress_congestion,
)


# ---------------------------------------------------------------------------
# Shared construction
# ---------------------------------------------------------------------------


def _build(
    context: ObservationContext,
    *,
    evidence_type: EvidenceType,
    indicator: StabilityIndicator | None,
    pressure: float,
    threshold: float,
    headline: str,
    detail: str,
    metrics: tuple[SupportingMetric, ...],
    zone_id: str | None = None,
) -> EvidenceItem:
    """Assemble an observation, deriving its severity and confidence.

    Both are derived rather than chosen per observation. A severity table
    written by hand once per observation type is a table that drifts; deriving
    severity from the same pressure that drives the index means the two can
    never disagree about how serious something is.
    """
    return EvidenceItem(
        evidence_type=evidence_type,
        severity=_severity_for(pressure, context.config),
        confidence=_confidence_for(pressure, threshold, context),
        headline=headline,
        detail=detail,
        metrics=metrics,
        observed_at=context.stability.frame_ts,
        frame_seq=context.stability.frame_seq,
        zone_id=zone_id,
        indicator=indicator,
    )


def _severity_for(pressure: float, config: EvidenceConfig) -> Severity:
    """Display severity, from the same pressure the index is built on."""
    if pressure >= config.critical_pressure:
        return Severity.CRITICAL
    if pressure >= config.warning_pressure:
        return Severity.WARNING
    return Severity.INFO


def _confidence_for(pressure: float, threshold: float, context: ObservationContext) -> float:
    """How certain this observation is.

    The Decision Confidence of the assessment - the measurable data quality
    everything in this window rests on - reduced by how narrowly the
    measurement cleared its own threshold. A reading a hair past the line is
    genuinely less certain than one far past it, and reporting both at the same
    confidence would waste the distinction.
    """
    span = 100.0 - threshold
    margin = (pressure - threshold) / span if span > 0 else 1.0
    floor = context.config.margin_floor
    scaled = floor + (1.0 - floor) * min(max(margin, 0.0), 1.0)
    return min(max(context.stability.confidence.value * scaled, 0.0), 1.0)


def _speed_metrics(context: ObservationContext) -> tuple[SupportingMetric, ...]:
    """Median speed against its baseline, in whichever space it was measured."""
    flow = context.crowd.flow
    unit = "m/s" if context.crowd.is_metric else "px/s"
    if flow.median_speed is None:
        return ()
    return (
        SupportingMetric(
            label="Median speed",
            value=flow.median_speed,
            unit=unit,
            baseline=flow.baseline_speed,
        ),
    )


def _worst_exit(context: ObservationContext) -> tuple[str | None, str | None]:
    """The most congested configured EXIT zone, as ``(zone_id, name)``.

    Matches the indicator, which also takes the worst exit rather than the
    average: an evacuation is limited by its most congested route.
    """
    exit_ids = {zone.zone_id for zone in context.camera.zones_of_type(ZoneType.EXIT)}
    candidates = [
        occupancy
        for occupancy in context.crowd.zone_occupancy
        if occupancy.zone_id in exit_ids and occupancy.capacity_ratio is not None
    ]
    if not candidates:
        return (None, None)

    worst = max(candidates, key=lambda occupancy: occupancy.capacity_ratio or 0.0)
    name = next(
        (zone.name for zone in context.camera.zones if zone.zone_id == worst.zone_id),
        None,
    )
    return (worst.zone_id, name)


def _peak_region(crowd: CrowdMetrics) -> str | None:
    """Where in the camera view the densest cell sits, in plain words.

    Describes the *view*, never the venue. "The lower centre of the camera
    view" is something the platform genuinely knows; "near Exit A" is not,
    unless an operator has drawn Exit A as a zone.
    """
    occupied = [cell for cell in crowd.density_map.cells if cell.persons > 0]
    if not occupied:
        return None

    peak = max(occupied, key=lambda cell: cell.density)
    vertical = _third(peak.row, crowd.density_map.rows, ("upper", "middle", "lower"))
    horizontal = _third(peak.col, crowd.density_map.cols, ("left", "centre", "right"))

    if vertical == "middle" and horizontal == "centre":
        return "centre"
    return f"{vertical} {horizontal}"


def _third(index: int, total: int, labels: tuple[str, str, str]) -> str:
    """Which third of a range an index falls in."""
    if total <= 1:
        return labels[1]
    position = index / (total - 1)
    if position < 1 / 3:
        return labels[0]
    if position < 2 / 3:
        return labels[1]
    return labels[2]
