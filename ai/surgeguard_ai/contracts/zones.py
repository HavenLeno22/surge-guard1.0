"""Zone flow contracts - how people move into, out of and between zones.

Everything here describes **one camera**. Entries, exits and transitions are
counted from that camera's own track identities, which are ephemeral and scoped
to it (see :class:`~surgeguard_ai.contracts.perception.Track`). Movement between
zones on *different* cameras is not in this module, because it cannot be counted
the same way: the platform does not re-identify people across cameras, and a
site-level flow link says so explicitly (:class:`~.enums.FlowLinkBasis`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import ZoneType

__all__ = ["ZoneFlowReport", "ZoneFlowSnapshot", "ZoneTransition"]


class ZoneFlowSnapshot(Contract):
    """Occupancy and movement for one zone over the rolling window."""

    zone_id: str
    zone_name: str
    zone_type: ZoneType

    occupancy: int = Field(
        ge=0,
        description="Tracks whose foot point is inside the zone in this frame.",
    )
    entries: int = Field(ge=0, description="Entries counted within the window.")
    exits: int = Field(
        ge=0,
        description=(
            "Exits counted within the window. A track must stay absent for the "
            "grace period first, so a momentary tracking dropout is not an exit."
        ),
    )
    entry_rate_per_min: float = Field(ge=0.0)
    exit_rate_per_min: float = Field(ge=0.0)

    dominant_heading_deg: float | None = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description=(
            "Circular mean direction of the moving tracks inside the zone, in "
            "image space, degrees clockwise from +X. None with fewer than two "
            "moving tracks - a direction of one person is not a flow - and None "
            "when they do not broadly agree, where an averaged arrow would "
            "point somewhere nobody is walking."
        ),
    )
    heading_coherence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "How much those tracks agree on direction, as the resultant length "
            "of their unit headings. Near 1 is an orderly stream; near 0 is "
            "people crossing in every direction."
        ),
    )
    moving_count: int = Field(
        default=0,
        ge=0,
        description="Tracks inside the zone moving fast enough to have a heading.",
    )

    @property
    def net_rate_per_min(self) -> float:
        """Entries minus exits per minute: positive when the zone is filling."""
        return self.entry_rate_per_min - self.exit_rate_per_min


class ZoneTransition(Contract):
    """People counted moving from one zone to another on the same camera.

    Counted per track identity: a track last seen in ``from_zone_id`` and next
    seen in ``to_zone_id`` within the transition gap. That is a measurement of
    movement - not a correlation of two rates - which is why it exists only
    within one camera.
    """

    from_zone_id: str
    to_zone_id: str
    count: int = Field(ge=0, description="Transitions counted within the window.")
    rate_per_min: float = Field(ge=0.0)
    median_transit_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Median time between leaving the first zone and entering the second.",
    )


class ZoneFlowReport(Contract):
    """Zone flow for every configured zone on one camera, for one frame."""

    camera_id: str
    frame_seq: int = Field(ge=0)
    frame_ts: datetime
    window_seconds: float = Field(gt=0, description="Rolling window rates are counted over.")
    observation_seconds: float = Field(
        ge=0.0,
        description=(
            "How long flow has been observed. Rates over a few seconds are "
            "arithmetically right and operationally meaningless, and the "
            "interface says so rather than presenting them with full weight."
        ),
    )
    zones: tuple[ZoneFlowSnapshot, ...] = Field(default=())
    transitions: tuple[ZoneTransition, ...] = Field(default=())

    def by_zone(self, zone_id: str) -> ZoneFlowSnapshot | None:
        for zone in self.zones:
            if zone.zone_id == zone_id:
                return zone
        return None

    def transition(self, from_zone_id: str, to_zone_id: str) -> ZoneTransition | None:
        for transition in self.transitions:
            if transition.from_zone_id == from_zone_id and transition.to_zone_id == to_zone_id:
                return transition
        return None
