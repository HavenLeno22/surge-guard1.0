"""Decision Intelligence contracts - the output of Stage 7 (``05:489-524``).

The Operational Decision Engine converts measurements into operational
guidance. It never exposes raw AI output to operators (``05:730-734``): every
field here is written in operational language, and every claim traces back to a
measured indicator.

**Nothing here is generated.** A :class:`PrimaryCause` is derived from the
indicator breakdown, a :class:`RecommendedAction` is selected from a closed
vocabulary and must name the indicators that selected it, and a report cannot
exist without the status, confidence and evidence it rests on. That is enforced
at the type level rather than by convention, because a decision-support layer
that *can* express an unsupported claim eventually will.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import (
    AlertPriority,
    OperationalStatus,
    RecommendationType,
    StabilityIndicator,
)
from .evidence import EvidenceItem

__all__ = ["PrimaryCause", "RecommendedAction", "OperationalIntelligenceReport"]


class PrimaryCause(Contract):
    """One measured factor contributing to the current crowd condition.

    Derived from :meth:`IndicatorBreakdown.ranked_contributors`, never authored.
    The ``contribution_pct`` is what makes the explanation concrete: the
    operator sees not only *what* is wrong but *how much* of the instability it
    accounts for.
    """

    indicator: StabilityIndicator
    label: str = Field(
        description=(
            "Operator-facing description, e.g. 'Exit congestion'. Avoid AI "
            "terminology - the operator should need no AI knowledge (``05:849-851``)."
        )
    )
    contribution_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="Share of total instability pressure attributable to this cause.",
    )
    pressure: float = Field(
        ge=0.0,
        le=100.0,
        description="The indicator's own instability pressure, before weighting.",
    )
    detail: str | None = Field(
        default=None,
        description="Supporting measurement, e.g. 'peak 4.8 persons/m2 near Exit B'.",
    )


class RecommendedAction(Contract):
    """One prioritised operational action (``06:822-842``, ``18:147-161``).

    Every action must cite the cause that produced it. An action that cannot
    name its rationale must not be shown - and here cannot be built, because
    ``supporting_indicators`` may not be empty.
    """

    priority: int = Field(
        ge=1,
        description="1 is most urgent. Actions are displayed in this order.",
    )
    recommendation_type: RecommendationType = Field(
        description=(
            "The kind of guidance, from the closed vocabulary at ``18:125-143``. "
            "Selected, never composed - an engine free to invent an action can "
            "recommend something the venue cannot do."
        )
    )
    action: str = Field(description="The action itself, e.g. 'Open Exit Gate B'.")
    rationale: str = Field(
        description=(
            "Why this action follows from the observed conditions, in operator "
            "language and naming the measurement that triggered it."
        )
    )

    supporting_indicators: tuple[StabilityIndicator, ...] = Field(
        min_length=1,
        description=(
            "Every indicator that contributed to selecting this action. Required "
            "and non-empty: an action whose rationale cannot be traced to a "
            "measurement is a fabricated one (Rule 8, ``15:129-133``)."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in this specific action - the assessment's Decision "
            "Confidence reduced by how firmly the triggering rule was satisfied."
        ),
    )

    urgency: AlertPriority = Field(
        description=(
            "Operational urgency of this action on its own, as distinct from its "
            "display order. Two actions may share a rank in one report and mean "
            "very different things in isolation."
        )
    )
    zone_id: str | None = Field(
        default=None,
        description=(
            "The camera zone this action refers to. Present only when a zone is "
            "configured - the platform never names infrastructure it cannot see "
            "(Architecture Review C26)."
        ),
    )
    rule_id: str = Field(
        description=(
            "Identifier of the decision rule that produced this action. Carried "
            "so a recommendation shown to an operator can be traced back to the "
            "exact rule, which is what makes the engine auditable (``18:99-109``)."
        )
    )


class OperationalIntelligenceReport(Contract):
    """The Operational Intelligence Report (OIR) (``05:666-710``, ``18:37``).

    The complete decision-support object: what the platform believes is
    happening, why it believes it, how sure it is, and what it suggests the
    operator consider. It decides nothing - ``18:9-11`` is explicit that the
    engine never acts autonomously and the operator remains responsible for
    every final action.

    Note the absence of a numeric improvement estimate. Predicting that an
    intervention will raise the CSI by a specific amount is a causal
    counterfactual with no mechanism behind it and no data to calibrate against
    (Architecture Review C4). ``dominant_contributor_statement`` replaces it
    with a claim the platform can actually substantiate.
    """

    # -- Identity -----------------------------------------------------------

    sequence: int = Field(
        ge=1,
        description=(
            "Monotonic per engine session. Lets a consumer order reports and "
            "detect a missed one without relying on timestamps, which can tie at "
            "the analysis rate."
        ),
    )
    revision: int = Field(
        ge=1,
        description=(
            "Reports are a revision series per Crowd Event, not a single record: "
            "the situation evolves and the panel updates (``06:345``). Distinct "
            "from ``sequence``, which counts every report the engine has ever "
            "issued regardless of which episode it belongs to."
        ),
    )
    generated_at: datetime
    frame_seq: int = Field(
        ge=0,
        description="The analysis window this report describes, for audit.",
    )

    # -- Assessment ---------------------------------------------------------

    status: OperationalStatus = Field(
        description="The crowd condition this report was produced for."
    )
    priority: AlertPriority = Field(
        description=(
            "Operational priority of the situation as a whole. Derived from the "
            "Operational Status and the severity of the evidence, never asserted."
        )
    )
    csi: float = Field(
        ge=0.0,
        le=100.0,
        description="The smoothed Crowd Stability Index this report was produced for.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Decision Confidence carried through from the assessment. A report "
            "is exactly as believable as the measurements behind it."
        ),
    )

    # -- Explanation --------------------------------------------------------

    situation_summary: str = Field(
        description="One or two sentences of plain operational language."
    )
    primary_causes: tuple[PrimaryCause, ...] = Field(default=())
    supporting_evidence: tuple[EvidenceItem, ...] = Field(
        default=(),
        description=(
            "The observations this report rests on, carried verbatim from the "
            "Evidence Engine. Included rather than referenced so a stored report "
            "remains self-explanatory after the live evidence has moved on."
        ),
    )
    dominant_contributor_statement: str | None = Field(
        default=None,
        description=(
            "Mechanism statement naming the largest single driver of instability "
            "and its share, e.g. 'Largest contributor: exit congestion, 42% of "
            "current instability.' States what is measured; claims no outcome."
        ),
    )

    # -- Guidance -----------------------------------------------------------

    recommended_actions: tuple[RecommendedAction, ...] = Field(default=())
    suppressed_actions: int = Field(
        default=0,
        ge=0,
        description=(
            "Actions a rule produced that were then dropped - superseded, "
            "unvalidatable, or past the display cap. Counted rather than "
            "silently discarded so what the engine decided and what it showed "
            "remain separable."
        ),
    )

    @property
    def is_actionable(self) -> bool:
        """Whether this report asks the operator to do anything beyond observe."""
        return any(
            action.recommendation_type is not RecommendationType.OBSERVE
            for action in self.recommended_actions
        )

    @property
    def top_action(self) -> RecommendedAction | None:
        """The highest-priority action, or ``None`` when there are none."""
        return self.recommended_actions[0] if self.recommended_actions else None
