"""The Crowd Stability Index engine - Stage 6 (``05:449-486``).

::

    CSI = clamp( 100 - SUM( w_i * p_i ), 0, 100 )

Five indicators, each contributing a normalized instability *pressure* that is
subtracted from a perfect score. The index is therefore a **stability** figure:
100 is a completely stable crowd and 0 is critical operational risk
(``16:30-38``). That polarity is not arbitrary - a stability score that falls
as conditions worsen reads correctly on a gauge, and choosing stability over a
"stampede probability" is what keeps the platform's headline number
operationally meaningful rather than an unfalsifiable prediction
(``05:132-138``).

**Deterministic, and deliberately not learned.** Every value is a weighted sum
of measurements against declared thresholds. There is no model here and no
training data, which is what makes the score explainable to an operator, to a
safety professional, and to an auditor after an incident - and what lets the
platform state *why* the number is what it is rather than merely asserting it.
"""

from __future__ import annotations

from collections import deque

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.enums import StabilityIndicator
from ..contracts.stability import (
    IndicatorBreakdown,
    IndicatorReading,
    PerceptionQuality,
    StabilityAssessment,
)
from ..errors import StabilityAssessmentError
from . import indicators
from .assessor import StabilityAssessor
from .confidence import assess_confidence
from .config import CsiConfig
from .indicators import IndicatorMeasurement
from .smoothing import BandHysteresis, ExponentialSmoother

__all__ = ["WeightedStabilityAssessor"]


class WeightedStabilityAssessor(StabilityAssessor):
    """Computes the Crowd Stability Index from crowd measurements.

    Stateful in three ways, each of which is load-bearing:

    - **Smoothing** - the reported index is an exponential moving average, so
      the gauge moves rather than jumping.
    - **Hysteresis** - a band change must hold for several windows, so the
      Operational Status does not flicker at a boundary.
    - **Trend** - rate of change is measured across windows, which is what lets
      the platform say conditions are developing before they have developed.

    All three are discarded by :meth:`reset`. Without that, the index from
    previous material bleeds into a new source - the specific defect that would
    make a scenario reset or a Live/Demo switch misleading.
    """

    def __init__(self, config: CsiConfig | None = None) -> None:
        self._config = config or CsiConfig()
        self._weights = self._config.weights.as_mapping()

        self._smoother = ExponentialSmoother(self._config.smoothing_seconds)
        self._hysteresis = BandHysteresis(
            escalate_windows=self._config.escalate_windows,
            de_escalate_windows=self._config.de_escalate_windows,
        )
        self._density_history: deque[tuple[float, float]] = deque()

    @property
    def config(self) -> CsiConfig:
        """The configuration in force, so a caller can report what it measured with."""
        return self._config

    # -- Assessment ---------------------------------------------------------

    def assess(
        self,
        crowd: CrowdMetrics,
        camera: CameraConfig,
        quality: PerceptionQuality,
    ) -> StabilityAssessment:
        """Assess crowd stability for one analysis window."""
        try:
            return self._assess(crowd, camera, quality)
        except StabilityAssessmentError:
            raise
        except Exception as error:  # noqa: BLE001 - surfaced as the stage's own failure
            raise StabilityAssessmentError(f"Stability assessment failed: {error}") from error

    def _assess(
        self, crowd: CrowdMetrics, camera: CameraConfig, quality: PerceptionQuality
    ) -> StabilityAssessment:
        timestamp = crowd.frame_ts.timestamp()
        signed_rate = self._update_trend(crowd.density_max, timestamp)

        measurements = self._measure(crowd, camera, signed_rate)
        readings = self._weigh(measurements)

        available_weight = sum(reading.weight for reading in readings)
        if available_weight <= 0.0:
            # Every indicator was unmeasurable. Resolving that into CSI 100
            # would report a perfectly stable crowd on the strength of having
            # measured nothing at all, which is the exact inversion of what an
            # absent measurement means.
            raise StabilityAssessmentError(
                "No stability indicator could be measured for this window."
            )

        total_pressure = sum(reading.contribution for reading in readings)
        csi_raw = _clamp(100.0 - total_pressure, 0.0, 100.0)
        csi_smoothed = self._smoother.update(csi_raw, timestamp)
        transition = self._hysteresis.offer(csi_smoothed)

        return StabilityAssessment(
            frame_seq=crowd.frame_seq,
            frame_ts=crowd.frame_ts,
            csi_raw=csi_raw,
            csi_smoothed=csi_smoothed,
            status=transition.status,
            status_changed=transition.changed,
            breakdown=IndicatorBreakdown(readings=readings),
            confidence=assess_confidence(
                quality,
                count_method=crowd.count_method,
                temporal_fill=self._smoother.fill_fraction,
                config=self._config.confidence,
            ),
        )

    def reset(self) -> None:
        """Discard smoothing state, hysteresis counters and trend history."""
        self._smoother.reset()
        self._hysteresis.reset()
        self._density_history.clear()

    # -- Indicators ---------------------------------------------------------

    def _measure(
        self, crowd: CrowdMetrics, camera: CameraConfig, signed_rate: float | None
    ) -> dict[StabilityIndicator, IndicatorMeasurement]:
        """Measure all five indicators for one window.

        Density is measured first because flow conflict is density-weighted and
        needs its pressure. That is the only ordering dependency between
        indicators; every other one is independent by construction.
        """
        density = indicators.density_pressure(crowd, self._config)

        return {
            StabilityIndicator.DENSITY_PRESSURE: density,
            StabilityIndicator.MOTION_SUPPRESSION: indicators.motion_suppression(
                crowd, self._config
            ),
            StabilityIndicator.EGRESS_CONGESTION: indicators.egress_congestion(
                crowd, camera, self._config
            ),
            StabilityIndicator.FLOW_CONFLICT: indicators.flow_conflict(
                crowd, self._config, density_pressure_value=density.pressure
            ),
            StabilityIndicator.RATE_OF_CHANGE: indicators.rate_of_change(
                signed_rate, crowd, self._config
            ),
        }

    def _weigh(
        self, measurements: dict[StabilityIndicator, IndicatorMeasurement]
    ) -> tuple[IndicatorReading, ...]:
        """Turn measurements into readings, renormalizing over what was available.

        An indicator that could not be measured contributes nothing *and*
        surrenders its weight to the others. The alternative - leaving its
        weight in place with zero pressure - would let an unmeasurable
        indicator quietly certify stability it never observed, which is the
        subtlest way a safety index can lie.
        """
        available_total = sum(
            self._weights[indicator]
            for indicator, measurement in measurements.items()
            if measurement.available
        )

        readings: list[IndicatorReading] = []
        for indicator, measurement in measurements.items():
            weight = (
                self._weights[indicator] / available_total
                if measurement.available and available_total > 0.0
                else 0.0
            )
            readings.append(
                IndicatorReading(
                    indicator=indicator,
                    available=measurement.available,
                    raw_value=measurement.raw_value,
                    pressure=measurement.pressure,
                    weight=weight,
                    unavailable_reason=measurement.unavailable_reason,
                )
            )
        return tuple(readings)

    # -- Trend --------------------------------------------------------------

    def _update_trend(self, density_max: float, timestamp: float) -> float | None:
        """Record peak density and return its rate of change, per second.

        Signed: a negative rate means the crowd is thinning. The index uses
        only the positive part - a dispersing crowd is not an unstable one -
        but the sign is what lets the Evidence Engine distinguish *"occupancy
        increasing"* from *"crowd dispersing"* without measuring density twice.
        """
        history = self._density_history

        if history and timestamp <= history[-1][0]:
            # Out-of-order or duplicate frame. Appending would produce a
            # negative or infinite span; ignoring the sample is the only safe
            # response.
            return self._rate_from(history)

        history.append((timestamp, density_max))
        cutoff = timestamp - self._config.rate_window_seconds
        while history and history[0][0] < cutoff:
            history.popleft()

        return self._rate_from(history)

    def _rate_from(self, history: deque[tuple[float, float]]) -> float | None:
        """Rate of change across the retained window, or ``None`` if too short."""
        if len(history) < 2:
            return None

        (first_time, first_density) = history[0]
        (last_time, last_density) = history[-1]
        span = last_time - first_time
        if span < self._config.rate_min_span_seconds:
            return None
        return (last_density - first_density) / span


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)
