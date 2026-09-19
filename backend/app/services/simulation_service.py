"""Simulation Mode - what-if analysis over the real prediction engines.

Problem Statement 9 section 23 asks for a mode that demonstrates the prediction
and recommendation engines when no camera is available. Section 35 sets the
condition under which that is acceptable: simulated input may be synthetic, but
it must be clearly labelled, and it must not be a second implementation that
merely looks like the real one.

So this generates **input**, never output. A synthetic arrival/service process
produces :class:`~surgeguard_ai.contracts.queue.QueueMetrics` windows, and those
are handed to a real :class:`~surgeguard_ai.forecast.QueueForecaster` and a real
:class:`~surgeguard_ai.resources.ResourceAllocator` - the same classes, with the
same configuration, that the live pipeline uses. Every forecast, every
abnormal-growth verdict and every counter recommendation a simulation produces
was computed by the production engines.

Two consequences follow, and both are deliberate:

- A bug in the forecaster shows up in simulation. If the two could diverge, the
  demonstration would stop being evidence about the real system.
- Simulation state is held entirely separately from live state. Nothing here
  touches :class:`~app.services.crowd_intelligence.CrowdIntelligenceService`, so
  a simulated surge can never reach a record tagged as live (Rule 7).
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from surgeguard_ai.contracts import (
    ForecastReport,
    QueueFormation,
    QueueGeometry,
    QueueMetrics,
    QueueReport,
    RateSource,
    ResourcePlanReport,
    ServiceCapacity,
    WaitEstimate,
)
from surgeguard_ai.contracts.queue import FlowRates
from surgeguard_ai.forecast import ForecastConfig, QueueForecaster
from surgeguard_ai.resources import AllocationConfig, ResourceAllocator

from ..core.logging import get_logger

__all__ = ["SimulationParameters", "SimulationResult", "SimulationService"]

logger = get_logger(__name__)

#: Simulated seconds per generated window. Matches the forecaster's default
#: resampling cadence, so one simulated window produces one forecast sample and
#: simulated minutes mean the same thing as real ones.
STEP_SECONDS = 10.0

#: The zone a simulation reports against. Named rather than borrowed from the
#: live camera so a simulated record can never be mistaken for a real zone's.
SIMULATION_ZONE_ID = "sim-queue"
SIMULATION_ZONE_NAME = "Simulated Queue"


class SimulationParameters:
    """The operator's what-if settings."""

    __slots__ = (
        "arrival_rate_per_min",
        "service_rate_per_counter_per_min",
        "total_counters",
        "active_counters",
        "initial_queue",
        "duration_minutes",
        "arrival_growth_per_min",
        "surge_start_minute",
        "seed",
    )

    def __init__(
        self,
        *,
        arrival_rate_per_min: float = 6.0,
        service_rate_per_counter_per_min: float = 2.0,
        total_counters: int = 4,
        active_counters: int = 2,
        initial_queue: int = 10,
        duration_minutes: float = 12.0,
        arrival_growth_per_min: float = 0.0,
        surge_start_minute: float = 5.0,
        seed: int = 20260916,
    ) -> None:
        self.arrival_rate_per_min = arrival_rate_per_min
        self.service_rate_per_counter_per_min = service_rate_per_counter_per_min
        self.total_counters = total_counters
        self.active_counters = min(active_counters, total_counters)
        self.initial_queue = initial_queue
        self.duration_minutes = duration_minutes
        self.arrival_growth_per_min = arrival_growth_per_min
        """Increase in arrival rate per simulated minute, once the surge starts.

        This is the surge control: a positive value makes arrivals accelerate,
        which is what drives the queue past what its counters can serve."""
        self.surge_start_minute = surge_start_minute
        """Simulated minute at which arrivals begin to accelerate.

        Before it, arrivals hold steady at the base rate. This is not cosmetic.
        Abnormal growth is defined against a queue's *own* baseline, so a run
        that accelerates from its first second never gives the detector a calm
        period to learn what normal looks like - and correctly concludes that
        fast growth is normal here. Real surges follow quiet periods, and a
        simulation without one cannot demonstrate the detector working."""
        self.seed = seed
        """Fixed by default, so the same settings always produce the same run.

        A demonstration that produces different numbers each time cannot be
        rehearsed, and an operator cannot tell a genuine change in the engine
        from noise."""

    @property
    def effective_service_rate_per_min(self) -> float:
        return self.active_counters * self.service_rate_per_counter_per_min


class SimulationResult:
    """One simulation run, in the same shapes the live pipeline produces."""

    __slots__ = (
        "parameters",
        "queue",
        "forecast",
        "resources",
        "series",
        "steps",
        "simulated_minutes",
    )

    def __init__(
        self,
        parameters: SimulationParameters,
        queue: QueueReport,
        forecast: ForecastReport,
        resources: ResourcePlanReport,
        series: tuple[tuple[float, int], ...],
        steps: int,
    ) -> None:
        self.parameters = parameters
        self.queue = queue
        self.forecast = forecast
        self.resources = resources
        self.series = series
        """(minute, queue length) for every simulated window - the history the
        forecast was actually computed from, so a chart can show the run rather
        than only its endpoint."""
        self.steps = steps
        self.simulated_minutes = steps * STEP_SECONDS / 60.0


class SimulationService:
    """Runs what-if scenarios through the production prediction engines."""

    def __init__(
        self,
        *,
        forecast_config: ForecastConfig | None = None,
        allocation_config: AllocationConfig | None = None,
    ) -> None:
        self._forecast_config = forecast_config or ForecastConfig()
        self._allocation_config = allocation_config or AllocationConfig()
        self._last: SimulationResult | None = None

    @property
    def last(self) -> SimulationResult | None:
        """The most recent run, so a reconnecting client sees what was shown."""
        return self._last

    def reset(self) -> None:
        self._last = None

    # -- Running ------------------------------------------------------------

    def run(self, parameters: SimulationParameters) -> SimulationResult:
        """Simulate a queue forward and analyse it with the real engines.

        The process is a simple deterministic balance with bounded noise:

            Q(t+dt) = max(0, Q(t) + (arrivals(t) - served(t)) * dt)

        where ``arrivals`` may accelerate over the run. Noise is small, seeded
        and multiplicative, so a run is reproducible but does not look like a
        straight line - a perfectly smooth queue would make the forecast look
        better than it is.
        """
        rng = random.Random(parameters.seed)

        # A forecaster per run, never shared with the live one: a simulated
        # surge must not train the baseline the live camera is judged against.
        forecaster = QueueForecaster(self._forecast_config)
        allocator = ResourceAllocator(self._allocation_config)

        start = datetime.now(UTC)
        steps = max(1, int(parameters.duration_minutes * 60.0 / STEP_SECONDS))

        queue_length = float(parameters.initial_queue)
        cumulative_arrivals = 0.0
        cumulative_served = 0.0
        series: list[tuple[float, int]] = []

        queue_report: QueueReport | None = None
        forecast_report: ForecastReport | None = None
        resource_report: ResourcePlanReport | None = None

        for step in range(steps):
            minutes_elapsed = step * STEP_SECONDS / 60.0
            frame_ts = start + timedelta(seconds=step * STEP_SECONDS)

            # Arrivals hold at the base rate until the surge begins, which is
            # what gives the growth detector a baseline to judge against.
            surge_minutes = max(0.0, minutes_elapsed - parameters.surge_start_minute)
            arrival_rate = max(
                0.0,
                parameters.arrival_rate_per_min
                + parameters.arrival_growth_per_min * surge_minutes,
            )
            service_rate = parameters.effective_service_rate_per_min

            step_minutes = STEP_SECONDS / 60.0
            arrivals = arrival_rate * step_minutes * _jitter(rng)
            # Nobody can be served who is not in the queue.
            served = min(queue_length + arrivals, service_rate * step_minutes * _jitter(rng))

            queue_length = max(0.0, queue_length + arrivals - served)
            cumulative_arrivals += arrivals
            cumulative_served += served

            observed_seconds = (step + 1) * STEP_SECONDS
            metrics = _metrics(
                parameters=parameters,
                frame_seq=step,
                frame_ts=frame_ts,
                queue_length=int(round(queue_length)),
                arrival_rate=arrival_rate,
                service_rate=service_rate,
                arrivals=int(cumulative_arrivals),
                served=int(cumulative_served),
                observed_seconds=observed_seconds,
            )

            queue_report = QueueReport(
                frame_seq=step, frame_ts=frame_ts, queues=(metrics,)
            )
            forecast_report = forecaster.observe(queue_report)
            resource_report = allocator.plan_all(
                queue_report.queues, forecast_report.forecasts
            )

            series.append((round(minutes_elapsed, 2), int(round(queue_length))))

        assert queue_report is not None
        assert forecast_report is not None
        assert resource_report is not None

        result = SimulationResult(
            parameters, queue_report, forecast_report, resource_report,
            tuple(series), steps,
        )
        self._last = result

        growth = forecast_report.forecasts[0].growth if forecast_report.forecasts else None
        logger.info(
            "Simulation complete",
            extra={
                "simulated_minutes": round(result.simulated_minutes, 1),
                "final_queue": series[-1][1] if series else 0,
                "arrival_rate": parameters.arrival_rate_per_min,
                "active_counters": parameters.active_counters,
                "growth_pattern": growth.pattern.value if growth else None,
            },
        )
        return result


def _jitter(rng: random.Random) -> float:
    """Small multiplicative noise, so a run does not look like a straight line."""
    return 1.0 + rng.uniform(-0.18, 0.18)


def _metrics(
    *,
    parameters: SimulationParameters,
    frame_seq: int,
    frame_ts: datetime,
    queue_length: int,
    arrival_rate: float,
    service_rate: float,
    arrivals: int,
    served: int,
    observed_seconds: float,
) -> QueueMetrics:
    """Wrap one simulated window in the contract the real engines consume.

    The formation is reported as a queue with full confidence because in a
    simulation it is one by construction - there is no detector whose judgement
    could be uncertain. The geometry fields stay empty rather than carrying
    invented linearity figures: a simulated queue has no spatial arrangement,
    and fabricating one would put a measurement-shaped number on screen that no
    measurement produced.
    """
    effective = max(0.01, service_rate)

    return QueueMetrics(
        zone_id=SIMULATION_ZONE_ID,
        zone_name=SIMULATION_ZONE_NAME,
        frame_seq=frame_seq,
        frame_ts=frame_ts,
        person_count=queue_length,
        formation=QueueFormation.QUEUE if queue_length > 3 else QueueFormation.SPARSE,
        formation_confidence=1.0,
        formation_basis=("simulated queue - formation is given, not measured",),
        geometry=QueueGeometry(sample_size=queue_length),
        flow=FlowRates(
            window_seconds=180.0,
            arrivals=arrivals,
            departures_served=served,
            departures_abandoned=0,
            arrival_rate_per_min=arrival_rate,
            service_rate_per_min=min(service_rate, arrival_rate + queue_length),
            abandonment_rate_per_min=0.0,
            rate_source=RateSource.MEASURED,
            observation_seconds=observed_seconds,
        ),
        capacity=ServiceCapacity(
            total_counters=parameters.total_counters,
            active_counters=parameters.active_counters,
            service_rate_per_counter_per_min=parameters.service_rate_per_counter_per_min,
            rate_source=RateSource.MEASURED,
        ),
        wait=WaitEstimate(
            minutes=queue_length / effective if service_rate > 0 else None,
            queue_length=queue_length,
            effective_service_rate_per_min=service_rate,
            rate_source=RateSource.MEASURED,
            assumptions=(
                f"simulated: arrivals {arrival_rate:.1f}/min, "
                f"{parameters.active_counters} "
                f"{'counter' if parameters.active_counters == 1 else 'counters'} "
                f"at {parameters.service_rate_per_counter_per_min:.1f}/min each",
            ),
            confidence=1.0,
        ),
        mean_dwell_seconds=(
            60.0 * queue_length / effective if service_rate > 0 else None
        ),
        max_dwell_seconds=None,
    )
