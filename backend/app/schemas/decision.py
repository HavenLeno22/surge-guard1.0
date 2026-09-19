"""Operational decision API schemas.

What the backend exposes about the platform's guidance: the current
Operational Intelligence Report, the revision series behind it, and the
operator workflow phase.

The AI Pipeline's :class:`OperationalIntelligenceReport` is carried through
verbatim rather than reshaped, for the same reason perception and the
assessment are: it is already the platform's shared vocabulary for this
concept, and restating its fields here would create a second definition to keep
in step with the first - including the supporting evidence and the rule
identifier on every action, which are precisely the parts that make a
recommendation auditable.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import OperationalIntelligenceReport, OperationalState

from ..services.operational_state import OperatorAction
from .timeline import TimelineEntry

__all__ = [
    "CameraDecisionRead",
    "DecisionHistoryRead",
    "DecisionRead",
    "OperatorActionRead",
    "OperatorActionWrite",
]


class OperatorActionWrite(BaseModel):
    """Something an operator did about a camera's situation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: OperatorAction
    note: str | None = Field(
        default=None,
        max_length=500,
        description="What the operator did or saw, in their words. Recorded on the timeline.",
    )
    rule_id: str | None = Field(
        default=None,
        max_length=64,
        description="The recommendation acted on, when the action followed one.",
    )


class OperatorActionRead(BaseModel):
    """The workflow phase after an operator action, and the timeline entry it made."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    operational_state: OperationalState
    entry: TimelineEntry


class DecisionRead(BaseModel):
    """The platform's current operational guidance."""

    model_config = ConfigDict(extra="forbid")

    report: OperationalIntelligenceReport = Field(
        description=(
            "The current report: situation summary, primary causes, prioritised "
            "recommended actions, decision confidence, supporting evidence and "
            "the dominant contributor statement."
        )
    )
    operational_state: OperationalState = Field(
        description=(
            "The operator workflow phase, which is a different thing from the "
            "crowd condition on the report and is rendered in a different "
            "palette (Architecture Review C8)."
        )
    )

    received_at: datetime = Field(description="When the backend accepted this report.")
    age_seconds: float = Field(
        ge=0,
        description=(
            "How long ago that was. Expected to exceed the assessment's age: "
            "guidance is reissued when something changes, not every window."
        ),
    )
    is_stale: bool = Field(
        description=(
            "True when the platform has stopped producing assessments entirely. "
            "An old report during steady conditions is correct, not stale - "
            "which is why this is measured from the analysis stream rather than "
            "from the report's own age."
        )
    )


class CameraDecisionRead(BaseModel):
    """One camera's guidance and workflow phase, answerable before any report exists.

    Unlike ``/decisions/current`` - which describes the primary camera and is 503
    until a report exists - this always answers: a camera with no report yet
    still has an Operational State, and a multi-camera view needs both for every
    camera. ``report`` is null rather than the request failing.
    """

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    report: OperationalIntelligenceReport | None = None
    operational_state: OperationalState
    received_at: datetime | None = None
    age_seconds: float | None = Field(default=None, ge=0)
    is_stale: bool = Field(
        default=False,
        description="True when a report exists but the analysis stream behind it has stopped.",
    )


class DecisionHistoryRead(BaseModel):
    """The revision series of reports issued this session.

    Always answerable, including before the first report - an empty series is a
    fact, not a failure.
    """

    model_config = ConfigDict(extra="forbid")

    reports: list[OperationalIntelligenceReport] = Field(
        default_factory=list, description="Newest first."
    )
    total: int = Field(ge=0, description="Reports retained.")
