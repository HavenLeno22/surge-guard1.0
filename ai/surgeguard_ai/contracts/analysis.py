"""The analysis result - the single payload that crosses the sink boundary.

This is the complete output of one pass of the AI Pipeline and the only
structure the backend needs to understand. Everything the Command Center
displays derives from it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .crowd import CrowdMetrics
from .enums import SourceMode
from .evidence import EvidenceReport
from .forecast import ForecastReport
from .intelligence import OperationalIntelligenceReport
from .perception import DetectionResult, TrackingResult
from .queue import QueueReport
from .resources import ResourcePlanReport
from .stability import StabilityAssessment
from .zones import ZoneFlowReport

__all__ = ["AnalysisResult"]


class AnalysisResult(Contract):
    """One complete analysis of one frame.

    Delivered to an :class:`~surgeguard_ai.sinks.base.AnalysisSink`. The AI
    Pipeline produces this and nothing else; it has no knowledge of databases,
    WebSockets or user interfaces.
    """

    # -- Provenance ---------------------------------------------------------

    camera_id: str
    source_mode: SourceMode = Field(
        description=(
            "Whether these frames came from a live camera or a demonstration "
            "recording. A tag only - the pipeline never branches on it. Enables "
            "the Live/Demo indicator and keeps demonstration records separable "
            "from live records (Rule 7)."
        )
    )
    frame_seq: int = Field(ge=0)
    frame_ts: datetime = Field(
        description=(
            "Timestamp of the analysed frame. Wall-clock for live sources; for "
            "recordings, paced to the source frame rate so temporal indicators "
            "behave identically in both modes."
        )
    )
    produced_at: datetime = Field(description="When this analysis completed.")

    # -- Results ------------------------------------------------------------

    crowd: CrowdMetrics
    stability: StabilityAssessment

    # -- Queue Intelligence -------------------------------------------------
    #
    # All three are optional and independent of the crowd/stability spine
    # above. A deployment watching an open concourse has no queue to measure and
    # leaves them absent; one watching a ticket hall fills all three. Keeping
    # them optional is what lets Queue Intelligence be added without any
    # existing consumer having to change (Rule 2).

    queue: QueueReport | None = Field(
        default=None,
        description=(
            "Measured state of every configured queue zone - what is happening "
            "now. Absent when the camera has no QUEUE zone, or when Queue "
            "Intelligence is disabled."
        ),
    )
    forecast: ForecastReport | None = Field(
        default=None,
        description=(
            "Projected queue length at each configured horizon, and the "
            "abnormal-growth assessment - what is expected to happen. Kept "
            "separate from `queue` so a measurement and a prediction can never "
            "be mistaken for one another."
        ),
    )
    resources: ResourcePlanReport | None = Field(
        default=None,
        description=(
            "Counter allocation recommendations - what could be done. The third "
            "of the three layers, and the only one describing an action rather "
            "than a fact."
        ),
    )

    zone_flow: ZoneFlowReport | None = Field(
        default=None,
        description=(
            "Entries, exits and tracked transitions for every configured zone on "
            "this camera. Absent when zone flow is not enabled or the camera has "
            "no zones. Optional for the same reason the queue fields are: a "
            "consumer that predates it is unaffected."
        ),
    )

    evidence: EvidenceReport | None = Field(
        default=None,
        description=(
            "What the platform observed in this window, in operator language. "
            "Present on every window the Evidence Engine ran for - unlike an "
            "Operational Intelligence Report, evidence is continuous rather "
            "than episodic: it describes the current situation, it does not "
            "announce a new one."
        ),
    )

    intelligence: OperationalIntelligenceReport | None = Field(
        default=None,
        description=(
            "Present only when the Decision Intelligence Engine produced a new "
            "report for this window. Most windows carry no new report."
        ),
    )

    # -- Optional perception detail ----------------------------------------

    detections: DetectionResult | None = Field(
        default=None,
        description=(
            "Included when the consumer needs overlay boxes. Omitted from "
            "persistence: raw detections are per-frame perception detail, not "
            "operational history."
        ),
    )
    tracking: TrackingResult | None = Field(
        default=None,
        description="Included when the consumer needs tracking overlays.",
    )

    # -- Health -------------------------------------------------------------

    processing_ms: float | None = Field(
        default=None,
        ge=0,
        description="End-to-end pipeline time for this frame, against the budget.",
    )
    degraded: bool = Field(
        default=False,
        description=(
            "True when one or more stages could not run normally. The Command "
            "Center surfaces this rather than silently presenting partial results."
        ),
    )
    degraded_reason: str | None = Field(default=None)

    @property
    def is_demo(self) -> bool:
        """Whether this result originated from demonstration footage."""
        return self.source_mode is SourceMode.DEMO
