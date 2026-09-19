"""Frame acquisition - Stage 1 of the AI Pipeline (``05:281-311``).

This module defines the boundary that makes Live Camera Mode and Demonstration
Mode interchangeable **without any change to the AI Pipeline**.

The pipeline consumes a :class:`FrameSource`. It does not know, and must never
ask, whether frames arrive from a camera or a file. ``source_mode`` is carried
through to the analysis result as a tag - for the Live/Demo indicator and for
keeping demonstration records separable from live records (Rule 7) - and is
never used as a behavioural switch.

    LiveCameraSource ─┐                              ┌─ InProcessSink
                      ├─→ [ AI PIPELINE ] ──────────→┤
    VideoFileSource ──┘    knows neither end         └─ HttpSink
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType

import numpy as np
from numpy.typing import NDArray

from ..contracts.enums import SourceMode

__all__ = ["Frame", "FrameSource"]


@dataclass(frozen=True, slots=True)
class Frame:
    """A single video frame.

    Deliberately **not** a Pydantic contract: it carries a raw image buffer and
    never crosses a process boundary. Contracts are for serializable data.

    Attributes:
        seq: Monotonic frame counter, starting at 0 for each source session.
            Reset whenever the source is reopened. The Command Center uses this
            to align overlay boxes with the correct rendered video frame.
        ts: Frame timestamp. Wall-clock for live sources. For recordings this is
            *paced* - derived from the session start plus ``seq / fps`` - so
            that every temporal calculation downstream (walking speed, rate of
            change, smoothing windows, hysteresis counters) behaves identically
            in both modes.
        image: Decoded frame as an OpenCV BGR array of shape ``(H, W, 3)``.
        source_id: Identifier of the originating source, for logging.
    """

    seq: int
    ts: datetime
    image: NDArray[np.uint8]
    source_id: str

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


class FrameSource(ABC):
    """Supplies video frames to the AI Pipeline.

    Implementations are responsible for connection handling and, for finite
    sources, for pacing frames to real time. They are *not* responsible for any
    form of analysis.

    Lifecycle::

        source = VideoFileSource(...)
        with source:                     # open() / close()
            while True:
                frame = source.read()
                if frame is None:        # transient gap - keep going
                    continue
                ...                      # SourceEnded terminates the loop

    A ``None`` return means a recoverable gap in an otherwise healthy source.
    Exhaustion raises :class:`~surgeguard_ai.errors.SourceEnded`; an unusable
    source raises :class:`~surgeguard_ai.errors.SourceUnavailableError`.
    """

    # -- Identity -----------------------------------------------------------

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Stable identifier for this source, used in logs and health reporting."""

    @property
    @abstractmethod
    def source_mode(self) -> SourceMode:
        """Whether this source is a live camera or a demonstration recording.

        Propagated to the analysis result as provenance metadata only.
        """

    @property
    @abstractmethod
    def fps(self) -> float:
        """Frames per second this source delivers.

        Used to derive paced timestamps and to size temporal analysis windows.
        """

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Whether the source is currently open and readable."""

    # -- Lifecycle ----------------------------------------------------------

    @abstractmethod
    def open(self) -> None:
        """Open the source and prepare it for reading.

        Raises:
            SourceUnavailableError: The source cannot be opened.
        """

    @abstractmethod
    def read(self) -> Frame | None:
        """Return the next frame.

        Returns:
            The next :class:`Frame`, or ``None`` for a recoverable gap - a
            dropped packet or a momentarily unavailable camera. Callers should
            continue rather than treating ``None`` as failure.

        Raises:
            SourceEnded: The source is exhausted. Normal termination for a
                finite source; a live camera never raises this.
            SourceUnavailableError: The source has been lost and cannot
                currently be read.
        """

    @abstractmethod
    def close(self) -> None:
        """Release the source and any underlying resources.

        Must be idempotent: closing an already-closed source is not an error.
        """

    # -- Context manager ----------------------------------------------------

    def __enter__(self) -> FrameSource:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(source_id={self.source_id!r}, "
            f"mode={self.source_mode.value}, open={self.is_open})"
        )
