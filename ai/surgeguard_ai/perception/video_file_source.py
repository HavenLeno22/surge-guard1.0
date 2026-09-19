"""Demonstration Mode frame source.

Replays a recorded video **through the real AI Pipeline**. Nothing about the
analysis is simulated, scripted or hardcoded (Rule 7, ``15:121-125``; ``11:668``).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2

from ..contracts.enums import SourceMode
from ..errors import SourceEnded, SourceUnavailableError
from ._capture import OpenCVCaptureSource
from .frame_source import Frame

__all__ = ["VideoFileSource"]

logger = logging.getLogger(__name__)

#: Assumed frame rate when a container does not declare one.
_DEFAULT_FILE_FPS = 25.0

#: Never skip more than this much material in one catch-up. Guards against a
#: pathological jump after the process was suspended (a debugger breakpoint,
#: a laptop sleeping). Beyond this the source resynchronises instead.
_MAX_CATCHUP_SECONDS = 2.0

#: Consecutive undecodable frames tolerated before the clip is treated as
#: finished. A damaged frame in the middle of an otherwise sound file should
#: cost that frame, not the rest of the scenario.
_MAX_DECODE_FAILURES = 10


class VideoFileSource(OpenCVCaptureSource):
    """Frames from a recorded video, paced to real time.

    **Why pacing matters.** A video file decodes far faster than it was
    recorded. Left unpaced, the pipeline would see several hundred frames per
    second, and every temporal quantity - walking speed, rate of change,
    smoothing windows, hysteresis counters, rolling baselines - would be wrong
    by an order of magnitude. Demonstration Mode would then behave nothing like
    Live Mode, and the requirement that recorded video be processed *exactly as
    a live camera feed* would hold in name only.

    This source therefore does what a camera does:

    - Delivers frame ``N`` at wall-clock offset ``N / fps`` from session start.
    - **Drops frames when the consumer falls behind**, exactly as a live camera
      does under load, rather than accumulating an ever-growing backlog of
      stale material.

    **A useful property.** Frame timestamps are derived from ``seq / fps``, not
    from the wall clock. Analysis therefore depends only on frame indices, so
    disabling pacing changes the *delivery rate* but not the *result*. Offline
    golden-clip regression runs can process a clip at full speed and still
    produce the identical CSI curve the live demonstration produces.
    """

    def __init__(
        self,
        source_id: str,
        path: str | Path,
        *,
        fps_override: float | None = None,
        fallback_fps: float = _DEFAULT_FILE_FPS,
        realtime_pacing: bool = True,
        loop: bool = False,
        resize: tuple[int, int] | None = None,
        api_preference: int | None = None,
    ) -> None:
        """
        Args:
            source_id: Stable identifier used in logs and health reporting.
            path: Path to the video file.
            fps_override: Declare the material's true frame rate, overriding
                whatever the container reports. Use this when a container is
                mislabelled - not to speed a scenario up. The value defines how
                long a frame *represents*, so every temporal measurement made
                downstream is scaled by it. To replay faster without distorting
                time, disable ``realtime_pacing`` instead.
            fallback_fps: Frame rate assumed when the container declares none
                and no override is given.
            realtime_pacing: Deliver frames at the source frame rate. Keep
                ``True`` for any demonstration. Set ``False`` only for offline
                batch processing such as golden-clip regression, where full
                speed is wanted and delivery timing is irrelevant.
            loop: Restart from the first frame on reaching the end. Off by
                default: looping introduces a discontinuity that stateful
                analysers (tracker, rolling baselines, hysteresis counters)
                would read as a sudden crowd change. The wrap restarts the frame
                sequence at 0, which is how a consumer detects it.
            resize: Optional ``(width, height)`` applied to every frame.
            api_preference: OpenCV backend constant, or ``None`` for the default.
        """
        if fps_override is not None and fps_override <= 0:
            raise ValueError(f"fps_override must be positive, got {fps_override!r}")

        self._path = Path(path)
        super().__init__(
            source_id=source_id,
            target=str(self._path),
            fallback_fps=fallback_fps,
            resize=resize,
            api_preference=api_preference,
        )
        self._fps_override = fps_override
        self._realtime_pacing = realtime_pacing
        self._loop = loop

        self._total_frames: int = 0
        self._session_start: datetime = datetime.now(UTC)
        self._wall_start: float = 0.0
        self._decode_failures: int = 0

    # -- Identity -----------------------------------------------------------

    @property
    def source_mode(self) -> SourceMode:
        return SourceMode.DEMO

    @property
    def path(self) -> Path:
        return self._path

    @property
    def total_frames(self) -> int:
        """Declared frame count, or 0 when the container does not report one."""
        return self._total_frames

    @property
    def duration_seconds(self) -> float | None:
        """Clip duration, when the frame count is known."""
        if self._total_frames <= 0:
            return None
        return self._total_frames / self._fps

    # -- Lifecycle ----------------------------------------------------------

    def open(self) -> None:
        if not self._path.exists():
            raise SourceUnavailableError(f"Demonstration video not found: {self._path}")
        if not self._path.is_file():
            raise SourceUnavailableError(f"Demonstration path is not a file: {self._path}")

        super().open()
        self._begin_session()

    def _on_opened(self, capture: cv2.VideoCapture) -> None:
        declared = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self._total_frames = max(declared, 0)
        self._decode_failures = 0

    def _resolve_fps(self, capture: cv2.VideoCapture) -> float:
        """Honour an explicit override, otherwise use the declared frame rate."""
        if self._fps_override is not None:
            logger.info(
                "Demonstration source %s using declared frame rate %.2f fps "
                "(container reported %.2f)",
                self._source_id,
                self._fps_override,
                float(capture.get(cv2.CAP_PROP_FPS) or 0.0),
            )
            return self._fps_override
        return super()._resolve_fps(capture)

    def _begin_session(self) -> None:
        """Reset the pacing clock. Called on open and on loop wrap."""
        self._session_start = datetime.now(UTC)
        self._wall_start = time.monotonic()

    # -- Timestamps ---------------------------------------------------------

    def _timestamp_for(self, seq: int) -> datetime:
        """Paced timestamp: session start advanced by the frame's media offset.

        Because this derives from the frame index rather than the wall clock,
        analysis is reproducible and independent of how fast frames are
        delivered.
        """
        return self._session_start + timedelta(seconds=seq / self._fps)

    # -- Reading ------------------------------------------------------------

    def read(self) -> Frame | None:
        capture = self._require_capture()

        if self._realtime_pacing:
            self._pace(capture)

        ok, image = capture.read()
        if not ok or image is None:
            return self._handle_read_failure()

        self._decode_failures = 0
        return self._make_frame(image)

    def _pace(self, capture: cv2.VideoCapture) -> None:
        """Align delivery of the next frame with real time.

        Sleeps when ahead of schedule; discards material when behind, which is
        what a live camera does when the consumer cannot keep up.
        """
        target_offset = self._seq / self._fps
        elapsed = time.monotonic() - self._wall_start
        drift = elapsed - target_offset

        if drift < 0:
            time.sleep(-drift)
            return

        frame_interval = 1.0 / self._fps
        if drift < frame_interval:
            return

        frames_behind = int(drift * self._fps)
        max_skip = int(_MAX_CATCHUP_SECONDS * self._fps)

        if frames_behind > max_skip:
            # Too far behind to catch up honestly - the process was probably
            # suspended. Resynchronise the clock to now rather than discarding
            # a large span of the scenario.
            logger.warning(
                "Frame source %s fell %.1fs behind; resynchronising pacing clock",
                self._source_id,
                drift,
            )
            self._wall_start = time.monotonic() - target_offset
            return

        # grab() advances the decoder without the cost of retrieving the image.
        for _ in range(frames_behind):
            if not capture.grab():
                break
            self._seq += 1

        logger.debug(
            "Frame source %s dropped %d frame(s) to hold real-time pacing",
            self._source_id,
            frames_behind,
        )

    def _handle_read_failure(self) -> Frame | None:
        """Decide whether a failed read is the end of the clip or a damaged frame.

        OpenCV reports both the same way, so the two are separated by position:
        a failure at or beyond the declared frame count is the end, and a failure
        before it is damage. A damaged frame costs that frame - the sequence
        advances so the timeline stays honest about the gap - and reading
        continues. Only a sustained run of failures, or a container that declared
        no frame count, ends the clip.
        """
        self._decode_failures += 1

        at_declared_end = 0 < self._total_frames <= self._seq
        exhausted = self._decode_failures >= _MAX_DECODE_FAILURES

        if at_declared_end or exhausted:
            return self._handle_end_of_file()

        logger.warning(
            "Demonstration source %s could not decode frame %d (%d/%d tolerated); skipping",
            self._source_id,
            self._seq,
            self._decode_failures,
            _MAX_DECODE_FAILURES,
        )
        self._seq += 1
        return None

    def _handle_end_of_file(self) -> Frame | None:
        """Loop or terminate on reaching the end of the clip."""
        if not self._loop:
            logger.info(
                "Demonstration source %s reached end of clip after %d frames",
                self._source_id,
                self._seq,
            )
            raise SourceEnded(f"Demonstration video exhausted: {self._path}")

        capture = self._require_capture()
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._seq = 0
        self._begin_session()

        logger.info("Demonstration source %s looped to start", self._source_id)

        ok, image = capture.read()
        if not ok or image is None:
            raise SourceUnavailableError(
                f"Demonstration video could not be rewound: {self._path}"
            )
        return self._make_frame(image)
