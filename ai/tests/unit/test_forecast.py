"""Forecasting and abnormal growth detection.

The requirement being tested is Problem Statement 9's, stated precisely: the
platform must predict queue length at fixed horizons from real observations, and
must raise abnormal growth on *rate against baseline* rather than on size.

The last of those is the one most easily got wrong, so it is tested from both
sides: a large stable queue must stay quiet, and a small fast-growing one must
not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from surgeguard_ai.contracts import (
    ForecastMethod,
    GrowthPattern,
    QueueFormation,
    RateSource,
)
from surgeguard_ai.contracts.queue import (
    FlowRates,
    QueueGeometry,
    QueueMetrics,
    QueueReport,
    ServiceCapacity,
    WaitEstimate,
)
from surgeguard_ai.forecast import (
    ForecastConfig,
    GrowthDetector,
    ObservationBuffer,
    QueueForecaster,
    fit_holt,
)

START = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def queue_metrics(
    *,
    count: int,
    seconds: float,
    arrival_rate: float = 6.0,
    service_rate_per_counter: float = 2.0,
    active_counters: int = 2,
    observation_seconds: float = 300.0,
    rate_source: RateSource = RateSource.MEASURED,
    formation_confidence: float = 1.0,
) -> QueueMetrics:
    """A measured queue state, built directly rather than through perception.

    The forecaster's contract is with QueueMetrics, so testing it against
    constructed metrics isolates forecasting from detection: a forecast bug and a
    queue-detection bug should not be able to hide behind each other.
    """
    return QueueMetrics(
        zone_id="queue-a",
        zone_name="Ticket Hall Queue",
        frame_seq=int(seconds),
        frame_ts=at(seconds),
        person_count=count,
        formation=QueueFormation.QUEUE,
        formation_confidence=formation_confidence,
        formation_basis=("arranged linearly (0.90)",),
        geometry=QueueGeometry(sample_size=count, linearity=0.9),
        flow=FlowRates(
            window_seconds=180.0,
            arrivals=int(arrival_rate * observation_seconds / 60.0),
            departures_served=int(
                service_rate_per_counter * active_counters * observation_seconds / 60.0
            ),
            departures_abandoned=0,
            arrival_rate_per_min=arrival_rate,
            service_rate_per_min=service_rate_per_counter * active_counters,
            abandonment_rate_per_min=0.0,
            rate_source=rate_source,
            observation_seconds=observation_seconds,
        ),
        capacity=ServiceCapacity(
            total_counters=4,
            active_counters=active_counters,
            service_rate_per_counter_per_min=service_rate_per_counter,
            rate_source=rate_source,
        ),
        wait=WaitEstimate(
            minutes=count / max(0.1, service_rate_per_counter * active_counters),
            queue_length=count,
            effective_service_rate_per_min=service_rate_per_counter * active_counters,
            rate_source=rate_source,
            confidence=0.8,
        ),
    )


def report_of(metrics: QueueMetrics) -> QueueReport:
    return QueueReport(
        frame_seq=metrics.frame_seq, frame_ts=metrics.frame_ts, queues=(metrics,)
    )


def drive(
    forecaster: QueueForecaster, lengths: list[int], *, step_seconds: float = 10.0, **kw
):
    """Feed a length series through the forecaster, returning the last report."""
    result = None
    for index, count in enumerate(lengths):
        result = forecaster.observe(
            report_of(queue_metrics(count=count, seconds=index * step_seconds, **kw))
        )
    assert result is not None
    return result


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------


class TestObservationBuffer:
    def test_readings_are_averaged_into_fixed_buckets(self) -> None:
        """Otherwise the trend would depend on frame rate: a queue would appear
        to grow faster simply because the machine got busier."""
        buffer = ObservationBuffer(sample_interval_seconds=10.0)
        for second in range(10):
            buffer.observe(at(second), 10.0)
        buffer.observe(at(11), 20.0)

        assert buffer.count == 1
        assert buffer.series[0] == pytest.approx(10.0)
        assert buffer.samples[0].readings == 10

    def test_steps_per_minute_reflects_the_interval(self) -> None:
        assert ObservationBuffer(sample_interval_seconds=10.0).steps_per_minute == 6.0
        assert ObservationBuffer(sample_interval_seconds=30.0).steps_per_minute == 2.0

    def test_a_rewound_clock_resets_the_buffer(self) -> None:
        buffer = ObservationBuffer(sample_interval_seconds=10.0)
        for second in range(0, 60, 11):
            buffer.observe(at(second), float(second))
        assert buffer.count > 0

        buffer.observe(at(0), 5.0)
        assert buffer.count == 0, "a looping clip must not forecast across the rewind"

    def test_change_over_a_window_needs_that_window_of_history(self) -> None:
        buffer = ObservationBuffer(sample_interval_seconds=10.0)
        for index in range(6):
            buffer.observe(at(index * 11), float(index))
        assert buffer.change_over(5.0) is None, (
            "a change computed over a shorter span than claimed would misstate "
            "the rate"
        )

    def test_change_over_reports_absolute_and_percentage(self) -> None:
        buffer = ObservationBuffer(sample_interval_seconds=10.0)
        for index in range(40):
            buffer.observe(at(index * 11), 10.0 + index)

        change = buffer.change_over(1.0)
        assert change is not None
        absolute, pct = change
        assert absolute > 0
        assert pct > 0


# ---------------------------------------------------------------------------
# Holt
# ---------------------------------------------------------------------------


class TestHolt:
    def test_too_short_a_series_has_no_trend(self) -> None:
        """Two points define a trend with zero residual, which would produce a
        confident forecast with a zero-width interval."""
        assert fit_holt([1.0, 2.0]) is None

    def test_a_rising_series_projects_upward(self) -> None:
        fitted = fit_holt([10.0, 12.0, 14.0, 16.0, 18.0, 20.0])
        assert fitted is not None
        assert fitted.trend > 0
        assert fitted.project(5) > fitted.project(1)

    def test_a_flat_series_projects_flat_with_a_narrow_band(self) -> None:
        fitted = fit_holt([20.0] * 10)
        assert fitted is not None
        assert fitted.trend == pytest.approx(0.0, abs=1e-6)
        assert fitted.project(10) == pytest.approx(20.0, abs=1e-6)
        assert fitted.residual_std == pytest.approx(0.0, abs=1e-9)

    def test_a_forecast_cannot_go_negative(self) -> None:
        fitted = fit_holt([20.0, 15.0, 10.0, 5.0, 2.0])
        assert fitted is not None
        assert fitted.project(50) >= 0.0

    def test_intervals_widen_with_horizon(self) -> None:
        fitted = fit_holt([10.0, 13.0, 11.0, 16.0, 14.0, 19.0, 17.0, 22.0])
        assert fitted is not None
        near = fitted.interval(6)
        far = fitted.interval(18)
        assert (far[1] - far[0]) > (near[1] - near[0])

    def test_invalid_smoothing_constants_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="alpha"):
            fit_holt([1.0, 2.0, 3.0], alpha=0.0)
        with pytest.raises(ValueError, match="beta"):
            fit_holt([1.0, 2.0, 3.0], beta=1.5)


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------


class TestGrowthDetector:
    def test_no_judgement_is_offered_without_a_baseline(self) -> None:
        """Declaring a queue normal on no evidence is the failure this component
        exists to prevent."""
        detector = GrowthDetector(min_samples=12)
        pattern, z = detector.classify(50.0)
        assert pattern is GrowthPattern.INSUFFICIENT_HISTORY
        assert z is None

    def test_a_steady_queue_reads_as_stable(self) -> None:
        detector = GrowthDetector(min_samples=5)
        for _ in range(20):
            detector.update(0.0)
        pattern, _ = detector.classify(0.0)
        assert pattern is GrowthPattern.STABLE

    def test_a_sudden_surge_against_a_calm_baseline_is_abnormal(self) -> None:
        detector = GrowthDetector(min_samples=5, z_threshold=2.5)
        for index in range(30):
            detector.update(0.2 if index % 2 else -0.2)

        pattern, z = detector.classify(9.0)
        assert pattern is GrowthPattern.ABNORMAL_GROWTH
        assert z is not None and z >= 2.5

    def test_a_large_but_stable_queue_never_triggers(self) -> None:
        """The explicit Problem Statement 9 requirement: size alone is not an
        alarm. This detector never sees size at all, which is the point."""
        detector = GrowthDetector(min_samples=5)
        for _ in range(40):
            detector.update(0.0)

        pattern, _ = detector.classify(0.0)
        assert pattern is GrowthPattern.STABLE

    def test_a_small_queue_growing_fast_does_trigger(self) -> None:
        """The other half of the same requirement."""
        detector = GrowthDetector(min_samples=5, min_absolute_rate_per_min=1.0)
        for _ in range(30):
            detector.update(0.1)

        pattern, _ = detector.classify(6.0)
        assert pattern is GrowthPattern.ABNORMAL_GROWTH

    def test_a_tiny_change_on_a_flat_baseline_does_not_cry_wolf(self) -> None:
        """A perfectly flat baseline makes any change an enormous z-score. The
        absolute floor is what stops one person joining reading as a crisis."""
        detector = GrowthDetector(min_samples=5, min_absolute_rate_per_min=1.0)
        for _ in range(40):
            detector.update(0.0)

        pattern, _ = detector.classify(0.4)
        assert pattern is not GrowthPattern.ABNORMAL_GROWTH

    def test_shrinking_is_distinguished_from_stable(self) -> None:
        detector = GrowthDetector(min_samples=5)
        for _ in range(20):
            detector.update(0.0)
        pattern, _ = detector.classify(-4.0)
        assert pattern is GrowthPattern.SHRINKING

    def test_explanations_cite_measurements_not_verdicts(self) -> None:
        detector = GrowthDetector(min_samples=5)
        for _ in range(30):
            detector.update(0.1)

        text = detector.explain(
            GrowthPattern.ABNORMAL_GROWTH,
            8.0,
            z=4.2,
            change_pct=47.0,
            window_minutes=5.0,
            arrival_rate=12.0,
            service_rate=4.0,
        )
        assert "8.0 people/min" in text
        assert "+47%" in text
        assert "standard deviations" in text
        assert "exceed service capacity" in text
        assert "dangerous" not in text.lower()


# ---------------------------------------------------------------------------
# The forecaster
# ---------------------------------------------------------------------------


class TestQueueForecaster:
    def test_early_windows_decline_to_forecast_and_say_why(self) -> None:
        forecaster = QueueForecaster()
        report = drive(forecaster, [10, 11, 12])

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        trend = forecast.method(ForecastMethod.TREND)
        assert trend is not None
        assert trend.available is False
        assert trend.unavailable_reason is not None
        assert "samples" in trend.unavailable_reason

    def test_a_growing_queue_is_forecast_to_keep_growing(self) -> None:
        forecaster = QueueForecaster()
        report = drive(forecaster, list(range(10, 50, 2)))

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        assert forecast.points, "a forecast must be produced once history exists"

        five = forecast.at_horizon(5)
        fifteen = forecast.at_horizon(15)
        assert five is not None and fifteen is not None
        assert five.expected > forecast.current_length
        assert fifteen.expected > five.expected

    def test_every_configured_horizon_is_forecast(self) -> None:
        forecaster = QueueForecaster(ForecastConfig(horizons_minutes=(5, 10, 15, 30)))
        report = drive(forecaster, list(range(10, 60, 2)))

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        assert [p.horizon_minutes for p in forecast.points] == [5, 10, 15, 30]

    def test_intervals_widen_with_horizon(self) -> None:
        forecaster = QueueForecaster()
        report = drive(forecaster, [10, 14, 11, 17, 13, 20, 16, 23, 19, 26, 22, 29])

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        widths = [p.interval_width for p in forecast.points]
        assert widths == sorted(widths), (
            "a forecast 15 minutes out is less certain than one 5 minutes out "
            "and must not be drawn as though it were"
        )

    def test_both_methods_are_reported(self) -> None:
        """Keeping both is what lets a forecast be answered with 'the trend says
        X, the flow balance says Y'."""
        forecaster = QueueForecaster()
        report = drive(forecaster, list(range(10, 50, 2)))

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        assert {m.method for m in forecast.methods} == {
            ForecastMethod.TREND,
            ForecastMethod.FLOW_BALANCE,
        }
        assert forecast.method_agreement is not None

    def test_a_forecast_never_predicts_a_negative_queue(self) -> None:
        forecaster = QueueForecaster()
        report = drive(forecaster, list(range(40, 0, -2)))

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        assert all(p.expected >= 0.0 for p in forecast.points)
        assert all(p.lower >= 0.0 for p in forecast.points)

    def test_assumptions_are_stated(self) -> None:
        forecaster = QueueForecaster()
        report = drive(forecaster, list(range(10, 50, 2)))

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        joined = " ".join(forecast.assumptions)
        assert "assumes" in joined

    def test_an_assumed_service_rate_lowers_confidence(self) -> None:
        measured = QueueForecaster()
        drive(measured, list(range(10, 50, 2)), rate_source=RateSource.MEASURED)
        high = measured.observe(
            report_of(queue_metrics(count=48, seconds=200, rate_source=RateSource.MEASURED))
        ).by_zone("queue-a")

        assumed = QueueForecaster()
        drive(assumed, list(range(10, 50, 2)), rate_source=RateSource.CONFIGURED)
        low = assumed.observe(
            report_of(
                queue_metrics(count=48, seconds=200, rate_source=RateSource.CONFIGURED)
            )
        ).by_zone("queue-a")

        assert high is not None and low is not None
        assert high.confidence > low.confidence

    def test_the_peak_is_the_worst_forecast_point(self) -> None:
        forecaster = QueueForecaster()
        report = drive(forecaster, list(range(10, 50, 2)))

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        peak = forecast.peak
        assert peak is not None
        assert peak.expected == max(p.expected for p in forecast.points)


class TestForecasterGrowthIntegration:
    def test_a_surge_raises_abnormal_growth(self) -> None:
        forecaster = QueueForecaster(
            ForecastConfig(growth_min_samples=6, growth_z_threshold=2.0)
        )

        # A long calm stretch establishes what normal looks like here...
        calm = [12, 12, 13, 12, 13, 12, 12, 13, 12, 13, 12, 12, 13, 12, 12, 13]
        # ...then the queue takes off.
        surge = [16, 22, 29, 37, 46, 56]

        report = drive(forecaster, calm + surge, step_seconds=11.0)
        forecast = report.by_zone("queue-a")
        assert forecast is not None
        assert forecast.growth.pattern is GrowthPattern.ABNORMAL_GROWTH
        assert forecast.growth.is_abnormal is True
        assert forecast.growth.growth_rate_per_min > 0
        assert report.any_abnormal_growth is True

    def test_a_large_steady_queue_stays_quiet(self) -> None:
        """A busy hall that is always busy is not an emergency."""
        forecaster = QueueForecaster(ForecastConfig(growth_min_samples=6))
        report = drive(forecaster, [80, 81, 80, 79, 80, 81, 80, 80, 79, 81] * 3,
                       step_seconds=11.0)

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        assert forecast.growth.is_abnormal is False
        assert forecast.growth.pattern in {
            GrowthPattern.STABLE,
            GrowthPattern.GROWING,
            GrowthPattern.SHRINKING,
        }

    def test_the_baseline_does_not_chase_a_sustained_surge(self) -> None:
        """Regression: the alarm must not silence itself as the queue worsens.

        Observed before the fix: during a sustained surge the baseline climbed
        from -0.8/min to +9.0/min over five minutes while the z-score *fell*
        from 2.6 to 1.2, so the detector talked itself out of the alarm it had
        just raised - exactly as the queue got worst. A baseline that adapts
        faster than the phenomenon it exists to detect will always do that.
        """
        forecaster = QueueForecaster(
            ForecastConfig(growth_min_samples=6, growth_z_threshold=2.0)
        )

        calm = [12, 12, 13, 12, 13, 12, 12, 13, 12, 13, 12, 12, 13, 12, 12, 13]
        surge = [17, 23, 31, 41, 53, 67, 83, 101, 121, 143]

        readings: list[tuple[float, float | None]] = []
        for index, count in enumerate(calm + surge):
            report = forecaster.observe(
                report_of(queue_metrics(count=count, seconds=index * 11.0))
            )
            forecast = report.by_zone("queue-a")
            assert forecast is not None
            readings.append(
                (forecast.growth.growth_rate_per_min, forecast.growth.z_score)
            )

        # Once the surge is well under way the verdict must stand, and the
        # z-score must not decay while the growth rate keeps climbing.
        final = forecaster.observe(
            report_of(queue_metrics(count=170, seconds=len(calm + surge) * 11.0))
        ).by_zone("queue-a")
        assert final is not None
        assert final.growth.pattern is GrowthPattern.ABNORMAL_GROWTH

        abnormal_z = [z for rate, z in readings[-6:] if z is not None and rate > 2.0]
        assert len(abnormal_z) >= 4
        assert abnormal_z[-1] > abnormal_z[0], (
            "a worsening surge must read as more abnormal, not less"
        )

    def test_growth_explanation_is_populated_early_too(self) -> None:
        forecaster = QueueForecaster()
        report = drive(forecaster, [10, 11, 12])

        forecast = report.by_zone("queue-a")
        assert forecast is not None
        assert forecast.growth.pattern is GrowthPattern.INSUFFICIENT_HISTORY
        assert "establishing" in forecast.growth.explanation


class TestConfigValidation:
    def test_horizons_must_be_ascending(self) -> None:
        with pytest.raises(ValueError, match="ascending"):
            ForecastConfig(horizons_minutes=(15, 5, 10))

    def test_horizons_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            ForecastConfig(horizons_minutes=(0, 5))

    def test_at_least_one_horizon_is_required(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            ForecastConfig(horizons_minutes=())
