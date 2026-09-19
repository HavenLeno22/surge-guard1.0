"""Evidence contracts - the output of the Evidence Engine.

The Evidence Engine answers one question: *what is the AI currently observing?*
(``17_Evidence_Engine_Specification.md``). It sits between crowd analysis and
the Operational Decision Engine and it never decides anything - it only reports
what was measured, in language an operator can act on without knowing any AI.

The structures here make an observation **explainable by construction**. An
:class:`EvidenceItem` cannot exist without the measurements that produced it,
so an unexplained warning is not merely discouraged, it is unrepresentable -
the same discipline
:class:`~surgeguard_ai.contracts.stability.IndicatorBreakdown` applies to the
Crowd Stability Index.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import EvidenceType, Severity, StabilityIndicator

__all__ = ["SupportingMetric", "EvidenceItem", "EvidenceReport"]


class SupportingMetric(Contract):
    """One measurement that supports an observation.

    Carries its own unit rather than assuming one. Density is persons/m2 only
    when the camera is calibrated and *relative* otherwise, and speed is
    metres/second only under the same condition - presenting either without its
    unit is how a relative figure ends up read as an absolute one
    (Architecture Review C21).
    """

    label: str = Field(description="Operator-facing name, e.g. 'Median speed'.")
    value: float
    unit: str = Field(
        description=(
            "Unit of ``value`` as it should be displayed: 'p/m2', 'rel.', 'm/s', "
            "'px/s', '%', or '' for a dimensionless ratio."
        )
    )
    baseline: float | None = Field(
        default=None,
        description=(
            "What ``value`` is being compared against, in the same unit. Present "
            "whenever the observation is a comparison - 'slowing' means nothing "
            "without saying slower than what."
        ),
    )


class EvidenceItem(Contract):
    """One thing the platform is currently observing.

    Every field the Evidence Engine specification requires is present and
    required: type, severity, confidence, supporting metrics, timestamp and
    affected region (``17:67-83``).

    ``confidence`` is measured, never asserted. It is the Decision Confidence of
    the assessment that produced the observation, reduced by how narrowly the
    measurement cleared its threshold: a reading barely past the line is a less
    certain observation than one far past it, and saying so is more honest than
    reporting both at the same confidence.
    """

    evidence_type: EvidenceType
    severity: Severity = Field(
        description=(
            "Display severity of this observation. Reuses the platform's "
            "existing Severity vocabulary rather than introducing a fourth "
            "severity taxonomy (Rule 3): INFO, WARNING and CRITICAL are the "
            "same three levels the source document calls low, medium and high, "
            "and these already carry the Crowd Event Timeline's presentation."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How certain this observation is, from measurable data quality.",
    )

    headline: str = Field(
        description="The observation itself, e.g. 'Movement slowing'. Operator language."
    )
    detail: str = Field(
        description=(
            "Why it was reported, in terms of the measurement, e.g. 'Median "
            "speed is 27% below the recent baseline.' Never empty: an "
            "observation the operator cannot trace to a number is exactly the "
            "unexplained warning the specification forbids (``17:105-109``)."
        )
    )
    metrics: tuple[SupportingMetric, ...] = Field(
        default=(),
        description="The measurements behind ``detail``, for audit and display.",
    )

    observed_at: datetime = Field(description="Timestamp of the frame this was observed in.")
    frame_seq: int = Field(ge=0)

    zone_id: str | None = Field(
        default=None,
        description=(
            "The affected region, when one is known. Present only where a camera "
            "zone is configured - the platform never names infrastructure it "
            "cannot see (Architecture Review C26)."
        ),
    )
    indicator: StabilityIndicator | None = Field(
        default=None,
        description=(
            "The Crowd Stability Index indicator this observation explains. This "
            "is the link that makes evidence and the CSI two views of one "
            "measurement rather than two independent calculations."
        ),
    )

    @property
    def severity_rank(self) -> int:
        """Ordinal severity, 0 (info) through 2 (critical), for ranking."""
        return _SEVERITY_RANK[self.severity]


class EvidenceReport(Contract):
    """Everything the platform is observing in one analysis window.

    Items are **already prioritised**: ``items[0]`` is the observation that most
    warrants attention. Ordering is part of the report rather than left to the
    display, so every consumer - the Command Center, the timeline, a future
    Operational Decision Engine - agrees on what matters most.
    """

    frame_seq: int = Field(ge=0)
    frame_ts: datetime
    generated_at: datetime

    items: tuple[EvidenceItem, ...] = Field(
        default=(),
        description="Prioritised, capped and deduplicated. Most important first.",
    )
    suppressed: int = Field(
        default=0,
        ge=0,
        description=(
            "Observations that were measured but not shown - below the "
            "confidence floor, or past the display cap. Reported rather than "
            "silently dropped so the count of what was observed is auditable."
        ),
    )

    @property
    def is_nominal(self) -> bool:
        """Whether the only observation is that conditions are normal."""
        if len(self.items) != 1:
            return False
        return self.items[0].evidence_type is EvidenceType.CONDITIONS_NOMINAL

    @property
    def highest_severity(self) -> Severity | None:
        """The most severe observation present, or ``None`` when there are none."""
        if not self.items:
            return None
        return max((item.severity for item in self.items), key=lambda s: _SEVERITY_RANK[s])


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.CRITICAL: 2,
}
