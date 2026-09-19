"""Intelligent resource allocation - how many counters should be open.

Problem Statement 9 requires recommendations "based on predicted demand" and
warns against arbitrary ones. The method here is deliberately simple enough to
be checked by hand:

1. Project the queue forward to a decision horizon at every staffing level the
   venue could run, from zero counters to all of them.
2. Compute the wait at each level.
3. Recommend the **fewest** counters that bring the projected wait within target.

Fewest, not most, because a recommendation engine that always says "open
everything" is not making a decision. Staff are finite, and an operator who is
told to open every counter during a mild lunch rush will stop reading the
recommendations by Tuesday.

The projection uses the same arithmetic in both directions, which is what makes
the *expected effect* honest: "queue 71 -> 49, wait 16 min -> 9 min" is the
difference between two evaluations of one function, not a claim attached to a
recommendation after the fact.

**What this does not model.** Queueing theory has better answers than
``L / mu`` - M/M/c gives expected waits under stochastic arrivals, and a real
deployment should use it. It is not used here because it assumes Poisson
arrivals and exponential service times, and the platform has no evidence that
either holds at a given venue. A transparent approximation whose assumptions are
printed on screen is worth more to an operator than a sophisticated one whose
assumptions are invisible and possibly violated.
"""

from __future__ import annotations

import logging

from ..contracts.enums import RecommendationType
from ..contracts.forecast import QueueForecast
from ..contracts.queue import QueueMetrics
from ..contracts.resources import CapacityOption, ResourcePlan, ResourcePlanReport
from .config import AllocationConfig

__all__ = ["ResourceAllocator"]

logger = logging.getLogger(__name__)


class ResourceAllocator:
    """Recommends a staffing level for each queue zone.

    Stateless: every plan is computed from the measured queue and its forecast,
    so the same inputs always produce the same recommendation. That is a
    requirement rather than a convenience - an operator who sees a
    recommendation change must be able to point at the measurement that changed.
    """

    def __init__(self, config: AllocationConfig | None = None) -> None:
        self._config = config or AllocationConfig()

    # -- Planning -----------------------------------------------------------

    def plan(
        self, queue: QueueMetrics, forecast: QueueForecast | None = None
    ) -> ResourcePlan:
        """Build the capacity recommendation for one queue zone."""
        config = self._config
        horizon = config.decision_horizon_minutes
        target = config.target_wait_minutes

        arrival_rate = queue.flow.arrival_rate_per_min
        abandonment = queue.flow.abandonment_rate_per_min
        per_counter = queue.capacity.service_rate_per_counter_per_min
        total = queue.capacity.total_counters
        active = queue.capacity.active_counters

        options = tuple(
            self._evaluate(
                counters=count,
                start_queue=queue.person_count,
                arrival_rate=arrival_rate,
                abandonment_rate=abandonment,
                per_counter_rate=per_counter,
                horizon=horizon,
                target=target,
            )
            for count in range(total + 1)
        )

        current = self._option_for(options, active) or self._evaluate(
            counters=active,
            start_queue=queue.person_count,
            arrival_rate=arrival_rate,
            abandonment_rate=abandonment,
            per_counter_rate=per_counter,
            horizon=horizon,
            target=target,
        )

        recommended, action, delta, feasible, limiting = self._choose(
            options, current, active, total
        )

        return ResourcePlan(
            zone_id=queue.zone_id,
            zone_name=queue.zone_name,
            horizon_minutes=horizon,
            target_wait_minutes=target,
            current_queue=queue.person_count,
            current_wait_minutes=queue.wait.minutes,
            arrival_rate_per_min=arrival_rate,
            total_counters=total,
            current=current,
            recommended=recommended,
            options=options,
            action=action,
            counters_to_change=delta,
            rationale=self._rationale(
                queue, current, recommended, action, delta, horizon, target, feasible
            ),
            expected_effect=self._expected_effect(current, recommended, horizon)
            if delta != 0
            else None,
            feasible=feasible,
            provisional=queue.flow.observation_seconds
            < config.min_observation_seconds,
            limiting_factor=limiting,
            confidence=forecast.confidence if forecast is not None else 0.0,
            assumptions=self._assumptions(queue, horizon, target),
        )

    def plan_all(
        self, queues: tuple[QueueMetrics, ...], forecasts: tuple[QueueForecast, ...] = ()
    ) -> ResourcePlanReport:
        """Plan every queue zone on a camera."""
        by_zone = {forecast.zone_id: forecast for forecast in forecasts}
        return ResourcePlanReport(
            plans=tuple(
                self.plan(queue, by_zone.get(queue.zone_id)) for queue in queues
            )
        )

    # -- Projection ---------------------------------------------------------

    def _evaluate(
        self,
        *,
        counters: int,
        start_queue: int,
        arrival_rate: float,
        abandonment_rate: float,
        per_counter_rate: float,
        horizon: int,
        target: float,
    ) -> CapacityOption:
        """Project the queue forward at one staffing level.

        ``Q(h) = max(0, Q + (arrivals - service - abandonment) * h)``, then
        ``W = Q(h) / service``. The clamp at zero matters: without it a
        well-staffed counter would be credited with driving the queue negative
        and would report an impossible negative wait.
        """
        service_rate = counters * per_counter_rate
        net = arrival_rate - service_rate - abandonment_rate
        projected = max(0.0, start_queue + net * horizon)

        if service_rate < self._config.min_service_rate_per_min:
            # Nothing is being served. The queue has no wait, it has no service.
            return CapacityOption(
                active_counters=counters,
                effective_service_rate_per_min=service_rate,
                projected_queue=projected,
                projected_wait_minutes=None,
                clears_target=False,
            )

        wait = projected / service_rate
        return CapacityOption(
            active_counters=counters,
            effective_service_rate_per_min=service_rate,
            projected_queue=projected,
            projected_wait_minutes=wait,
            clears_target=wait <= target,
            capacity_pressure=arrival_rate / service_rate,
        )

    @staticmethod
    def _option_for(
        options: tuple[CapacityOption, ...], counters: int
    ) -> CapacityOption | None:
        for option in options:
            if option.active_counters == counters:
                return option
        return None

    # -- Choosing -----------------------------------------------------------

    def _choose(
        self,
        options: tuple[CapacityOption, ...],
        current: CapacityOption,
        active: int,
        total: int,
    ) -> tuple[CapacityOption, RecommendationType, int, bool, str | None]:
        """Pick the fewest counters that clear the target."""
        config = self._config

        sufficient = [option for option in options if option.clears_target]

        if not sufficient:
            # Even everything open is not enough. Recommend everything anyway -
            # it is still the best available action - but say plainly that it
            # will not be sufficient, rather than presenting it as a fix.
            best = max(options, key=lambda o: o.effective_service_rate_per_min)
            limiting = (
                "Arrival rate exceeds the throughput of every counter combined. "
                "Capacity alone cannot bring the wait within target."
            )
            delta = best.active_counters - active
            action = (
                RecommendationType.OPEN_COUNTER
                if delta > 0
                else RecommendationType.OBSERVE
            )
            return best, action, delta, False, limiting

        minimal = min(sufficient, key=lambda option: option.active_counters)

        if minimal.active_counters > active:
            return (
                minimal,
                RecommendationType.OPEN_COUNTER,
                minimal.active_counters - active,
                True,
                None,
            )

        if minimal.active_counters < active:
            # Closing is only proposed with margin to spare, so the platform does
            # not oscillate a counter open and shut around the threshold.
            margin_wait = minimal.projected_wait_minutes
            if (
                margin_wait is not None
                and margin_wait <= config.target_wait_minutes * config.close_margin
                and (active - minimal.active_counters) >= 1
            ):
                return (
                    minimal,
                    RecommendationType.CLOSE_COUNTER,
                    minimal.active_counters - active,
                    True,
                    None,
                )

        return current, RecommendationType.OBSERVE, 0, True, None

    # -- Explanation --------------------------------------------------------

    def _rationale(
        self,
        queue: QueueMetrics,
        current: CapacityOption,
        recommended: CapacityOption,
        action: RecommendationType,
        delta: int,
        horizon: int,
        target: float,
        feasible: bool,
    ) -> str:
        arrivals = queue.flow.arrival_rate_per_min

        if not feasible:
            return (
                f"Arrivals are running at {arrivals:.1f}/min against a maximum "
                f"throughput of {recommended.effective_service_rate_per_min:.1f}/min "
                f"with all {queue.capacity.total_counters} counters open. The queue "
                f"is projected to reach {recommended.projected_queue:.0f} people in "
                f"{horizon} min even at full capacity - opening counters will slow "
                "the growth but not stop it."
            )

        if action is RecommendationType.OPEN_COUNTER:
            current_wait = (
                f"{current.projected_wait_minutes:.0f} min"
                if current.projected_wait_minutes is not None
                else "unbounded"
            )
            return (
                f"Projected demand exceeds current service capacity. At "
                f"{current.active_counters} "
                f"{'counter' if current.active_counters == 1 else 'counters'}, the "
                f"queue reaches {current.projected_queue:.0f} people in {horizon} min "
                f"and the wait reaches {current_wait} - above the {target:.0f} min "
                f"target. Arrivals are {arrivals:.1f}/min against "
                f"{current.effective_service_rate_per_min:.1f}/min of service."
            )

        if action is RecommendationType.CLOSE_COUNTER:
            return (
                f"Service capacity exceeds demand. At "
                f"{recommended.active_counters} "
                f"{'counter' if recommended.active_counters == 1 else 'counters'} the "
                f"wait stays at {recommended.projected_wait_minutes:.0f} min, within "
                f"the {target:.0f} min target, freeing "
                f"{abs(delta)} {'counter' if abs(delta) == 1 else 'counters'} for "
                "other duties."
            )

        wait_text = (
            f"{current.projected_wait_minutes:.0f} min"
            if current.projected_wait_minutes is not None
            else "unknown"
        )
        return (
            f"Current allocation is sufficient. At {current.active_counters} "
            f"{'counter' if current.active_counters == 1 else 'counters'}, the "
            f"projected wait in {horizon} min is {wait_text}, within the "
            f"{target:.0f} min target."
        )

    @staticmethod
    def _expected_effect(
        current: CapacityOption, recommended: CapacityOption, horizon: int
    ) -> str:
        """The projected difference, computed rather than asserted."""
        queue_text = (
            f"Queue at +{horizon} min: {current.projected_queue:.0f} "
            f"-> {recommended.projected_queue:.0f} people."
        )

        before = current.projected_wait_minutes
        after = recommended.projected_wait_minutes

        if before is None and after is not None:
            wait_text = f" Wait: currently not draining -> {after:.0f} min."
        elif before is not None and after is not None:
            wait_text = f" Wait: {before:.0f} min -> {after:.0f} min."
        else:
            wait_text = ""

        return queue_text + wait_text

    def _assumptions(
        self, queue: QueueMetrics, horizon: int, target: float
    ) -> tuple[str, ...]:
        observed = queue.flow.observation_seconds
        provisional = (
            (
                f"rates measured over only {observed:.0f}s so far - this plan "
                "will firm up as observation continues",
            )
            if observed < self._config.min_observation_seconds
            else ()
        )
        return provisional + (
            f"target wait is {target:.0f} min, decision horizon {horizon} min",
            f"assumes arrivals hold at {queue.flow.arrival_rate_per_min:.1f}/min",
            f"assumes each counter serves "
            f"{queue.capacity.service_rate_per_counter_per_min:.1f} people/min "
            f"({queue.capacity.rate_source.value.lower()})",
            "assumes a counter reaches full rate immediately once opened",
        )
