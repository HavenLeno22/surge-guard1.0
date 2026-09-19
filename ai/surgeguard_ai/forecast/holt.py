"""Holt's linear trend method - double exponential smoothing with a trend term.

Chosen over a plain rolling average because a rolling average has no trend term
at all: it answers "how long has the queue been recently", which is not a
forecast. Chosen over linear regression because regression weights a reading
from ten minutes ago exactly as heavily as one from ten seconds ago, and a queue
that has just started surging is precisely the case where that is wrong.

Chosen over an ML model because there is not yet any history to train one on, and
a model fitted to a handful of minutes of a single camera would be a far more
elaborate way of being wrong. The forecaster sits behind an interface so a
trained model can replace this later without disturbing anything above it.

The recurrence, on an evenly spaced series ``y``:

    level_t = alpha * y_t + (1 - alpha) * (level_(t-1) + trend_(t-1))
    trend_t = beta * (level_t - level_(t-1)) + (1 - beta) * trend_(t-1)
    forecast(h) = level_t + h * trend_t
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["HoltState", "fit_holt"]


class HoltState:
    """The fitted state of a Holt model, and what it can say about the future."""

    __slots__ = ("level", "trend", "residual_std", "observations")

    def __init__(
        self, level: float, trend: float, residual_std: float, observations: int
    ) -> None:
        self.level = level
        """Smoothed current value, with noise removed."""
        self.trend = trend
        """Smoothed change per step."""
        self.residual_std = residual_std
        """Standard deviation of one-step-ahead errors while fitting.

        This is the model's own record of how wrong it has been, which is a far
        better basis for a prediction interval than any assumed figure.
        """
        self.observations = observations

    def project(self, steps: float) -> float:
        """Forecast ``steps`` ahead. Clamped at zero - a queue cannot be negative."""
        return max(0.0, self.level + steps * self.trend)

    def interval(self, steps: float, z: float = 1.96) -> tuple[float, float]:
        """Prediction interval ``steps`` ahead.

        The interval widens as ``sqrt(steps)``: errors accumulate like a random
        walk, so uncertainty grows with the square root of the horizon rather
        than linearly. A forecast fifteen minutes out is genuinely less certain
        than one five minutes out, and drawing them with the same band would
        misrepresent that.
        """
        centre = self.project(steps)
        spread = z * self.residual_std * math.sqrt(max(1.0, steps))
        return max(0.0, centre - spread), max(0.0, centre + spread)


def fit_holt(
    series: Sequence[float], *, alpha: float = 0.3, beta: float = 0.1
) -> HoltState | None:
    """Fit Holt's linear trend to an evenly spaced series.

    Returns ``None`` for fewer than three points: two points define a trend with
    no residual at all, which would produce a confident-looking forecast with a
    zero-width interval off the back of a single observed change.

    Args:
        series: Evenly spaced observations, oldest first.
        alpha: Level smoothing, in ``(0, 1]``. Higher follows recent readings
            more closely and is noisier.
        beta: Trend smoothing, in ``(0, 1]``. Deliberately lower than ``alpha``
            by default: trend estimates are far noisier than level estimates, and
            an over-responsive trend term extrapolates a two-person fluctuation
            into a crisis.
    """
    if len(series) < 3:
        return None
    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must lie in (0, 1]")
    if not 0.0 < beta <= 1.0:
        raise ValueError("beta must lie in (0, 1]")

    level = float(series[0])
    trend = float(series[1]) - float(series[0])

    squared_error = 0.0
    residuals = 0

    for value in series[1:]:
        # One-step-ahead prediction made before seeing this value - the only
        # honest basis for a residual.
        predicted = level + trend
        error = float(value) - predicted
        squared_error += error * error
        residuals += 1

        previous_level = level
        level = alpha * float(value) + (1.0 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1.0 - beta) * trend

    residual_std = math.sqrt(squared_error / residuals) if residuals else 0.0

    return HoltState(
        level=level,
        trend=trend,
        residual_std=residual_std,
        observations=len(series),
    )
