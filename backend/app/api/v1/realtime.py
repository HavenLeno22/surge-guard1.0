"""The Command Center WebSocket endpoint.

One socket carries every live update (``09:177-198``). The Command Center never
polls (Rule 12, ``15:181-186``).

The endpoint itself stays deliberately thin: accept, snapshot, then read client
messages until disconnect. Outbound traffic is the
:class:`~app.realtime.broadcaster.Broadcaster`'s concern, not this handler's.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ...auth.dependencies import OptionalPrincipalDep
from ...core.logging import get_logger
from ...realtime.connection_manager import Connection, ConnectionManager
from ...realtime.envelope import WSClientAction, WSClientMessage
from ..deps import ConnectionManagerDep

router = APIRouter()
logger = get_logger(__name__)

#: Close code for a socket opened without a valid sign-in. In the 4000-4999
#: application range, and deliberately not a network failure code: a client that
#: receives it signs in again instead of retrying a connection that cannot succeed.
CLOSE_UNAUTHORIZED = 4401


@router.websocket("")
async def command_center_socket(
    websocket: WebSocket,
    connections: ConnectionManagerDep,
    principal: OptionalPrincipalDep,
) -> None:
    """Serve one Command Center client for the life of its connection.

    On accept the client receives a snapshot of full current state, so it is
    correct immediately rather than after the next update. Every subsequent
    message carries an incrementing sequence number; a client that sees a gap
    sends ``resync`` and receives a fresh snapshot.

    Without a valid session the socket is accepted and immediately closed with
    4401. Refusing the handshake instead would reach the browser as an anonymous
    1006, indistinguishable from the backend being down.
    """
    if principal is None:
        await websocket.accept()
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Sign in to continue.")
        return

    connection = await connections.connect(websocket, session_id=principal.session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(raw, connection, connections)
    except WebSocketDisconnect:
        logger.debug(
            "Command Center client closed the connection",
            extra={"connection_id": connection.id},
        )
    except RuntimeError as error:
        # Raised when the socket was already closed - the client disconnected
        # during the opening snapshot. Expected, not a fault.
        if "not connected" not in str(error).lower():
            raise
        logger.debug(
            "Client disconnected before the session began",
            extra={"connection_id": connection.id},
        )
    except Exception as error:  # noqa: BLE001 - one client must not affect others
        logger.warning(
            "Command Center connection failed",
            exc_info=error,
            extra={"connection_id": connection.id},
        )
    finally:
        await connections.disconnect(connection)


async def _handle_client_message(
    raw: str,
    connection: Connection,
    connections: ConnectionManager,
) -> None:
    """Process one inbound message.

    Malformed input is logged and ignored rather than closing the socket: a
    client bug should not cost the operator their live view.
    """
    try:
        message = WSClientMessage.model_validate_json(raw)
    except ValidationError:
        logger.warning(
            "Discarding malformed client message",
            extra={"connection_id": connection.id},
        )
        return

    if message.action is WSClientAction.RESYNC:
        logger.info(
            "Client requested resynchronisation",
            extra={"connection_id": connection.id, "seq": connection.next_seq},
        )
        await connections.send_snapshot(connection)

    # PONG needs no action: receiving it is itself the liveness signal.
