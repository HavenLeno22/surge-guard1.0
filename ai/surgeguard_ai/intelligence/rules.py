"""The decision rules.

One function per thing the platform is willing to suggest. Each reads the
stability assessment and the evidence that already exist, and either proposes an
action or returns ``None`` because the condition it watches for is not present.

**Nothing here measures anything, and nothing here is generated.** Every rule
selects a :class:`~surgeguard_ai.contracts.enums.RecommendationType` from a
closed vocabulary, cites the indicators that satisfied it, and phrases its
rationale from figures computed upstream. That is what makes the engine
auditable (``18:99-109``): a recommendation on screen can be traced to exactly
one rule, and that rule to exactly one measurement.

Rules are declared in **escalation order**, most serious first. The order is
load-bearing twice over - it is the decision hierarchy, and it is the tie-break
when two proposals are otherwise equal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.camera import CameraConfig, CameraZone
from ..contracts.enums import (
    AlertPriority,
    EvidenceType,
    OperationalStatus,
    RecommendationType,
    StabilityIndicator,
    ZoneType,
)
from ..contracts.evidence import EvidenceItem, EvidenceReport
from ..contracts.stability import IndicatorReading, StabilityAssessment
from .config import PRIORITY_BY_STATUS, DecisionConfig

__all__ = ["DecisionContext", "ProposedAction", "RULES"]


# ---------------------------------------------------------------------------
# Rule identifiers
#
# Stable strings, carried onto every action so a recommendation an operator saw
# can be traced back to the rule that produced it - after the fact, from a log
# or a stored report.
# ---------------------------------------------------------------------------

RULE_EMERGENCY = "emergency-response"
RULE_ESCALATE = "escalate-control-room"
RULE_OPEN_EXIT_ZONE = "open-exit-zone"
RULE_OPEN_EXIT_GENERAL = "open-exit-general"
RULE_DEPLOY_PERSONNEL = "deploy-personnel"
RULE_REDIRECT_CROWD = "redirect-crowd"
RULE_BROADCAST_GUIDANCE = "broadcast-guidance"
RULE_INCREASE_MONITORING = "increase-monitoring"
RULE_OBSERVE = "observe"


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything a rule is allowed to look at.

    Deliberately narrow. A rule cannot reach perception, cannot see a frame, and
    cannot recompute a measurement - it sees only the assessment, the evidence,
    and the camera configuration that says which zones exist.
    """

    stability: StabilityAssessment
    evidence: EvidenceReport | None
    camera: CameraConfig
    config: DecisionConfig

    @property
    def status(self) -> OperationalStatus:
        return self.stability.status

    def reading(self, indicator: StabilityIndicator) -> IndicatorReading | None:
        """An indicator's reading, or ``None`` when it could not be measured.

        An unmeasured indicator triggers no rule. Recommending an action on the
        strength of something never observed is the decision-support equivalent
        of the fabricated explanation Rule 8 forbids.
        """
        for reading in self.stability.breakdown.readings:
            if reading.indicator is indicator and reading.available:
                return reading
        return None

    def pressure(self, indicator: StabilityIndicator) -> float | None:
        reading = self.reading(indicator)
        return reading.pressure if reading is not None else None

    def contribution(self, indicator: StabilityIndicator) -> float:
        """Weighted instability points this indicator currently accounts for."""
        reading = self.reading(indicator)
        return reading.contribution if reading is not None else 0.0

    def has_evidence(self, evidence_type: EvidenceType) -> bool:
        """Whether the Evidence Engine reported a given observation this window."""
        if self.evidence is None:
            return False
        return any(item.evidence_type is evidence_type for item in self.evidence.items)

    def evidence_for(self, indicator: StabilityIndicator) -> tuple[EvidenceItem, ...]:
        """Observations explaining a given indicator."""
        if self.evidence is None:
            return ()
        return tuple(item for item in self.evidence.items if item.indicator is indicator)

    def worst_exit(self) -> CameraZone | None:
        """The configured EXIT zone, if the operator has drawn one.

        The prototype is single-camera with at most one exit zone; where several
        exist the first is taken, and the egress indicator already reports the
        worst of them, so the two agree on which exit the pressure came from.
        """
        exits = self.camera.zones_of_type(ZoneType.EXIT)
        return exits[0] if exits else None


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """One rule's proposal, before validation, ranking and capping.

    Not a :class:`~surgeguard_ai.contracts.intelligence.RecommendedAction` yet:
    a proposal has no display priority, because priority depends on what the
    *other* rules proposed, which no single rule can see.
    """

    rule_id: str
    recommendation_type: RecommendationType
    action: str
    rationale: str
    indicators: tuple[StabilityIndicator, ...]
    urgency: AlertPriority
    strength: float
    """How firmly the rule was satisfied, in ``[0, 1]``. Drives confidence."""

    zone_id: str | None = None
    supersedes: frozenset[str] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Rules, most serious first
# ---------------------------------------------------------------------------


def rule_emergency_response(context: DecisionContext) -> ProposedAction | None:
    """Emergency response, at a Critical crowd condition.

    Gated on the Operational Status rather than on any single indicator, and set
    at CRITICAL rather than lower on purpose. An emergency recommendation an
    operator learns to dismiss is worse than none at all, so this fires only
    when the platform's own headline assessment says the situation is critical.
    """
    if context.status.severity_rank < context.config.emergency_status.severity_rank:
        return None

    drivers = _ranked_indicators(context)
    if not drivers:
        return None

    return ProposedAction(
        rule_id=RULE_EMERGENCY,
        recommendation_type=RecommendationType.EMERGENCY_RESPONSE,
        action="Activate emergency response protocol",
        rationale=(
            f"Crowd Stability Index has fallen to {context.stability.csi_smoothed:.0f} "
            f"({_label(context.status)}). "
            f"{_driver_phrase(context, drivers)} "
            "Emergency procedures should be considered immediately."
        ),
        indicators=drivers,
        urgency=AlertPriority.CRITICAL,
        strength=1.0,
        supersedes=frozenset({RULE_INCREASE_MONITORING, RULE_OBSERVE}),
    )


def rule_escalate_to_control_room(context: DecisionContext) -> ProposedAction | None:
    """Escalate to the control room, at High Alert or worse."""
    if context.status.severity_rank < OperationalStatus.HIGH_ALERT.severity_rank:
        return None

    drivers = _ranked_indicators(context)
    if not drivers:
        return None

    return ProposedAction(
        rule_id=RULE_ESCALATE,
        recommendation_type=RecommendationType.ESCALATE_TO_CONTROL_ROOM,
        action="Escalate to the control room supervisor",
        rationale=(
            f"Conditions have reached {_label(context.status)} with a Crowd "
            f"Stability Index of {context.stability.csi_smoothed:.0f}. "
            f"{_driver_phrase(context, drivers)} "
            "A supervisor should be made aware."
        ),
        indicators=drivers,
        urgency=_urgency_for(context.status),
        strength=_strength_from_status(context.status),
        supersedes=frozenset({RULE_INCREASE_MONITORING, RULE_OBSERVE}),
    )


def rule_open_exit_zone(context: DecisionContext) -> ProposedAction | None:
    """Open a named exit, when a configured exit zone is approaching capacity.

    The only rule permitted to name infrastructure, and only because an operator
    configured that exit as a zone (Architecture Review C26).
    """
    pressure = context.pressure(StabilityIndicator.EGRESS_CONGESTION)
    if pressure is None or pressure < context.config.egress_pressure_trigger:
        return None

    zone = context.worst_exit()
    if zone is None:
        # Egress pressure without a zone should be impossible - the indicator
        # needs one to be measurable at all - but naming an exit the platform
        # cannot see is the one thing this rule must never do.
        return None

    reading = context.reading(StabilityIndicator.EGRESS_CONGESTION)
    occupancy = (reading.raw_value or 0.0) * 100.0 if reading else 0.0

    return ProposedAction(
        rule_id=RULE_OPEN_EXIT_ZONE,
        recommendation_type=RecommendationType.OPEN_EXIT,
        action=f"Open additional exit capacity at {zone.name}",
        rationale=(
            f"{zone.name} is at {occupancy:.0f}% of its nominal capacity. "
            "Additional egress capacity would relieve the measured congestion."
        ),
        indicators=(StabilityIndicator.EGRESS_CONGESTION,),
        urgency=_urgency_for(context.status),
        strength=_strength(pressure, context.config.egress_pressure_trigger),
        zone_id=zone.zone_id,
        supersedes=frozenset({RULE_OPEN_EXIT_GENERAL, RULE_OBSERVE}),
    )


def rule_open_exit_general(context: DecisionContext) -> ProposedAction | None:
    """Open additional egress, when density is severe but no exit zone is known.

    Names no infrastructure, because the platform has not been told where the
    exits are. It still cites a real measurement - the density that motivated
    it - so the operator can see why the suggestion was made and apply it to
    the venue they can see and the platform cannot.
    """
    if context.status.severity_rank < OperationalStatus.HIGH_ALERT.severity_rank:
        return None
    if context.worst_exit() is not None:
        # A zone exists; the named rule above is the correct one to fire.
        return None

    pressure = context.pressure(StabilityIndicator.DENSITY_PRESSURE)
    if pressure is None or pressure < context.config.density_pressure_trigger:
        return None

    return ProposedAction(
        rule_id=RULE_OPEN_EXIT_GENERAL,
        recommendation_type=RecommendationType.OPEN_EXIT,
        action="Open additional exit capacity",
        rationale=(
            f"{_density_phrase(context)} at {_label(context.status)}. "
            "No exit zone is configured for this camera, so the platform cannot "
            "name a specific gate - operator judgement is required on which to open."
        ),
        indicators=(StabilityIndicator.DENSITY_PRESSURE,),
        urgency=_urgency_for(context.status),
        strength=_strength(pressure, context.config.density_pressure_trigger),
        supersedes=frozenset({RULE_OBSERVE}),
    )


def rule_deploy_personnel(context: DecisionContext) -> ProposedAction | None:
    """Deploy staff to a congested area."""
    pressure = context.pressure(StabilityIndicator.DENSITY_PRESSURE)
    if pressure is None or pressure < context.config.density_pressure_trigger:
        return None
    if context.status is OperationalStatus.STABLE:
        # Density alone, in an otherwise stable crowd, does not warrant staff.
        return None

    indicators: list[StabilityIndicator] = [StabilityIndicator.DENSITY_PRESSURE]
    motion = context.pressure(StabilityIndicator.MOTION_SUPPRESSION)
    if motion is not None and motion >= context.config.motion_pressure_trigger:
        indicators.append(StabilityIndicator.MOTION_SUPPRESSION)

    return ProposedAction(
        rule_id=RULE_DEPLOY_PERSONNEL,
        recommendation_type=RecommendationType.DEPLOY_PERSONNEL,
        action="Deploy security personnel to the congested area",
        rationale=(
            f"{_density_phrase(context)}"
            + (
                " and movement has slowed against the recent baseline."
                if len(indicators) > 1
                else "."
            )
            + " Staff on the ground can manage flow directly."
        ),
        indicators=tuple(indicators),
        urgency=_urgency_for(context.status),
        strength=_strength(pressure, context.config.density_pressure_trigger),
        supersedes=frozenset({RULE_OBSERVE}),
    )


def rule_redirect_crowd(context: DecisionContext) -> ProposedAction | None:
    """Separate opposing flows."""
    pressure = context.pressure(StabilityIndicator.FLOW_CONFLICT)
    if pressure is None or pressure < context.config.flow_pressure_trigger:
        return None

    reading = context.reading(StabilityIndicator.FLOW_CONFLICT)
    opposing = (reading.raw_value or 0.0) * 100.0 if reading else 0.0

    return ProposedAction(
        rule_id=RULE_REDIRECT_CROWD,
        recommendation_type=RecommendationType.REDIRECT_CROWD,
        action="Redirect pedestrian flow to separate opposing movement",
        rationale=(
            f"{opposing:.0f}% of moving people are travelling against the main "
            "direction of the crowd. Separating the two directions reduces the "
            "friction that measurement describes."
        ),
        indicators=(StabilityIndicator.FLOW_CONFLICT,),
        urgency=_urgency_for(context.status),
        strength=_strength(pressure, context.config.flow_pressure_trigger),
        supersedes=frozenset({RULE_OBSERVE}),
    )


def rule_broadcast_guidance(context: DecisionContext) -> ProposedAction | None:
    """Announce guidance, when a dense group has stopped moving.

    Requires both suppressed movement and raised density - the same pairing the
    Evidence Engine requires for a stationary cluster, and for the same reason:
    people standing still in an empty space are waiting, and people standing
    still in a full one are a crowd that cannot move.
    """
    motion = context.pressure(StabilityIndicator.MOTION_SUPPRESSION)
    density = context.pressure(StabilityIndicator.DENSITY_PRESSURE)
    if motion is None or motion < context.config.motion_pressure_trigger:
        return None
    if density is None or density < context.config.density_pressure_trigger:
        return None

    return ProposedAction(
        rule_id=RULE_BROADCAST_GUIDANCE,
        recommendation_type=RecommendationType.BROADCAST_GUIDANCE,
        action="Broadcast movement guidance to the affected area",
        rationale=(
            "Movement has slowed markedly while density is elevated - a crowd "
            "that is losing the ability to move. A public announcement can "
            "restore flow without physical intervention."
        ),
        indicators=(
            StabilityIndicator.MOTION_SUPPRESSION,
            StabilityIndicator.DENSITY_PRESSURE,
        ),
        urgency=_urgency_for(context.status),
        strength=_strength(motion, context.config.motion_pressure_trigger),
        supersedes=frozenset({RULE_OBSERVE}),
    )


def rule_increase_monitoring(context: DecisionContext) -> ProposedAction | None:
    """Watch more closely, when conditions are developing.

    The early-warning rule, and the one that most justifies the platform: it
    fires on a *rate*, before any absolute threshold has been crossed.
    """
    rate = context.pressure(StabilityIndicator.RATE_OF_CHANGE)
    rising = rate is not None and rate >= context.config.rate_pressure_trigger
    watchful = context.status.severity_rank >= OperationalStatus.OBSERVE.severity_rank

    if not rising and not watchful:
        return None

    indicators: list[StabilityIndicator] = []
    if rising:
        indicators.append(StabilityIndicator.RATE_OF_CHANGE)
    if watchful:
        indicators.extend(
            indicator
            for indicator in _ranked_indicators(context)[:1]
            if indicator not in indicators
        )
    if not indicators:
        return None

    reason = (
        "Conditions are changing quickly enough to warrant closer attention "
        "before any threshold is crossed."
        if rising
        else f"Conditions have reached {_label(context.status)} and warrant closer attention."
    )

    return ProposedAction(
        rule_id=RULE_INCREASE_MONITORING,
        recommendation_type=RecommendationType.INCREASE_MONITORING,
        action="Increase monitoring of the affected area",
        rationale=reason,
        indicators=tuple(indicators),
        urgency=(
            AlertPriority.LOW
            if context.status is OperationalStatus.OBSERVE
            else _urgency_for(context.status)
        ),
        strength=(
            _strength(rate or 0.0, context.config.rate_pressure_trigger)
            if rising
            else _strength_from_status(context.status)
        ),
        supersedes=frozenset({RULE_OBSERVE}),
    )


def rule_observe(context: DecisionContext) -> ProposedAction | None:
    """Continue normal monitoring.

    The baseline recommendation, produced unconditionally and kept only when no
    rule above it fired. "No action required" is a real operational answer, and
    an empty panel does not say it - an operator looking at a blank
    Recommended Actions card cannot tell whether the platform assessed the
    situation and found nothing, or failed to assess it at all.
    """
    drivers = _ranked_indicators(context)
    measured = tuple(
        reading.indicator for reading in context.stability.breakdown.available_readings
    )
    if not measured:
        return None

    return ProposedAction(
        rule_id=RULE_OBSERVE,
        recommendation_type=RecommendationType.OBSERVE,
        action="Continue normal monitoring",
        rationale=(
            f"Crowd Stability Index is {context.stability.csi_smoothed:.0f} "
            f"({_label(context.status)}) and no measured indicator has crossed "
            "its intervention threshold. No action is required."
        ),
        indicators=drivers or measured[:1],
        urgency=AlertPriority.LOW,
        strength=1.0,
    )


#: Every rule, in escalation order - most serious first.
#:
#: The order is the decision hierarchy. It decides which proposal supersedes
#: which, and breaks ties between proposals of equal urgency and equal measured
#: contribution.
RULES = (
    rule_emergency_response,
    rule_escalate_to_control_room,
    rule_open_exit_zone,
    rule_open_exit_general,
    rule_deploy_personnel,
    rule_redirect_crowd,
    rule_broadcast_guidance,
    rule_increase_monitoring,
    rule_observe,
)


# ---------------------------------------------------------------------------
# Shared phrasing and scoring
# ---------------------------------------------------------------------------


def _ranked_indicators(context: DecisionContext) -> tuple[StabilityIndicator, ...]:
    """Measured indicators ordered by how much instability they account for."""
    return tuple(
        reading.indicator
        for reading in context.stability.breakdown.ranked_contributors()
        if reading.contribution > 0.0
    )


def _driver_phrase(
    context: DecisionContext, drivers: tuple[StabilityIndicator, ...]
) -> str:
    """Name the largest measured driver, in operator language."""
    if not drivers:
        return ""
    share = _share(context, drivers[0])
    return (
        f"The largest measured driver is {_indicator_label(drivers[0])} "
        f"at {share:.0f}% of current instability."
    )


def _density_phrase(context: DecisionContext) -> str:
    """State the density that motivated an action, in whichever unit it is in."""
    reading = context.reading(StabilityIndicator.DENSITY_PRESSURE)
    if reading is None or reading.raw_value is None:
        return "Crowd density is elevated"
    return f"Peak crowd density has reached {reading.raw_value:.1f}"


def _share(context: DecisionContext, indicator: StabilityIndicator) -> float:
    """An indicator's share of the total instability pressure, as a percentage."""
    total = context.stability.breakdown.total_pressure
    if total <= 0.0:
        return 0.0
    return context.contribution(indicator) / total * 100.0


def _strength(pressure: float, trigger: float) -> float:
    """How far past its trigger a measurement sits, in ``[0, 1]``."""
    span = 100.0 - trigger
    if span <= 0.0:
        return 1.0
    return min(max((pressure - trigger) / span, 0.0), 1.0)


def _strength_from_status(status: OperationalStatus) -> float:
    """Rule strength for a status-gated rule, from how severe the band is."""
    return min(status.severity_rank / 4.0, 1.0)


def _urgency_for(status: OperationalStatus) -> AlertPriority:
    """Baseline urgency for an action taken under a given crowd condition."""
    return PRIORITY_BY_STATUS[status]


def _label(status: OperationalStatus) -> str:
    """Operator-facing name for a crowd condition."""
    return _STATUS_LABELS[status]


def _indicator_label(indicator: StabilityIndicator) -> str:
    """Operator-facing name for an indicator (``05:849-851``)."""
    return _INDICATOR_LABELS[indicator]


#: Operator-facing names. Mirrors `design-system/tokens.ts` so the interface and
#: the engine's own prose call the same thing by the same name.
_STATUS_LABELS: dict[OperationalStatus, str] = {
    OperationalStatus.STABLE: "Stable",
    OperationalStatus.OBSERVE: "Observe",
    OperationalStatus.ATTENTION_REQUIRED: "Attention Required",
    OperationalStatus.HIGH_ALERT: "High Alert",
    OperationalStatus.CRITICAL: "Critical",
}

_INDICATOR_LABELS: dict[StabilityIndicator, str] = {
    StabilityIndicator.DENSITY_PRESSURE: "crowd density",
    StabilityIndicator.MOTION_SUPPRESSION: "movement",
    StabilityIndicator.EGRESS_CONGESTION: "exit congestion",
    StabilityIndicator.FLOW_CONFLICT: "opposing flow",
    StabilityIndicator.RATE_OF_CHANGE: "rate of change",
}
