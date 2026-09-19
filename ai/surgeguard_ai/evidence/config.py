"""Evidence Engine configuration.

Thresholds decide *when* the platform says something out loud, and that is a
tuning decision a venue owns rather than a constant the engine should hide.
They are expressed as **instability pressures** (0-100) wherever possible,
because those are already normalized: one number means the same thing whether
the camera is calibrated or not, which a raw density threshold would not.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["EvidenceConfig"]


@dataclass(frozen=True, slots=True)
class EvidenceConfig:
    """When an observation is worth reporting, and how it is ranked.

    Attributes:
        congestion_pressure: Density pressure at which congestion is reported
            as forming.
        movement_slowing_pressure: Motion-suppression pressure at which
            movement is reported as slowing. 25 corresponds to a median speed a
            quarter below this camera's own baseline.
        stationary_motion_pressure: Motion-suppression pressure required for a
            stationary cluster. Higher than ``movement_slowing_pressure``: a
            cluster is not merely slow, it has largely stopped.
        stationary_density_pressure: Density pressure that must accompany it.
            Both are required - people standing still in an empty space are
            waiting, and people standing still in a full one are a crowd that
            cannot move.
        flow_conflict_pressure: Flow-conflict pressure at which opposing
            movement is reported.
        egress_pressure: Egress-congestion pressure at which an exit is
            reported as congested.
        relative_rate_per_second: Fractional change in peak density per second
            at which occupancy is reported as increasing, or the crowd as
            dispersing. Expressed as a fraction of current density so that it
            needs no unit and works identically on a calibrated and an
            uncalibrated camera. 0.01 is roughly a 45% change per minute.
        min_density_for_rate: Peak density below which a rate is not reported
            at all. A near-empty view produces enormous fractional changes from
            one person walking into it, and calling that "occupancy increasing"
            would be arithmetically true and operationally worthless. Read in
            whichever unit density is being measured in - 1.5 is a sparse space
            at 1.5 p/m2 and a pair of people sharing a cell in relative terms,
            which is the right floor in both.
        warning_pressure: Pressure at or above which an observation is shown as
            a warning rather than as information.
        critical_pressure: Pressure at or above which it is shown as critical.
        min_confidence: Observations below this confidence are suppressed. An
            uncertain observation on a safety display costs more attention than
            it returns.
        max_items: Most observations reported at once. The platform exists to
            surface what needs attention, not to enumerate everything it can
            see (``03:60-62``).
        margin_floor: Share of an observation's confidence that survives when
            its measurement only just cleared the threshold. The remainder
            scales with how far past the threshold it actually is.
        history_limit: Observations retained for the Evidence History.
    """

    congestion_pressure: float = 50.0

    movement_slowing_pressure: float = 25.0
    stationary_motion_pressure: float = 70.0
    stationary_density_pressure: float = 50.0

    flow_conflict_pressure: float = 30.0
    egress_pressure: float = 40.0

    relative_rate_per_second: float = 0.01
    min_density_for_rate: float = 1.5

    warning_pressure: float = 40.0
    critical_pressure: float = 75.0

    min_confidence: float = 0.25
    max_items: int = 5
    margin_floor: float = 0.7

    history_limit: int = 50

    def __post_init__(self) -> None:
        pressures = (
            self.congestion_pressure,
            self.movement_slowing_pressure,
            self.stationary_motion_pressure,
            self.stationary_density_pressure,
            self.flow_conflict_pressure,
            self.egress_pressure,
            self.warning_pressure,
            self.critical_pressure,
        )
        for pressure in pressures:
            if not 0.0 <= pressure <= 100.0:
                raise ValueError("Evidence pressure thresholds must be within [0, 100]")
        if self.warning_pressure > self.critical_pressure:
            raise ValueError("warning_pressure must not exceed critical_pressure")
        if self.relative_rate_per_second <= 0:
            raise ValueError("relative_rate_per_second must be positive")
        if self.min_density_for_rate < 0:
            raise ValueError("min_density_for_rate must not be negative")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0, 1]")
        if self.max_items < 1:
            raise ValueError("max_items must be at least 1")
        if not 0.0 <= self.margin_floor <= 1.0:
            raise ValueError("margin_floor must be within [0, 1]")
        if self.history_limit < 1:
            raise ValueError("history_limit must be at least 1")
