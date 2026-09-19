"""Fixed platform constants.

Values here are structural - changing one changes a contract with the frontend
or the AI Pipeline. Anything an operator or deployment might legitimately vary
belongs in :mod:`app.core.config` instead.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

#: All REST routes are versioned. 09:118 and 09:294 disagree on this in the
#: source documentation; /api/v1 is the resolution (Architecture Review C14).
API_V1_PREFIX: Final[str] = "/api/v1"

#: Single WebSocket endpoint serving the Command Center.
WS_COMMAND_CENTER_PATH: Final[str] = "/ws/command-center"

# ---------------------------------------------------------------------------
# Real-time contract
# ---------------------------------------------------------------------------

#: First sequence number issued on a connection. The snapshot carries 0, so any
#: client holding seq 0 knows it has full state and nothing more.
WS_INITIAL_SEQUENCE: Final[int] = 0

#: A client that has heard nothing for this multiple of the analysis interval
#: raises the stale-data banner. A control-room display that silently freezes
#: is more dangerous than one that visibly fails (Architecture Review R9).
WS_STALE_INTERVAL_MULTIPLIER: Final[float] = 2.0

# ---------------------------------------------------------------------------
# Operational defaults
# ---------------------------------------------------------------------------

#: Identifier of the single camera in the prototype (05:1084-1086). Multi-camera
#: support is Future work; the schema already carries camera_id throughout.
DEFAULT_CAMERA_ID: Final[str] = "cam-01"

#: Operator shown in the header. The prototype opens directly into the Command
#: Center without authentication (07:429-433); role-based access remains part of
#: the production architecture.
DEFAULT_OPERATOR_NAME: Final[str] = "Control Room Operator"

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

#: A component that has not reported within this many seconds is degraded.
COMPONENT_HEARTBEAT_TIMEOUT_SECONDS: Final[float] = 10.0

#: A perception result older than this is reported as stale. At any plausible
#: analysis rate this is tens of missed frames, so it cannot be reached by
#: ordinary jitter - only by a pipeline that has actually stopped producing.
#:
#: Reported rather than hidden: a display showing a frozen crowd count without
#: saying so is more dangerous than one that visibly fails, because the operator
#: has no way to tell that what they are watching is a memory
#: (Architecture Review R9).
PERCEPTION_STALE_AFTER_SECONDS: Final[float] = 2.0
