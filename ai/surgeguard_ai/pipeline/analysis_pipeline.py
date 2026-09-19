"""The analysis pipeline - Stages 4 to 6 plus evidence, wired together.

::

    PerceptionResult ──► CrowdAnalyzer ──► StabilityAssessor ──► EvidenceEngine ──► DecisionEngine
                          (metrics)          (CSI)                (observations)

**Separate from, and downstream of, the perception pipeline.**
:class:`~surgeguard_ai.pipeline.perception_pipeline.PerceptionPipeline` owns the
frame loop, the camera and the model, and is deliberately untouched by this
module: it produces a
:class:`~surgeguard_ai.contracts.perception.PerceptionResult` and knows nothing
about what happens next. This pipeline consumes that result. Keeping them apart
means analysis can fail, be reset, be reconfigured or be run twice over the same
frame without any of it reaching the loop that is keeping up with a camera.

It is also synchronous and allocation-light by design. Everything here is
arithmetic over at most a few hundred tracks - no model, no I/O - so it runs on
the caller's thread in well under a frame interval, and pushing it onto a
queue would add latency and ordering hazards to buy nothing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..analysis.analyzer import CrowdAnalyzer
from ..contracts.analysis import AnalysisResult
from ..contracts.camera import CameraConfig
from ..contracts.forecast import ForecastReport
from ..contracts.perception import PerceptionResult
from ..contracts.queue import QueueReport
from ..contracts.resources import ResourcePlanReport
from ..contracts.stability import PerceptionQuality
from ..evidence.engine import EvidenceEngine
from ..forecast.engine import QueueForecaster
from ..intelligence.engine import DecisionIntelligenceEngine
from ..queue.analyzer import QueueAnalyzer
from ..resources.allocator import ResourceAllocator
from ..stability.assessor import StabilityAssessor
from ..zones.transitions import ZoneTransitionTracker

__all__ = ["AnalysisPipeline"]

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """Turns one frame's perception into crowd intelligence.

    Stateful, because three of the four things it runs are: the speed baseline,
    the smoothing and hysteresis behind the Crowd Stability Index, and the
    Evidence Engine's history. :meth:`reset` discards all of them together, and
    a break in frame continuity triggers it automatically - the same discipline
    the perception pipeline applies to tracking, for the same reason. Without
    it, a scenario change would blend two crowds into one trend.
    """

    def __init__(
        self,
        camera: CameraConfig,
        analyzer: CrowdAnalyzer,
        assessor: StabilityAssessor,
        evidence: EvidenceEngine,
        decisions: DecisionIntelligenceEngine | None = None,
        *,
        queues: QueueAnalyzer | None = None,
        forecaster: QueueForecaster | None = None,
        allocator: ResourceAllocator | None = None,
        zone_flow: ZoneTransitionTracker | None = None,
    ) -> None:
        """
        Args:
            camera: The camera being watched. Decides which indicators are
                measurable and which zones an observation may name.
            analyzer: Stages 4 and 5 - density, flow and zone occupancy.
            assessor: Stage 6 - the Crowd Stability Index.
            evidence: The Evidence Engine.
            decisions: Stage 7 - the Operational Decision Engine. Optional
                because measurement is useful without guidance: a deployment
                may want the index and the evidence while an operator team
                decides its own policy. When absent, ``AnalysisResult.intelligence``
                stays ``None``, which already means "no report was produced".
            queues: Queue Intelligence. Optional: a camera watching an open
                concourse has no queue to measure.
            forecaster: Queue forecasting. Requires ``queues`` - there is
                nothing to forecast without a measured queue - and is ignored
                without it rather than failing, so a partial configuration
                degrades to less output instead of to no output.
            allocator: Counter allocation. Requires ``queues`` for the same
                reason; uses ``forecaster`` output when present to attach
                confidence to its recommendations.
            zone_flow: Entries, exits and transitions for every zone. Optional,
                and silent on a camera with no zones: ``AnalysisResult.zone_flow``
                stays ``None`` rather than reporting an empty map.
        """
        self._camera = camera
        self._analyzer = analyzer
        self._assessor = assessor
        self._evidence = evidence
        self._decisions = decisions
        self._queues = queues
        self._forecaster = forecaster
        self._allocator = allocator
        self._zone_flow = zone_flow
        self._last_seq: int | None = None

        if forecaster is not None and queues is None:
            logger.warning(
                "A forecaster was supplied without a queue analyser; forecasting "
                "is inactive because there is no measured queue to forecast"
            )
        if allocator is not None and queues is None:
            logger.warning(
                "An allocator was supplied without a queue analyser; resource "
                "planning is inactive because there is no measured queue to plan for"
            )

    @property
    def camera(self) -> CameraConfig:
        """The camera these measurements describe."""
        return self._camera

    @property
    def evidence_engine(self) -> EvidenceEngine:
        """The Evidence Engine, for callers that need its history."""
        return self._evidence

    @property
    def decision_engine(self) -> DecisionIntelligenceEngine | None:
        """The Operational Decision Engine, for callers that need its history."""
        return self._decisions

    def process(self, perception: PerceptionResult) -> AnalysisResult:
        """Analyse one perception result.

        Raises:
            AnalysisError: Crowd measurement failed.
            StabilityAssessmentError: The Crowd Stability Index could not be
                computed - including when no indicator was measurable at all.
            EvidenceError: Observations could not be produced.

        Every one of these is raised rather than swallowed. A caller that
        receives an exception knows the assessment is missing; a caller handed
        a partially-invented one does not, and would display it as though it
        were complete.
        """
        self._note_continuity(perception)

        crowd = self._analyzer.analyze(perception.tracking, self._camera)
        stability = self._assessor.assess(
            crowd, self._camera, PerceptionQuality.from_perception(perception)
        )
        evidence = self._evidence.observe(crowd, stability, self._camera)

        # Returns None on most windows: guidance is reissued when something
        # material changes, not ten times a second (``03:60-62``, ``05:618``).
        report = (
            self._decisions.evaluate(stability, crowd, self._camera, evidence)
            if self._decisions is not None
            else None
        )

        queue_report, forecast_report, resource_report = self._run_queue_intelligence(
            perception
        )
        zone_flow = (
            self._zone_flow.observe(perception)
            if self._zone_flow is not None and self._camera.zones
            else None
        )

        return AnalysisResult(
            camera_id=perception.camera_id,
            source_mode=perception.source_mode,
            frame_seq=perception.frame_seq,
            frame_ts=perception.frame_ts,
            produced_at=datetime.now(UTC),
            crowd=crowd,
            stability=stability,
            evidence=evidence,
            # Absent rather than empty on a window with nothing new to say:
            # "no report was produced" and "the engine recommended nothing" are
            # different facts, and the panel shows the last report either way.
            intelligence=report,
            queue=queue_report,
            forecast=forecast_report,
            resources=resource_report,
            zone_flow=zone_flow,
            detections=perception.detections,
            tracking=perception.tracking,
            processing_ms=perception.processing_ms,
            degraded=perception.degraded,
            degraded_reason=perception.degraded_reason,
        )

    def _run_queue_intelligence(
        self, perception: PerceptionResult
    ) -> tuple[QueueReport | None, ForecastReport | None, ResourcePlanReport | None]:
        """Measure, forecast and plan for every configured queue zone.

        Each stage depends on the one before it, so an absent stage simply
        truncates the chain rather than producing an empty structure. A
        ``None`` forecast means no forecast was produced; an empty one would
        claim a forecast of nothing, which is a different and untrue statement.
        """
        if self._queues is None:
            return None, None, None

        queue_report = self._queues.analyze(perception)

        forecast_report = (
            self._forecaster.observe(queue_report)
            if self._forecaster is not None
            else None
        )

        if self._allocator is None or not queue_report.queues:
            return queue_report, forecast_report, None

        forecasts = forecast_report.forecasts if forecast_report is not None else ()
        resource_report = self._allocator.plan_all(queue_report.queues, forecasts)

        return queue_report, forecast_report, resource_report

    def reset(self) -> None:
        """Discard every accumulated baseline, trend, counter and history."""
        self._analyzer.reset()
        self._assessor.reset()
        self._evidence.reset()
        if self._decisions is not None:
            self._decisions.reset()
        if self._forecaster is not None:
            self._forecaster.reset()
        if self._zone_flow is not None:
            self._zone_flow.reset()
        self._last_seq = None
        logger.info("Analysis pipeline reset")

    @property
    def queue_analyzer(self) -> QueueAnalyzer | None:
        """Queue Intelligence, for callers that need to change counter settings."""
        return self._queues

    def _note_continuity(self, perception: PerceptionResult) -> None:
        """Reset when the frame sequence restarts.

        A source restarting its sequence at 0 - a camera reconnecting, a
        demonstration clip looping - means the material before the seam
        describes a different scene. Trend and baseline measured across that
        seam describe change that never happened.
        """
        previous = self._last_seq
        self._last_seq = perception.frame_seq

        if previous is not None and perception.frame_seq <= previous:
            logger.info(
                "Frame sequence restarted (%d -> %d); discarding analysis state",
                previous,
                perception.frame_seq,
            )
            self.reset()
            self._last_seq = perception.frame_seq
