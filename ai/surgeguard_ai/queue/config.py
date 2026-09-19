"""Tuning for Queue Intelligence.

Every number a deployment might legitimately vary lives here rather than inside
the analyser, for the same reason the Crowd Stability Index weights do
(``16:142-168``): a hospital outpatient desk and a stadium turnstile are both
queues, and they are not the same queue.

The classification thresholds in particular are **judgement calls made explicit**
rather than derived constants. Writing them down here, named and defended, is
what lets an operator disagree with one.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["QueueAnalysisConfig"]


@dataclass(frozen=True, slots=True)
class QueueAnalysisConfig:
    """How a queue is measured and how it is told apart from a crowd.

    Attributes:
        min_track_age_frames: Tracks younger than this are excluded from every
            geometric measurement. A track one frame old has no velocity, an
            unreliable position, and a meaningful chance of being a detector
            flicker that will vanish next frame. Including such tracks would let
            noise drive the queue/crowd decision.
        sparse_threshold: At or below this many people, formation is reported as
            ``SPARSE`` and no classification is attempted. Three people standing
            near each other are always collinear; calling that a queue would
            make the classifier fire constantly on empty scenes.

        linearity_weight: Weight of spatial linearity in the queue score.
            Highest of the four because it is the signal that most directly
            distinguishes a line from a cluster, and the one least disturbed by
            people standing still.
        spacing_weight: Weight of spacing regularity.
        heading_weight: Weight of heading coherence. Lower than linearity
            because a stationary queue - the most common kind - produces no
            headings at all, and an indicator that is frequently unavailable
            should not dominate when it happens to be present.
        counter_weight: Weight of alignment toward a COUNTER zone. Unavailable
            unless a counter zone is configured.

        queue_threshold: Weighted score at or above which the formation is
            classified ``QUEUE``.
        crowd_threshold: Weighted score at or below which it is classified
            ``GENERAL_CROWD``. Between the two thresholds the platform reports
            ``UNDETERMINED`` rather than forcing a side. The gap between them is
            not wasted range - it is where honest uncertainty is expressed.

        flow_window_seconds: Rolling window over which arrivals and departures
            are counted into rates. Three minutes: long enough that a single
            person joining does not swing the rate wildly, short enough to
            follow a genuine surge.
        min_flow_observation_seconds: Observation time before a measured service
            rate is trusted over the configured one. Below this the rate is
            blended, and the interface says it is blended.
        service_end_fraction: Fraction of the queue's length, measured from the
            counter end, within which a departure counts as *served* rather than
            *abandoned*. A person leaving from the front was served; a person
            leaving from the middle gave up. The distinction is measurable only
            because it is positional.

        min_service_rate_per_min: Floor on any service rate used as a divisor,
            so a momentary lull cannot produce a division by zero or an
            implausibly enormous wait.
        default_service_rate_per_min: Per-counter rate assumed until enough
            departures have been observed to measure one. An assumption, labelled
            as one everywhere it reaches the interface.

        max_dwell_seconds: Ceiling on reported dwell time. A track that survives
            longer than this is almost certainly a stationary false positive -
            a coat on a chair, a poster - rather than a person who has waited
            that long, and letting it inflate mean dwell would corrupt the wait
            estimate that rests on it.
    """

    # -- Sampling -----------------------------------------------------------

    min_track_age_frames: int = 5
    sparse_threshold: int = 3

    # -- Formation scoring --------------------------------------------------

    linearity_weight: float = 0.40
    spacing_weight: float = 0.25
    heading_weight: float = 0.15
    counter_weight: float = 0.20

    queue_threshold: float = 0.55
    crowd_threshold: float = 0.35

    # -- Flow measurement ---------------------------------------------------

    flow_window_seconds: float = 180.0
    min_flow_observation_seconds: float = 60.0
    service_end_fraction: float = 0.25

    # -- Service assumptions ------------------------------------------------

    min_service_rate_per_min: float = 0.1
    default_service_rate_per_min: float = 2.0

    # -- Dwell --------------------------------------------------------------

    max_dwell_seconds: float = 3600.0

    def __post_init__(self) -> None:
        total = (
            self.linearity_weight
            + self.spacing_weight
            + self.heading_weight
            + self.counter_weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                "Queue formation weights must sum to 1.0, got "
                f"{total:.6f}. Rescaling them silently would change what a "
                "queue score means without anyone noticing."
            )
        if self.crowd_threshold >= self.queue_threshold:
            raise ValueError(
                "crowd_threshold must be below queue_threshold, leaving a band "
                "in which the platform reports UNDETERMINED rather than guessing."
            )
