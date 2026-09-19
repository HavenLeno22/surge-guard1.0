"""Geometric primitives shared across the AI Pipeline.

Two coordinate spaces exist and must never be mixed:

- **Image space** - pixels, origin at the top-left of the frame. Everything
  produced by detection and tracking lives here.
- **Ground space** - metres on the ground plane, obtained by projecting image
  points through the camera homography. Density in persons/m2 and speed in m/s
  are only meaningful here.

Types carry their space in the name so a mix-up is visible at the call site.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from .base import Contract

__all__ = [
    "ImagePoint",
    "GroundPoint",
    "BoundingBox",
    "ImagePolygon",
    "Vector2D",
]


class ImagePoint(Contract):
    """A point in image space, in pixels."""

    x: float = Field(description="Horizontal pixel coordinate from the left edge.")
    y: float = Field(description="Vertical pixel coordinate from the top edge.")


class GroundPoint(Contract):
    """A point on the ground plane, in metres.

    Produced by projecting an :class:`ImagePoint` through the camera homography.
    Only available when the camera is calibrated.
    """

    x_m: float = Field(description="Ground-plane X coordinate in metres.")
    y_m: float = Field(description="Ground-plane Y coordinate in metres.")


class Vector2D(Contract):
    """A two-dimensional vector.

    Used for velocity. The unit depends on the space the vector was computed in
    - pixels/second in image space, metres/second in ground space - so the
    producing contract states which it is.
    """

    dx: float
    dy: float


class BoundingBox(Contract):
    """An axis-aligned bounding box in image space, in pixels.

    Stored as absolute corner coordinates rather than centre-plus-size so that
    no conversion is needed when drawing overlays.
    """

    x1: float = Field(description="Left edge.")
    y1: float = Field(description="Top edge.")
    x2: float = Field(description="Right edge.")
    y2: float = Field(description="Bottom edge.")

    @field_validator("x2")
    @classmethod
    def _x2_after_x1(cls, x2: float, info) -> float:
        x1 = info.data.get("x1")
        if x1 is not None and x2 < x1:
            raise ValueError("BoundingBox x2 must be greater than or equal to x1")
        return x2

    @field_validator("y2")
    @classmethod
    def _y2_after_y1(cls, y2: float, info) -> float:
        y1 = info.data.get("y1")
        if y1 is not None and y2 < y1:
            raise ValueError("BoundingBox y2 must be greater than or equal to y1")
        return y2

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def centroid(self) -> ImagePoint:
        """Geometric centre of the box."""
        return ImagePoint(x=(self.x1 + self.x2) / 2.0, y=(self.y1 + self.y2) / 2.0)

    @property
    def foot_point(self) -> ImagePoint:
        """Bottom-centre of the box - where the person meets the ground.

        This is the point projected through the homography to obtain a ground
        position. The centroid must not be used: it sits at torso height and
        projects to a position metres behind where the person is standing.
        """
        return ImagePoint(x=(self.x1 + self.x2) / 2.0, y=self.y2)


class ImagePolygon(Contract):
    """A closed polygon in image space, used to delimit camera zones."""

    points: tuple[ImagePoint, ...] = Field(
        min_length=3,
        description="Ordered vertices. The polygon is implicitly closed.",
    )
