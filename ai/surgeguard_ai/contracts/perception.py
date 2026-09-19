"""Perception contracts - the output of Stages 2 and 3 (``05:315-381``).

These describe *what was seen*, before any crowd-level interpretation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import SourceMode
from .geometry import BoundingBox, GroundPoint, ImagePoint, Vector2D

__all__ = [
    "Detection",
    "DetectionResult",
    "PerceptionResult",
    "Track",
    "TrackingResult",
]


class Detection(Contract):
    """One detected person in one frame (Stage 2, ``05:315-347``)."""

    bbox: BoundingBox
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Detector confidence that this region contains a person.",
    )


class DetectionResult(Contract):
    """Every person detected in a single frame."""

    frame_seq: int = Field(
        ge=0,
        description=(
            "Sequence number of the source frame. Used by the Command Center to "
            "align overlay boxes with the correct video frame."
        ),
    )
    frame_ts: datetime
    detections: tuple[Detection, ...] = Field(default=())
    inference_ms: float | None = Field(
        default=None,
        ge=0,
        description="Detector wall-clock time, for the performance budget.",
    )

    @property
    def count(self) -> int:
        return len(self.detections)


class Track(Contract):
    """One person followed across consecutive frames (Stage 3, ``05:351-381``).

    Track identities are **ephemeral**: scoped to a single camera, discarded
    when the track is lost, and never persisted. This is a privacy commitment,
    not an implementation detail - SurgeGuard does not identify individuals.
    """

    track_id: int = Field(
        description=(
            "Temporary identity, unique within one source session only. Carries "
            "no meaning across sessions, cameras or restarts."
        )
    )
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    age_frames: int = Field(
        ge=0,
        description="Frames since this track was first observed.",
    )
    foot_point: ImagePoint = Field(
        description="Bottom-centre of the box; the point projected to ground space."
    )
    ground_point: GroundPoint | None = Field(
        default=None,
        description="Ground-plane position. None when the camera is uncalibrated.",
    )
    velocity_image: Vector2D | None = Field(
        default=None,
        description="Velocity in pixels/second. None until enough history exists.",
    )
    velocity_ground: Vector2D | None = Field(
        default=None,
        description="Velocity in metres/second. Requires calibration and history.",
    )


class TrackingResult(Contract):
    """Every active track for a single frame."""

    frame_seq: int = Field(ge=0)
    frame_ts: datetime
    tracks: tuple[Track, ...] = Field(default=())
    id_switches: int = Field(
        default=0,
        ge=0,
        description=(
            "Identity switches observed in this frame. Feeds the track-stability "
            "factor of Decision Confidence."
        ),
    )

    @property
    def count(self) -> int:
        return len(self.tracks)


class PerceptionResult(Contract):
    """The complete perception output for one frame - Stages 1 to 3.

    This is what leaves the perception half of the AI Pipeline: *who was seen,
    where, and how fast the seeing was*. It carries no crowd-level
    interpretation - no density, no stability, no recommendation - because those
    are produced by later stages from this input.

    It is a contract rather than an internal structure because it crosses a
    boundary: the pipeline produces it and a consumer (a console runner today, a
    later stage tomorrow) receives it without sharing any of the pipeline's
    internals.
    """

    # -- Provenance ---------------------------------------------------------

    camera_id: str
    source_mode: SourceMode = Field(
        description=(
            "Whether these frames came from a live camera or a demonstration "
            "recording. A tag only - the pipeline never branches on it."
        )
    )
    frame_seq: int = Field(
        ge=0,
        description=(
            "Source frame index. Restarts at 0 whenever the source is reopened, "
            "which is how a consumer recognises a continuity break."
        ),
    )
    frame_ts: datetime = Field(
        description=(
            "Timestamp of the analysed frame. Wall-clock for live sources; for "
            "recordings, paced to the source frame rate so temporal behaviour is "
            "identical in both modes."
        )
    )
    produced_at: datetime = Field(description="When perception completed for this frame.")

    # -- Results ------------------------------------------------------------

    person_count: int = Field(
        ge=0,
        description=(
            "People counted in this frame. Taken from confirmed tracks when "
            "tracking ran, and from raw detections when it did not - so the "
            "count never silently reports zero because a later stage failed."
        ),
    )
    detections: DetectionResult
    tracking: TrackingResult

    # -- Performance --------------------------------------------------------

    inference_ms: float | None = Field(
        default=None,
        ge=0,
        description="Detector time for this frame.",
    )
    processing_ms: float = Field(
        ge=0,
        description="Detection plus tracking time for this frame.",
    )
    achieved_fps: float = Field(
        ge=0,
        description=(
            "Recent end-to-end throughput, measured over a rolling window of "
            "frames. This is the number to compare against the performance "
            "budget - not the reciprocal of the inference time, which excludes "
            "acquisition and tracking."
        ),
    )

    # -- Health -------------------------------------------------------------

    degraded: bool = Field(
        default=False,
        description=(
            "True when a stage could not run for this frame. The result is still "
            "emitted, carrying whatever was obtained, so that a consumer sees a "
            "reported gap rather than an unexplained silence."
        ),
    )
    degraded_reason: str | None = Field(default=None)

    @property
    def is_demo(self) -> bool:
        """Whether this result originated from demonstration footage."""
        return self.source_mode is SourceMode.DEMO

    @property
    def track_ids(self) -> tuple[int, ...]:
        """Active track identities in this frame, in track order."""
        return tuple(track.track_id for track in self.tracking.tracks)
