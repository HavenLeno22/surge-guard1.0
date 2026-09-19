"""The backend's implementation of the AI Pipeline's PerceptionSink.

The inbound half of the boundary described in ``00_Architecture_Review.md`` §9.5.
``07:99-103`` requires the AI Pipeline and the Backend to remain independent
systems communicating through structured data; this is where that structured
data arrives.

Note the dependency direction: this module imports from ``surgeguard_ai``, and
``surgeguard_ai`` imports nothing from here. The pipeline is handed a sink and
never learns what kind it is - swapping in an ``HttpSink`` to move the pipeline
onto its own host would change no pipeline code.

**This module contains no operational logic.** It records what arrived and
announces it. Crowd analysis, the Crowd Stability Index, Crowd Event lifecycle
and alerting are all downstream concerns; keeping them out of here is what stops
the primary data path from depending on every eventual consumer of its output.
"""

from __future__ import annotations

from surgeguard_ai.contracts import PerceptionResult
from surgeguard_ai.sinks import PerceptionSink

from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from ..services.perception_state import PerceptionStateService

__all__ = ["InProcessPerceptionSink"]

logger = get_logger(__name__)


class InProcessPerceptionSink(PerceptionSink):
    """Accepts perception results and makes them available to the backend.

    Two things happen per result, in this order:

    1. **The current state is updated**, synchronously. This is one assignment
       and a few counters, and doing it inline rather than through a subscriber
       is deliberate: a fire-and-forget subscriber would leave a window in which
       a frame had been ingested but ``GET /perception/latest`` still reported
       nothing. Application state is the ingest boundary's own record of what it
       received, not a consumer of it.

    2. **A domain event is dispatched**, without waiting. Everything that is a
       genuine consumer - persistence, Crowd Event evaluation, the Command
       Center broadcast - subscribes to that event. Dispatching rather than
       publishing is what keeps a slow subscriber from stalling video analysis
       (``04:826-830``).

    **This must not block and must not raise.** The caller is the pipeline's
    frame loop. A backend problem is a logged backend problem, never a reason to
    stop analysing frames (``04:838-849``).
    """

    def __init__(self, state: PerceptionStateService, event_bus: EventBus) -> None:
        self._state = state
        self._event_bus = event_bus
        self._failures = 0

    @property
    def received(self) -> int:
        """Results accepted since startup, for health reporting."""
        return self._state.received

    @property
    def failures(self) -> int:
        """Results that could not be recorded. Non-zero means a backend defect."""
        return self._failures

    async def emit(self, result: PerceptionResult) -> None:
        """Accept one perception result and return immediately."""
        try:
            self._state.record(result)
        except Exception as error:  # noqa: BLE001 - never propagate into the pipeline
            self._failures += 1
            logger.error(
                "Failed to record perception result",
                exc_info=error,
                extra=self._context(result),
            )
            # Deliberately continues to the dispatch below. A failure to store
            # the current view is no reason to also withhold the result from
            # subscribers that may not care about it.

        try:
            self._event_bus.dispatch(DomainEvent.PERCEPTION_RECEIVED, result)
        except Exception as error:  # noqa: BLE001 - never propagate into the pipeline
            self._failures += 1
            logger.error(
                "Failed to dispatch perception result",
                exc_info=error,
                extra=self._context(result),
            )

    async def open(self) -> None:
        logger.info("Perception ingest opened")

    async def close(self) -> None:
        logger.info(
            "Perception ingest closed",
            extra={"results_received": self.received, "failures": self._failures},
        )

    @staticmethod
    def _context(result: PerceptionResult) -> dict[str, object]:
        """Structured log context identifying the frame that failed."""
        return {
            "camera_id": result.camera_id,
            "source_mode": result.source_mode.value,
            "frame_seq": result.frame_seq,
        }
