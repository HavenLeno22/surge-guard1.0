"""Operational decision state - reports, workflow phase and the timeline.

Subscribes to :attr:`~app.core.event_bus.DomainEvent.ANALYSIS_RECEIVED` and
turns each completed assessment into the things an operator sees: the current
Operational Intelligence Report, the workflow phase, and the timeline entries
recording what changed.

**The engine decides; this service records and announces.** The Operational
Decision Engine lives in the AI package and is already run inside the analysis
pipeline, so its output arrives here alongside the assessment that produced it.
This module adds no operational logic of its own - it holds state, decides what
was worth writing to the timeline, and publishes domain events. Keeping the
judgement in one place and the plumbing in another is what lets the engine be
tested without a backend and the backend without an engine.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from surgeguard_ai.contracts import (
    AnalysisResult,
    OperationalIntelligenceReport,
    OperationalState,
    OperationalStatus,
    Severity,
    TimelineEntryType,
)

from ..core.constants import PERCEPTION_STALE_AFTER_SECONDS
from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from ..schemas.timeline import TimelineEntry
from .operational_state import OperationalStateService, OperatorAction
from .timeline_service import TimelineService

__all__ = ["DecisionSnapshot", "DecisionService", "IssuedReport", "StateChange"]

logger = get_logger(__name__)

#: Operator-facing names for a crowd condition. Mirrors the engine's own prose
#: and the frontend tokens, so one condition is called one thing everywhere.
_STATUS_LABELS: dict[OperationalStatus, str] = {
    OperationalStatus.STABLE: "Stable",
    OperationalStatus.OBSERVE: "Observe",
    OperationalStatus.ATTENTION_REQUIRED: "Attention Required",
    OperationalStatus.HIGH_ALERT: "High Alert",
    OperationalStatus.CRITICAL: "Critical",
}

#: Timeline severity for a crowd condition. A status change is informational
#: until the condition itself is serious - a control room that logs every
#: transition as a warning teaches operators to skim the timeline.
_STATUS_SEVERITY: dict[OperationalStatus, Severity] = {
    OperationalStatus.STABLE: Severity.INFO,
    OperationalStatus.OBSERVE: Severity.INFO,
    OperationalStatus.ATTENTION_REQUIRED: Severity.WARNING,
    OperationalStatus.HIGH_ALERT: Severity.WARNING,
    OperationalStatus.CRITICAL: Severity.CRITICAL,
}

_OPERATOR_TITLES: dict[OperatorAction, str] = {
    OperatorAction.ACKNOWLEDGE: "Acknowledged by {actor}",
    OperatorAction.LOG_ACTION: "Action logged by {actor}",
    OperatorAction.CLOSE: "Situation closed by {actor}",
}

_STATE_LABELS: dict[OperationalState, str] = {
    OperationalState.MONITORING: "Monitoring",
    OperationalState.OBSERVING: "Observing",
    OperationalState.INVESTIGATING: "Investigating",
    OperationalState.RESPONDING: "Responding",
    OperationalState.RECOVERING: "Recovering",
}


@dataclass(frozen=True, slots=True)
class IssuedReport:
    """A report and the camera whose decision service issued it.

    The report contract itself names no camera. With several cameras publishing
    on one bus, a consumer handed a bare report cannot tell whose it is - which
    left two cameras' guidance alternating in one panel.
    """

    camera_id: str
    report: OperationalIntelligenceReport


@dataclass(frozen=True, slots=True)
class StateChange:
    """A camera's operator workflow phase changed, and who changed it, if anyone did."""

    camera_id: str
    state: OperationalState
    actor: str | None = None


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    """The current report with its age.

    Carried together for the same reason every other snapshot in this backend
    does it: a consumer handed a bare report cannot tell whether it describes
    the situation now or the situation before the pipeline stopped.
    """

    report: OperationalIntelligenceReport
    received_at: datetime
    age_seconds: float
    is_stale: bool


class DecisionService:
    """Holds the latest guidance, the workflow phase and the timeline."""

    def __init__(
        self,
        timeline: TimelineService,
        operational_state: OperationalStateService,
        event_bus: EventBus | None = None,
        *,
        camera_id: str,
        history_limit: int = 50,
    ) -> None:
        """
        Args:
            timeline: Where operational events are recorded.
            operational_state: The operator workflow machine.
            event_bus: Bus on which to announce reports and timeline entries.
            camera_id: The camera this service speaks for.
            history_limit: Reports retained. Bounded because a control-room
                process runs for a shift: an unbounded list of reports is a
                slow leak, and the engine's own history is bounded for the same
                reason (Architecture Review R14).
        """
        self._timeline = timeline
        self._operational_state = operational_state
        self._event_bus = event_bus
        self._camera_id = camera_id

        self._latest: OperationalIntelligenceReport | None = None
        self._received_at: datetime | None = None
        self._history: deque[OperationalIntelligenceReport] = deque(maxlen=history_limit)
        self._last_status: OperationalStatus | None = None
        self._last_frame_seq: int | None = None
        #: When an assessment last arrived - not when a report was last issued.
        #: Guidance is reissued only on a material change, so an old report
        #: during steady conditions is correct. What makes it *stale* is the
        #: analysis stream stopping, which is what this measures.
        self._last_analysis_at: datetime | None = None

    # -- Writing ------------------------------------------------------------

    def handle_analysis(self, analysis: AnalysisResult) -> None:
        """Record one completed assessment. Never raises.

        Synchronous for the same reason
        :meth:`~app.services.crowd_intelligence.CrowdIntelligenceService.handle_perception`
        is: the timeline is an ordered log, and a coroutine handler could
        interleave two windows and record them out of order.

        Assessments for other cameras are ignored: guidance, the workflow phase
        and continuity are all properties of the camera this service speaks for.
        """
        if analysis.camera_id != self._camera_id:
            return
        try:
            self._handle(analysis)
        except Exception as error:  # noqa: BLE001 - a subscriber must not escape
            logger.error(
                "Decision handling failed",
                exc_info=error,
                extra={"frame_seq": analysis.frame_seq},
            )

    def _handle(self, analysis: AnalysisResult) -> None:
        self._note_continuity(analysis)
        self._last_analysis_at = datetime.now(UTC)

        entries: list[TimelineEntry] = []
        entries.extend(self._record_status_change(analysis))
        entries.extend(self._record_workflow_change(analysis))
        entries.extend(self._record_report(analysis))

        for entry in entries:
            self._dispatch(DomainEvent.TIMELINE_ENTRY_ADDED, entry)

    def _record_status_change(self, analysis: AnalysisResult) -> list[TimelineEntry]:
        """A band transition - the single most important thing to log.

        Driven by the assessment's own ``status_changed`` flag, which is already
        hysteresis-debounced, rather than by comparing statuses here. Comparing
        would log the flicker the hysteresis exists to suppress.
        """
        stability = analysis.stability
        if not stability.status_changed or self._last_status is stability.status:
            self._last_status = stability.status
            return []

        previous = self._last_status
        self._last_status = stability.status

        direction = "escalated to" if _is_escalation(previous, stability.status) else "returned to"
        detail = f"Crowd Stability Index {stability.csi_smoothed:.0f}."
        if previous is not None:
            detail = f"From {_STATUS_LABELS[previous]}. " + detail

        return [
            self._timeline.append(
                entry_type=TimelineEntryType.STATUS_CHANGE,
                severity=_STATUS_SEVERITY[stability.status],
                title=f"Operational Status {direction} {_STATUS_LABELS[stability.status]}",
                detail=detail,
                camera_id=analysis.camera_id,
                occurred_at=analysis.frame_ts,
            )
        ]

    def _record_workflow_change(self, analysis: AnalysisResult) -> list[TimelineEntry]:
        """A change in the operator workflow phase."""
        new_state = self._operational_state.observe(analysis.stability.status)
        if new_state is None:
            return []

        self._dispatch(
            DomainEvent.OPERATIONAL_STATE_CHANGED, StateChange(self._camera_id, new_state)
        )
        return [
            self._timeline.append(
                entry_type=TimelineEntryType.SYSTEM,
                severity=Severity.INFO,
                title=f"Operational State: {_STATE_LABELS[new_state]}",
                detail=(
                    "Conditions returned to stable; the platform is tracking recovery."
                    if new_state is OperationalState.RECOVERING
                    else None
                ),
                camera_id=analysis.camera_id,
                occurred_at=analysis.frame_ts,
            )
        ]

    def _record_report(self, analysis: AnalysisResult) -> list[TimelineEntry]:
        """A new Operational Intelligence Report, and the guidance it carries."""
        report = analysis.intelligence
        if report is None:
            return []

        now = datetime.now(UTC)
        previous = self._latest

        self._latest = report
        self._received_at = now
        self._history.append(report)

        self._dispatch(DomainEvent.OIR_GENERATED, IssuedReport(self._camera_id, report))

        entries: list[TimelineEntry] = []

        if previous is not None and report.priority is not previous.priority:
            entries.append(
                self._timeline.append(
                    entry_type=TimelineEntryType.STATUS_CHANGE,
                    severity=_STATUS_SEVERITY[report.status],
                    title=f"Operational priority now {report.priority.value.title()}",
                    detail=report.dominant_contributor_statement,
                    camera_id=analysis.camera_id,
                    occurred_at=report.generated_at,
                )
            )

        # Guidance is logged only when it actually changes. The engine already
        # suppresses unchanged reports, but a report reissued on the interval
        # timer carries the same actions and would otherwise fill the timeline
        # with repetition.
        if _guidance_changed(previous, report) and report.is_actionable:
            top = report.top_action
            entries.append(
                self._timeline.append(
                    entry_type=TimelineEntryType.AI_OBSERVATION,
                    severity=_STATUS_SEVERITY[report.status],
                    title=(
                        f"Recommendation issued: {top.action}"
                        if top is not None
                        else "Recommendation issued"
                    ),
                    detail=top.rationale if top is not None else None,
                    camera_id=analysis.camera_id,
                    occurred_at=report.generated_at,
                )
            )

        return entries

    def record_system(self, title: str, detail: str | None = None) -> TimelineEntry:
        """Record a platform event - startup, recovery, a stage failure.

        Public so the composition root and the ingest path can note things the
        assessment stream cannot describe, without either of them needing to
        know how a timeline entry is shaped.
        """
        entry = self._timeline.append(
            entry_type=TimelineEntryType.SYSTEM,
            severity=Severity.INFO,
            title=title,
            detail=detail,
            camera_id=self._camera_id,
        )
        self._dispatch(DomainEvent.TIMELINE_ENTRY_ADDED, entry)
        return entry

    def record_operator_action(
        self,
        action: OperatorAction,
        *,
        actor: str,
        note: str | None = None,
        rule_id: str | None = None,
    ) -> tuple[OperationalState, TimelineEntry]:
        """Record what an operator did, and advance the workflow phase accordingly.

        The timeline entry names the operator - the ``actor`` field existed for
        exactly this, and nothing could fill it until operators signed in.

        Args:
            action: What the operator did.
            actor: The operator's display name.
            note: What they wrote about it, if anything.
            rule_id: The recommendation they acted on, when they acted on one.

        Returns:
            The workflow phase after the action, and the timeline entry recorded.

        Raises:
            IllegalTransitionError: The action does not apply to the current phase.
        """
        new_state = self._operational_state.apply_operator_action(
            action, current_status=self._last_status
        )

        recommendation = None
        if rule_id is not None and self._latest is not None:
            recommendation = next(
                (item for item in self._latest.recommended_actions if item.rule_id == rule_id),
                None,
            )

        details: list[str] = []
        if recommendation is not None:
            details.append(f"In response to: {recommendation.action}.")
        if note:
            details.append(note)

        entry = self._timeline.append(
            entry_type=TimelineEntryType.OPERATOR_ACTION,
            severity=Severity.INFO,
            title=_OPERATOR_TITLES[action].format(actor=actor),
            detail=" ".join(details) or None,
            camera_id=self._camera_id,
            actor=actor,
        )
        self._dispatch(DomainEvent.TIMELINE_ENTRY_ADDED, entry)
        if new_state is not None:
            self._dispatch(
                DomainEvent.OPERATIONAL_STATE_CHANGED,
                StateChange(self._camera_id, new_state, actor=actor),
            )
        return self._operational_state.state, entry

    @property
    def last_status(self) -> OperationalStatus | None:
        """The Operational Status of the most recent assessment, if any."""
        return self._last_status

    def clear(self) -> None:
        """Discard guidance, workflow phase and this camera's timeline entries.

        Only this camera's entries: the timeline is shared by every camera, and
        one camera's source restarting says nothing about what the others saw.
        """
        self._latest = None
        self._received_at = None
        self._history.clear()
        self._last_status = None
        self._last_frame_seq = None
        self._last_analysis_at = None
        previous_state = self._operational_state.state
        self._operational_state.reset()
        self._timeline.clear_camera(self._camera_id)
        if previous_state is not OperationalState.MONITORING:
            self._dispatch(
                DomainEvent.OPERATIONAL_STATE_CHANGED,
                StateChange(self._camera_id, OperationalState.MONITORING),
            )

    @property
    def camera_id(self) -> str:
        """The camera this service speaks for."""
        return self._camera_id

    # -- Reading ------------------------------------------------------------

    @property
    def latest(self) -> OperationalIntelligenceReport | None:
        return self._latest

    @property
    def has_report(self) -> bool:
        return self._latest is not None

    @property
    def operational_state(self) -> OperationalState:
        return self._operational_state.state

    def history(self, limit: int | None = None) -> tuple[OperationalIntelligenceReport, ...]:
        """Reports issued this session, newest first."""
        newest_first = tuple(reversed(self._history))
        return newest_first[:limit] if limit is not None else newest_first

    def snapshot(self, *, now: datetime | None = None) -> DecisionSnapshot | None:
        """The current report with its age, or ``None`` if none exists."""
        if self._latest is None or self._received_at is None:
            return None

        reference = now or datetime.now(UTC)
        age = max((reference - self._received_at).total_seconds(), 0.0)

        # A report is reissued only when something changes, so it is
        # legitimately older than an assessment - measuring staleness from the
        # report's own age would flag steady conditions as a fault. What makes
        # guidance stale is the *analysis stream* stopping, so that is what is
        # measured.
        analysis_age = (
            (reference - self._last_analysis_at).total_seconds()
            if self._last_analysis_at is not None
            else None
        )

        return DecisionSnapshot(
            report=self._latest,
            received_at=self._received_at,
            age_seconds=age,
            is_stale=(
                analysis_age is None or analysis_age > PERCEPTION_STALE_AFTER_SECONDS
            ),
        )

    # -- Internals ----------------------------------------------------------

    def _note_continuity(self, analysis: AnalysisResult) -> None:
        """Clear session state when the frame sequence restarts."""
        previous = self._last_frame_seq
        self._last_frame_seq = analysis.frame_seq

        if previous is not None and analysis.frame_seq <= previous:
            logger.info(
                "Frame sequence restarted (%d -> %d); clearing decision state",
                previous,
                analysis.frame_seq,
            )
            self.clear()
            self._last_frame_seq = analysis.frame_seq
            self.record_system(
                "Monitoring session restarted",
                "The frame source restarted; assessment history was discarded.",
            )

    def _dispatch(self, event: DomainEvent, payload: object) -> None:
        if self._event_bus is not None:
            self._event_bus.dispatch(event, payload)


def _is_escalation(
    previous: OperationalStatus | None, current: OperationalStatus
) -> bool:
    """Whether the condition got worse rather than better."""
    if previous is None:
        return current is not OperationalStatus.STABLE
    return current.severity_rank > previous.severity_rank


def _guidance_changed(
    previous: OperationalIntelligenceReport | None,
    current: OperationalIntelligenceReport,
) -> bool:
    """Whether the recommended action set differs from the last report's.

    Compared by rule identifier rather than by text: rationales carry live
    figures that change every window, and comparing those would make every
    report look like new guidance.
    """
    if previous is None:
        return True
    return tuple(action.rule_id for action in previous.recommended_actions) != tuple(
        action.rule_id for action in current.recommended_actions
    )
