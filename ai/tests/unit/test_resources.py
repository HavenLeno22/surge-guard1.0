"""Resource allocation - how many counters should be open.

Problem Statement 9 section 13 requires recommendations based on predicted
demand, with the current demand, current capacity, predicted demand, required
capacity, recommended action and expected effect all disclosed.

The property most worth protecting is that the expected effect is **computed**:
if the platform says opening a counter takes the wait from 16 minutes to 9, then
running the projection at that staffing level must actually produce 9.
"""

from __future__ import annotations

import pytest

from surgeguard_ai.contracts import RateSource, RecommendationType
from surgeguard_ai.resources import AllocationConfig, ResourceAllocator

from .test_forecast import queue_metrics


def allocator(**overrides: float | int) -> ResourceAllocator:
    settings: dict = {"decision_horizon_minutes": 10, "target_wait_minutes": 10.0}
    settings.update(overrides)
    return ResourceAllocator(AllocationConfig(**settings))


class TestOpeningCounters:
    def test_demand_beyond_capacity_recommends_opening(self) -> None:
        plan = allocator().plan(
            queue_metrics(
                count=48, seconds=0, arrival_rate=12.0,
                active_counters=2, service_rate_per_counter=2.0,
            )
        )

        assert plan.action is RecommendationType.OPEN_COUNTER
        assert plan.counters_to_change > 0
        assert plan.recommended.active_counters > plan.current.active_counters

    def test_the_fewest_sufficient_counters_are_recommended(self) -> None:
        """An engine that always says 'open everything' is not making a
        decision, and an operator stops reading it."""
        plan = allocator().plan(
            queue_metrics(
                count=30, seconds=0, arrival_rate=5.0,
                active_counters=1, service_rate_per_counter=3.0,
            )
        )

        assert plan.recommended.clears_target
        cheaper = [
            option
            for option in plan.options
            if option.active_counters < plan.recommended.active_counters
        ]
        assert not any(option.clears_target for option in cheaper), (
            "a cheaper sufficient option existed and was not chosen"
        )

    def test_the_whole_ladder_of_options_is_reported(self) -> None:
        """So the interface can answer 'why not two counters?' with a number."""
        plan = allocator().plan(
            queue_metrics(count=40, seconds=0, active_counters=2)
        )
        assert [o.active_counters for o in plan.options] == [0, 1, 2, 3, 4]


class TestExpectedEffect:
    def test_the_effect_matches_the_projection_it_claims(self) -> None:
        """The central integrity property of the whole recommendation."""
        plan = allocator().plan(
            queue_metrics(
                count=48, seconds=0, arrival_rate=12.0,
                active_counters=2, service_rate_per_counter=2.0,
            )
        )

        assert plan.expected_effect is not None
        assert f"{plan.current.projected_queue:.0f}" in plan.expected_effect
        assert f"{plan.recommended.projected_queue:.0f}" in plan.expected_effect

        recommended = plan.recommended
        expected_queue = max(
            0.0,
            plan.current_queue
            + (plan.arrival_rate_per_min - recommended.effective_service_rate_per_min)
            * plan.horizon_minutes,
        )
        assert recommended.projected_queue == pytest.approx(expected_queue)
        assert recommended.projected_wait_minutes == pytest.approx(
            expected_queue / recommended.effective_service_rate_per_min
        )

    def test_opening_a_counter_actually_improves_the_projection(self) -> None:
        plan = allocator().plan(
            queue_metrics(
                count=48, seconds=0, arrival_rate=12.0,
                active_counters=2, service_rate_per_counter=2.0,
            )
        )
        assert plan.recommended.projected_queue < plan.current.projected_queue

    def test_no_change_means_no_claimed_effect(self) -> None:
        plan = allocator().plan(
            queue_metrics(
                count=4, seconds=0, arrival_rate=1.0,
                active_counters=1, service_rate_per_counter=3.0,
            )
        )
        assert plan.action is RecommendationType.OBSERVE
        assert plan.expected_effect is None
        assert plan.changes_anything is False


class TestClosingCounters:
    def test_surplus_capacity_recommends_closing(self) -> None:
        plan = allocator().plan(
            queue_metrics(
                count=2, seconds=0, arrival_rate=0.5,
                active_counters=4, service_rate_per_counter=3.0,
            )
        )
        assert plan.action is RecommendationType.CLOSE_COUNTER
        assert plan.counters_to_change < 0

    def test_a_counter_at_the_threshold_is_not_closed(self) -> None:
        """Recommending a close at exactly the threshold has the platform
        reopen it next window, and an operator watching a counter flap stops
        trusting the recommendations."""
        conservative = allocator(close_margin=0.6)
        plan = conservative.plan(
            queue_metrics(
                count=27, seconds=0, arrival_rate=3.0,
                active_counters=3, service_rate_per_counter=1.0,
            )
        )
        assert plan.action is not RecommendationType.CLOSE_COUNTER


class TestInfeasibility:
    def test_demand_beyond_every_counter_is_reported_as_infeasible(self) -> None:
        """Presenting an insufficient action as a fix and letting the operator
        find out later is the failure being prevented."""
        plan = allocator().plan(
            queue_metrics(
                count=120, seconds=0, arrival_rate=40.0,
                active_counters=2, service_rate_per_counter=2.0,
            )
        )

        assert plan.feasible is False
        assert plan.limiting_factor is not None
        assert "cannot" in plan.limiting_factor.lower()
        assert "not stop it" in plan.rationale

    def test_an_infeasible_case_still_recommends_the_best_available(self) -> None:
        plan = allocator().plan(
            queue_metrics(
                count=120, seconds=0, arrival_rate=40.0,
                active_counters=1, service_rate_per_counter=2.0,
            )
        )
        assert plan.recommended.active_counters == plan.total_counters

    def test_zero_active_counters_reports_an_unknown_wait(self) -> None:
        plan = allocator().plan(
            queue_metrics(
                count=20, seconds=0, arrival_rate=5.0,
                active_counters=0, service_rate_per_counter=2.0,
            )
        )
        assert plan.current.projected_wait_minutes is None
        assert plan.current.is_viable is False
        assert plan.action is RecommendationType.OPEN_COUNTER


class TestDisclosure:
    def test_the_rationale_cites_measured_rates(self) -> None:
        # Feasible: arrivals 5/min against 4/min of current service, with 8/min
        # available across all four counters - so the open-counter branch runs
        # rather than the infeasible one.
        plan = allocator().plan(
            queue_metrics(
                count=48, seconds=0, arrival_rate=5.0,
                active_counters=2, service_rate_per_counter=2.0,
            )
        )
        assert plan.feasible is True
        assert plan.action is RecommendationType.OPEN_COUNTER
        assert "5.0/min" in plan.rationale, "arrival rate must be cited"
        assert "4.0/min" in plan.rationale, "current service rate must be cited"

    def test_assumptions_are_stated(self) -> None:
        plan = allocator().plan(
            queue_metrics(count=48, seconds=0, rate_source=RateSource.CONFIGURED)
        )
        joined = " ".join(plan.assumptions)
        assert "target wait" in joined
        assert "configured" in joined, "an assumed service rate must say so"
        assert "reaches full rate immediately" in joined

    def test_confidence_is_inherited_from_the_forecast(self) -> None:
        """A recommendation cannot be more certain than the prediction behind it."""
        from surgeguard_ai.forecast import QueueForecaster

        from .test_forecast import drive

        forecaster = QueueForecaster()
        report = drive(forecaster, list(range(10, 50, 2)))
        forecast = report.by_zone("queue-a")
        assert forecast is not None

        metrics = queue_metrics(count=48, seconds=0, arrival_rate=12.0)
        plan = allocator().plan(metrics, forecast)
        assert plan.confidence == pytest.approx(forecast.confidence)

    def test_without_a_forecast_confidence_is_zero_not_assumed(self) -> None:
        plan = allocator().plan(queue_metrics(count=48, seconds=0))
        assert plan.confidence == 0.0


class TestReport:
    def test_planning_all_zones(self) -> None:
        metrics = queue_metrics(count=48, seconds=0, arrival_rate=12.0)
        report = ResourceAllocator().plan_all((metrics,))

        assert report.by_zone("queue-a") is not None
        assert report.by_zone("missing") is None
        assert report.any_action_needed is True

    def test_utilisation_after_the_recommendation(self) -> None:
        plan = allocator().plan(
            queue_metrics(
                count=48, seconds=0, arrival_rate=12.0,
                active_counters=2, service_rate_per_counter=2.0,
            )
        )
        assert plan.utilisation_after == pytest.approx(
            plan.recommended.active_counters / plan.total_counters
        )


class TestConfigValidation:
    def test_close_margin_must_leave_hysteresis(self) -> None:
        with pytest.raises(ValueError, match="close_margin"):
            AllocationConfig(close_margin=1.5)

    def test_target_wait_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="target_wait_minutes"):
            AllocationConfig(target_wait_minutes=0.0)

    def test_horizon_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="decision_horizon_minutes"):
            AllocationConfig(decision_horizon_minutes=0)
