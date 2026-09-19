"""Real-time communication with the Command Center.

Owns the WebSocket contract: message envelope, connection lifecycle, sequence
numbering and broadcast. Nothing outside this package writes to a socket.
"""

from __future__ import annotations

from .broadcaster import Broadcaster
from .connection_manager import Connection, ConnectionManager, SnapshotProvider
from .envelope import WSClientAction, WSClientMessage, WSEnvelope, WSEventType

__all__ = [
    "Broadcaster",
    "Connection",
    "ConnectionManager",
    "SnapshotProvider",
    "WSClientAction",
    "WSClientMessage",
    "WSEnvelope",
    "WSEventType",
]
