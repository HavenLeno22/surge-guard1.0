"""Shared OpenCV VideoCapture handling for concrete frame sources.

Private to :mod:`surgeguard_ai.perception`. Both :class:`LiveCameraSource` and
:class:`VideoFileSource` wrap ``cv2.VideoCapture``; this holds the mechanics
they genuinely share so neither duplicates it (Rule 9).

What each subclass still owns is what actually differs between them: their
source mode, and how they derive frame timestamps.
"""

from __future__ import annotations

import logging
import time
from abc import abstractmethod
from collections.abc import Callable

import cv2
import numpy as np
from numpy.typing import NDArray

from ..errors import SourceUnavailableError
from .frame_source import Frame, FrameSource

__all__ = ["OpenCVCaptureSource"]

logger = logging.getLogger(__name__)

#: Consecutive failed grabs tolerated before a source is declared lost.
#: A handful of dropped frames is normal on an IP camera; a sustained run of
#: them is a disconnection.
_MAX_CONSECUTIVE_FAILURES = 30


class OpenCVCaptureSource(FrameSource):
    """Base for frame sources backed by ``cv2.VideoCapture``."""

    def __init__(
        self,
        source_id: str,
        target: int | str,
        fallback_fps: float,
        *,
        resize: tuple[int, int] | None = None,
        api_preference: int | None = None,
        open_timeout_ms: int | None = None,
        read_timeout_ms: int | None = None,
        max_stall_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Args:
            source_id: Stable identifier used in logs and health reporting.
            target: What OpenCV should open - a device index or a URL/path.
            fallback_fps: Frame rate to assume when the source does not report
                a usable one. Webcams frequently report 0.
            resize: Optional ``(width, height)`` to scale every frame to before
                it leaves the source. Detection cost scales with pixel count, so
                this is the primary lever for meeting the analysis-rate budget.
                It belongs here rather than in the detector because it changes
                the image space every downstream coordinate lives in: bounding
                boxes, foot points and any camera calibration are all expressed
                in the *delivered* frame's pixels.
            api_preference: OpenCV backend constant (``cv2.CAP_DSHOW``,
                ``cv2.CAP_FFMPEG``, ...). ``None`` lets OpenCV choose.
            open_timeout_ms: Give up opening a network stream after this long.
                ``None`` keeps the backend's own default.
            read_timeout_ms: Give up waiting for a frame from a network stream
                after this long. **This is what makes a vanished phone
                detectable at all:** without it, a read on a stream whose device
                has left the network can block for minutes while the pipeline
                goes on reporting itself as running. ``None`` keeps the
                backend's default. Passed to FFmpeg, so an ``api_preference`` of
                ``cv2.CAP_FFMPEG`` is used when either timeout is set.
            max_stall_seconds: Declare the source lost once reads have been
                failing for this long, however few of them there were. A run of
                failures counted only by number takes thirty timeouts to add up;
                measured by time, a stalled stream is reported within seconds.
                ``None`` keeps count-only behaviour.
            clock: Monotonic time source, injectable so stall detection can be
                tested without waiting.
        """
        self._source_id = source_id
        self._target = target
        self._fallback_fps = fallback_fps
        self._resize = self._validated_resize(resize)
        self._api_preference = api_preference
        self._open_timeout_ms = open_timeout_ms
        self._read_timeout_ms = read_timeout_ms
        self._max_stall_seconds = max_stall_seconds
        self._clock = clock

        self._capture: cv2.VideoCapture | None = None
        self._fps: float = fallback_fps
        self._seq: int = 0
        self._consecutive_failures: int = 0
        self._failing_since: float | None = None
        self._native_size: tuple[int, int] | None = None

    @staticmethod
    def _validated_resize(resize: tuple[int, int] | None) -> tuple[int, int] | None:
        if resize is None:
            return None
        width, height = resize
        if width <= 0 or height <= 0:
            raise ValueError(f"resize must be positive, got {resize!r}")
        return int(width), int(height)

    # -- FrameSource identity ----------------------------------------------

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    @property
    def resize(self) -> tuple[int, int] | None:
        """The ``(width, height)`` every delivered frame is scaled to, if any."""
        return self._resize

    @property
    def native_size(self) -> tuple[int, int] | None:
        """``(width, height)`` of frames as the source delivers them, before resize.

        Known once a frame has been read. Reported for camera health: an
        operator comparing two phones wants the resolution each one is sending,
        not the size the platform scales both down to.
        """
        return self._native_size

    # -- Lifecycle ----------------------------------------------------------

    def open(self) -> None:
        if self.is_open:
            return

        capture = self._create_capture()
        if not capture.isOpened():
            capture.release()
            raise SourceUnavailableError(
                f"Could not open frame source {self._source_id!r} (target={self._target!r})"
            )

        self._capture = capture
        self._fps = self._resolve_fps(capture)
        self._seq = 0
        self._consecutive_failures = 0
        self._failing_since = None
        # A reconnected device may come back at a different resolution.
        self._native_size = None
        self._on_opened(capture)

        logger.info(
            "Frame source opened: %s (mode=%s, fps=%.2f, resize=%s)",
            self._source_id,
            self.source_mode.value,
            self._fps,
            "none" if self._resize is None else f"{self._resize[0]}x{self._resize[1]}",
        )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            logger.info("Frame source closed: %s", self._source_id)

    def _create_capture(self) -> cv2.VideoCapture:
        """Construct the OpenCV capture, with network timeouts when configured.

        The three-argument constructor is used only when a timeout is actually
        set, so a source configured as before is opened exactly as before.
        """
        params: list[int] = []
        if self._open_timeout_ms is not None:
            params += [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), int(self._open_timeout_ms)]
        if self._read_timeout_ms is not None:
            params += [int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), int(self._read_timeout_ms)]

        if params:
            api = self._api_preference if self._api_preference is not None else cv2.CAP_FFMPEG
            return cv2.VideoCapture(self._target, api, params)
        if self._api_preference is None:
            return cv2.VideoCapture(self._target)
        return cv2.VideoCapture(self._target, self._api_preference)

    # -- Shared read mechanics ---------------------------------------------

    def _require_capture(self) -> cv2.VideoCapture:
        """Return the open capture handle or fail loudly."""
        if self._capture is None:
            raise SourceUnavailableError(
                f"Frame source {self._source_id!r} was read before being opened"
            )
        return self._capture

    def _grab(self) -> NDArray[np.uint8] | None:
        """Read one raw image, tolerating a bounded run of transient failures.

        Returns:
            The decoded image, or ``None`` for a recoverable gap.

        Raises:
            SourceUnavailableError: Too many consecutive failures - the source
                is considered lost and reconnection should be attempted.
        """
        capture = self._require_capture()
        ok, image = capture.read()

        if not ok or image is None:
            now = self._clock()
            if self._failing_since is None:
                self._failing_since = now
            self._consecutive_failures += 1

            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                raise SourceUnavailableError(
                    f"Frame source {self._source_id!r} failed "
                    f"{self._consecutive_failures} consecutive reads"
                )
            stalled_for = now - self._failing_since
            if self._max_stall_seconds is not None and stalled_for >= self._max_stall_seconds:
                raise SourceUnavailableError(
                    f"Frame source {self._source_id!r} delivered no frame for "
                    f"{stalled_for:.1f}s"
                )
            return None

        self._consecutive_failures = 0
        self._failing_since = None
        if self._native_size is None:
            height, width = image.shape[:2]
            self._native_size = (int(width), int(height))
        return image

    def _make_frame(self, image: NDArray[np.uint8]) -> Frame:
        """Wrap a raw image as a :class:`Frame` and advance the sequence counter."""
        frame = Frame(
            seq=self._seq,
            ts=self._timestamp_for(self._seq),
            image=self._scale(image),
            source_id=self._source_id,
        )
        self._seq += 1
        return frame

    def _scale(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Apply the configured resize, if any.

        ``INTER_AREA`` is used when shrinking because it averages over the
        source pixels rather than sampling one of them - which preserves small,
        distant people that nearest-neighbour or bilinear sampling would thin
        out, and those are precisely the detections that matter in a crowd.
        """
        if self._resize is None:
            return image

        target_width, target_height = self._resize
        height, width = image.shape[:2]
        if (width, height) == (target_width, target_height):
            return image

        shrinking = target_width * target_height < width * height
        interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
        return cv2.resize(
            image,
            (target_width, target_height),
            interpolation=interpolation,
        )

    def _resolve_fps(self, capture: cv2.VideoCapture) -> float:
        """Read the source frame rate, falling back when it is not reported."""
        reported = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if reported <= 0.0 or not np.isfinite(reported):
            logger.warning(
                "Frame source %s reported no usable frame rate; assuming %.2f fps",
                self._source_id,
                self._fallback_fps,
            )
            return self._fallback_fps
        return reported

    # -- Subclass hooks -----------------------------------------------------

    def _on_opened(self, capture: cv2.VideoCapture) -> None:
        """Hook for per-source configuration once the capture is open."""

    @abstractmethod
    def _timestamp_for(self, seq: int):
        """Return the timestamp for the frame at ``seq``.

        This is the one place Live and Demonstration modes genuinely differ:
        a live camera stamps wall-clock at grab time, a recording derives a
        paced timestamp from its own frame rate.
        """
