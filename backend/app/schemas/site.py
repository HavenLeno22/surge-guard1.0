"""Site topology request and response shapes.

The site report itself is the AI contract, returned as it is: re-declaring it
here would be a second definition of the same facts to keep in step.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import CameraRole, ZoneType

__all__ = [
    "FlowLinkWrite",
    "TopologyCameraRead",
    "TopologyLinkRead",
    "TopologyRead",
    "TopologyWrite",
    "TopologyZoneRead",
]


class FlowLinkWrite(BaseModel):
    """One directed connection an operator draws: people in one zone go on to another."""

    model_config = ConfigDict(extra="forbid")

    from_camera_id: str = Field(min_length=1)
    from_zone_id: str = Field(min_length=1)
    to_camera_id: str = Field(min_length=1)
    to_zone_id: str = Field(min_length=1)


class TopologyWrite(BaseModel):
    """The complete set of links. Replaces what was saved before."""

    model_config = ConfigDict(extra="forbid")

    links: list[FlowLinkWrite] = Field(default_factory=list)


class TopologyCameraRead(BaseModel):
    camera_id: str
    display_id: str
    name: str
    role: CameraRole
    coverage_area: str
    enabled: bool


class TopologyZoneRead(BaseModel):
    """A zone a link can name."""

    camera_id: str
    zone_id: str
    name: str
    zone_type: ZoneType


class TopologyLinkRead(BaseModel):
    link_id: str
    from_camera_id: str
    from_zone_id: str
    to_camera_id: str
    to_zone_id: str
    crosses_cameras: bool = Field(
        description=(
            "True when the zones are on different cameras. Such a link is shown as "
            "a correlation of two rates, never as a count of the same people."
        )
    )


class TopologyRead(BaseModel):
    cameras: list[TopologyCameraRead]
    zones: list[TopologyZoneRead]
    links: list[TopologyLinkRead]
    load_error: str | None = Field(
        default=None,
        description="Set when the saved topology could not be read; edits are refused.",
    )
