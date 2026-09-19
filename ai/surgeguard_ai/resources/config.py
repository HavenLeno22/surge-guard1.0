"""Tuning for resource allocation."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AllocationConfig"]


@dataclass(frozen=True, slots=True)
class AllocationConfig:
    """How the platform decides how many counters should be open.

    Attributes:
        decision_horizon_minutes: How far ahead the staffing decision is made.
            Ten minutes: long enough that opening a counter has time to change
            the outcome, short enough that the forecast is still worth acting on.
        target_wait_minutes: The wait the venue is trying to stay within. The
            single most deployment-specific number here - an outpatient clinic
            and a stadium turnstile do not share it - which is exactly why it is
            configuration rather than a constant.
        min_service_rate_per_min: Below this a staffing level is treated as
            serving nobody, so a wait is reported as unknown rather than as an
            enormous number.
        min_observation_seconds: Observation below which a plan is marked
            provisional. Rates measured over a few seconds are arithmetically
            correct and operationally meaningless - eight people entering at
            once over four seconds reads as 114 arrivals/minute.
        close_margin: A counter is only recommended for closing when the
            projected wait without it sits within this fraction of target.
            Below 1.0 on purpose: recommending a close at exactly the threshold
            would have the platform reopen it on the next window, and an
            operator watching a counter flap open and shut stops trusting the
            recommendations entirely.
    """

    min_observation_seconds: float = 60.0
    decision_horizon_minutes: int = 10
    target_wait_minutes: float = 10.0
    min_service_rate_per_min: float = 0.1
    close_margin: float = 0.6

    def __post_init__(self) -> None:
        if self.decision_horizon_minutes <= 0:
            raise ValueError("decision_horizon_minutes must be positive")
        if self.target_wait_minutes <= 0:
            raise ValueError("target_wait_minutes must be positive")
        if not 0.0 < self.close_margin <= 1.0:
            raise ValueError(
                "close_margin must lie in (0, 1] - at 1.0 the platform would "
                "reopen a counter on the window after closing it"
            )
