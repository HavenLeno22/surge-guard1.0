"""Queue Intelligence API schemas.

As elsewhere, the AI Pipeline's contracts are carried through verbatim rather
than reshaped. :class:`QueueReport`, :class:`ForecastReport` and
:class:`ResourcePlanReport` are already the platform's shared vocabulary, and
restating their fields here would create a second definition to keep in step
with the first.

What is added around them is context they cannot carry for themselves: how old
the measurement is, whether Queue Intelligence is running at all, and - for the
write surfaces - the shapes an operator sends in.

The three layers are exposed on three separate routes rather than one combined
payload. Problem Statement 9 section 15 requires real-time, prediction and
recommendation to be clearly separated, and an API that returns them in one
object invites a client to render them in one panel.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from surgeguard_ai.contracts import (
    ForecastReport,
    QueueReport,
    ResourcePlanReport,
    SourceMode,
    ZoneType,
)

__all__ = [
    "QueueCurrentRead",
    "QueuePredictionRead",
    "RecommendationsRead",
    "CounterSettingsWrite",
    "CounterStateRead",
    "CountersRead",
    "ZonePointWrite",
    "ZoneWrite",
    "ZonesWrite",
    "ZonesRead",
]


class _Aged(BaseModel):
    """Common provenance carried by every Queue Intelligence read."""

    model_config = ConfigDict(from_attributes=True)

    camera_id: str
    source_mode: SourceMode = Field(
        description=(
            "Whether these figures came from a live camera or demonstration "
            "footage. A tag on the record, never a change in behaviour."
        )
    )
    frame_ts: datetime
    age_seconds: float = Field(
        ge=0.0,
        description=(
            "How old this measurement is. Displayed so that a frozen pipeline "
            "reads as stale rather than as a steady queue."
        ),
    )


class QueueCurrentRead(_Aged):
    """What every configured queue is doing right now."""

    queue: QueueReport = Field(
        description="Measured state per zone - counts, formation, rates, wait."
    )


class QueuePredictionRead(_Aged):
    """What every configured queue is expected to do next."""

    forecast: ForecastReport = Field(
        description=(
            "Projections at each configured horizon plus the abnormal-growth "
            "assessment. Never mixed into the measurement payload."
        )
    )


class RecommendationsRead(_Aged):
    """What the operator could do about capacity."""

    resources: ResourcePlanReport


class CounterSettingsWrite(BaseModel):
    """An operator's statement of the service resources on a queue zone.

    The platform cannot see how many ticket windows a hall has, nor which are
    staffed. This is where it is told.
    """

    total_counters: int = Field(
        ge=0, le=64, description="Counters physically available."
    )
    active_counters: int = Field(ge=0, le=64, description="Counters in service now.")
    service_rate_per_min: float | None = Field(
        default=None,
        gt=0.0,
        le=120.0,
        description=(
            "Per-counter rate to assume until enough departures are observed to "
            "measure one. Omitted keeps the current assumption."
        ),
    )

    @field_validator("active_counters")
    @classmethod
    def _active_within_total(cls, active: int, info) -> int:
        total = info.data.get("total_counters")
        if total is not None and active > total:
            raise ValueError(
                f"active_counters ({active}) cannot exceed total_counters ({total})"
            )
        return active


class CounterStateRead(BaseModel):
    """Current counter allocation for one queue zone."""

    zone_id: str
    zone_name: str
    total_counters: int
    active_counters: int
    service_rate_per_min: float = Field(
        description="Per-counter rate currently assumed or measured."
    )
    idle_counters: int


class CountersRead(BaseModel):
    """Counter allocation across every queue zone."""

    counters: tuple[CounterStateRead, ...] = ()


class ZonePointWrite(BaseModel):
    """One vertex of a zone polygon, in image space."""

    x: float = Field(ge=-10_000.0, le=10_000.0)
    y: float = Field(ge=-10_000.0, le=10_000.0)


class ZoneWrite(BaseModel):
    """A zone as an operator draws it."""

    zone_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    zone_type: ZoneType
    polygon: tuple[ZonePointWrite, ...] = Field(
        min_length=3,
        max_length=64,
        description="Ordered vertices. The polygon is implicitly closed.",
    )
    width_m: float | None = Field(
        default=None,
        gt=0.0,
        description="Clear width in metres, for EXIT and ENTRY zones.",
    )


class ZonesWrite(BaseModel):
    """The complete zone set for a camera.

    A replacement rather than a patch: partial zone updates invite a state where
    the stored set and the operator's mental model differ, and the operator is
    the one who has to notice.
    """

    zones: tuple[ZoneWrite, ...] = Field(
        max_length=32,
        description="Every zone on this camera. An empty list clears them all.",
    )


class ZonesRead(BaseModel):
    """The camera's current zone set."""

    camera_id: str
    zones: tuple[ZoneWrite, ...] = ()
    requires_restart: bool = Field(
        default=False,
        description=(
            "True when the running pipeline is still measuring against the "
            "previous zone set. Surfaced rather than hidden so an operator is "
            "never left wondering why a zone they just drew is not being "
            "measured."
        ),
    )
