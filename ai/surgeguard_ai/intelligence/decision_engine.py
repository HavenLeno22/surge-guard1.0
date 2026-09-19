"""The Operational Decision Engine (``18_Operationa_ Decision_Engine _ODE).md``).

::

    StabilityAssessment ─┐
    IndicatorBreakdown  ─┼─► RULES ─► conflicts ─► validate ─► rank ─► REPORT
    EvidenceReport      ─┤
    OperationalStatus   ─┘

**The engine measures nothing.** It runs no perception, no model, no
probability. Every figure it prints was computed by an earlier stage, and every
recommendation is a selection from a closed vocabulary made by exactly one rule
whose identifier travels with the result. Given identical inputs it produces an
identical report, every time - which is what makes it auditable after an
incident rather than merely plausible during one.

The decision pipeline, in order:

1. **Evaluate** every rule in escalation order. Each proposes an action or
   declines.
2. **Resolve conflicts.** A stronger proposal removes the weaker ones it
   supersedes - "activate emergency response" alongside "continue normal
   monitoring" is not a prioritised list, it is a contradiction.
3. **Validate.** A proposal citing an unmeasured indicator, or naming a zone
   that is not configured, or falling below the confidence floor, is dropped
   and counted. Nothing invalid reaches an operator.
4. **Rank and cap.** By urgency, then by how much instability the supporting
   indicators actually account for, then by escalation order.
5. **Explain.** Primary Causes from the breakdown, a situation summary from the
   status and the dominant cause, and the evidence carried through verbatim.
6. **Gate.** Report only when something material changed, or enough time has
   passed.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime

from ..contracts.camera import CameraConfig
from ..contracts.crowd import CrowdMetrics
from ..contracts.enums import (
    AlertPriority,
    OperationalStatus,
    RecommendationType,
    Severity,
    StabilityIndicator,
)
from ..contracts.evidence import EvidenceReport
from ..contracts.intelligence import (
    OperationalIntelligenceReport,
    PrimaryCause,
    RecommendedAction,
)
from ..contracts.stability import StabilityAssessment
from ..errors import IntelligenceError
from .config import PRIORITY_BY_STATUS, DecisionConfig
from .engine import DecisionIntelligenceEngine
from .rules import RULES, DecisionContext, ProposedAction

__all__ = ["DeterministicDecisionEngine"]

logger = logging.getLogger(__name__)

#: Operator-facing indicator names, for Primary Cause labels (``05:849-851``).
_CAUSE_LABELS: dict[StabilityIndicator, str] = {
    StabilityIndicator.DENSITY_PRESSURE: "Crowd density",
    StabilityIndicator.MOTION_SUPPRESSION: "Movement suppression",
    StabilityIndicator.EGRESS_CONGESTION: "Exit congestion",
    StabilityIndicator.FLOW_CONFLICT: "Opposing flow",
    StabilityIndicator.RATE_OF_CHANGE: "Rate of change",
}

_STATUS_PROSE: dict[OperationalStatus, str] = {
    OperationalStatus.STABLE: "Conditions are stable",
    OperationalStatus.OBSERVE: "Conditions warrant observation",
    OperationalStatus.ATTENTION_REQUIRED: "Conditions require attention",
    OperationalStatus.HIGH_ALERT: "Conditions have reached High Alert",
    OperationalStatus.CRITICAL: "Conditions are critical",
}


class DeterministicDecisionEngine(DecisionIntelligenceEngine):
    """Rule-based operational guidance, with no learned component.

    Stateful in three respects, each required by what a report *is*:

    - **The last reported condition**, so a window can be recognised as
      materially unchanged and suppressed.
    - **A sequence counter**, so consumers can order reports and detect a
      missed one.
    - **History**, so the revision series survives long enough to be reviewed.

    All three are discarded by :meth:`reset` when frame continuity breaks.
    """

    def __init__(self, config: DecisionConfig | None = None) -> None:
        self._config = config or DecisionConfig()
        self._history: deque[OperationalIntelligenceReport] = deque(
            maxlen=self._config.history_limit
        )
        self._sequence = 0
        self._revision = 0
        self._latest: OperationalIntelligenceReport | None = None
        self._last_reported_at: datetime | None = None

        self._priority: AlertPriority | None = None
        self._priority_candidate: AlertPriority | None = None
        self._priority_run = 0

    @property
    def config(self) -> DecisionConfig:
        """The policy in force, so a caller can report what it decided with."""
        return self._config

    # -- Evaluation ---------------------------------------------------------

    def evaluate(
        self,
        stability: StabilityAssessment,
        crowd: CrowdMetrics,
        camera: CameraConfig,
        evidence: EvidenceReport | None,
    ) -> OperationalIntelligenceReport | None:
        """Assess one window and report if there is anything new to say."""
        try:
            return self._evaluate(stability, crowd, camera, evidence)
        except IntelligenceError:
            raise
        except Exception as error:  # noqa: BLE001 - surfaced as the stage's own failure
            raise IntelligenceError(f"Decision evaluation failed: {error}") from error

    def _evaluate(
        self,
        stability: StabilityAssessment,
        crowd: CrowdMetrics,
        camera: CameraConfig,
        evidence: EvidenceReport | None,
    ) -> OperationalIntelligenceReport | None:
        context = DecisionContext(
            stability=stability, evidence=evidence, camera=camera, config=self._config
        )

        proposals = [
            proposal for rule in RULES if (proposal := rule(context)) is not None
        ]
        surviving = _resolve_conflicts(proposals)
        valid, invalid = self._validate(surviving, context)

        ranked = sorted(valid, key=lambda pair: _rank_key(pair[0], pair[1], context))
        shown = ranked[: self._config.max_actions]
        suppressed = invalid + (len(ranked) - len(shown))

        actions = tuple(
            _to_action(proposal, confidence, priority)
            for priority, (proposal, confidence) in enumerate(shown, start=1)
        )
        priority = self._stabilise_priority(_operational_priority(context))

        if not self._is_reportable(stability, priority, actions):
            return None

        report = self._build(stability, crowd, context, actions, priority, suppressed)
        self._record(report)
        return report

    def latest(self) -> OperationalIntelligenceReport | None:
        return self._latest

    def history(self) -> tuple[OperationalIntelligenceReport, ...]:
        return tuple(reversed(self._history))

    def reset(self) -> None:
        """Discard reporting state, history and counters."""
        self._history.clear()
        self._sequence = 0
        self._revision = 0
        self._latest = None
        self._last_reported_at = None
        self._priority = None
        self._priority_candidate = None
        self._priority_run = 0

    # -- Priority -----------------------------------------------------------

    def _stabilise_priority(self, observed: AlertPriority) -> AlertPriority:
        """Hold the operational priority steady across a noisy window.

        Priority combines two signals of very different steadiness: the
        Operational Status, which the index has already debounced, and evidence
        severity, which is per-window and unsmoothed by design. Without a gate
        the result is as noisy as the rawer of the two - observed live as the
        figure alternating between Low and Medium every second while the crowd
        condition never moved, and writing a timeline entry each time.

        Symmetric, unlike the band hysteresis: priority is a *consequence* of a
        condition rather than an assessment of one, so there is no case for
        raising it faster than lowering it - the status it follows has already
        applied that asymmetry.
        """
        if self._priority is None:
            self._priority = observed
            self._priority_candidate = None
            self._priority_run = 0
            return observed

        if observed is self._priority:
            self._priority_candidate = None
            self._priority_run = 0
            return self._priority

        if observed is self._priority_candidate:
            self._priority_run += 1
        else:
            self._priority_candidate = observed
            self._priority_run = 1

        if self._priority_run >= self._config.priority_hysteresis_windows:
            self._priority = observed
            self._priority_candidate = None
            self._priority_run = 0

        return self._priority

    # -- Validation ---------------------------------------------------------

    def _validate(
        self, proposals: list[ProposedAction], context: DecisionContext
    ) -> tuple[list[tuple[ProposedAction, float]], int]:
        """Drop anything unsupportable, and count what was dropped.

        Three checks, each closing a way a recommendation could reach an
        operator without a measurement behind it:

        - Every cited indicator must be **available** in this window's
          breakdown. A rule firing on a stale or absent reading would advise on
          something never observed.
        - Any named zone must be **configured**. The platform does not invent
          infrastructure (Architecture Review C26).
        - Confidence must clear the floor. Acting on an uncertain
          recommendation costs more than not seeing it.
        """
        measured = {
            reading.indicator for reading in context.stability.breakdown.available_readings
        }
        zone_ids = {zone.zone_id for zone in context.camera.zones}

        valid: list[tuple[ProposedAction, float]] = []
        invalid = 0

        for proposal in proposals:
            if not proposal.indicators or not set(proposal.indicators) <= measured:
                logger.debug(
                    "Rejecting recommendation citing an unmeasured indicator",
                    extra={"rule_id": proposal.rule_id},
                )
                invalid += 1
                continue

            if proposal.zone_id is not None and proposal.zone_id not in zone_ids:
                logger.debug(
                    "Rejecting recommendation naming an unconfigured zone",
                    extra={"rule_id": proposal.rule_id, "zone_id": proposal.zone_id},
                )
                invalid += 1
                continue

            confidence = self._confidence_for(proposal, context)
            if confidence < self._config.min_action_confidence:
                invalid += 1
                continue

            valid.append((proposal, confidence))

        return valid, invalid

    def _confidence_for(self, proposal: ProposedAction, context: DecisionContext) -> float:
        """Decision Confidence, reduced by how firmly the rule was satisfied.

        An action cannot be more certain than the measurements behind it, and a
        rule that only just triggered is genuinely less certain than one far
        past its threshold.
        """
        floor = self._config.action_confidence_floor
        scaled = floor + (1.0 - floor) * min(max(proposal.strength, 0.0), 1.0)
        return min(max(context.stability.confidence.value * scaled, 0.0), 1.0)

    # -- Reporting gate -----------------------------------------------------

    def _is_reportable(
        self,
        stability: StabilityAssessment,
        priority: AlertPriority,
        actions: tuple[RecommendedAction, ...],
    ) -> bool:
        """Whether this window warrants a new report.

        Reporting every window would reissue guidance ten times a second, which
        is precisely the flooding the platform exists to prevent. Reporting only
        on a timer would delay a band transition an operator needs immediately.
        Both matter, so both are checked.
        """
        previous = self._latest
        if previous is None:
            return True

        if self._config.report_on_status_change and stability.status is not previous.status:
            return True
        if self._config.report_on_priority_change and priority is not previous.priority:
            return True
        if self._config.report_on_action_change and _action_signature(
            actions
        ) != _action_signature(previous.recommended_actions):
            return True

        # A report carries the confidence it was issued with. Leaving it behind
        # while the live assessment moves puts two different confidence figures
        # on one screen, which an operator has no way to reconcile.
        if (
            abs(stability.confidence.value - previous.confidence)
            >= self._config.report_on_confidence_change
        ):
            return True

        if self._last_reported_at is None:
            return True
        elapsed = (datetime.now(UTC) - self._last_reported_at).total_seconds()
        return elapsed >= self._config.report_min_interval_seconds

    # -- Construction -------------------------------------------------------

    def _build(
        self,
        stability: StabilityAssessment,
        crowd: CrowdMetrics,
        context: DecisionContext,
        actions: tuple[RecommendedAction, ...],
        priority: AlertPriority,
        suppressed: int,
    ) -> OperationalIntelligenceReport:
        causes = _primary_causes(stability, crowd)

        self._sequence += 1
        # A revision series per Crowd Event (``06:345``). No Crowd Event
        # lifecycle exists yet, so the whole session is treated as one episode
        # and the revision advances with the sequence. When the lifecycle lands
        # this resets per episode and nothing else here changes.
        self._revision += 1

        return OperationalIntelligenceReport(
            sequence=self._sequence,
            revision=self._revision,
            generated_at=datetime.now(UTC),
            frame_seq=stability.frame_seq,
            status=stability.status,
            priority=priority,
            csi=stability.csi_smoothed,
            confidence=stability.confidence.value,
            situation_summary=_situation_summary(context, causes, actions),
            primary_causes=causes,
            supporting_evidence=context.evidence.items if context.evidence else (),
            dominant_contributor_statement=_dominant_contributor(causes),
            recommended_actions=actions,
            suppressed_actions=suppressed,
        )

    def _record(self, report: OperationalIntelligenceReport) -> None:
        self._latest = report
        self._last_reported_at = report.generated_at
        self._history.append(report)

        logger.info(
            "Operational Intelligence Report issued",
            extra={
                "sequence": report.sequence,
                "status": report.status.value,
                "priority": report.priority.value,
                "csi": round(report.csi, 1),
                "actions": len(report.recommended_actions),
            },
        )


# ---------------------------------------------------------------------------
# Decision pipeline stages
# ---------------------------------------------------------------------------


def _resolve_conflicts(proposals: list[ProposedAction]) -> list[ProposedAction]:
    """Remove proposals that a surviving stronger proposal supersedes.

    "Activate emergency response" beside "continue normal monitoring" is not a
    prioritised list; it is a contradiction, and an operator reading it learns
    the list cannot be trusted.
    """
    superseded: set[str] = set()
    for proposal in proposals:
        superseded.update(proposal.supersedes)
    return [proposal for proposal in proposals if proposal.rule_id not in superseded]


def _rank_key(
    proposal: ProposedAction, confidence: float, context: DecisionContext
) -> tuple[float, ...]:
    """Sort key placing the most urgent, best-supported action first.

    Urgency leads, because that is what an operator scans for. Ties break on the
    *largest* instability contribution among the supporting indicators - among
    two equally urgent actions, the one addressing the bigger problem is listed
    first - then on escalation order, then confidence. Negated because Python
    sorts ascending and the most important action must come first.

    Deliberately the maximum rather than the sum. Summing would rank an action
    higher simply for citing more indicators, so a rule that happened to name
    three minor contributors would outrank one addressing the single dominant
    driver. Ranking must measure what an action addresses, not how much it
    mentions.
    """
    contribution = max(
        (context.contribution(indicator) for indicator in proposal.indicators),
        default=0.0,
    )
    return (
        -proposal.urgency.rank,
        -contribution,
        -proposal.recommendation_type.escalation_rank,
        -confidence,
    )


def _to_action(
    proposal: ProposedAction, confidence: float, priority: int
) -> RecommendedAction:
    """Turn a validated proposal into the contract the interface displays."""
    return RecommendedAction(
        priority=priority,
        recommendation_type=proposal.recommendation_type,
        action=proposal.action,
        rationale=proposal.rationale,
        supporting_indicators=proposal.indicators,
        confidence=confidence,
        urgency=proposal.urgency,
        zone_id=proposal.zone_id,
        rule_id=proposal.rule_id,
    )


def _operational_priority(context: DecisionContext) -> AlertPriority:
    """Operational priority of the situation as a whole.

    The Operational Status sets the baseline, because it is already the
    platform's assessment of the crowd. A Critical *observation* inside a
    lesser condition raises it one step - evidence that severe is worth
    treating more urgently than the band alone suggests - and nothing ever
    lowers it.
    """
    base = PRIORITY_BY_STATUS[context.status]
    if context.evidence is None:
        return base

    highest = context.evidence.highest_severity
    if highest is Severity.CRITICAL:
        return AlertPriority.from_rank(base.rank + 1)
    return base


def _primary_causes(
    stability: StabilityAssessment, crowd: CrowdMetrics
) -> tuple[PrimaryCause, ...]:
    """Derive causes from the indicator breakdown - never authored.

    This is the whole of Rule 8 in one function: the operator is shown what is
    driving the index and by how much, taken directly from the arithmetic that
    produced the index, rather than from a narrative composed about it.
    """
    total = stability.breakdown.total_pressure
    if total <= 0.0:
        return ()

    causes: list[PrimaryCause] = []
    for reading in stability.breakdown.ranked_contributors():
        if reading.contribution <= 0.0 or reading.pressure is None:
            continue
        causes.append(
            PrimaryCause(
                indicator=reading.indicator,
                label=_CAUSE_LABELS[reading.indicator],
                contribution_pct=reading.contribution / total * 100.0,
                pressure=reading.pressure,
                detail=_cause_detail(reading.indicator, reading.raw_value, crowd),
            )
        )
    return tuple(causes)


def _cause_detail(
    indicator: StabilityIndicator, raw_value: float | None, crowd: CrowdMetrics
) -> str | None:
    """The measurement behind a cause, in its own unit.

    Density carries its unit explicitly, because without calibration these are
    persons per grid cell and presenting them as persons/m2 would be a
    fabricated unit (Architecture Review C21).
    """
    if raw_value is None:
        return None

    unit = "p/m2" if crowd.is_metric else "rel"
    match indicator:
        case StabilityIndicator.DENSITY_PRESSURE:
            return f"peak density {raw_value:.1f} {unit}"
        case StabilityIndicator.MOTION_SUPPRESSION:
            return f"median speed {(1.0 - raw_value) * 100:.0f}% below baseline"
        case StabilityIndicator.EGRESS_CONGESTION:
            return f"exit occupancy {raw_value * 100:.0f}% of capacity"
        case StabilityIndicator.FLOW_CONFLICT:
            return f"{raw_value * 100:.0f}% of movement opposing the majority"
        case StabilityIndicator.RATE_OF_CHANGE:
            return f"density changing {raw_value:+.3f} {unit}/s"
    return None


def _situation_summary(
    context: DecisionContext,
    causes: tuple[PrimaryCause, ...],
    actions: tuple[RecommendedAction, ...],
) -> str:
    """One or two sentences of plain operational language.

    Composed from a fixed template rather than generated. Every clause is
    either a measured figure or a fixed phrase keyed to the Operational Status,
    so the same conditions always produce the same sentence - which is what lets
    an operator learn to read it at a glance, and what makes it reproducible in
    an incident review.
    """
    prose = _STATUS_PROSE[context.status]
    lead = f"{prose}. Crowd Stability Index is {context.stability.csi_smoothed:.0f}"

    if causes:
        lead += f", driven mainly by {causes[0].label.lower()}"
        if causes[0].detail:
            lead += f" ({causes[0].detail})"
    lead += "."

    if not actions:
        return f"{lead} No guidance is available for this window."

    top = actions[0]
    if top.recommendation_type is RecommendationType.OBSERVE:
        return f"{lead} No intervention is required."
    return f"{lead} Highest-priority guidance: {top.action.lower()}."


def _dominant_contributor(causes: tuple[PrimaryCause, ...]) -> str | None:
    """Name the largest driver and its share.

    Replaces the rejected "Estimated Improvement: CSI +18" (Architecture Review
    C4). It states what has been measured and claims no outcome, which is both
    honest and - to a technical audience - more credible than a fabricated
    integer.
    """
    if not causes:
        return None
    dominant = causes[0]
    return (
        f"Largest contributor: {dominant.label.lower()}, "
        f"{dominant.contribution_pct:.0f}% of current instability."
    )


def _action_signature(actions: tuple[RecommendedAction, ...]) -> tuple[str, ...]:
    """What must change for guidance to count as *new*.

    The rule identifiers, in order. Deliberately not the rationale text: that
    carries live figures which change every window, and comparing it would make
    every window look like new guidance.
    """
    return tuple(action.rule_id for action in actions)
