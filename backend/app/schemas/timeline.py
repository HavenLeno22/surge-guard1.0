"""Crowd Event Timeline schemas.

A chronological record of what the platform did and why (``06:425-449``,
``06:846-868``). Unlike perception and the assessment - which describe *now* and
are superseded by the next window - the timeline is the one operational surface
where history is the point.

Timeline entries are a **backend** concept rather than an AI contract. The AI
Pipeline reports what it measured; deciding that a measurement was worth
recording as an operational event is a platform judgement, and belongs on the
side of the boundary that also knows about operators, alerts and Crowd Events.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import Severity, TimelineEntryType

__all__ = ["TimelineEntry", "TimelineRead"]


class TimelineEntry(BaseModel):
    """One thing that happened, and when.

    Shaped to match the ``TimelineEntry`` entity proposed in
    ``00_Architecture_Review.md`` §9.6, so that persisting these later is a
    matter of writing the same fields to a table rather than reshaping them.
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(description="Stable identifier, unique within a session.")
    sequence: int = Field(
        ge=1,
        description=(
            "Monotonic append order. The timeline is ordered by this rather than "
            "by timestamp: at the analysis rate several entries can share a "
            "millisecond, and an operator reviewing an incident needs to know "
            "which came first."
        ),
    )
    occurred_at: datetime

    entry_type: TimelineEntryType
    severity: Severity = Field(
        description="Display severity, reusing the platform's existing vocabulary."
    )

    title: str = Field(description="What happened, in operator language.")
    detail: str | None = Field(
        default=None,
        description="Why it happened, citing the measurement where there is one.",
    )

    camera_id: str
    actor: str | None = Field(
        default=None,
        description=(
            "Who caused this entry. Null for platform-generated entries; set for "
            "operator actions, which nothing produces yet."
        ),
    )


class TimelineRead(BaseModel):
    """A page of timeline entries.

    Always answerable, including before anything has happened - an empty
    timeline is a fact, not a failure.
    """

    model_config = ConfigDict(extra="forbid")

    entries: list[TimelineEntry] = Field(
        default_factory=list, description="Newest first."
    )
    total: int = Field(ge=0, description="Entries currently retained.")
    latest_sequence: int = Field(
        ge=0,
        description=(
            "Append sequence of the newest entry, or 0 when empty. A client that "
            "has this number knows whether it has seen everything."
        ),
    )
