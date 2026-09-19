"""Person tracking with ByteTrack - Stage 3 of the AI Pipeline.

Implements :class:`~surgeguard_ai.perception.tracker.Tracker` (``05:351-381``).

ByteTrack is used through Ultralytics' implementation rather than reimplemented:
association is a solved problem, and a hand-written tracker would cost days for
no operational gain (``02_Hackathon_Execution_Plan.md``, Rejected Decision R3).
What this module owns is the adaptation - turning SurgeGuard detections into
what the tracker expects, and turning its output back into
:class:`~surgeguard_ai.contracts.perception.Track` records with movement history.

**Privacy commitment.** Track identities are ephemeral: scoped to one camera and
one source session, discarded when a track is lost, never persisted. SurgeGuard
does not identify individuals and does not re-identify anyone across cameras.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ..contracts.camera import CameraConfig
from ..contracts.geometry import BoundingBox, ImagePoint, Vector2D
from ..contracts.perception import DetectionResult, Track, TrackingResult
from ..errors import TrackingError
from .frame_source import Frame
from .tracker import Tracker

__all__ = ["ByteTrackTracker"]

logger = logging.getLogger(__name__)

#: How long a track survives without being matched, in seconds. ByteTrack keeps
#: a lost track alive for this long so a person walking behind a pillar keeps
#: their identity; beyond it the track is removed and a reappearance becomes a
#: new person. Expressed in seconds rather than frames because the operational
#: meaning - "how long may somebody be hidden?" - does not change with frame rate.
_DEFAULT_LOST_TRACK_TIMEOUT_S = 1.0

#: Frames of foot-point history used to estimate velocity. Short enough to
#: follow a change of pace, long enough that detector jitter does not dominate.
_DEFAULT_VELOCITY_WINDOW = 5

#: Track count above which per-person tracking is no longer trusted. A provisional
#: proxy: the real criterion is crowd density, which is not measurable until
#: ground-plane calibration lands (Architecture Review C11). Documented as a
#: placeholder rather than presented as a calibrated threshold.
_DEFAULT_RELIABLE_TRACK_LIMIT = 150


@dataclass(slots=True)
class _TrackHistory:
    """Per-identity movement history, held only while the track is alive."""

    first_frame: int
    last_frame: int
    points: deque[tuple[datetime, ImagePoint]]

    def velocity(self) -> Vector2D | None:
        """Average image-space velocity over the retained window, in px/s."""
        if len(self.points) < 2:
            return None

        (first_ts, first_point) = self.points[0]
        (last_ts, last_point) = self.points[-1]
        elapsed = (last_ts - first_ts).total_seconds()
        if elapsed <= 0:
            return None

        return Vector2D(
            dx=(last_point.x - first_point.x) / elapsed,
            dy=(last_point.y - first_point.y) / elapsed,
        )


@dataclass(slots=True)
class _DetectionArrays:
    """The array view ByteTrack consumes.

    Ultralytics' tracker takes a results-like object exposing ``xywh``, ``conf``
    and ``cls`` and supporting boolean-mask indexing, which it uses to split
    detections into high- and low-confidence sets. Providing that view directly
    keeps detection and tracking as separate pipeline stages: the detector does
    not track, and the tracker does not run a model.
    """

    xywh: NDArray[np.float32]
    conf: NDArray[np.float32]
    cls: NDArray[np.float32] = field(default_factory=lambda: np.empty(0, dtype=np.float32))

    def __len__(self) -> int:
        return int(self.conf.shape[0])

    def __getitem__(self, mask: NDArray[np.bool_]) -> _DetectionArrays:
        return _DetectionArrays(xywh=self.xywh[mask], conf=self.conf[mask], cls=self.cls[mask])

    @classmethod
    def from_detections(cls, detections: DetectionResult) -> _DetectionArrays:
        """Build the view from a detection result, converting corners to centres."""
        count = detections.count
        xywh = np.zeros((count, 4), dtype=np.float32)
        conf = np.zeros(count, dtype=np.float32)

        for index, detection in enumerate(detections.detections):
            box = detection.bbox
            xywh[index] = (
                (box.x1 + box.x2) / 2.0,
                (box.y1 + box.y2) / 2.0,
                box.width,
                box.height,
            )
            conf[index] = detection.confidence

        return cls(xywh=xywh, conf=conf, cls=np.zeros(count, dtype=np.float32))


class ByteTrackTracker(Tracker):
    """Follows detected people across frames using ByteTrack.

    ByteTrack associates in two passes: high-confidence detections first, then
    the low-confidence remainder against tracks still unmatched. That second
    pass is what makes it suitable here - a partially occluded person in a crowd
    produces a weak detection, and a tracker that discards weak detections loses
    exactly the people who matter most.

    The tracker is **stateful**. :meth:`reset` discards everything, and must be
    called whenever frame continuity breaks, or movement history from before the
    break becomes fabricated motion after it.
    """

    def __init__(
        self,
        *,
        frame_rate: float = 30.0,
        lost_track_timeout_s: float = _DEFAULT_LOST_TRACK_TIMEOUT_S,
        track_high_thresh: float = 0.25,
        track_low_thresh: float = 0.1,
        new_track_thresh: float = 0.25,
        match_thresh: float = 0.8,
        fuse_score: bool = True,
        velocity_window: int = _DEFAULT_VELOCITY_WINDOW,
        reliable_track_limit: int = _DEFAULT_RELIABLE_TRACK_LIMIT,
    ) -> None:
        """
        Args:
            frame_rate: Frame rate of the source, used to convert the lost-track
                timeout into frames. Should match the attached
                :class:`~surgeguard_ai.perception.frame_source.FrameSource`.
            lost_track_timeout_s: How long an unmatched track is kept alive.
                Longer survives deeper occlusion at the cost of more identity
                switches when a different person appears where one was lost.
            track_high_thresh: Confidence above which a detection is used in the
                first association pass.
            track_low_thresh: Confidence below which a detection is discarded
                entirely. Detections between the two thresholds are used only to
                sustain existing tracks, never to start new ones.
            new_track_thresh: Confidence required to start a new identity.
            match_thresh: Association similarity threshold.
            fuse_score: Combine detection confidence with motion similarity when
                matching. Stabilises association on weak detections.
            velocity_window: Frames of foot-point history used for velocity.
            reliable_track_limit: Track count above which :attr:`is_reliable`
                reports that per-person tracking can no longer be trusted.
        """
        if frame_rate <= 0:
            raise ValueError(f"frame_rate must be positive, got {frame_rate!r}")
        if velocity_window < 2:
            raise ValueError(f"velocity_window must be at least 2, got {velocity_window}")

        self._frame_rate = frame_rate
        self._lost_track_timeout_s = lost_track_timeout_s
        self._track_buffer = max(int(round(frame_rate * lost_track_timeout_s)), 1)
        self._track_high_thresh = track_high_thresh
        self._track_low_thresh = track_low_thresh
        self._new_track_thresh = new_track_thresh
        self._match_thresh = match_thresh
        self._fuse_score = fuse_score
        self._velocity_window = velocity_window
        self._reliable_track_limit = reliable_track_limit

        self._tracker: Any | None = None
        self._histories: dict[int, _TrackHistory] = {}
        self._frame_index = 0
        self._active_count = 0

    # -- Identity -----------------------------------------------------------

    @property
    def lost_track_timeout_frames(self) -> int:
        """Frames an unmatched track survives before removal."""
        return self._track_buffer

    @property
    def active_track_count(self) -> int:
        """Tracks confirmed in the most recent update."""
        return self._active_count

    @property
    def is_reliable(self) -> bool:
        """Whether per-person tracking is currently within its trusted range.

        The prototype's criterion is track count, which is a stand-in for crowd
        density. Density requires ground-plane calibration and is therefore a
        later phase; until then this reports a conservative proxy rather than an
        authoritative threshold.
        """
        return self._active_count <= self._reliable_track_limit

    # -- Tracking -----------------------------------------------------------

    def update(
        self,
        frame: Frame,
        detections: DetectionResult,
        camera: CameraConfig,
    ) -> TrackingResult:
        """Advance tracking by one frame."""
        tracker = self._require_tracker()
        self._frame_index += 1

        try:
            rows = tracker.update(_DetectionArrays.from_detections(detections), frame.image)
        except Exception as exc:  # noqa: BLE001 - one bad frame must not stop monitoring
            raise TrackingError(
                f"Tracking failed for frame {frame.seq} of {frame.source_id!r}: {exc}"
            ) from exc

        tracks = self._to_tracks(rows, frame=frame, camera=camera)
        self._prune_histories()
        self._active_count = len(tracks)

        return TrackingResult(
            frame_seq=frame.seq,
            frame_ts=frame.ts,
            tracks=tracks,
            # Identity switches cannot be counted without ground truth. Reporting
            # a guess here would put a fabricated number into Decision Confidence,
            # so the field stays at its honest default until a defensible
            # estimator exists.
            id_switches=0,
        )

    def reset(self) -> None:
        """Discard every identity and all movement history."""
        if self._tracker is not None:
            self._tracker.reset()
        self._histories.clear()
        self._frame_index = 0
        self._active_count = 0
        logger.debug("Tracker reset; all identities and movement history discarded")

    # -- Internals ----------------------------------------------------------

    def _require_tracker(self) -> Any:
        """Return the underlying tracker, constructing it on first use."""
        if self._tracker is None:
            self._tracker = self._build_tracker()
        return self._tracker

    def _build_tracker(self) -> Any:
        """Construct Ultralytics' ByteTrack with SurgeGuard's parameters.

        Ultralytics is imported lazily so that importing
        ``surgeguard_ai.perception`` does not pull in a model runtime.
        """
        try:
            from types import SimpleNamespace

            from ultralytics.trackers.byte_tracker import BYTETracker
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise TrackingError(
                "Ultralytics is not installed; person tracking is unavailable. "
                "Install the AI package with its detection dependencies."
            ) from exc

        args = SimpleNamespace(
            tracker_type="bytetrack",
            track_high_thresh=self._track_high_thresh,
            track_low_thresh=self._track_low_thresh,
            new_track_thresh=self._new_track_thresh,
            track_buffer=self._track_buffer,
            match_thresh=self._match_thresh,
            fuse_score=self._fuse_score,
        )

        logger.info(
            "Tracker ready: ByteTrack (frame_rate=%.2f, lost-track timeout=%.2fs / %d frames, "
            "high=%.2f low=%.2f new=%.2f match=%.2f)",
            self._frame_rate,
            self._lost_track_timeout_s,
            self._track_buffer,
            self._track_high_thresh,
            self._track_low_thresh,
            self._new_track_thresh,
            self._match_thresh,
        )
        return BYTETracker(args)

    def _to_tracks(
        self,
        rows: NDArray[np.float32],
        *,
        frame: Frame,
        camera: CameraConfig,
    ) -> tuple[Track, ...]:
        """Convert tracker output rows into contract tracks, updating history.

        Ultralytics returns ``[x1, y1, x2, y2, track_id, score, class, index]``
        per confirmed track.
        """
        if rows is None or len(rows) == 0:
            return ()

        tracks: list[Track] = []

        for row in np.atleast_2d(np.asarray(rows, dtype=np.float32)):
            x1, y1, x2, y2 = (float(value) for value in row[:4])
            track_id = int(row[4])
            score = float(min(max(row[5], 0.0), 1.0))

            foot_point = ImagePoint(x=(x1 + x2) / 2.0, y=y2)
            history = self._record_point(track_id, frame.ts, foot_point)

            tracks.append(
                Track(
                    track_id=track_id,
                    bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                    confidence=score,
                    age_frames=self._frame_index - history.first_frame,
                    foot_point=foot_point,
                    # Ground-space position and velocity require a calibrated
                    # camera. Leaving them unset is what keeps an uncalibrated
                    # measurement from being read as metres (Review C21).
                    ground_point=None,
                    velocity_image=history.velocity(),
                    velocity_ground=None,
                )
            )

        return tuple(tracks)

    def _record_point(
        self,
        track_id: int,
        timestamp: datetime,
        foot_point: ImagePoint,
    ) -> _TrackHistory:
        """Append a foot point to a track's history, creating it if new."""
        history = self._histories.get(track_id)

        if history is None:
            history = _TrackHistory(
                first_frame=self._frame_index,
                last_frame=self._frame_index,
                points=deque(maxlen=self._velocity_window),
            )
            self._histories[track_id] = history

        history.last_frame = self._frame_index
        history.points.append((timestamp, foot_point))
        return history

    def _prune_histories(self) -> None:
        """Forget tracks that have outlived the lost-track timeout.

        Both a resource measure and a privacy one: movement history is retained
        only while the track it belongs to is alive.
        """
        horizon = self._frame_index - self._track_buffer
        stale = [
            track_id
            for track_id, history in self._histories.items()
            if history.last_frame < horizon
        ]
        for track_id in stale:
            del self._histories[track_id]
