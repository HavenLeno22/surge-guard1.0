"""Crowd Stability Index configuration.

``16:142-168`` requires that weights be configurable per deployment and **not
hardcoded**. Everything the CSI computation depends on therefore lives here:
weights, normalization curves, ceilings, the smoothing time constant and the
hysteresis counts. The engine itself contains no numbers.

Defaults are the specification frozen in ``02_Hackathon_Execution_Plan.md``
section 4. They are defaults, not constants - a venue with a different geometry
is expected to change them, which is the entire reason this module exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..contracts.enums import StabilityIndicator

__all__ = [
    "IndicatorWeights",
    "NormalizationCurve",
    "ConfidenceConfig",
    "CsiConfig",
    "METRIC_DENSITY_CURVE",
    "RELATIVE_DENSITY_CURVE",
]


@dataclass(frozen=True, slots=True)
class NormalizationCurve:
    """A piecewise-linear map from a measurement to instability pressure.

    Expressed as knots rather than as a formula so that the shape is readable
    and auditable: an operator asking "what density counts as critical?" can be
    shown this table, which is not true of a polynomial fit.

    Below the first knot the pressure is the first knot's; above the last, the
    last knot's. Both are held rather than extrapolated - a curve anchored to
    published guidance says nothing about what lies past its last anchor, and
    extrapolating would invent a claim the anchoring does not support.
    """

    knots: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.knots) < 2:
            raise ValueError("A normalization curve needs at least two knots")
        measurements = [measurement for measurement, _ in self.knots]
        if measurements != sorted(measurements):
            raise ValueError("Normalization curve knots must be ordered by measurement")
        for _, pressure in self.knots:
            if not 0.0 <= pressure <= 100.0:
                raise ValueError("Normalization curve pressures must be within [0, 100]")

    def pressure_for(self, measurement: float) -> float:
        """Instability pressure, 0-100, for one measurement."""
        first_measurement, first_pressure = self.knots[0]
        if measurement <= first_measurement:
            return first_pressure

        last_measurement, last_pressure = self.knots[-1]
        if measurement >= last_measurement:
            return last_pressure

        for (x0, y0), (x1, y1) in zip(self.knots, self.knots[1:], strict=False):
            if x0 <= measurement <= x1:
                if math.isclose(x1, x0):
                    return y1
                return y0 + (y1 - y0) * (measurement - x0) / (x1 - x0)
        return last_pressure  # pragma: no cover - unreachable given the bounds above


#: Density pressure for a **calibrated** camera, in persons/m2.
#:
#: Anchored to published crowd-safety density guidance (Fruin's levels of
#: service and Still's density work), which is what makes the Crowd Stability
#: Index defensible to a safety professional rather than a plausible-looking
#: number (Architecture Review §9.1). Frozen at ``02`` section 4: at or below
#: 2 p/m2 movement is free; 4 p/m2 is where free movement stops; beyond 5 p/m2
#: is where crowd-crush literature places the onset of danger.
METRIC_DENSITY_CURVE = NormalizationCurve(
    knots=((2.0, 0.0), (4.0, 50.0), (5.0, 80.0), (6.0, 100.0)),
)

#: Density pressure for an **uncalibrated** camera, in persons per grid cell.
#:
#: Carries none of the published-threshold anchoring above and is not
#: comparable across cameras or across view changes - it is a per-deployment
#: heuristic that must be tuned against the actual view. It exists because the
#: alternative, dropping density from the index entirely whenever a camera is
#: uncalibrated, removes the single largest contributor and leaves the score
#: driven by movement alone. The interface labels values from this curve
#: *relative* and never as persons/m2 (Architecture Review C21).
#:
#: Calibrated so that an ordinary scene reads as ordinary: with the default
#: 6x8 grid a cell is an eighth of the view across, so one person in the
#: busiest cell is unremarkable, three is a group standing together, and six is
#: a cell that cannot hold more. A curve that treated two people sharing a cell
#: as congestion would raise the index's largest contributor on nearly every
#: frame, which trains an operator to ignore it.
RELATIVE_DENSITY_CURVE = NormalizationCurve(
    knots=((1.0, 0.0), (3.0, 50.0), (4.5, 80.0), (6.0, 100.0)),
)


@dataclass(frozen=True, slots=True)
class IndicatorWeights:
    """How much each indicator contributes to the Crowd Stability Index.

    Must sum to 1. The weights are renormalized at assessment time over
    whichever indicators could actually be measured, so an unmeasurable
    indicator lowers confidence rather than silently biasing the score toward
    stability.
    """

    density_pressure: float = 0.35
    motion_suppression: float = 0.20
    egress_congestion: float = 0.20
    flow_conflict: float = 0.15
    rate_of_change: float = 0.10

    def __post_init__(self) -> None:
        for value in self.as_mapping().values():
            if value < 0.0:
                raise ValueError("Indicator weights must not be negative")
        total = sum(self.as_mapping().values())
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"Indicator weights must sum to 1.0, got {total}")

    def as_mapping(self) -> dict[StabilityIndicator, float]:
        """The weights keyed by indicator, in the frozen specification's order."""
        return {
            StabilityIndicator.DENSITY_PRESSURE: self.density_pressure,
            StabilityIndicator.MOTION_SUPPRESSION: self.motion_suppression,
            StabilityIndicator.EGRESS_CONGESTION: self.egress_congestion,
            StabilityIndicator.FLOW_CONFLICT: self.flow_conflict,
            StabilityIndicator.RATE_OF_CHANGE: self.rate_of_change,
        }


@dataclass(frozen=True, slots=True)
class ConfidenceConfig:
    """Thresholds for the three Decision Confidence factors.

    Decision Confidence is a product of measurable data quality, never an
    asserted number (Architecture Review C5). These are the values that turn
    each raw measurement into a factor in ``[0, 1]``.

    Attributes:
        detection_floor: Mean detection confidence at or below which detection
            quality scores zero. Set at the detector's own confidence threshold
            by default: a frame whose mean confidence sits at the threshold is
            made entirely of marginal detections.
        detection_target: Mean detection confidence at which detection quality
            scores one.
        track_age_target_frames: Mean track lifetime at which track stability
            scores one. Below it, identities are churning and every
            speed-derived indicator is being computed from short fragments.
        estimated_count_penalty: Multiplier applied to track stability when the
            count method is ``ESTIMATED``. Above the tracking ceiling the
            identities are not reliable, and the platform is required to lower
            confidence rather than continue displaying confident numbers
            (Architecture Review C11).
        degraded_penalty: Multiplier applied to detection quality when the
            perception stage reported itself degraded for this frame.
    """

    detection_floor: float = 0.35
    detection_target: float = 0.75
    track_age_target_frames: float = 15.0
    estimated_count_penalty: float = 0.5
    degraded_penalty: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.detection_floor < self.detection_target <= 1.0:
            raise ValueError("Require 0 <= detection_floor < detection_target <= 1")
        if self.track_age_target_frames <= 0:
            raise ValueError("track_age_target_frames must be positive")
        for penalty in (self.estimated_count_penalty, self.degraded_penalty):
            if not 0.0 <= penalty <= 1.0:
                raise ValueError("Confidence penalties must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class CsiConfig:
    """Everything the Crowd Stability Index computation depends on.

    Attributes:
        weights: Per-indicator weights. Must sum to 1.
        metric_density_curve: Density normalization for a calibrated camera.
        relative_density_curve: Density normalization for an uncalibrated one.
        egress_ceiling_ratio: Occupancy-to-capacity ratio at which egress
            congestion reaches full pressure. 1.0 means a zone at its nominal
            capacity is maximally congested.
        flow_conflict_ceiling: Opposing-track fraction at which flow conflict
            reaches full pressure. Half the crowd moving against the majority
            is total conflict; there is no meaningful "worse" beyond it,
            because past 50% the majority has simply changed.
        flow_density_floor: The share of flow-conflict pressure that applies
            regardless of how full the space is. The frozen specification calls
            for flow conflict to be density-weighted - two people passing in an
            empty concourse are not a conflict - but weighting it to zero at
            low density would discard the early warning that opposing movement
            provides before a space fills. The remainder scales with density
            pressure.
        rate_ceiling_metric: Rate of density change, in persons/m2 per second,
            at which rate of change reaches full pressure.
        rate_ceiling_relative: The same ceiling in persons per grid cell per
            second, for an uncalibrated camera.
        rate_window_seconds: Window over which density change is measured.
        rate_min_span_seconds: Time that must actually have been observed
            before a rate is reported. Two samples a fraction of a second apart
            produce an arithmetically valid and operationally meaningless rate;
            below this span the indicator is unavailable instead.
        smoothing_seconds: Time constant of the exponential moving average
            applied to the raw index. Frames do not arrive on a fixed clock, so
            the smoothing is time-based rather than sample-based - a dropped
            frame must not change how much history the reported value carries.
        escalate_windows: Consecutive windows a **more severe** band must hold
            before the Operational Status follows it.
        de_escalate_windows: Consecutive windows a **less severe** band must
            hold. Higher than ``escalate_windows`` on purpose: the platform
            should be quicker to warn than to reassure.
        confidence: Decision Confidence thresholds.
    """

    weights: IndicatorWeights = field(default_factory=IndicatorWeights)

    metric_density_curve: NormalizationCurve = METRIC_DENSITY_CURVE
    relative_density_curve: NormalizationCurve = RELATIVE_DENSITY_CURVE

    egress_ceiling_ratio: float = 1.0

    flow_conflict_ceiling: float = 0.5
    flow_density_floor: float = 0.4

    rate_ceiling_metric: float = 0.05
    rate_ceiling_relative: float = 0.05
    rate_window_seconds: float = 60.0
    rate_min_span_seconds: float = 10.0

    smoothing_seconds: float = 10.0

    escalate_windows: int = 3
    de_escalate_windows: int = 5

    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)

    def __post_init__(self) -> None:
        if self.egress_ceiling_ratio <= 0:
            raise ValueError("egress_ceiling_ratio must be positive")
        if not 0.0 < self.flow_conflict_ceiling <= 1.0:
            raise ValueError("flow_conflict_ceiling must be within (0, 1]")
        if not 0.0 <= self.flow_density_floor <= 1.0:
            raise ValueError("flow_density_floor must be within [0, 1]")
        if self.rate_ceiling_metric <= 0 or self.rate_ceiling_relative <= 0:
            raise ValueError("Rate ceilings must be positive")
        if self.rate_window_seconds <= 0:
            raise ValueError("rate_window_seconds must be positive")
        if not 0 < self.rate_min_span_seconds <= self.rate_window_seconds:
            raise ValueError("rate_min_span_seconds must be within (0, rate_window_seconds]")
        if self.smoothing_seconds <= 0:
            raise ValueError("smoothing_seconds must be positive")
        if self.escalate_windows < 1 or self.de_escalate_windows < 1:
            raise ValueError("Hysteresis window counts must be at least 1")

    def density_curve(self, *, is_metric: bool) -> NormalizationCurve:
        """The density normalization matching the units actually being measured."""
        return self.metric_density_curve if is_metric else self.relative_density_curve

    def rate_ceiling(self, *, is_metric: bool) -> float:
        """The rate-of-change ceiling matching the units actually being measured."""
        return self.rate_ceiling_metric if is_metric else self.rate_ceiling_relative
