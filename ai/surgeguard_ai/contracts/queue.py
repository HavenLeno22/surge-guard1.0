"""Queue Intelligence contracts - the measured state of a service queue.

These describe *what a queue is doing right now*: how many people are in it,
whether it is actually a queue rather than a loose crowd, how fast people are
joining and being served, and how long they have been waiting.

Nothing here is a prediction. Forecasts live in :mod:`.forecast`, which consumes
these. The separation is deliberate and matches the interface: Problem Statement
9 asks for real-time and predicted figures to be distinguishable at a glance,
and they cannot be if one structure carries both.

Every figure is either counted from observation or explicitly marked as an
operator-supplied assumption. There is no third category.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import QueueFormation, RateSource

__all__ = [
    "QueueGeometry",
    "FlowRates",
    "ServiceCapacity",
    "WaitEstimate",
    "QueueMetrics",
    "QueueReport",
]


class QueueGeometry(Contract):
    """The measured spatial structure of people in a queue zone.

    This is the evidence behind a :class:`~.enums.QueueFormation`
    classification. It is carried alongside the classification rather than
    discarded, so that "this is a queue" can always be answered with "because
    its people are arranged in a line, evenly spaced, facing the counter"
    instead of an unexplained label.
    """

    sample_size: int = Field(
        ge=0,
        description=(
            "Tracks that contributed to these figures. Tracks too young to be "
            "trusted are excluded, so this is usually below the zone headcount."
        ),
    )

    linearity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "How line-like the arrangement is, from principal component analysis "
            "of foot points: 1 - (minor axis / major axis). A perfect line reads "
            "1.0, a circular blob reads near 0.0. None below three samples, "
            "where the concept has no meaning."
        ),
    )
    spacing_regularity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "How evenly spaced people are along the major axis, as "
            "1 - min(1, coefficient of variation of the gaps). Queues space "
            "themselves regularly; crowds do not."
        ),
    )
    heading_coherence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Agreement in direction of travel, as the resultant length of the "
            "heading unit vectors. A queue shuffling forward reads high; a "
            "concourse of people crossing in all directions reads low. None when "
            "too few tracks carry velocity."
        ),
    )
    counter_alignment: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "How closely the queue's major axis points at the nearest COUNTER "
            "zone, as |cos(angle)|. None when no COUNTER zone is configured - "
            "which is why counter zones improve queue detection rather than "
            "merely labelling it."
        ),
    )
    mean_spacing_px: float | None = Field(
        default=None,
        ge=0.0,
        description="Mean gap between consecutive people along the major axis, in pixels.",
    )
    mean_spacing_m: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Mean gap in metres. Present only when the camera is calibrated; "
            "otherwise the pixel figure is the only honest one."
        ),
    )
    major_axis_deg: float | None = Field(
        default=None,
        ge=0.0,
        lt=180.0,
        description="Orientation of the queue's principal axis, degrees from +X.",
    )


class FlowRates(Contract):
    """Counted arrivals and departures over a rolling window.

    These are **event counts divided by elapsed time**, not estimates. A person
    is counted as an arrival when a track that was outside the queue zone is
    observed inside it, and as a departure on the reverse transition. Departures
    are split by where they left: through the service end of the queue, or away
    from it.

    That split is what separates throughput from abandonment. A queue emptying
    because people are being served and a queue emptying because people are
    giving up look identical in a headcount and mean opposite things.
    """

    window_seconds: float = Field(
        gt=0,
        description="Length of the rolling window these rates were counted over.",
    )

    arrivals: int = Field(ge=0, description="Join events counted in the window.")
    departures_served: int = Field(
        ge=0,
        description="Tracks that left through the service end of the queue.",
    )
    departures_abandoned: int = Field(
        ge=0,
        description=(
            "Tracks that left the queue away from the service end - people who "
            "gave up. Reneging is an operationally important signal: a queue "
            "shedding people is failing its users even while its length falls."
        ),
    )

    arrival_rate_per_min: float = Field(
        ge=0.0,
        description="Lambda - arrivals per minute over the window.",
    )
    service_rate_per_min: float = Field(
        ge=0.0,
        description=(
            "Mu - observed people served per minute across all active counters. "
            "This is throughput actually achieved, not nominal capacity."
        ),
    )
    abandonment_rate_per_min: float = Field(
        default=0.0,
        ge=0.0,
        description="People abandoning the queue per minute.",
    )

    rate_source: RateSource = Field(
        description=(
            "Whether the service rate was measured, assumed, or blended. Shown "
            "beside every derived wait so a measured figure and an assumed one "
            "are never mistaken for each other."
        )
    )
    observation_seconds: float = Field(
        ge=0.0,
        description=(
            "How long the queue has actually been observed. Short observation "
            "makes every rate here provisional, and the interface says so rather "
            "than presenting an early guess with full confidence."
        ),
    )

    @property
    def net_rate_per_min(self) -> float:
        """Rate of change of queue length: arrivals minus everything leaving.

        Positive means the queue is growing. This is the quantity the flow
        balance forecast integrates forward.
        """
        return self.arrival_rate_per_min - (
            self.service_rate_per_min + self.abandonment_rate_per_min
        )

    @property
    def is_measured(self) -> bool:
        """Whether the service rate rests on counted departures."""
        return self.rate_source is RateSource.MEASURED


class ServiceCapacity(Contract):
    """The service resources attached to a queue, and what they deliver.

    Counter counts are operator configuration - the platform cannot see how many
    ticket windows a station has. The *per-counter rate* is measured whenever
    enough departures have been observed, and falls back to the configured value
    until then, saying which it used.
    """

    total_counters: int = Field(
        ge=0,
        description="Counters physically available, whether staffed or not.",
    )
    active_counters: int = Field(
        ge=0,
        description="Counters currently in service.",
    )
    service_rate_per_counter_per_min: float = Field(
        gt=0,
        description="People one active counter serves per minute.",
    )
    rate_source: RateSource

    @property
    def effective_service_rate_per_min(self) -> float:
        """Mu_eff - total throughput of the currently active counters.

        The denominator of every waiting-time estimate the platform produces.
        """
        return self.active_counters * self.service_rate_per_counter_per_min

    @property
    def idle_counters(self) -> int:
        """Counters available but not in service - the headroom to recommend."""
        return max(0, self.total_counters - self.active_counters)

    @property
    def utilisation(self) -> float | None:
        """Fraction of total capacity currently committed. None with no counters."""
        if self.total_counters <= 0:
            return None
        return self.active_counters / self.total_counters


class WaitEstimate(Contract):
    """Estimated time for someone joining now to reach service.

    Derived, not measured: nobody is followed from joining to being served, and
    claiming otherwise would be a fabricated measurement. What the platform
    knows is the queue length and the rate it drains at, so the estimate is
    ``L / mu_eff`` - Little's Law - and the assumptions it rests on travel with
    it so an operator can judge it.
    """

    minutes: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Estimated wait in minutes. None when the effective service rate is "
            "zero or unknown - an unbounded wait is reported as unknown rather "
            "than as a very large number, which would read as a measurement."
        ),
    )
    queue_length: int = Field(ge=0, description="People ahead of a joiner.")
    effective_service_rate_per_min: float = Field(
        ge=0.0,
        description="Denominator used, in people per minute.",
    )
    rate_source: RateSource
    assumptions: tuple[str, ...] = Field(
        default=(),
        description=(
            "Operator-readable statements of what this estimate takes for "
            "granted, e.g. 'service rate measured over 4.2 min of observation', "
            "'assumes all 3 active counters remain open'. Displayed with the "
            "figure, never hidden behind it."
        ),
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in this estimate, from observation length, rate source "
            "and queue-detection confidence. A product of knowable quantities, "
            "consistent with how Decision Confidence is defined elsewhere."
        ),
    )

    @property
    def is_unbounded(self) -> bool:
        """Whether the queue is not draining at all - nobody is being served."""
        return self.minutes is None and self.queue_length > 0


class QueueMetrics(Contract):
    """The complete measured state of one queue zone for one analysis window."""

    zone_id: str
    zone_name: str = Field(description="Operator-facing name, e.g. 'Ticket Hall Queue'.")
    frame_seq: int = Field(ge=0)
    frame_ts: datetime

    person_count: int = Field(
        ge=0,
        description="People currently inside the queue zone boundary.",
    )

    formation: QueueFormation
    formation_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in the formation classification. Low confidence is "
            "displayed, not rounded up: the platform says 'probably a queue' "
            "when that is what it knows."
        ),
    )
    formation_basis: tuple[str, ...] = Field(
        default=(),
        description=(
            "Operator-readable reasons for the classification, derived from "
            "geometry, e.g. 'people arranged linearly (0.82)', 'oriented toward "
            "Counter 2 (0.91)'. Never authored prose - each entry names the "
            "measurement that produced it."
        ),
    )
    geometry: QueueGeometry

    flow: FlowRates
    capacity: ServiceCapacity
    wait: WaitEstimate

    mean_dwell_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Mean time current occupants have been inside the zone. Measured "
            "from track entry, so it under-reports whenever a track identity is "
            "lost and re-acquired - which is why it is reported beside track "
            "stability rather than alone."
        ),
    )
    max_dwell_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Longest continuous presence among current occupants.",
    )

    @property
    def is_queue(self) -> bool:
        """Whether this zone currently holds something the platform calls a queue."""
        return self.formation is QueueFormation.QUEUE


class QueueReport(Contract):
    """Every queue zone's measured state for one analysis window.

    A camera may watch several queues. This is the structure the rest of the
    platform consumes; individual zones are addressed by id within it.
    """

    frame_seq: int = Field(ge=0)
    frame_ts: datetime
    queues: tuple[QueueMetrics, ...] = Field(default=())

    unconfigured: bool = Field(
        default=False,
        description=(
            "True when the camera has no QUEUE zone defined. Queue Intelligence "
            "then has nothing to measure, and the interface says exactly that "
            "rather than showing zeroes that look like a measured empty queue."
        ),
    )

    @property
    def total_waiting(self) -> int:
        """People across every queue zone on this camera."""
        return sum(queue.person_count for queue in self.queues)

    def by_zone(self, zone_id: str) -> QueueMetrics | None:
        """The metrics for one zone, or None when that zone is not configured."""
        for queue in self.queues:
            if queue.zone_id == zone_id:
                return queue
        return None

    @property
    def busiest(self) -> QueueMetrics | None:
        """The queue with the most people, or None when no queue is configured."""
        return max(self.queues, key=lambda q: q.person_count, default=None)
