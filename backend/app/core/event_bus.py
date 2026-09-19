"""In-process asynchronous event bus.

The backend is a modular monolith: services are separate modules, not separate
deployables (Architecture Review, Accepted Decision A6). The event bus is what
keeps those modules from calling each other directly.

The motivating case is the analysis ingest path. When a result arrives it must
be persisted, evaluated for a Crowd Event transition, and broadcast to the
Command Center. Wiring the ingest service to all three would make it depend on
all three. Instead it publishes one event, and each concern subscribes.

**Subscriber failure is isolated.** A subscriber raising an exception must not
prevent the others from running, and must not propagate back to the publisher.
On the ingest path the publisher is the AI Pipeline, and a persistence failure
must never stop frame analysis (``04:838-849``).
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any, TypeAlias

from .logging import get_logger

__all__ = ["DomainEvent", "EventBus", "EventHandler", "get_event_bus"]

logger = get_logger(__name__)

EventHandler: TypeAlias = Callable[[Any], Awaitable[None]] | Callable[[Any], None]


class DomainEvent(StrEnum):
    """Events published within the backend.

    Names describe *what happened*, never *what should happen next* - a
    publisher that names an outcome has taken on the subscriber's job.
    """

    # -- Ingest -------------------------------------------------------------
    PERCEPTION_RECEIVED = "perception.received"
    """One frame's detections and tracks arrived from the AI Pipeline."""

    ANALYSIS_RECEIVED = "analysis.received"
    """A complete operational assessment arrived. Awaits Stages 4-7."""

    # -- Crowd Event lifecycle ---------------------------------------------
    CROWD_EVENT_OPENED = "crowd_event.opened"
    CROWD_EVENT_UPDATED = "crowd_event.updated"
    CROWD_EVENT_CLOSED = "crowd_event.closed"

    # -- Operational alerts -------------------------------------------------
    ALERT_GENERATED = "alert.generated"
    ALERT_ACKNOWLEDGED = "alert.acknowledged"

    # -- Operational intelligence -------------------------------------------
    OIR_GENERATED = "oir.generated"
    """A camera's decision service issued a report. Payload: ``IssuedReport``."""

    OPERATIONAL_STATE_CHANGED = "operational_state.changed"
    """A camera's operator workflow phase changed. Payload: ``StateChange``."""

    # -- Timeline -----------------------------------------------------------
    TIMELINE_ENTRY_ADDED = "timeline.entry_added"

    # -- Platform -----------------------------------------------------------
    CAMERA_STATUS_CHANGED = "camera.status_changed"
    COMPONENT_HEALTH_CHANGED = "component.health_changed"
    PIPELINE_STATE_CHANGED = "pipeline.state_changed"

    # -- Multi-camera ---------------------------------------------------------
    CAMERAS_CHANGED = "cameras.changed"
    """An operator added, edited or removed a camera, or redrew its zones."""

    SITE_UPDATED = "site.updated"
    """Site intelligence was recomputed across every camera."""


class EventBus:
    """Asynchronous publish/subscribe within a single process.

    Not a message broker and not a substitute for one. When SurgeGuard grows to
    multiple processes, this is the seam an external broker replaces - callers
    depend on :meth:`publish` and :meth:`subscribe`, not on the transport.
    """

    def __init__(self) -> None:
        self._subscribers: dict[DomainEvent, list[EventHandler]] = defaultdict(list)
        self._background_tasks: set[asyncio.Task[None]] = set()

    # -- Subscription -------------------------------------------------------

    def subscribe(self, event: DomainEvent, handler: EventHandler) -> None:
        """Register a handler for an event.

        Handlers may be synchronous or asynchronous. Synchronous handlers must
        not block: they run on the event loop.
        """
        self._subscribers[event].append(handler)
        logger.debug(
            "Subscribed %s to %s", getattr(handler, "__qualname__", handler), event.value
        )

    def unsubscribe(self, event: DomainEvent, handler: EventHandler) -> None:
        """Remove a handler. Removing an unregistered handler is not an error."""
        handlers = self._subscribers.get(event)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def subscriber_count(self, event: DomainEvent) -> int:
        """Number of handlers registered for an event."""
        return len(self._subscribers.get(event, ()))

    def clear(self) -> None:
        """Remove every subscription. Intended for test teardown."""
        self._subscribers.clear()

    # -- Publication --------------------------------------------------------

    async def publish(self, event: DomainEvent, payload: Any = None) -> None:
        """Publish an event and wait for every handler to finish.

        Handler exceptions are logged and swallowed: one failing subscriber must
        not prevent the others from running, nor surface to the publisher.

        Use this when the publisher can afford to wait. On latency-sensitive
        paths use :meth:`dispatch`.
        """
        handlers = tuple(self._subscribers.get(event, ()))
        if not handlers:
            return

        results = await asyncio.gather(
            *(self._invoke(handler, event, payload) for handler in handlers),
            return_exceptions=True,
        )
        for handler, result in zip(handlers, results, strict=True):
            if isinstance(result, BaseException):
                self._log_handler_failure(handler, event, result)

    def dispatch(self, event: DomainEvent, payload: Any = None) -> None:
        """Publish without waiting for handlers.

        For paths that must not block - notably analysis ingest, where the
        publisher is the AI Pipeline and any delay costs frames.

        A strong reference to each task is retained until it completes;
        otherwise the event loop may garbage-collect a running task.
        """
        if not self._subscribers.get(event):
            return

        task = asyncio.create_task(self.publish(event, payload))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def drain(self) -> None:
        """Wait for all dispatched handlers to finish.

        Used at shutdown, and in tests that need to assert on the result of a
        :meth:`dispatch`.
        """
        while self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)

    # -- Internals ----------------------------------------------------------

    @staticmethod
    async def _invoke(handler: EventHandler, event: DomainEvent, payload: Any) -> None:
        result = handler(payload)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _log_handler_failure(
        handler: EventHandler, event: DomainEvent, error: BaseException
    ) -> None:
        logger.error(
            "Event handler failed",
            exc_info=error,
            extra={
                "event": event.value,
                "handler": getattr(handler, "__qualname__", repr(handler)),
            },
        )


#: Process-wide bus. Held on the FastAPI application state and injected through
#: `app.api.deps`; this module-level instance exists so that non-request code
#: (the AI Pipeline sink, background workers) can reach the same bus.
_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """Return the process-wide event bus."""
    return _event_bus
