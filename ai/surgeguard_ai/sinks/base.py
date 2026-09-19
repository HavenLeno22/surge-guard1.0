"""The AnalysisSink boundary - where AI results leave the pipeline.

This is the outward half of the pair of abstractions that bound the AI Pipeline
(:class:`~surgeguard_ai.perception.frame_source.FrameSource` is the inward half).

``07:99-103`` requires the AI Pipeline and the Backend to remain independent
systems communicating through structured data. This interface is that boundary.
The pipeline emits :class:`~surgeguard_ai.contracts.analysis.AnalysisResult` and
knows nothing about what receives it.

Concrete sinks live in the **consuming application**, never here, so the
dependency direction is always ``backend -> surgeguard_ai``:

- ``InProcessSink`` (``backend/app/ingest/``) - calls the backend service layer
  directly. Used for the prototype: identical modularity, none of the cost of a
  distributed system.
- ``HttpSink`` - posts to a backend endpoint. A later swap, requiring no change
  to any pipeline code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.analysis import AnalysisResult
from ..contracts.perception import PerceptionResult

__all__ = ["AnalysisSink", "PerceptionSink"]


class AnalysisSink(ABC):
    """Receives analysis results from the AI Pipeline.

    **A sink must never block the pipeline.** Frame analysis is real-time work;
    persistence and broadcast are not. An implementation that writes
    synchronously to a database will stall video analysis whenever the database
    is slow - which is exactly the coupling ``04:826-830`` requires to be
    avoided by queueing. Implementations should hand off and return.

    Sink failure must likewise never stop processing. The pipeline logs and
    continues (``04:838-849``).
    """

    @abstractmethod
    async def emit(self, result: AnalysisResult) -> None:
        """Accept one analysis result.

        Should return promptly. Any durable work belongs on a queue.

        Args:
            result: The complete analysis of one frame.

        Raises:
            SinkError: Delivery failed. The caller logs and continues.
        """

    async def open(self) -> None:  # noqa: B027 - optional hook, not required
        """Prepare the sink. Called once before the first :meth:`emit`.

        Concrete but empty by design: a stateless sink should not be forced to
        implement a no-op.
        """

    async def close(self) -> None:  # noqa: B027 - optional hook, not required
        """Flush and release resources. Must be idempotent.

        Concrete but empty by design, as with :meth:`open`.
        """


class PerceptionSink(ABC):
    """Receives perception results from the AI Pipeline.

    The same boundary as :class:`AnalysisSink`, one stage earlier. Perception
    (Stages 1-3) is implemented and produces
    :class:`~surgeguard_ai.contracts.perception.PerceptionResult`; crowd
    analysis, stability assessment and decision intelligence (Stages 4-7) are
    not, so no :class:`~surgeguard_ai.contracts.analysis.AnalysisResult` exists
    to emit yet.

    Both interfaces are permanent rather than one superseding the other. A
    consumer that needs raw detections and tracks - a detection overlay, a
    recording tool, a diagnostic - wants perception output and should not be
    made to wait for an operational assessment it will discard.

    The same constraints apply as for :class:`AnalysisSink`: **a sink must never
    block the pipeline, and a sink failure must never stop it.** The caller is
    the frame loop, and any delay here costs frames.
    """

    @abstractmethod
    async def emit(self, result: PerceptionResult) -> None:
        """Accept one perception result.

        Should return promptly. Any durable work belongs on a queue.

        Args:
            result: Detections, tracks and timings for one frame.

        Raises:
            SinkError: Delivery failed. The caller logs and continues.
        """

    async def open(self) -> None:  # noqa: B027 - optional hook, not required
        """Prepare the sink. Called once before the first :meth:`emit`."""

    async def close(self) -> None:  # noqa: B027 - optional hook, not required
        """Flush and release resources. Must be idempotent."""
