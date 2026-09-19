"""Resource allocation contracts - what the operator could do about capacity.

The third of the three layers Problem Statement 9 requires to be kept visibly
apart: :mod:`.queue` is what is happening, :mod:`.forecast` is what is expected,
and this is what could be done. Mixing them is how a dashboard ends up
presenting a recommendation as though it were a measurement.

Every figure in a :class:`ResourcePlan` is **computed by re-running the forecast
at the proposed capacity**, never authored. When the platform says opening one
counter takes the queue from 71 to 49 and the wait from 16 minutes to 9, those
four numbers come from evaluating the same projection twice at two different
service rates. An operator can therefore check the claim, and the platform
cannot promise an improvement it has not calculated.
"""

from __future__ import annotations

from pydantic import Field

from .base import Contract
from .enums import RecommendationType

__all__ = ["CapacityOption", "ResourcePlan", "ResourcePlanReport"]


class CapacityOption(Contract):
    """What the queue is projected to do at one staffing level.

    One of these is produced for every counter count the venue could actually
    run, from zero to the number it has. Keeping the whole ladder rather than
    only the winner is what lets the interface answer "why not two counters?"
    with a number instead of a shrug.
    """

    active_counters: int = Field(ge=0)
    effective_service_rate_per_min: float = Field(
        ge=0.0, description="Throughput at this staffing level, people per minute."
    )

    projected_queue: float = Field(
        ge=0.0,
        description="Queue length at the decision horizon if this option is taken.",
    )
    projected_wait_minutes: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Wait at the decision horizon under this option. None when this "
            "option does not drain the queue at all - an unbounded wait is "
            "reported as unknown, never as a very large number."
        ),
    )

    clears_target: bool = Field(
        description="Whether this option brings the projected wait within target."
    )
    capacity_pressure: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Arrival rate over this option's service rate. Below 1.0 the counters "
            "keep up with arrivals; above it the queue grows no matter how it "
            "started. None when the option serves nobody, where the ratio has "
            "no finite value."
        ),
    )

    @property
    def is_viable(self) -> bool:
        """Whether this option serves anybody at all."""
        return self.effective_service_rate_per_min > 0.0


class ResourcePlan(Contract):
    """The capacity recommendation for one queue zone.

    Carries the full Problem Statement 9 section 13 disclosure: current demand,
    current capacity, predicted demand, required capacity, the recommended
    action, and its expected effect.
    """

    zone_id: str
    zone_name: str

    # -- The question being answered ----------------------------------------

    horizon_minutes: int = Field(
        gt=0,
        description=(
            "How far ahead the decision is made. Chosen to be long enough that "
            "opening a counter has time to matter and short enough that the "
            "forecast is still worth acting on."
        ),
    )
    target_wait_minutes: float = Field(
        gt=0, description="Wait the venue is trying to stay within."
    )

    # -- Current state ------------------------------------------------------

    current_queue: int = Field(ge=0)
    current_wait_minutes: float | None = Field(default=None, ge=0.0)
    arrival_rate_per_min: float = Field(ge=0.0)
    total_counters: int = Field(ge=0)

    # -- The options --------------------------------------------------------

    current: CapacityOption = Field(
        description="What happens if nothing changes - the do-nothing baseline."
    )
    recommended: CapacityOption = Field(
        description="The option the platform recommends."
    )
    options: tuple[CapacityOption, ...] = Field(
        default=(), description="Every staffing level considered, ascending."
    )

    # -- The recommendation -------------------------------------------------

    action: RecommendationType
    counters_to_change: int = Field(
        description=(
            "Counters to open (positive) or close (negative). Zero when the "
            "current allocation is already right."
        )
    )
    rationale: str = Field(
        description=(
            "Why, in operator language, citing the measurements behind it. "
            "Never an assertion the numbers do not support."
        )
    )
    expected_effect: str | None = Field(
        default=None,
        description=(
            "The difference the change is projected to make, e.g. 'Queue at "
            "+10 min: 71 -> 49. Wait: 16 min -> 9 min.' None when no change is "
            "recommended, because there is no effect to describe."
        ),
    )

    # -- Honesty ------------------------------------------------------------

    feasible: bool = Field(
        default=True,
        description=(
            "False when even every counter open cannot bring the wait within "
            "target. The platform says so rather than recommending an "
            "insufficient action and letting the operator discover it later."
        ),
    )
    provisional: bool = Field(
        default=False,
        description=(
            "True when the rates this plan rests on have not been observed long "
            "enough to be steady. Observed in the field: seconds after a "
            "pipeline restart, eight people entering the zone at once divide by "
            "a four-second observation window and read as 114 arrivals/minute, "
            "which drove a confident 'capacity cannot meet target'. The "
            "arithmetic was right and the conclusion was not. A plan flagged "
            "here is still shown - it may well be correct - but the interface "
            "marks it as resting on a short sample rather than presenting it "
            "with the same weight as one built on minutes of observation."
        ),
    )
    limiting_factor: str | None = Field(
        default=None,
        description="What prevents the target being met, when it cannot be.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Inherited from the forecast this rests on. A recommendation cannot "
            "be more certain than the prediction that motivated it."
        ),
    )
    assumptions: tuple[str, ...] = Field(default=())

    @property
    def changes_anything(self) -> bool:
        return self.counters_to_change != 0

    @property
    def utilisation_after(self) -> float | None:
        """Fraction of counters committed under the recommendation."""
        if self.total_counters <= 0:
            return None
        return self.recommended.active_counters / self.total_counters


class ResourcePlanReport(Contract):
    """Capacity recommendations for every queue zone on one camera."""

    plans: tuple[ResourcePlan, ...] = Field(default=())

    def by_zone(self, zone_id: str) -> ResourcePlan | None:
        for plan in self.plans:
            if plan.zone_id == zone_id:
                return plan
        return None

    @property
    def any_action_needed(self) -> bool:
        return any(plan.changes_anything for plan in self.plans)

    @property
    def any_infeasible(self) -> bool:
        """Whether any queue cannot be brought within target at full staffing."""
        return any(not plan.feasible for plan in self.plans)
