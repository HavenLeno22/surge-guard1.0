"""Person detection - Stage 2 of the AI Pipeline (``05:315-347``).

Interface only. The concrete detector is Phase 2 work.

Every downstream module depends on these detections, so the interface is kept
deliberately narrow: a detector takes a frame and returns people. It performs no
tracking, no counting, and no interpretation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

from ..contracts.perception import DetectionResult
from .frame_source import Frame

__all__ = ["Detector"]


class Detector(ABC):
    """Detects every visible person in a frame.

    Implementations must:

    - Return only people. Non-human objects are ignored (``05:335``).
    - Report a confidence per detection, so that Decision Confidence can
      reflect detection quality rather than asserting a number.
    - Be safe to call repeatedly from a single pipeline thread. Implementations
      are not required to be thread-safe.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable model identifier, recorded in logs and health output."""

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """Whether the model is loaded and able to serve inference."""

    @abstractmethod
    def load(self) -> None:
        """Load model weights and warm up.

        Called once before the first :meth:`detect`. Warm-up matters: the first
        inference on a cold GPU is far slower than steady state, and measuring
        the performance budget against a cold call would be misleading.

        Raises:
            DetectionError: The model could not be loaded.
        """

    @abstractmethod
    def detect(self, frame: Frame) -> DetectionResult:
        """Detect people in one frame.

        Args:
            frame: The frame to analyse.

        Returns:
            Detections for this frame, carrying ``frame.seq`` so the Command
            Center can align overlay boxes with the correct rendered frame.

        Raises:
            DetectionError: Inference failed for this frame.
        """

    def unload(self) -> None:  # noqa: B027 - optional hook, not required
        """Release model resources. Idempotent; safe to call when not loaded.

        Concrete but empty by design: a detector holding no releasable resources
        should not be forced to implement a no-op.
        """

    # -- Context manager ----------------------------------------------------

    def __enter__(self) -> Detector:
        self.load()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.unload()
