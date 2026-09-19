"""The five Crowd Stability Index indicators.

Each function here answers one question about the crowd and returns a
normalized *instability pressure* in ``[0, 100]``, or an explicit statement
that it could not be measured. Nothing here holds state, reads a clock, or
knows about any other indicator: composition, weighting and smoothing all
belong to the assessor.

Keeping them separate and pure is what makes the index auditable. Each
measurement can be checked against a hand-computed value in isolation, which is
the only practical defence against the failure mode
``02_Hackathon_Execution_Plan.md`` section 7 names explicitly: *"A
plausible-looking wrong formula is undetectable by inspection and will
misbehave on stage."*
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.enums import ZoneType
from .config import CsiConfig

__all__ = [
    "IndicatorMeasurement",
    "density_pressure",
    "motion_suppression",
    "egress_congestion",
    "flow_conflict",
    "rate_of_change",
]


@dataclass(frozen=True, slots=True)
class IndicatorMeasurement:
    """One indicator's measurement, before weighting.

    Carries no weight: weights are renormalized over whichever indicators were
    available, which is a decision only the assessor - seeing all five - can
    make.
    """

    available: bool
    raw_value: float | None = None
    pressure: float | None = None
    unavailable_reason: str | None = None

    @classmethod
    def measured(cls, raw_value: float, pressure: float) -> IndicatorMeasurement:
        """A successful measurement, with its pressure clamped into range."""
        return cls(available=True, raw_value=raw_value, pressure=_clamp(pressure, 0.0, 100.0))

    @classmethod
    def unmeasurable(cls, reason: str) -> IndicatorMeasurement:
        """An indicator that could not be measured, and why.

        The reason is operator-facing: it is shown beside the index to explain
        why the assessment rests on four inputs rather than five, which is a
        thing an operator is entitled to know.
        """
        return cls(available=False, unavailable_reason=reason)


def density_pressure(crowd: CrowdMetrics, config: CsiConfig) -> IndicatorMeasurement:
    """How compressed the most crowded part of the view is.

    The largest single contributor to the index, and the only one grounded in
    published crowd-safety thresholds - but only when the camera is calibrated.
    Uncalibrated, the same shape of curve is applied to persons per grid cell
    and the result is *relative*: internally consistent and useful for trend,
    but carrying none of the external anchoring (Architecture Review C21).

    Peak rather than mean, deliberately. A crush happens in one place; a mean
    across the view would let a dangerous corner be averaged away by the empty
    space beside it.
    """
    curve = config.density_curve(is_metric=crowd.is_metric)
    return IndicatorMeasurement.measured(
        raw_value=crowd.density_max,
        pressure=curve.pressure_for(crowd.density_max),
    )


def motion_suppression(crowd: CrowdMetrics, config: CsiConfig) -> IndicatorMeasurement:
    """How far movement has fallen below this camera's own normal.

    Speed collapse under density is the classic precursor to a crowd incident:
    people stop being able to move before anything visibly goes wrong. Measured
    as a *ratio* against a rolling baseline rather than an absolute speed, which
    is what lets it work on an uncalibrated camera - the unit cancels - and what
    keeps it meaningful across venues where normal walking speed differs.
    """
    speed = crowd.flow.median_speed
    baseline = crowd.flow.baseline_speed

    if speed is None:
        return IndicatorMeasurement.unmeasurable(
            "Too few tracks carry movement for a speed to be measured."
        )
    if baseline is None or baseline <= 0.0:
        return IndicatorMeasurement.unmeasurable(
            "No movement baseline yet - still learning this camera's normal."
        )

    ratio = speed / baseline
    return IndicatorMeasurement.measured(
        raw_value=ratio,
        pressure=100.0 * _clamp(1.0 - ratio, 0.0, 1.0),
    )


def egress_congestion(
    crowd: CrowdMetrics, camera: CameraConfig, config: CsiConfig
) -> IndicatorMeasurement:
    """How full the exits are, against their nominal capacity.

    Unmeasurable without a configured EXIT zone that records its clear width -
    and reported as unmeasurable rather than as zero. Nothing tells the platform
    where an exit is until an operator draws one, and treating an unknown exit
    as an uncongested one would bias the index toward stability exactly where
    the risk concentrates (Architecture Review C26).
    """
    exits = camera.zones_of_type(ZoneType.EXIT)
    if not exits:
        return IndicatorMeasurement.unmeasurable(
            "No exit zone is configured for this camera."
        )

    exit_ids = {zone.zone_id for zone in exits}
    ratios = [
        occupancy.capacity_ratio
        for occupancy in crowd.zone_occupancy
        if occupancy.zone_id in exit_ids and occupancy.capacity_ratio is not None
    ]
    if not ratios:
        return IndicatorMeasurement.unmeasurable(
            "Exit zones have no recorded clear width, so capacity is unknown."
        )

    # The worst exit, not the average: an evacuation is limited by its most
    # congested route, and averaging would hide it behind the clear ones.
    peak = max(ratios)
    return IndicatorMeasurement.measured(
        raw_value=peak,
        pressure=100.0 * _clamp(peak / config.egress_ceiling_ratio, 0.0, 1.0),
    )


def flow_conflict(
    crowd: CrowdMetrics, config: CsiConfig, *, density_pressure_value: float | None
) -> IndicatorMeasurement:
    """How much of the crowd is moving against the majority.

    Density-weighted per the frozen specification: two people passing in an
    empty concourse are not a conflict, and the same fraction in a full one is.
    ``flow_density_floor`` sets how much of the pressure survives at zero
    density, so that opposing movement still registers as the early warning it
    is before a space fills.

    When density itself could not be measured the pressure is left
    unattenuated. Scaling by an unknown would be inventing the very quantity
    the attenuation is supposed to account for.
    """
    fraction = crowd.flow.opposing_fraction
    if fraction is None:
        return IndicatorMeasurement.unmeasurable(
            "No dominant direction of travel - too little movement to compare against."
        )

    base = 100.0 * _clamp(fraction / config.flow_conflict_ceiling, 0.0, 1.0)

    if density_pressure_value is None:
        attenuation = 1.0
    else:
        floor = config.flow_density_floor
        attenuation = floor + (1.0 - floor) * _clamp(density_pressure_value / 100.0, 0.0, 1.0)

    return IndicatorMeasurement.measured(raw_value=fraction, pressure=base * attenuation)


def rate_of_change(
    signed_rate: float | None, crowd: CrowdMetrics, config: CsiConfig
) -> IndicatorMeasurement:
    """How fast conditions are worsening.

    The early-warning term, and the reason the platform can say something is
    developing before it has developed. Only *rising* density produces pressure:
    a dispersing crowd is not an unstable one, and letting a negative rate push
    the index upward would reward the platform for a crowd that has already
    left.

    The signed rate is still reported as ``raw_value``, because "conditions are
    improving" is a fact the Evidence Engine needs and the index does not use.
    """
    if signed_rate is None:
        return IndicatorMeasurement.unmeasurable(
            "Not enough history yet to measure how conditions are changing."
        )

    ceiling = config.rate_ceiling(is_metric=crowd.is_metric)
    return IndicatorMeasurement.measured(
        raw_value=signed_rate,
        pressure=100.0 * _clamp(max(signed_rate, 0.0) / ceiling, 0.0, 1.0),
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)
