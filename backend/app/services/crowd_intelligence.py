"""Crowd intelligence state - the Crowd Stability Index and current evidence.

Runs the analysis half of the AI Pipeline (Stages 4 to 6, plus the Evidence
Engine) over every perception result the backend receives, and holds the most
recent outcome for the Command Center to read.

**Why this is a subscriber rather than part of the ingest sink.** The sink's own
documentation is explicit that it contains no operational logic: it records what
arrived and announces it, and everything that is a genuine consumer subscribes
to :attr:`~app.core.event_bus.DomainEvent.PERCEPTION_RECEIVED`. Crowd analysis
is exactly such a consumer. Putting it in the sink would make the primary data
path depend on the assessment, so a failing indicator could stop frames being
recorded at all.

**Why the latest only.** The same reasoning as
:class:`~app.services.perception_state.PerceptionStateService`: this is the
current state of a live camera, every window supersedes the one before it, and
operational history is a different shape of thing - Crowd Events, with a
lifecycle - belonging in the database when that lands. The one exception is
Evidence History, which the Evidence Engine itself retains because it records
*transitions* rather than windows, and is therefore bounded by how often
conditions actually change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from surgeguard_ai.contracts import AnalysisResult, EvidenceItem, PerceptionResult
from surgeguard_ai.errors import SurgeGuardAIError
from surgeguard_ai.pipeline import AnalysisPipeline

from ..core.constants import PERCEPTION_STALE_AFTER_SECONDS
from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger

__all__ = ["IntelligenceSnapshot", "CrowdIntelligenceService"]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IntelligenceSnapshot:
    """An analysis result together with how old it is.

    The age travels with the result for the same reason it does on a perception
    snapshot: a consumer handed a bare Crowd Stability Index has no way to know
    whether it describes the crowd now or the crowd before the pipeline stopped.
    """

    result: AnalysisResult
    received_at: datetime
    age_seconds: float
    is_stale: bool


class CrowdIntelligenceService:
    """The backend's record of what the crowd is currently doing, and why.

    Written only by the perception subscriber and read by anything that needs
    the current assessment. Both happen on the event loop, so no lock is needed.
    """

    def __init__(
        self,
        pipeline: AnalysisPipeline | None,
        event_bus: EventBus | None = None,
        *,
        camera_id: str | None = None,
    ) -> None:
        """
        Args:
            pipeline: The analysis pipeline, or ``None`` when crowd analysis is
                disabled. A disabled service answers every query honestly with
                "nothing has been analysed" rather than being absent, which is
                what lets a route report the situation instead of failing to
                resolve a dependency.
            event_bus: Bus on which to announce completed analyses, so later
                consumers - persistence, Crowd Event lifecycle, the Command
                Center broadcast - can subscribe without this service knowing
                they exist.
            camera_id: The camera this service analyses. Every camera's
                perception arrives on the same bus, and an analysis pipeline fed
                two cameras' frames would blend two crowds into one trend - so a
                service bound to a camera ignores the rest. ``None`` accepts
                everything, which is the single-camera behaviour.
        """
        self._pipeline = pipeline
        self._event_bus = event_bus
        self._camera_id = camera_id

        self._latest: AnalysisResult | None = None
        self._received_at: datetime | None = None
        self._analysed = 0
        self._failures = 0
        self._last_error: str | None = None
        self._first_received_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        """Whether crowd analysis is running at all."""
        return self._pipeline is not None

    @property
    def camera_id(self) -> str | None:
        """The camera this service is bound to, or ``None`` for any."""
        return self._camera_id

    @property
    def pipeline(self) -> AnalysisPipeline | None:
        """The analysis pipeline in use."""
        return self._pipeline

    def rebind(self, pipeline: AnalysisPipeline | None) -> None:
        """Adopt a newly built analysis pipeline - after a zone change, say.

        The previous assessment is discarded with it: it was measured against
        zones that no longer exist, and a trend spanning the change would
        describe movement across a boundary that moved.
        """
        self._pipeline = pipeline
        self._latest = None
        self._received_at = None
        self._last_error = None

    # -- Writing ------------------------------------------------------------

    def handle_perception(self, result: PerceptionResult) -> None:
        """Analyse one perception result. Never raises.

        **Deliberately synchronous.** The Crowd Stability Index carries
        smoothing, hysteresis and a trend window, all of which assume windows
        arrive in order. A coroutine handler would yield at its first ``await``
        and could interleave two frames; a synchronous one runs to completion
        inside the dispatch, which is what guarantees the ordering those
        stateful stages depend on. It can afford to: this is arithmetic over at
        most a few hundred tracks, with no model and no I/O.
        """
        if self._pipeline is None:
            return
        if self._camera_id is not None and result.camera_id != self._camera_id:
            return

        try:
            analysis = self._pipeline.process(result)
        except SurgeGuardAIError as error:
            self._failures += 1
            self._last_error = str(error)
            # Logged and counted, never raised. The result is simply not
            # updated, so it ages and is reported stale - which is the honest
            # outcome, and the same one a stopped pipeline produces.
            logger.warning(
                "Crowd analysis failed",
                extra={
                    "camera_id": result.camera_id,
                    "frame_seq": result.frame_seq,
                    "error": str(error),
                },
            )
            return
        except Exception as error:  # noqa: BLE001 - a subscriber must not escape
            self._failures += 1
            self._last_error = str(error)
            logger.error(
                "Crowd analysis raised an unexpected error",
                exc_info=error,
                extra={"camera_id": result.camera_id, "frame_seq": result.frame_seq},
            )
            return

        self._record(analysis)

    def _record(self, analysis: AnalysisResult) -> None:
        """Store an analysis as the current assessment and announce it."""
        now = datetime.now(UTC)

        self._latest = analysis
        self._received_at = now
        self._analysed += 1
        self._last_error = None

        if self._first_received_at is None:
            self._first_received_at = now
            logger.info(
                "First crowd assessment produced",
                extra={
                    "camera_id": analysis.camera_id,
                    "csi": round(analysis.stability.csi_smoothed, 1),
                    "status": analysis.stability.status.value,
                },
            )
        elif analysis.stability.status_changed:
            logger.info(
                "Operational Status changed",
                extra={
                    "camera_id": analysis.camera_id,
                    "status": analysis.stability.status.value,
                    "csi": round(analysis.stability.csi_smoothed, 1),
                    "confidence": round(analysis.stability.confidence.value, 2),
                },
            )

        if self._event_bus is not None:
            self._event_bus.dispatch(DomainEvent.ANALYSIS_RECEIVED, analysis)

    def clear(self) -> None:
        """Discard the current assessment and every accumulated baseline.

        Called when the pipeline stops. What was being displayed describes a
        camera that is no longer reporting, and a trend spanning the gap would
        describe change that never happened.
        """
        self._latest = None
        self._received_at = None
        if self._pipeline is not None:
            self._pipeline.reset()

    # -- Reading ------------------------------------------------------------

    @property
    def latest(self) -> AnalysisResult | None:
        """The most recent assessment, or ``None`` if none has been produced."""
        return self._latest

    @property
    def has_result(self) -> bool:
        return self._latest is not None

    @property
    def analysed(self) -> int:
        """Assessments produced since startup."""
        return self._analysed

    @property
    def failures(self) -> int:
        """Windows that could not be assessed."""
        return self._failures

    @property
    def last_error(self) -> str | None:
        """Why the most recent assessment failed, or ``None`` if it succeeded."""
        return self._last_error

    @property
    def first_received_at(self) -> datetime | None:
        return self._first_received_at

    @property
    def received_at(self) -> datetime | None:
        return self._received_at

    def evidence_history(self) -> tuple[EvidenceItem, ...]:
        """Distinct observations since the last reset, newest first."""
        if self._pipeline is None:
            return ()
        return self._pipeline.evidence_engine.history()

    def snapshot(self, *, now: datetime | None = None) -> IntelligenceSnapshot | None:
        """The current assessment with its age, or ``None`` if none exists."""
        if self._latest is None or self._received_at is None:
            return None

        reference = now or datetime.now(UTC)
        age = max((reference - self._received_at).total_seconds(), 0.0)

        return IntelligenceSnapshot(
            result=self._latest,
            received_at=self._received_at,
            age_seconds=age,
            # Analysis runs once per perception result, so it goes stale on
            # exactly the same schedule and shares the same threshold. A second
            # constant here would be a second definition of one fact.
            is_stale=age > PERCEPTION_STALE_AFTER_SECONDS,
        )
