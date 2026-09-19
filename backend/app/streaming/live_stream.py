"""The live video stream - annotated frames, served as MJPEG.

Sits between the pipeline thread, which produces images, and the HTTP handlers,
which serve them. Holds exactly one frame: the most recent.

**Why only the latest.** This is a surveillance feed. A viewer who falls behind
wants the current view of the crowd, not a backlog of the past - the same
reasoning the perception state service applies to measurements, and the same
reasoning that makes the frame *source* drop material under load rather than
queue it. A buffer here would add latency and show operators a crowd that has
already moved.

**Threading, and what runs where.** :meth:`LiveStreamService.handle_frame` runs
on the AI Pipeline's dedicated thread - the one keeping pace with the camera -
so it does the least it possibly can: one buffer copy, then it returns. Drawing
overlays and encoding a JPEG cost around ten milliseconds together, and spending
that on the pipeline thread taxes every frame whether or not a viewer ever asks
for one.

Instead they happen per *viewer*, on a worker thread, at the rate that viewer is
actually being served. A stream capped at 15 fps therefore encodes 15 times a
second no matter how fast the pipeline runs, and a pipeline with no viewers
encodes nothing at all.

The copy is not optional: the buffer handed to :meth:`handle_frame` belongs to
the pipeline and the tracker may still hold a reference to it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence

import cv2
import numpy as np
from numpy.typing import NDArray
from surgeguard_ai.contracts import AnalysisResult, CameraZone, PerceptionResult
from surgeguard_ai.perception import Frame
from surgeguard_ai.stability import CsiConfig

from ..core.logging import get_logger
from .annotator import DEFAULT_LAYERS, OverlayState, StreamLayer, Trails, annotate

#: Foot points kept per person for the trails layer - a couple of seconds of
#: movement at the analysis rate, enough to read direction without clutter.
TRAIL_LENGTH = 24

__all__ = ["LiveStreamService", "MJPEG_BOUNDARY", "MJPEG_CONTENT_TYPE"]

logger = get_logger(__name__)

#: Multipart boundary for the MJPEG response. Arbitrary but must not appear in
#: the payload; JPEG data cannot contain this ASCII sequence.
MJPEG_BOUNDARY = "surgeguardframe"
MJPEG_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}"


class LiveStreamService:
    """Holds the latest annotated frame and serves it to viewers."""

    def __init__(
        self,
        *,
        jpeg_quality: int = 75,
        target_fps: float = 15.0,
        camera_id: str | None = None,
        csi_config: CsiConfig | None = None,
    ) -> None:
        """
        Args:
            jpeg_quality: JPEG quality, 0-100. 75 is visually clean at control-
                room size while keeping frames small enough that encoding stays
                off the critical path.
            target_fps: Ceiling on how often a viewer is served a frame.
                Independent of the analysis rate: the pipeline may run faster,
                and there is no value in sending frames a display cannot show.
            camera_id: The camera whose video this stream carries. Assessments
                for every camera arrive on one bus; a stream bound to a camera
                draws only its own, so one camera's figures are never burned
                into another's picture.
            csi_config: The Crowd Stability Index configuration, whose density
                curve colours the heatmap - so a cell drawn as pressured is one
                the index itself counts as pressured.
        """
        if not 1 <= jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be within [1, 100]")
        if target_fps <= 0:
            raise ValueError("target_fps must be positive")

        self._camera_id = camera_id
        self._encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        self._frame_interval = 1.0 / target_fps
        self._csi_config = csi_config or CsiConfig()

        self._latest: tuple[NDArray[np.uint8], PerceptionResult, Trails] | None = None
        self._sequence = 0
        self._overlay = OverlayState()
        self._viewers = 0
        self._zones: tuple[CameraZone, ...] = ()
        # Replaced, never mutated: the render thread reads whichever mapping was
        # current when its frame was captured.
        self._trails: dict[int, tuple[tuple[float, float], ...]] = {}
        self._trail_seq: int | None = None

    # -- Writing ------------------------------------------------------------

    def handle_frame(self, frame: Frame, result: PerceptionResult) -> None:
        """Take a copy of one frame. Runs on the pipeline thread.

        Deliberately does nothing else. Annotation and encoding happen per
        viewer, off this thread - see the module docstring. Skipped entirely
        when nobody is watching, so an unwatched pipeline pays nothing at all.
        """
        if self._viewers == 0:
            return

        try:
            trails = self._advance_trails(result)
            self._latest = (frame.image.copy(), result, trails)
            self._sequence += 1
        except Exception as error:  # noqa: BLE001 - never propagate into the pipeline
            logger.error(
                "Frame capture failed",
                exc_info=error,
                extra={"frame_seq": result.frame_seq},
            )

    def _advance_trails(self, result: PerceptionResult) -> Trails:
        """Append each tracked person's foot point to their trail.

        People no longer tracked lose their trail at once - a line leading to
        where someone used to be would suggest they are still there. A restarted
        frame sequence clears every trail, because identities restart with it
        and an old path would be attached to a new person.
        """
        if self._trail_seq is not None and result.frame_seq <= self._trail_seq:
            self._trails = {}
        self._trail_seq = result.frame_seq

        previous = self._trails
        updated: dict[int, tuple[tuple[float, float], ...]] = {}
        for track in result.tracking.tracks:
            point = (track.foot_point.x, track.foot_point.y)
            updated[track.track_id] = (*previous.get(track.track_id, ()), point)[-TRAIL_LENGTH:]
        self._trails = updated
        return updated

    def set_zones(self, zones: Sequence[CameraZone]) -> None:
        """The camera's zones, outlined by the zones layer. Called when they change."""
        self._zones = tuple(zones)

    def _render(
        self,
        image: NDArray[np.uint8],
        result: PerceptionResult,
        layers: frozenset[StreamLayer] = DEFAULT_LAYERS,
        trails: Trails | None = None,
    ) -> bytes | None:
        """Annotate and JPEG-encode one frame. Runs on a worker thread."""
        try:
            annotated = annotate(
                image, result, self._overlay, layers, zones=self._zones, trails=trails
            )
            encoded, buffer = cv2.imencode(".jpg", annotated, self._encode_params)
        except Exception as error:  # noqa: BLE001 - a bad frame must not end the stream
            logger.error(
                "Frame annotation failed",
                exc_info=error,
                extra={"frame_seq": result.frame_seq},
            )
            return None

        return buffer.tobytes() if encoded else None

    def update_overlay(self, analysis: AnalysisResult) -> None:
        """Take the assessment figures drawn over subsequent frames.

        Subscribed to the analysis event rather than read on demand, so the
        pipeline thread never reaches across into backend state while encoding.
        """
        if self._camera_id is not None and analysis.camera_id != self._camera_id:
            return
        report = analysis.intelligence
        density_map = analysis.crowd.density_map
        self._overlay = OverlayState(
            csi=analysis.stability.csi_smoothed,
            status=analysis.stability.status,
            density=analysis.crowd.density_max,
            is_metric=analysis.crowd.is_metric,
            priority=report.priority.value if report is not None else None,
            density_map=density_map,
            density_curve=self._csi_config.density_curve(is_metric=density_map.is_metric),
            zone_flow=analysis.zone_flow,
            queue=analysis.queue,
        )

    def clear(self) -> None:
        """Drop the current frame and assessment overlay.

        Called when the pipeline stops. Continuing to serve the last frame of a
        camera that is no longer reporting is the video equivalent of a frozen
        number, and this platform does not do that quietly.
        """
        self._latest = None
        self._overlay = OverlayState()
        self._trails = {}
        self._trail_seq = None

    # -- Reading ------------------------------------------------------------

    @property
    def has_frame(self) -> bool:
        return self._latest is not None

    @property
    def viewers(self) -> int:
        """Connected stream viewers, for health reporting."""
        return self._viewers

    async def snapshot(
        self,
        layers: frozenset[StreamLayer] = DEFAULT_LAYERS,
        *,
        timeout_seconds: float = 2.0,
    ) -> bytes | None:
        """One annotated JPEG of the current view, or ``None`` if none arrives in time.

        For thumbnails. A browser holds an MJPEG response open for as long as it
        is shown and allows only a handful of connections per origin, so a grid
        of live tiles would starve every other request; a tile that fetches one
        frame every few seconds holds nothing open.

        Waits for a frame captured *after* the request, never serving whatever
        was left behind: frames are only captured while someone is watching, so
        without the wait a snapshot could show the crowd as it was minutes ago.
        It counts as a viewer while it waits, which is what makes a frame arrive.
        """
        start_sequence = self._sequence
        self._viewers += 1
        try:
            deadline = time.monotonic() + timeout_seconds
            while self._sequence == start_sequence:
                if time.monotonic() >= deadline:
                    return None
                await asyncio.sleep(0.02)
            captured = self._latest
            if captured is None:
                return None
            image, result, trails = captured
            return await asyncio.to_thread(self._render, image, result, layers, trails)
        finally:
            self._viewers = max(self._viewers - 1, 0)

    async def stream(
        self, layers: frozenset[StreamLayer] = DEFAULT_LAYERS
    ) -> AsyncIterator[bytes]:
        """Yield MJPEG parts for one viewer until they disconnect.

        ``layers`` are this viewer's overlays; another viewer of the same camera
        can ask for different ones.

        Polls rather than waiting on a cross-thread signal. At the frame
        interval this is a handful of wake-ups a second, and it avoids
        marshalling an event from the pipeline thread onto the loop for a
        latency saving smaller than the interval itself.
        """
        self._viewers += 1
        last_sent = -1
        logger.info("Live stream viewer connected", extra={"viewers": self._viewers})

        try:
            while True:
                captured = self._latest
                sequence = self._sequence

                if captured is not None and sequence != last_sent:
                    last_sent = sequence
                    image, result, trails = captured
                    # Off the event loop as well as off the pipeline thread:
                    # encoding is CPU-bound and would otherwise stall every
                    # other request for the duration.
                    payload = await asyncio.to_thread(
                        self._render, image, result, layers, trails
                    )
                    if payload is not None:
                        yield _mjpeg_part(payload)

                await asyncio.sleep(self._frame_interval)
        finally:
            self._viewers = max(self._viewers - 1, 0)
            logger.info(
                "Live stream viewer disconnected", extra={"viewers": self._viewers}
            )


def _mjpeg_part(payload: bytes) -> bytes:
    """One multipart chunk: boundary, headers, then the JPEG."""
    return b"".join(
        (
            b"--",
            MJPEG_BOUNDARY.encode("ascii"),
            b"\r\nContent-Type: image/jpeg\r\nContent-Length: ",
            str(len(payload)).encode("ascii"),
            b"\r\n\r\n",
            payload,
            b"\r\n",
        )
    )
