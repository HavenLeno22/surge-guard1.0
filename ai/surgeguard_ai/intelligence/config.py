"""Operational Decision Engine configuration.

``18:99-109`` requires the engine to be **configurable** alongside transparent,
explainable, deterministic and auditable. Every threshold that decides whether
guidance appears, how urgent it is, and how often a report is reissued lives
here rather than inside the engine.

The values are venue policy, not physics. A stadium concourse and a station
platform warrant different escalation points, and changing one should be a
configuration change - never a code change (``18:177``, venue-specific policies).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.enums import AlertPriority, OperationalStatus

__all__ = ["DecisionConfig", "PRIORITY_BY_STATUS"]


#: Baseline operational priority for each crowd condition.
#:
#: The Operational Status is the platform's own assessment of the crowd, so the
#: priority of acting on it follows from it directly rather than being asserted
#: separately. Evidence severity can raise this by one step (never lower it):
#: a Critical observation inside an Attention Required condition is a situation
#: worth treating more urgently than the band alone suggests.
PRIORITY_BY_STATUS: dict[OperationalStatus, AlertPriority] = {
    OperationalStatus.STABLE: AlertPriority.LOW,
    OperationalStatus.OBSERVE: AlertPriority.LOW,
    OperationalStatus.ATTENTION_REQUIRED: AlertPriority.MEDIUM,
    OperationalStatus.HIGH_ALERT: AlertPriority.HIGH,
    OperationalStatus.CRITICAL: AlertPriority.CRITICAL,
}


@dataclass(frozen=True, slots=True)
class DecisionConfig:
    """Thresholds governing what the engine recommends, and when it says so.

    Attributes:
        max_actions: Most recommendations shown at once. The platform exists to
            surface what needs attention, not to enumerate every option
            (``03:60-62``). Beyond about four, a prioritised list stops being
            prioritised.
        min_action_confidence: Actions below this confidence are dropped and
            counted. Acting on an uncertain recommendation costs more than not
            seeing it.
        report_min_interval_seconds: Minimum time between reports when nothing
            has materially changed. A report on every analysis window would
            reissue guidance ten times a second, which is the flooding
            ``05:618`` and ``03:60-62`` exist to prevent.
        report_on_status_change: Always issue a report when the Operational
            Status changes, regardless of the interval. A band transition is the
            single most important thing an operator needs told about.
        report_on_priority_change: Likewise for a change in operational
            priority, which can move without the band moving.
        report_on_action_change: Likewise when the recommended action set
            changes - new guidance is by definition something new to say.
        density_pressure_trigger: Density pressure at or above which
            congestion-relief guidance becomes eligible.
        egress_pressure_trigger: Egress pressure at or above which exit guidance
            becomes eligible.
        motion_pressure_trigger: Motion-suppression pressure at or above which
            movement guidance becomes eligible.
        flow_pressure_trigger: Flow-conflict pressure at or above which
            flow-separation guidance becomes eligible.
        rate_pressure_trigger: Rate-of-change pressure at or above which
            early-warning guidance becomes eligible.
        emergency_status: Operational Status at which emergency guidance
            becomes eligible. Set at CRITICAL and not lower: an emergency
            recommendation the operator learns to dismiss is worse than none.
        history_limit: Reports retained in memory for the revision series.
    """

    max_actions: int = 4
    min_action_confidence: float = 0.2
    action_confidence_floor: float = 0.7
    """Share of an action's confidence that survives when its triggering rule
    was only just satisfied. The remainder scales with how far past the trigger
    the measurement actually sits - the same treatment the Evidence Engine
    applies to an observation, for the same reason."""

    report_min_interval_seconds: float = 20.0
    report_on_status_change: bool = True
    report_on_priority_change: bool = True
    report_on_action_change: bool = True

    report_on_confidence_change: float = 0.15
    """Change in Decision Confidence that makes a window worth reporting.

    A report carries the confidence it was issued with, and guidance is
    otherwise reissued only when the *situation* changes - so during the
    startup ramp, while temporal sufficiency fills, the report can sit at 20%
    while the live assessment beside it reads 60%. Both figures are correct and
    they mean different things, but an operator seeing two confidences on one
    screen has no way to know that.

    Set to a step large enough that ordinary jitter does not trigger it: the
    ramp produces a handful of reports in the first seconds and none afterwards,
    because confidence is steady once the window is full.
    """

    priority_hysteresis_windows: int = 3
    """Consecutive windows a new operational priority must hold before it is
    adopted.

    Required because priority is derived from two signals of very different
    steadiness: the Operational Status, which the Crowd Stability Index has
    already debounced, and evidence severity, which is measured per window and
    unsmoothed by design. Combining them without a gate produces a priority as
    noisy as the rawer of the two - observed live as the figure alternating
    between Low and Medium every second while the crowd condition never moved.

    The same discipline the index applies to its own bands, applied one layer
    up."""

    density_pressure_trigger: float = 50.0
    egress_pressure_trigger: float = 40.0
    motion_pressure_trigger: float = 40.0
    flow_pressure_trigger: float = 40.0
    rate_pressure_trigger: float = 40.0

    emergency_status: OperationalStatus = OperationalStatus.CRITICAL

    history_limit: int = 50

    def __post_init__(self) -> None:
        if self.max_actions < 1:
            raise ValueError("max_actions must be at least 1")
        if not 0.0 <= self.min_action_confidence <= 1.0:
            raise ValueError("min_action_confidence must be within [0, 1]")
        if not 0.0 <= self.action_confidence_floor <= 1.0:
            raise ValueError("action_confidence_floor must be within [0, 1]")
        if self.report_min_interval_seconds < 0:
            raise ValueError("report_min_interval_seconds must not be negative")
        if self.priority_hysteresis_windows < 1:
            raise ValueError("priority_hysteresis_windows must be at least 1")
        if not 0.0 < self.report_on_confidence_change <= 1.0:
            raise ValueError("report_on_confidence_change must be within (0, 1]")
        for trigger in (
            self.density_pressure_trigger,
            self.egress_pressure_trigger,
            self.motion_pressure_trigger,
            self.flow_pressure_trigger,
            self.rate_pressure_trigger,
        ):
            if not 0.0 <= trigger <= 100.0:
                raise ValueError("Pressure triggers must be within [0, 100]")
        if self.history_limit < 1:
            raise ValueError("history_limit must be at least 1")
