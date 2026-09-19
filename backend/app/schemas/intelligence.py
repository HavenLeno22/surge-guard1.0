"""Crowd intelligence API schemas.

What the backend exposes about the crowd's condition: the Crowd Stability
Index, the Operational Status derived from it, Decision Confidence, and the
observations that explain them.

As with perception, the AI Pipeline's own contracts are carried through
verbatim rather than reshaped. :class:`StabilityAssessment` and
:class:`EvidenceReport` are already the platform's shared vocabulary for these
concepts, and restating their fields here would create a second definition to
keep in step with the first - including the indicator breakdown, which is
precisely the part that must not drift, since it is what makes a CSI value
auditable after the fact.

What is added around them is context they cannot carry for themselves: a
summary of the crowd measurements behind them, how old the assessment is, and
whether analysis is running at all.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import (
    CountMethod,
    CrowdMetrics,
    EvidenceItem,
    EvidenceReport,
    SourceMode,
    StabilityAssessment,
)

__all__ = ["CrowdSummary", "CrowdIntelligenceRead", "EvidenceHistoryRead"]


class CrowdSummary(BaseModel):
    """The crowd measurements behind an assessment, without the full grid.

    The density map is deliberately omitted. It is a few dozen cells per frame
    and backs a heatmap overlay nothing renders yet; sending it at the analysis
    rate would multiply this payload for no current benefit. The two figures
    derived from it that the interface actually shows - the peak and the mean -
    are here, along with the flag that says which unit they are in.
    """

    model_config = ConfigDict(extra="forbid")

    person_count: int = Field(ge=0)
    count_method: CountMethod = Field(
        description=(
            "TRACKED below the reliable tracking density, ESTIMATED above it. "
            "The interface must never present an estimate as a tracked count."
        )
    )

    density_max: float = Field(ge=0, description="Peak density across the grid.")
    density_mean: float = Field(ge=0, description="Mean density across occupied cells.")
    is_metric: bool = Field(
        description=(
            "True when density is persons/m2 (camera calibrated). When false "
            "the figures are relative and must be labelled as such - never "
            "displayed as persons/m2 (Architecture Review C21)."
        )
    )

    median_speed: float | None = Field(
        default=None,
        ge=0,
        description="Median track speed - m/s when calibrated, otherwise px/s.",
    )
    baseline_speed: float | None = Field(
        default=None,
        ge=0,
        description="This camera's rolling baseline speed, for comparison.",
    )

    @classmethod
    def from_crowd(cls, crowd: CrowdMetrics) -> CrowdSummary:
        """Summarise one window's crowd measurements.

        The single definition of this mapping. It previously existed twice -
        once in the REST route and once in the WebSocket payload builder - which
        is a field-by-field duplication of exactly the shape those two paths are
        required to keep identical, so that a client applying a pushed message
        and a fetched one lands in the same state. Two copies of a mapping that
        must not diverge is a mapping that eventually will.
        """
        return cls(
            person_count=crowd.person_count,
            count_method=crowd.count_method,
            density_max=crowd.density_max,
            density_mean=crowd.density_mean,
            is_metric=crowd.is_metric,
            median_speed=crowd.flow.median_speed,
            baseline_speed=crowd.flow.baseline_speed,
        )


class CrowdIntelligenceRead(BaseModel):
    """The current crowd assessment and the evidence explaining it."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    source_mode: SourceMode = Field(
        description="Whether this assessment came from a live camera or a recording."
    )
    frame_seq: int = Field(ge=0)

    stability: StabilityAssessment = Field(
        description=(
            "The Crowd Stability Index, the Operational Status derived from it "
            "with hysteresis, the per-indicator breakdown that produced it, and "
            "Decision Confidence with its limiting factor."
        )
    )
    evidence: EvidenceReport | None = Field(
        default=None,
        description="What the platform is currently observing, already prioritised.",
    )
    crowd: CrowdSummary

    received_at: datetime = Field(description="When the backend produced this assessment.")
    age_seconds: float = Field(
        ge=0,
        description="How long ago that was. The number that decides whether to trust it.",
    )
    is_stale: bool = Field(
        description=(
            "True when this assessment is too old to describe the crowd now. A "
            "Crowd Stability Index frozen at a reassuring value without saying "
            "so is the single most dangerous thing this display can show."
        )
    )

    degraded: bool = Field(
        default=False,
        description="True when a perception stage could not run for this frame.",
    )
    degraded_reason: str | None = Field(default=None)


class EvidenceHistoryRead(BaseModel):
    """Observations recorded since analysis last started or was reset.

    Records an observation when it **appears**, not on every window it persists
    for. At the analysis rate the latter would append a dozen identical entries
    a second and bury the moment a condition actually began - which is the only
    thing a history is useful for.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[EvidenceItem] = Field(
        default_factory=list, description="Newest first."
    )
    total: int = Field(ge=0, description="Observations retained.")
    analysed: int = Field(
        ge=0, description="Analysis windows completed since startup, for context."
    )
