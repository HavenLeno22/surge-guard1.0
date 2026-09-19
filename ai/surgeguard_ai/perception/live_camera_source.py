"""Live Camera Mode frame source.

Reads from an attached webcam or a network camera (RTSP/HTTP).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

import cv2

from ..contracts.enums import SourceMode
from ..errors import SourceUnavailableError
from ._capture import OpenCVCaptureSource
from .frame_source import Frame

__all__ = ["LiveCameraSource"]

logger = logging.getLogger(__name__)

#: Assumed frame rate when a device does not report one. Webcams commonly
#: report 0 through the V4L2/DirectShow backends.
_DEFAULT_LIVE_FPS = 30.0

#: Reconnection backoff, in seconds. Starts short because most camera dropouts
#: are momentary, and grows so that a genuinely absent camera is not probed in a
#: tight loop for as long as the platform runs.
_DEFAULT_RECONNECT_BACKOFF_S = 0.5
_DEFAULT_RECONNECT_BACKOFF_MAX_S = 8.0
_DEFAULT_RECONNECT_ATTEMPTS = 5


class LiveCameraSource(OpenCVCaptureSource):
    """Frames from a live camera (``11:93-107``).

    Timestamps are wall-clock at grab time: the frame is happening now.

    A live camera is an infinite source. It never raises
    :class:`~surgeguard_ai.errors.SourceEnded`. A lost connection is first
    *retried* - the documented behaviour is "attempt automatic reconnection"
    (``05:878-886``, ``04:803-809``) - and only surfaces as
    :class:`~surgeguard_ai.errors.SourceUnavailableError` once reconnection has
    been exhausted, so the caller can inform the operator.

    **Reconnection restarts the frame sequence at 0.** That is the documented
    meaning of :attr:`~surgeguard_ai.perception.frame_source.Frame.seq` - it is
    per source *session* - and it is deliberately how a consumer learns that
    continuity broke. Movement history spanning a dropout would be fabricated
    motion; a consumer that sees the sequence restart knows to discard it.
    """

    def __init__(
        self,
        source_id: str,
        device: int | str = 0,
        *,
        fallback_fps: float = _DEFAULT_LIVE_FPS,
        buffer_size: int = 1,
        resize: tuple[int, int] | None = None,
        api_preference: int | None = None,
        reconnect_attempts: int = _DEFAULT_RECONNECT_ATTEMPTS,
        reconnect_backoff_s: float = _DEFAULT_RECONNECT_BACKOFF_S,
        reconnect_backoff_max_s: float = _DEFAULT_RECONNECT_BACKOFF_MAX_S,
        open_timeout_ms: int | None = None,
        read_timeout_ms: int | None = None,
        max_stall_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Args:
            source_id: Stable identifier used in logs and health reporting.
            device: Device index for an attached camera, or an RTSP/HTTP URL.
            fallback_fps: Frame rate assumed when the device reports none.
            buffer_size: Driver-side buffer depth. Kept at 1 so the pipeline
                always analyses the most recent frame - a backlog of stale
                frames would mean the Command Center reports the past as the
                present, which is the failure mode this platform exists to
                prevent.
            resize: Optional ``(width, height)`` applied to every frame.
            api_preference: OpenCV backend constant. On Windows,
                ``cv2.CAP_DSHOW`` opens webcams considerably faster than the
                default Media Foundation backend.
            reconnect_attempts: Reconnection attempts after a dropout before the
                source is declared lost. Zero disables reconnection.
            reconnect_backoff_s: Delay before the first reconnection attempt.
            reconnect_backoff_max_s: Ceiling for the doubling backoff.
            open_timeout_ms: Network stream open timeout. See
                :class:`~surgeguard_ai.perception._capture.OpenCVCaptureSource`.
            read_timeout_ms: Network stream read timeout - what turns a phone
                that has left the network into a detected dropout instead of a
                read that blocks while the pipeline reports itself running.
            max_stall_seconds: Declare the camera lost after reads have failed
                for this long.
            clock: Monotonic time source for stall detection.
        """
        super().__init__(
            source_id=source_id,
            target=device,
            fallback_fps=fallback_fps,
            resize=resize,
            api_preference=api_preference,
            open_timeout_ms=open_timeout_ms,
            read_timeout_ms=read_timeout_ms,
            max_stall_seconds=max_stall_seconds,
            clock=clock,
        )
        self._buffer_size = buffer_size
        self._reconnect_attempts = max(reconnect_attempts, 0)
        self._reconnect_backoff_s = reconnect_backoff_s
        self._reconnect_backoff_max_s = reconnect_backoff_max_s
        self._reconnections = 0

    # -- Identity -----------------------------------------------------------

    @property
    def source_mode(self) -> SourceMode:
        return SourceMode.LIVE

    @property
    def reconnections(self) -> int:
        """How many times this source has recovered from a dropout."""
        return self._reconnections

    # -- Availability -------------------------------------------------------

    @staticmethod
    def is_available(device: int | str = 0, *, api_preference: int | None = None) -> bool:
        """Whether a camera can currently be opened and read.

        Opening alone is not proof: several backends report success for an index
        that has no device behind it and only fail on the first read. This
        therefore takes one frame and discards it.

        Args:
            device: Device index or stream URL to probe.
            api_preference: OpenCV backend constant, or ``None`` for the default.

        Returns:
            True when a frame was successfully read.
        """
        capture = (
            cv2.VideoCapture(device)
            if api_preference is None
            else cv2.VideoCapture(device, api_preference)
        )
        try:
            if not capture.isOpened():
                return False
            ok, image = capture.read()
            return bool(ok and image is not None and image.size > 0)
        finally:
            capture.release()

    @staticmethod
    def list_available_devices(
        max_index: int = 4,
        *,
        api_preference: int | None = None,
    ) -> tuple[int, ...]:
        """Probe device indices ``0..max_index`` and return those that deliver a frame.

        Intended for setup and diagnostics rather than the hot path: probing a
        camera opens and closes the device, which is slow and briefly claims it.
        """
        return tuple(
            index
            for index in range(max_index + 1)
            if LiveCameraSource.is_available(index, api_preference=api_preference)
        )

    # -- Lifecycle ----------------------------------------------------------

    def _on_opened(self, capture: cv2.VideoCapture) -> None:
        # Not honoured by every backend; harmless where unsupported.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self._buffer_size)

    def _timestamp_for(self, seq: int) -> datetime:
        """Wall-clock at grab time - a live frame is happening now."""
        return datetime.now(UTC)

    # -- Reading ------------------------------------------------------------

    def read(self) -> Frame | None:
        try:
            image = self._grab()
        except SourceUnavailableError:
            # The camera has gone. Try to get it back before telling the caller.
            if not self._reconnect():
                raise
            return None

        if image is None:
            return None
        return self._make_frame(image)

    def _reconnect(self) -> bool:
        """Attempt to reopen the camera, with a doubling backoff.

        Returns:
            True once the camera is open again, False when the attempts are
            exhausted and the source should be declared lost.
        """
        if self._reconnect_attempts == 0:
            return False

        delay = self._reconnect_backoff_s

        for attempt in range(1, self._reconnect_attempts + 1):
            self.close()
            time.sleep(delay)

            try:
                self.open()
            except SourceUnavailableError:
                logger.warning(
                    "Camera %s reconnection attempt %d/%d failed",
                    self._source_id,
                    attempt,
                    self._reconnect_attempts,
                )
                delay = min(delay * 2, self._reconnect_backoff_max_s)
                continue

            self._reconnections += 1
            logger.info(
                "Camera %s reconnected after %d attempt(s); frame sequence restarted",
                self._source_id,
                attempt,
            )
            return True

        logger.error(
            "Camera %s could not be reconnected after %d attempts",
            self._source_id,
            self._reconnect_attempts,
        )
        return False
