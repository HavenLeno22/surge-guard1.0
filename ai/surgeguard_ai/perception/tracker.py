"""Person tracking - Stage 3 of the AI Pipeline (``05:351-381``).

Interface only. The concrete tracker is Phase 2 work.

Tracking exists so that movement can be measured over time: walking speed and
flow direction are only meaningful when the same person is followed across
frames.

**Privacy commitment.** Track identities are ephemeral. They are scoped to a
single camera and a single source session, discarded when a track is lost, and
never persisted. SurgeGuard does not identify individuals and does not
re-identify a person across cameras.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.camera import CameraConfig
from ..contracts.perception import DetectionResult, TrackingResult
from .frame_source import Frame

__all__ = ["Tracker"]


class Tracker(ABC):
    """Follows detected people across consecutive frames.

    A tracker is **stateful**: it accumulates movement history. That state must
    be discarded whenever continuity breaks - a source switch, a loop wrap, a
    reconnection - or the previous material's movement bleeds into the new.
    :meth:`reset` is the single mechanism for this, and it is what makes both
    Live/Demo switching and One-Click Reset correct.
    """

    @property
    @abstractmethod
    def is_reliable(self) -> bool:
        """Whether tracking is currently within its reliable operating range.

        Per-person tracking degrades severely at high crowd density: identities
        become unstable and every speed-derived measurement silently decays.
        When this returns ``False`` the pipeline must switch the crowd count to
        an explicitly-labelled estimate, mark track-derived indicators
        unavailable, and lower Decision Confidence accordingly - rather than
        continuing to present confident numbers derived from noise
        (Architecture Review C11).
        """

    @abstractmethod
    def update(
        self,
        frame: Frame,
        detections: DetectionResult,
        camera: CameraConfig,
    ) -> TrackingResult:
        """Advance tracking by one frame.

        Args:
            frame: The frame the detections came from.
            detections: Detections for this frame.
            camera: Camera configuration. Supplies the calibration used to
                project foot points to ground space, so that velocity can be
                reported in metres/second rather than pixels/second. When the
                camera is uncalibrated, ground-space fields are left unset.

        Returns:
            Active tracks for this frame.

        Raises:
            TrackingError: Tracking failed for this frame.
        """

    @abstractmethod
    def reset(self) -> None:
        """Discard all tracking state.

        Must be called whenever frame continuity breaks. After this call no
        track identity or movement history from before it may influence any
        subsequent result.
        """
