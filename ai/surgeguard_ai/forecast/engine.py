"""The queue forecast engine.

Consumes :class:`~surgeguard_ai.contracts.queue.QueueReport` windows and produces
:class:`~surgeguard_ai.contracts.forecast.ForecastReport`: where each queue is
expected to be at +5, +10 and +15 minutes, how confident that is, and whether the
queue is growing abnormally.

Two methods run on every window (see the module docstring of
:mod:`surgeguard_ai.contracts.forecast` for why both are kept):

- **Trend** - Holt's linear trend over the resampled queue length.
- **Flow balance** - integrating ``arrivals - departures`` forward.

The headline figure is a confidence-weighted consensus of the two, and their
level of agreement is reported alongside it. A forecast the two methods disagree
about is shown as disputed rather than quietly averaged, because the operator
acting on it deserves to know which of those two situations they are in.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..contracts.enums import ForecastMethod, GrowthPattern, RateSource
from ..contracts.forecast import (
    ForecastPoint,
    ForecastReport,
    GrowthAssessment,
    MethodForecast,
    QueueForecast,
)
from ..contracts.queue import QueueMetrics, QueueReport
from .config import ForecastConfig
from .growth import GrowthDetector
from .observations import ObservationBuffer

__all__ = ["QueueForecaster"]

logger = logging.getLogger(__name__)


class _ZoneState:
    """Per-zone forecasting state: history, baseline, and the last sample seen."""

    __slots__ = ("buffer", "growth", "last_sample_value")

    def __init__(self, config: ForecastConfig) -> None:
        self.buffer = ObservationBuffer(
            sample_interval_seconds=config.sample_interval_seconds,
            max_samples=config.max_samples,
        )
        self.growth = GrowthDetector(
            alpha=config.growth_alpha,
            min_samples=config.growth_min_samples,
            z_threshold=config.growth_z_threshold,
            min_absolute_rate_per_min=config.growth_min_rate_per_min,
        )
        self.last_sample_value: float | None = None


class QueueForecaster:
    """Forecasts every queue zone on one camera.

    Stateful across windows: a forecast is a statement about a trajectory, and a
    trajectory only exists in history. One instance follows one camera.
    """

    def __init__(self, config: ForecastConfig | None = None) -> None:
        self._config = config or ForecastConfig()
        self._zones: dict[str, _ZoneState] = {}

    # -- Driving ------------------------------------------------------------

    def observe(self, report: QueueReport) -> ForecastReport:
        """Fold one queue report into history and forecast from it."""
        forecasts = tuple(
            self._forecast_zone(queue, report.frame_ts) for queue in report.queues
        )
        return ForecastReport(
            frame_seq=report.frame_seq,
            frame_ts=report.frame_ts,
            forecasts=forecasts,
        )

    def _state(self, zone_id: str) -> _ZoneState:
        state = self._zones.get(zone_id)
        if state is None:
            state = _ZoneState(self._config)
            self._zones[zone_id] = state
        return state

    def _forecast_zone(self, queue: QueueMetrics, frame_ts: datetime) -> QueueForecast:
        config = self._config
        state = self._state(queue.zone_id)

        sealed = state.buffer.observe(frame_ts, float(queue.person_count))
        if sealed:
            self._update_baseline(state)

        trend = self._trend_forecast(state, frame_ts)
        flow = self._flow_forecast(queue, frame_ts)
        consensus, agreement = self._consensus(trend, flow, frame_ts)

        growth = self._assess_growth(state, queue)
        confidence = self._confidence(state, queue, trend, flow, agreement)

        return QueueForecast(
            zone_id=queue.zone_id,
            zone_name=queue.zone_name,
            generated_at=datetime.now(tz=frame_ts.tzinfo),
            frame_ts=frame_ts,
            current_length=queue.person_count,
            points=consensus,
            methods=(trend, flow),
            method_agreement=agreement,
            growth=growth,
            confidence=confidence,
            assumptions=self._assumptions(queue, trend, flow),
            observation_minutes=state.buffer.span_seconds / 60.0,
        )

    def _windowed_rate(
        self, state: _ZoneState
    ) -> tuple[float, float, float] | None:
        """Rate of change, percentage change, and the window both were measured over.

        The single definition of "how fast is this queue changing", used by both
        the baseline and the classification. They must be the same quantity: a
        baseline built from one-sample differences and a judgement made on a
        five-minute rate are measured on completely different scales, and
        comparing them makes the baseline's noise swamp every real surge.

        The window shrinks to the available history rather than waiting for the
        full configured span, so a queue can be assessed a minute after the
        platform starts rather than six.
        """
        config = self._config
        span_minutes = state.buffer.span_seconds / 60.0
        if span_minutes < config.growth_min_window_minutes:
            return None

        window = min(config.growth_window_minutes, span_minutes)
        change = state.buffer.change_over(window)
        if change is None:
            return None

        absolute, percentage = change
        return absolute / window, percentage, window

    def _update_baseline(self, state: _ZoneState) -> None:
        """Fold the newest windowed rate of change into the growth baseline.

        Samples the detector already considers abnormal are **withheld**. A
        baseline that trains on an active surge adapts to it: measured over one
        sustained surge, it climbed from -0.8/min to +9.0/min in five minutes
        while the z-score fell from 2.6 to 1.2, so the alarm silenced itself
        exactly as the queue got worst.

        Everything short of abnormal still trains it, so a venue genuinely
        getting busier is still learned - only the periods already judged
        exceptional are excluded, which is what a baseline means.
        """
        measured = self._windowed_rate(state)
        if measured is None:
            return

        rate, _, _ = measured

        pattern, _z = state.growth.classify(rate)
        if pattern is not GrowthPattern.ABNORMAL_GROWTH:
            state.growth.update(rate)

        latest = state.buffer.latest
        if latest is not None:
            state.last_sample_value = latest.value

    # -- Method: trend ------------------------------------------------------

    def _trend_forecast(self, state: _ZoneState, frame_ts: datetime) -> MethodForecast:
        config = self._config
        series = state.buffer.series

        if len(series) < config.min_samples_for_trend:
            return MethodForecast(
                method=ForecastMethod.TREND,
                confidence=0.0,
                unavailable_reason=(
                    f"Needs {config.min_samples_for_trend} observation samples, "
                    f"has {len(series)}"
                ),
            )

        from .holt import fit_holt

        fitted = fit_holt(series, alpha=config.alpha, beta=config.beta)
        if fitted is None:  # pragma: no cover - guarded by the length check above
            return MethodForecast(
                method=ForecastMethod.TREND,
                confidence=0.0,
                unavailable_reason="Insufficient history to fit a trend",
            )

        steps_per_minute = state.buffer.steps_per_minute
        points = []
        for horizon in config.horizons_minutes:
            steps = horizon * steps_per_minute
            lower, upper = fitted.interval(steps, z=config.interval_z)
            points.append(
                ForecastPoint(
                    horizon_minutes=horizon,
                    at=frame_ts + timedelta(minutes=horizon),
                    expected=fitted.project(steps),
                    lower=lower,
                    upper=upper,
                )
            )

        # Confidence grows with history depth and falls as the model's own
        # one-step errors grow relative to the level it is predicting.
        depth = min(1.0, len(series) / (config.min_samples_for_trend * 4))
        noise = fitted.residual_std / max(1.0, abs(fitted.level))
        fit_quality = max(0.0, min(1.0, 1.0 - noise))

        return MethodForecast(
            method=ForecastMethod.TREND,
            points=tuple(points),
            confidence=max(0.0, min(1.0, depth * fit_quality)),
        )

    # -- Method: flow balance ----------------------------------------------

    def _flow_forecast(
        self, queue: QueueMetrics, frame_ts: datetime
    ) -> MethodForecast:
        config = self._config
        flow = queue.flow

        if flow.observation_seconds < config.min_flow_observation_seconds:
            return MethodForecast(
                method=ForecastMethod.FLOW_BALANCE,
                confidence=0.0,
                unavailable_reason=(
                    f"Needs {config.min_flow_observation_seconds:.0f}s of flow "
                    f"observation, has {flow.observation_seconds:.0f}s"
                ),
            )

        # The queue drains at whatever the counters actually achieve, which is
        # the capacity figure - not the raw observed departure rate, because a
        # queue that is currently empty has a departure rate of zero without
        # having lost any capacity.
        net_per_min = flow.arrival_rate_per_min - (
            queue.capacity.effective_service_rate_per_min
            + flow.abandonment_rate_per_min
        )

        points = []
        for horizon in config.horizons_minutes:
            expected = max(0.0, queue.person_count + net_per_min * horizon)
            # Uncertainty here comes from the rates being estimates from a finite
            # count of events. Poisson counting error on the arrivals observed so
            # far, propagated over the horizon.
            observed_minutes = max(1e-6, flow.observation_seconds / 60.0)
            rate_error = (
                (flow.arrivals**0.5) / observed_minutes if flow.arrivals else 1.0
            )
            spread = config.interval_z * rate_error * horizon
            points.append(
                ForecastPoint(
                    horizon_minutes=horizon,
                    at=frame_ts + timedelta(minutes=horizon),
                    expected=expected,
                    lower=max(0.0, expected - spread),
                    upper=max(0.0, expected + spread),
                )
            )

        maturity = min(
            1.0, flow.observation_seconds / (config.min_flow_observation_seconds * 4)
        )
        source_factor = {
            RateSource.MEASURED: 1.0,
            RateSource.BLENDED: 0.6,
            RateSource.CONFIGURED: 0.3,
        }[queue.capacity.rate_source]

        return MethodForecast(
            method=ForecastMethod.FLOW_BALANCE,
            points=tuple(points),
            confidence=max(0.0, min(1.0, maturity * source_factor)),
        )

    # -- Consensus ----------------------------------------------------------

    def _consensus(
        self, trend: MethodForecast, flow: MethodForecast, frame_ts: datetime
    ) -> tuple[tuple[ForecastPoint, ...], float | None]:
        """Combine the two methods, weighted by their own confidence."""
        available = [m for m in (trend, flow) if m.available and m.confidence > 0.0]

        if not available:
            # One may have points but zero confidence; prefer showing it to
            # showing nothing, since the confidence is reported beside it.
            fallback = next((m for m in (trend, flow) if m.available), None)
            if fallback is None:
                return (), None
            return fallback.points, None

        if len(available) == 1:
            return available[0].points, None

        total_weight = sum(m.confidence for m in available)
        points: list[ForecastPoint] = []

        for horizon in self._config.horizons_minutes:
            contributions = [
                (m.at_horizon(horizon), m.confidence)
                for m in available
                if m.at_horizon(horizon) is not None
            ]
            if not contributions:
                continue

            expected = sum(p.expected * w for p, w in contributions) / total_weight
            lower = sum(p.lower * w for p, w in contributions) / total_weight
            upper = sum(p.upper * w for p, w in contributions) / total_weight

            points.append(
                ForecastPoint(
                    horizon_minutes=horizon,
                    at=frame_ts + timedelta(minutes=horizon),
                    expected=expected,
                    lower=min(lower, expected),
                    upper=max(upper, expected),
                )
            )

        return tuple(points), self._agreement(trend, flow)

    def _agreement(self, trend: MethodForecast, flow: MethodForecast) -> float | None:
        """How closely the methods agree at the furthest horizon, in ``[0, 1]``."""
        if not (trend.available and flow.available):
            return None

        horizon = self._config.horizons_minutes[-1]
        a, b = trend.at_horizon(horizon), flow.at_horizon(horizon)
        if a is None or b is None:
            return None

        scale = max(a.expected, b.expected, 1.0)
        return max(0.0, min(1.0, 1.0 - abs(a.expected - b.expected) / scale))

    # -- Growth -------------------------------------------------------------

    def _assess_growth(
        self, state: _ZoneState, queue: QueueMetrics
    ) -> GrowthAssessment:
        measured = self._windowed_rate(state)
        if measured is None:
            rate_per_min = 0.0
            change_pct: float | None = None
            effective_window = state.buffer.span_seconds / 60.0
        else:
            rate_per_min, change_pct, effective_window = measured

        pattern, z = state.growth.classify(rate_per_min)

        explanation = state.growth.explain(
            pattern,
            rate_per_min,
            z=z,
            change_pct=change_pct,
            window_minutes=effective_window,
            arrival_rate=queue.flow.arrival_rate_per_min,
            service_rate=queue.capacity.effective_service_rate_per_min,
        )

        if pattern is GrowthPattern.ABNORMAL_GROWTH:
            logger.info(
                "Abnormal queue growth on zone %s: %.1f people/min (z=%.1f)",
                queue.zone_id,
                rate_per_min,
                z if z is not None else float("nan"),
            )

        return GrowthAssessment(
            pattern=pattern,
            growth_rate_per_min=rate_per_min,
            baseline_rate_per_min=state.growth.baseline_mean,
            baseline_std=state.growth.baseline_std,
            z_score=z,
            change_pct=change_pct,
            window_minutes=effective_window,
            samples=state.growth.samples,
            explanation=explanation,
        )

    # -- Confidence and assumptions ----------------------------------------

    def _confidence(
        self,
        state: _ZoneState,
        queue: QueueMetrics,
        trend: MethodForecast,
        flow: MethodForecast,
        agreement: float | None,
    ) -> float:
        """Overall forecast confidence.

        A product of knowable quantities, consistent with how Decision Confidence
        is defined elsewhere in the platform: the best method's own confidence,
        discounted by how much the two methods disagree and by how sure the
        platform is that it is looking at a queue at all.
        """
        best = max(trend.confidence, flow.confidence)
        agreement_factor = 0.75 + 0.25 * agreement if agreement is not None else 0.85
        formation_factor = max(0.3, queue.formation_confidence)
        return max(0.0, min(1.0, best * agreement_factor * formation_factor))

    def _assumptions(
        self, queue: QueueMetrics, trend: MethodForecast, flow: MethodForecast
    ) -> tuple[str, ...]:
        assumptions: list[str] = []

        if trend.available:
            assumptions.append(
                "trend projection assumes the recent rate of change continues"
            )
        if flow.available:
            assumptions.append(
                f"flow projection assumes arrivals hold at "
                f"{queue.flow.arrival_rate_per_min:.1f}/min and "
                f"{queue.capacity.active_counters} "
                f"{'counter' if queue.capacity.active_counters == 1 else 'counters'} "
                "stay open"
            )
        if queue.capacity.rate_source is not RateSource.MEASURED:
            assumptions.append(
                "service rate is not yet fully measured - forecast will sharpen "
                "as departures are observed"
            )
        if not assumptions:
            assumptions.append("insufficient history for any forecast method")

        return tuple(assumptions)

    # -- Introspection ------------------------------------------------------

    def samples_for(self, zone_id: str) -> int:
        """Observation samples retained for a zone."""
        state = self._zones.get(zone_id)
        return state.buffer.count if state else 0

    def reset(self, zone_id: str | None = None) -> None:
        """Discard history for one zone, or all of them."""
        if zone_id is None:
            self._zones.clear()
        else:
            self._zones.pop(zone_id, None)
