"""Forecast contracts - what the platform expects to happen next.

Kept strictly separate from :mod:`.queue`, which describes what is happening
now. Problem Statement 9 requires real-time, predicted and recommended figures
to be distinguishable at a glance, and they cannot be if one structure carries
more than one of them.

Two forecasting methods run on every window and both are reported. They rest on
different assumptions:

- **Trend** extrapolates the observed queue length. It knows nothing about why
  the queue is that length, so it follows a surge faithfully and keeps following
  it after the surge ends.
- **Flow balance** integrates arrivals minus departures. It is grounded in
  mechanism, so it turns when the mechanism turns - but it inherits every error
  in the measured rates.

When they agree, the forecast is trustworthy. When they disagree, that is
genuine information about how well understood the situation is, and the
interface shows the disagreement rather than averaging it into a single number
that conceals it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import ForecastMethod, GrowthPattern

__all__ = [
    "ForecastPoint",
    "MethodForecast",
    "GrowthAssessment",
    "QueueForecast",
    "ForecastReport",
]


class ForecastPoint(Contract):
    """Expected queue length at one horizon, with its uncertainty."""

    horizon_minutes: int = Field(
        gt=0, description="Minutes ahead of the observation this projects to."
    )
    at: datetime = Field(description="Wall-clock moment this point projects to.")

    expected: float = Field(
        ge=0.0, description="Expected queue length, in people."
    )
    lower: float = Field(
        ge=0.0,
        description=(
            "Lower bound of the prediction interval. Widens with horizon, "
            "because a forecast fifteen minutes out genuinely is less certain "
            "than one five minutes out and must not be drawn as though it were."
        ),
    )
    upper: float = Field(ge=0.0, description="Upper bound of the prediction interval.")

    @property
    def interval_width(self) -> float:
        """Span of the prediction interval - how unsure this point is."""
        return self.upper - self.lower


class MethodForecast(Contract):
    """One method's complete projection, kept alongside the consensus.

    Retained rather than discarded so that a forecast can always be answered
    with "the trend says 61, the flow balance says 48, and here is why they
    differ" instead of a single unexplainable number.
    """

    method: ForecastMethod
    points: tuple[ForecastPoint, ...] = Field(default=())
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How much weight this method's own inputs justify.",
    )
    unavailable_reason: str | None = Field(
        default=None,
        description=(
            "Why this method produced nothing, when it produced nothing - too "
            "little history, or no measured rates yet. Displayed rather than "
            "hidden, so a missing line on the chart has a stated cause."
        ),
    )

    @property
    def available(self) -> bool:
        return bool(self.points)

    def at_horizon(self, minutes: int) -> ForecastPoint | None:
        for point in self.points:
            if point.horizon_minutes == minutes:
                return point
        return None


class GrowthAssessment(Contract):
    """Whether the queue is growing abnormally, judged against its own baseline.

    This is the Problem Statement 9 abnormal-growth requirement, and it is keyed
    to **rate against baseline** rather than to size. A large stable queue is
    normal and stays quiet; a small queue growing far faster than it usually does
    raises the alarm. Those are the correct behaviours in that order of
    importance.
    """

    pattern: GrowthPattern
    growth_rate_per_min: float = Field(
        description=(
            "Current rate of change in people per minute. Negative when the "
            "queue is shrinking."
        )
    )
    baseline_rate_per_min: float | None = Field(
        default=None,
        description=(
            "What this queue's rate of change normally is. None until enough "
            "history exists to know."
        ),
    )
    baseline_std: float | None = Field(
        default=None,
        ge=0.0,
        description="Spread of the baseline, the scale a deviation is judged on.",
    )
    z_score: float | None = Field(
        default=None,
        description=(
            "How many baseline standard deviations the current rate sits above "
            "normal. The quantity the abnormality decision is actually made on."
        ),
    )

    change_pct: float | None = Field(
        default=None,
        description="Percentage change in queue length over the comparison window.",
    )
    window_minutes: float = Field(
        ge=0.0, description="Window the change was measured over."
    )
    samples: int = Field(ge=0, description="Baseline samples accumulated so far.")

    explanation: str = Field(
        description=(
            "Operator-readable reason, derived from the measurement that "
            "triggered it - never an authored phrase like 'AI detected danger'."
        )
    )

    @property
    def is_abnormal(self) -> bool:
        return self.pattern is GrowthPattern.ABNORMAL_GROWTH


class QueueForecast(Contract):
    """The complete forward view for one queue zone."""

    zone_id: str
    zone_name: str
    generated_at: datetime
    frame_ts: datetime

    current_length: int = Field(
        ge=0, description="Observed queue length this forecast starts from."
    )

    points: tuple[ForecastPoint, ...] = Field(
        default=(),
        description=(
            "The headline consensus forecast, one point per configured horizon. "
            "Empty when neither method could run."
        ),
    )
    methods: tuple[MethodForecast, ...] = Field(
        default=(),
        description="Each method's own projection, including unavailable ones.",
    )
    method_agreement: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "How closely the two methods agree at the furthest horizon, as "
            "1 - |difference| / max(expected). 1.0 is exact agreement. Shown to "
            "the operator: a confident-looking forecast the two methods disagree "
            "about deserves less trust than its interval alone suggests."
        ),
    )

    growth: GrowthAssessment
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall confidence, from history depth, rate quality and agreement.",
    )
    assumptions: tuple[str, ...] = Field(
        default=(),
        description="What this forecast takes for granted, in operator language.",
    )
    observation_minutes: float = Field(
        ge=0.0, description="How long this queue has been observed."
    )

    def at_horizon(self, minutes: int) -> ForecastPoint | None:
        """The consensus point at one horizon, or None when not forecast."""
        for point in self.points:
            if point.horizon_minutes == minutes:
                return point
        return None

    def method(self, method: ForecastMethod) -> MethodForecast | None:
        for entry in self.methods:
            if entry.method is method:
                return entry
        return None

    @property
    def peak(self) -> ForecastPoint | None:
        """The highest forecast point - when the queue is expected to be worst."""
        return max(self.points, key=lambda p: p.expected, default=None)


class ForecastReport(Contract):
    """Forecasts for every queue zone on one camera, for one analysis window."""

    frame_seq: int = Field(ge=0)
    frame_ts: datetime
    forecasts: tuple[QueueForecast, ...] = Field(default=())

    def by_zone(self, zone_id: str) -> QueueForecast | None:
        for forecast in self.forecasts:
            if forecast.zone_id == zone_id:
                return forecast
        return None

    @property
    def any_abnormal_growth(self) -> bool:
        """Whether any queue is growing abnormally - the alarm condition."""
        return any(forecast.growth.is_abnormal for forecast in self.forecasts)
