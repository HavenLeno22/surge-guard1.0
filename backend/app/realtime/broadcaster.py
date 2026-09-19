"""Real-time broadcast to the Command Center.

The single outbound path for live updates. Services never touch a WebSocket:
they publish a domain event, and this module decides what reaches the operator.

That indirection is what allows a service to be tested without a socket, and
what keeps the WebSocket contract changeable without touching operational logic.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from ..core.config import Settings
from ..core.logging import get_logger
from .connection_manager import ConnectionManager
from .envelope import WSEventType

__all__ = ["Broadcaster"]

logger = get_logger(__name__)


class Broadcaster:
    """Publishes operational updates to connected clients.

    Also owns the heartbeat. Its purpose is not to keep the socket alive but to
    give the client something whose *absence* is detectable: a Command Center
    that has heard nothing for longer than expected raises the stale-data
    banner rather than continuing to present frozen values as current.
    """

    def __init__(self, connections: ConnectionManager, settings: Settings) -> None:
        self._connections = connections
        self._settings = settings
        self._heartbeat_task: asyncio.Task[None] | None = None

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Begin the heartbeat loop."""
        if self._heartbeat_task is not None:
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(
            "Broadcaster started",
            extra={"heartbeat_seconds": self._settings.ws_heartbeat_seconds},
        )

    async def stop(self) -> None:
        """Stop the heartbeat and close every client connection."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        await self._connections.disconnect_all()
        logger.info("Broadcaster stopped")

    # -- Publication --------------------------------------------------------

    async def publish(
        self,
        event_type: WSEventType,
        data: dict[str, Any],
        camera_id: str | None = None,
    ) -> None:
        """Send an update to every connected client."""
        await self._connections.broadcast(event_type, data, camera_id)

    @property
    def client_count(self) -> int:
        return self._connections.client_count

    # -- Internals ----------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Emit a heartbeat at the configured interval until cancelled."""
        interval = self._settings.ws_heartbeat_seconds
        while True:
            try:
                await asyncio.sleep(interval)
                if self._connections.client_count:
                    await self.publish(
                        WSEventType.HEARTBEAT,
                        {"clients": self._connections.client_count},
                    )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the heartbeat must not die
                logger.error("Heartbeat iteration failed", exc_info=error)
