"""WebSocket connection management.

Owns the set of connected Command Center clients and the per-connection
sequence counters that let a client detect a missed message.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeAlias

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from ..core.constants import WS_INITIAL_SEQUENCE
from ..core.logging import get_logger
from .envelope import WSEnvelope, WSEventType

__all__ = ["Connection", "ConnectionManager", "SnapshotProvider"]

logger = get_logger(__name__)

#: Supplies the full current state sent as the first message on a connection.
#: Registered by the application during startup; see `ConnectionManager.
#: set_snapshot_provider`.
SnapshotProvider: TypeAlias = Callable[[], Awaitable[dict[str, Any]]]


def _is_disconnect(error: BaseException) -> bool:
    """Whether a send failure simply means the client had already gone."""
    name = type(error).__name__
    if name in {"ClientDisconnected", "WebSocketDisconnect", "ConnectionClosed"}:
        return True
    return isinstance(error, RuntimeError) and "not connected" in str(error).lower()


class Connection:
    """One connected Command Center client.

    Holds its own sequence counter: numbering is per connection, so a client
    that reconnects starts cleanly at the snapshot rather than inheriting a
    global counter it has no history for.
    """

    def __init__(
        self,
        websocket: WebSocket,
        connection_id: str | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        self.id = connection_id or str(uuid.uuid4())
        self.websocket = websocket
        self.connected_at = datetime.now(UTC)
        self.session_id = session_id
        """The sign-in session this client connected with, so signing out closes it."""

        self._seq = WS_INITIAL_SEQUENCE
        # A WebSocket frame must be written atomically. Without this lock, two
        # concurrent sends interleave and produce a corrupt frame.
        self._send_lock = asyncio.Lock()

    @property
    def next_seq(self) -> int:
        """The sequence number the next message will carry."""
        return self._seq

    @property
    def is_connected(self) -> bool:
        return self.websocket.client_state is WebSocketState.CONNECTED

    async def send(
        self,
        event_type: WSEventType,
        data: dict[str, Any],
        camera_id: str | None = None,
    ) -> None:
        """Send one message, stamping it with the next sequence number.

        Raises:
            RuntimeError: The socket is no longer connected. The caller is
                expected to drop the connection.
        """
        async with self._send_lock:
            envelope = WSEnvelope(
                type=event_type,
                seq=self._seq,
                camera_id=camera_id,
                data=data,
            )
            await self.websocket.send_text(envelope.model_dump_json())
            self._seq += 1

    async def close(self, code: int = 1000) -> None:
        """Close the socket. Safe to call on an already-closed connection."""
        if self.is_connected:
            # A socket already closing raises; that is the outcome we wanted.
            with contextlib.suppress(RuntimeError):
                await self.websocket.close(code=code)

    def __repr__(self) -> str:
        return f"<Connection id={self.id[:8]} seq={self._seq}>"


class ConnectionManager:
    """Tracks connected clients and fans messages out to them."""

    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}
        self._lock = asyncio.Lock()
        self._snapshot_provider: SnapshotProvider | None = None

    # -- Configuration ------------------------------------------------------

    def set_snapshot_provider(self, provider: SnapshotProvider) -> None:
        """Register the source of the initial state message.

        Registered during application startup. Until one is registered, clients
        receive an empty snapshot - correct for a platform with no state yet,
        and never a silent omission once there is.
        """
        self._snapshot_provider = provider

    # -- Lifecycle ----------------------------------------------------------

    async def connect(self, websocket: WebSocket, *, session_id: str | None = None) -> Connection:
        """Accept a client and send it the opening snapshot.

        The snapshot is sent before any incremental update, so a client is never
        applying deltas to state it does not have.
        """
        await websocket.accept()
        connection = Connection(websocket, session_id=session_id)

        async with self._lock:
            self._connections[connection.id] = connection

        logger.info(
            "Command Center client connected",
            extra={"connection_id": connection.id, "clients": len(self._connections)},
        )

        await self.send_snapshot(connection)
        return connection

    async def disconnect(self, connection: Connection) -> None:
        """Remove a client and close its socket. Idempotent."""
        async with self._lock:
            self._connections.pop(connection.id, None)

        await connection.close()
        logger.info(
            "Command Center client disconnected",
            extra={"connection_id": connection.id, "clients": len(self._connections)},
        )

    async def disconnect_session(self, session_id: str, code: int = 4401) -> int:
        """Close every socket opened by one sign-in session.

        Called when that session signs out or is revoked, so a console left open
        elsewhere stops receiving live data at once rather than when it next
        reconnects. Code 4401 tells the client to sign in again, not to retry.

        Returns:
            How many sockets were closed.
        """
        async with self._lock:
            matching = [
                connection
                for connection in self._connections.values()
                if connection.session_id == session_id
            ]
            for connection in matching:
                self._connections.pop(connection.id, None)

        for connection in matching:
            await connection.close(code=code)
        return len(matching)

    async def disconnect_all(self) -> None:
        """Close every connection. Called at application shutdown."""
        async with self._lock:
            connections = tuple(self._connections.values())
            self._connections.clear()

        for connection in connections:
            await connection.close(code=1001)  # going away

    # -- Sending ------------------------------------------------------------

    async def send_snapshot(self, connection: Connection) -> None:
        """Send the full current state to one client.

        Also serves resynchronisation: a client that detected a sequence gap
        asks for this rather than reconnecting.
        """
        data = await self._snapshot_provider() if self._snapshot_provider else {}
        try:
            await connection.send(WSEventType.SNAPSHOT, data)
        except Exception as error:  # noqa: BLE001 - a failed send drops the client
            # A client that goes away mid-snapshot is ordinary, not exceptional:
            # a reload, a closed tab, or React's development double-mount. It is
            # logged without a traceback so a genuine delivery fault - which
            # keeps its stack - stays visible in the noise.
            if _is_disconnect(error):
                logger.debug(
                    "Client disconnected before the snapshot was delivered",
                    extra={"connection_id": connection.id},
                )
            else:
                logger.warning(
                    "Snapshot delivery failed",
                    exc_info=error,
                    extra={"connection_id": connection.id},
                )
            await self.disconnect(connection)

    async def broadcast(
        self,
        event_type: WSEventType,
        data: dict[str, Any],
        camera_id: str | None = None,
    ) -> None:
        """Send a message to every connected client.

        Clients that fail to receive are dropped rather than retried: a socket
        that cannot be written to is gone, and holding it would stall the
        broadcast for everyone else.
        """
        async with self._lock:
            connections = tuple(self._connections.values())

        if not connections:
            return

        results = await asyncio.gather(
            *(connection.send(event_type, data, camera_id) for connection in connections),
            return_exceptions=True,
        )

        failed = [
            connection
            for connection, result in zip(connections, results, strict=True)
            if isinstance(result, BaseException)
        ]
        for connection in failed:
            logger.warning(
                "Dropping unwritable client",
                extra={"connection_id": connection.id, "event_type": event_type.value},
            )
            await self.disconnect(connection)

    # -- Observation --------------------------------------------------------

    @property
    def client_count(self) -> int:
        """Number of connected Command Center clients."""
        return len(self._connections)
