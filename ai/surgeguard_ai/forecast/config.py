"""Tuning for the forecast engine."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ForecastConfig"]


@dataclass(frozen=True, slots=True)
class ForecastConfig:
    """How far ahead the platform looks, and how much it trusts each method.

    Attributes:
        horizons_minutes: Horizons to forecast, in minutes. Problem Statement 9
            asks for +5, +10 and +15.
        sample_interval_seconds: Resampling cadence. Ten seconds gives six
            samples a minute - frequent enough to catch a surge, coarse enough
            that per-frame detector noise averages out before the trend model
            ever sees it.
        max_samples: Retained samples. 360 at ten seconds is one hour, which is
            the span over which a venue's baseline is worth learning.

        alpha: Holt level smoothing.
        beta: Holt trend smoothing. Lower than alpha on purpose - see
            :func:`~surgeguard_ai.forecast.holt.fit_holt`.
        interval_z: Multiplier for the prediction interval. 1.96 is the 95%
            two-sided normal quantile.

        min_samples_for_trend: Samples before the trend method is offered at all.
        min_flow_observation_seconds: Observation before the flow-balance method
            is offered. Both exist so an early, badly-supported forecast is
            declined rather than shown with a wide interval and full confidence.

        growth_window_minutes: Window the growth rate and percentage change are
            measured over. Five minutes matches the phrasing Problem Statement 9
            uses. The baseline is built from this same windowed quantity - a
            baseline measured on a different scale to the judgement made against
            it would let its own noise swamp every real surge.
        growth_min_window_minutes: Shortest history the growth rate will be
            measured over. Below this no rate is reported at all; above it the
            window grows toward ``growth_window_minutes`` as history
            accumulates, so a queue can be assessed a minute after start-up
            rather than six.
        growth_alpha: Baseline learning rate. Low, because windowed rates
            sampled every few seconds are heavily autocorrelated - thirty
            near-duplicate samples at a higher rate would otherwise drag the
            baseline most of the way to a surge within the surge.
        growth_min_samples: Samples before any growth judgement is offered.
        growth_z_threshold: Standard deviations above baseline that count as
            abnormal.
        growth_min_rate_per_min: Absolute growth floor for an abnormal verdict,
            so a perfectly flat baseline cannot make one person joining look like
            a crisis.
    """

    horizons_minutes: tuple[int, ...] = (5, 10, 15)

    sample_interval_seconds: float = 10.0
    max_samples: int = 360

    alpha: float = 0.3
    beta: float = 0.1
    interval_z: float = 1.96

    min_samples_for_trend: int = 6
    min_flow_observation_seconds: float = 45.0

    growth_window_minutes: float = 5.0
    growth_min_window_minutes: float = 1.0
    growth_alpha: float = 0.02
    growth_min_samples: int = 12
    growth_z_threshold: float = 2.5
    growth_min_rate_per_min: float = 1.0

    def __post_init__(self) -> None:
        if not self.horizons_minutes:
            raise ValueError("At least one forecast horizon must be configured")
        if any(h <= 0 for h in self.horizons_minutes):
            raise ValueError("Forecast horizons must be positive")
        if list(self.horizons_minutes) != sorted(self.horizons_minutes):
            raise ValueError(
                "Forecast horizons must be in ascending order - the interface "
                "draws them in the order given"
            )
