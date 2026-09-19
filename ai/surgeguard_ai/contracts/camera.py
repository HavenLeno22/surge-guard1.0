"""Camera configuration contracts.

Calibration and zones are configuration inputs to the AI Pipeline, not outputs.
They are supplied by the consuming application (from the database or a config
file) and are required for two of the five Crowd Stability Index indicators to
be computable at all (Architecture Review C21, C26).
"""

from __future__ import annotations

from pydantic import Field

from .base import Contract
from .enums import ZoneType
from .geometry import ImagePolygon

__all__ = ["CameraCalibration", "CameraZone", "CameraConfig"]


class CameraCalibration(Contract):
    """Ground-plane calibration for one camera.

    Without this, "density" is persons-per-image-region: not comparable across
    cameras, not comparable over time, and not connectable to published
    crowd-safety density thresholds. Anything derived from an uncalibrated
    camera must be labelled *relative density* and must never be presented as
    persons/m2.
    """

    homography: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] = Field(
        description=(
            "Row-major 3x3 matrix mapping image-space points to ground-plane "
            "metres. Obtained from four image points whose real-world spacing "
            "is known."
        )
    )
    ground_area_m2: float = Field(
        gt=0,
        description="Total monitored ground area in square metres.",
    )
    calibrated_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of when calibration was performed.",
    )


class CameraZone(Contract):
    """A named region of the camera view with an operational role.

    Zones are what let the platform measure egress congestion and name a real
    location in a recommendation ("open Exit Gate B") rather than inventing one.
    """

    zone_id: str
    name: str = Field(description="Operator-facing name, e.g. 'Exit Gate B'.")
    zone_type: ZoneType
    polygon: ImagePolygon = Field(description="Zone boundary in image space.")
    width_m: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Clear width in metres, for EXIT and ENTRY zones. Required to "
            "convert occupancy into an egress capacity ratio."
        ),
    )


class CameraConfig(Contract):
    """Everything the AI Pipeline needs to know about the camera it is watching.

    Supplied once at pipeline construction. Note that this deliberately contains
    no stream URL or device index: how frames are obtained is the concern of the
    :class:`~surgeguard_ai.perception.frame_source.FrameSource`, which keeps the
    pipeline unaware of whether it is processing a live feed or a recording.
    """

    camera_id: str
    name: str
    location: str = Field(description="Operator-facing location, e.g. 'Platform 3'.")
    calibration: CameraCalibration | None = Field(
        default=None,
        description="Absent when the camera has not been calibrated.",
    )
    zones: tuple[CameraZone, ...] = Field(default=())

    @property
    def is_calibrated(self) -> bool:
        """Whether metric (persons/m2) density can be produced for this camera."""
        return self.calibration is not None

    def zones_of_type(self, zone_type: ZoneType) -> tuple[CameraZone, ...]:
        """Return every configured zone of a given role."""
        return tuple(zone for zone in self.zones if zone.zone_type is zone_type)
