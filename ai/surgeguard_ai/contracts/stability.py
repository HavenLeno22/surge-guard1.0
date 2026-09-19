"""Crowd Stability Index contracts - the output of Stage 6 (``05:449-486``).

The structures here exist to make the CSI *explainable by construction*. A
stability assessment always carries the per-indicator breakdown that produced
it, so the Decision Intelligence Engine derives its Primary Causes from
measurements rather than authoring them (Rule 8, ``15:129-133``).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import ConfidenceFactor, OperationalStatus, StabilityIndicator
from .perception import PerceptionResult

__all__ = [
    "IndicatorReading",
    "IndicatorBreakdown",
    "ConfidenceReading",
    "DecisionConfidence",
    "PerceptionQuality",
    "StabilityAssessment",
]


class IndicatorReading(Contract):
    """One indicator's contribution to the Crowd Stability Index."""

    indicator: StabilityIndicator
    available: bool = Field(
        description=(
            "False when the indicator could not be measured - for example, "
            "track-derived indicators above the reliable tracking density, or "
            "egress congestion with no EXIT zone configured. Unavailable "
            "indicators are excluded and the remaining weights renormalised."
        )
    )
    raw_value: float | None = Field(
        default=None,
        description="The underlying measurement, in the indicator's own units.",
    )
    pressure: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Normalised instability pressure. None when unavailable.",
    )
    weight: float = Field(
        ge=0.0,
        le=1.0,
        description="Effective weight after renormalisation over available indicators.",
    )
    unavailable_reason: str | None = Field(
        default=None,
        description="Operator-readable explanation when `available` is False.",
    )

    @property
    def contribution(self) -> float:
        """Weighted points of instability contributed by this indicator."""
        if not self.available or self.pressure is None:
            return 0.0
        return self.pressure * self.weight


class IndicatorBreakdown(Contract):
    """The full set of indicator readings behind one CSI value.

    Persisted with every analysis record. This is what makes an Operational
    Intelligence Report derived rather than authored, and what allows a CSI
    value to be audited after the fact.
    """

    readings: tuple[IndicatorReading, ...]

    @property
    def total_pressure(self) -> float:
        """Sum of weighted contributions - the amount subtracted from 100."""
        return sum(reading.contribution for reading in self.readings)

    @property
    def available_readings(self) -> tuple[IndicatorReading, ...]:
        return tuple(r for r in self.readings if r.available)

    def ranked_contributors(self) -> tuple[IndicatorReading, ...]:
        """Available readings ordered by contribution, largest first.

        The Decision Intelligence Engine uses this ordering directly to produce
        Primary Causes.
        """
        return tuple(
            sorted(self.available_readings, key=lambda r: r.contribution, reverse=True)
        )


class ConfidenceReading(Contract):
    """One data-quality factor contributing to Decision Confidence."""

    factor: ConfidenceFactor
    value: float = Field(ge=0.0, le=1.0)
    detail: str | None = Field(
        default=None,
        description="Operator-readable explanation of why this factor is reduced.",
    )


class DecisionConfidence(Contract):
    """Confidence in the overall operational assessment (``06:922-928``).

    Defined as the product of measurable data-quality factors rather than as an
    asserted number. Confidence falling when conditions degrade is the intended
    behaviour, not a defect: it is how the platform communicates uncertainty
    honestly (``05:250-254``).
    """

    value: float = Field(
        ge=0.0,
        le=1.0,
        description="Product of all factor values.",
    )
    factors: tuple[ConfidenceReading, ...]
    limiting_factor: ConfidenceFactor | None = Field(
        default=None,
        description=(
            "The lowest-scoring factor. Always displayed alongside the value so "
            "the operator knows why confidence is reduced."
        ),
    )


class PerceptionQuality(Contract):
    """How good the perception was that these measurements rest on.

    Decision Confidence is defined as a product of measurable data-quality
    factors rather than an asserted number (Architecture Review C5, §9.2), and
    two of those three factors - detection quality and track stability - are
    properties of *perception*, which crowd metrics deliberately no longer
    describe: past Stage 4 the pipeline talks about a crowd, not about
    individuals or boxes.

    This contract carries those signals across that boundary, so that the
    assessor can compute confidence honestly instead of assuming it.
    """

    mean_detection_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Mean detector confidence this frame. None when nothing was detected.",
    )
    detection_count: int = Field(default=0, ge=0)
    track_count: int = Field(default=0, ge=0)
    mean_track_age_frames: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Mean lifetime of active tracks. Short-lived tracks mean identities "
            "are churning, which corrupts every speed-derived indicator while "
            "the display continues to show confident numbers (Architecture "
            "Review C11)."
        ),
    )
    id_switches: int = Field(default=0, ge=0)
    degraded: bool = Field(
        default=False,
        description="True when a perception stage could not run for this frame.",
    )

    @classmethod
    def from_perception(cls, result: PerceptionResult) -> PerceptionQuality:
        """Derive quality signals from a perception result.

        Kept here rather than in the assessor so that exactly one definition of
        "how good was this frame" exists, whatever consumes it.
        """
        detections = result.detections.detections
        tracks = result.tracking.tracks

        mean_confidence = (
            sum(detection.confidence for detection in detections) / len(detections)
            if detections
            else None
        )
        mean_age = (
            sum(track.age_frames for track in tracks) / len(tracks) if tracks else None
        )

        return cls(
            mean_detection_confidence=mean_confidence,
            detection_count=len(detections),
            track_count=len(tracks),
            mean_track_age_frames=mean_age,
            id_switches=result.tracking.id_switches,
            degraded=result.degraded,
        )


class StabilityAssessment(Contract):
    """The Crowd Stability Index and its complete justification (Stage 6).

    ``csi_raw`` is the instantaneous value; ``csi_smoothed`` is the reported
    value after temporal smoothing. ``status`` is derived from ``csi_smoothed``
    with hysteresis applied, so it does not flicker at a band boundary.
    """

    frame_seq: int = Field(ge=0)
    frame_ts: datetime

    csi_raw: float = Field(ge=0.0, le=100.0)
    csi_smoothed: float = Field(ge=0.0, le=100.0)
    status: OperationalStatus = Field(
        description="Band for csi_smoothed after hysteresis. See `status_for_csi`."
    )
    status_changed: bool = Field(
        default=False,
        description="True on the analysis window where the status transitioned.",
    )

    breakdown: IndicatorBreakdown
    confidence: DecisionConfidence
