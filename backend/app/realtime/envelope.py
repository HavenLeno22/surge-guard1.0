"""The WebSocket message contract.

``15:181-186`` mandates WebSockets for live updates, and ``04:834-840`` requires
that interrupted communication be cached and resynchronised. The source
documentation defines no message format, so this module supplies one
(``00_Architecture_Review.md`` §9.8).

Three properties matter, and each exists to prevent a specific failure:

- **``seq``** - a monotonic per-connection counter. A client that sees a gap
  knows it has missed a message and can resynchronise instead of silently
  diverging from the true state.
- **``snapshot``** - the first message on any connection carries full current
  state, so a client that connects late or reconnects is immediately correct
  rather than waiting for the next update.
- **``ts``** - lets the client detect staleness. A control-room display that
  silently freezes is more dangerous than one that visibly fails: the operator
  trusts frozen numbers (Architecture Review R9).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["WSEventType", "WSEnvelope", "WSClientMessage", "WSClientAction"]


class WSEventType(StrEnum):
    """Server-to-client message types (``09:177-198``)."""

    # -- Connection lifecycle ----------------------------------------------
    SNAPSHOT = "snapshot"
    """Full current state. Always the first message on a connection."""

    HEARTBEAT = "heartbeat"
    """Liveness ping. Its absence is what the client's staleness check detects."""

    # -- Operational updates ------------------------------------------------
    CSI_UPDATED = "csi.updated"
    DETECTIONS_UPDATED = "detections.updated"
    CROWD_EVENT_CREATED = "event.created"
    CROWD_EVENT_UPDATED = "event.updated"
    ALERT_CREATED = "alert.created"
    OIR_UPDATED = "oir.updated"
    STATE_UPDATED = "state.updated"
    """A camera's Operational State changed. Data: ``{camera_id, operational_state, actor}``."""
    TIMELINE_APPENDED = "timeline.appended"

    # -- Platform updates ---------------------------------------------------
    CAMERA_STATUS = "camera.status"
    HEALTH_UPDATED = "health.updated"
    DEMO_STATE = "demo.state"

    # -- Multi-camera -------------------------------------------------------
    CAMERA_ANALYSIS = "camera.analysis"
    """One camera's latest assessment and queue intelligence, tagged by camera."""

    CAMERAS_CHANGED = "cameras.changed"
    """The camera set or a camera's configuration changed."""

    SITE_UPDATED = "site.updated"
    """Site intelligence across every camera."""


class WSEnvelope(BaseModel):
    """A single server-to-client message.

    Every message on the socket uses this shape, so a client has one parser and
    one place to check sequence continuity.
    """

    model_config = ConfigDict(extra="forbid")

    type: WSEventType
    seq: int = Field(
        ge=0,
        description=(
            "Monotonic per connection, starting at 0 for the snapshot. A gap "
            "means a message was missed and the client should resynchronise."
        ),
    )
    ts: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Server send time. The client uses this to detect staleness.",
    )
    camera_id: str | None = Field(
        default=None,
        description=(
            "Camera this message concerns; null for platform-wide messages. "
            "Present from the outset so multi-camera clients can filter without "
            "a protocol change."
        ),
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Message payload. Shape is determined by `type`.",
    )


class WSClientAction(StrEnum):
    """Client-to-server message types.

    Deliberately minimal. Operator actions go through REST, where they are
    validated, persisted and auditable; the socket carries only connection
    management.
    """

    RESYNC = "resync"
    """Request a fresh snapshot, after the client detected a sequence gap."""

    PONG = "pong"
    """Response to a heartbeat."""


class WSClientMessage(BaseModel):
    """A single client-to-server message."""

    model_config = ConfigDict(extra="forbid")

    action: WSClientAction
    data: dict[str, Any] = Field(default_factory=dict)
