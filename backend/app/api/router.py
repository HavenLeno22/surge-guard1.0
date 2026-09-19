"""API router assembly.

One place where every route is mounted, so the complete surface is readable in
a single file - including who may call it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.dependencies import require_operator
from ..core.constants import API_V1_PREFIX, WS_COMMAND_CENTER_PATH
from .v1 import (
    auth,
    camera,
    cameras,
    decisions,
    global_intel,
    hardware,
    history,
    intelligence,
    operations,
    perception,
    pipeline,
    queue,
    realtime,
    simulation,
    system,
    users,
)

__all__ = ["api_router", "websocket_router"]

#: Every operational route needs a signed-in operator. Routes that change how the
#: platform is set up additionally require an administrator, declared on the route
#: itself so the requirement sits beside the handler it guards.
_OPERATOR = [Depends(require_operator)]

#: REST routes. Versioned so future versions can be added alongside rather than
#: replacing (``09:288-296``).
api_router = APIRouter(prefix=API_V1_PREFIX)

# Public by design: sign-in itself, and liveness/readiness probes (guarded
# per-route inside `system`, which also serves the protected health panel).
api_router.include_router(auth.router)
api_router.include_router(system.router)

api_router.include_router(users.router)
api_router.include_router(perception.router, dependencies=_OPERATOR)
api_router.include_router(pipeline.router, dependencies=_OPERATOR)
api_router.include_router(intelligence.router, dependencies=_OPERATOR)
api_router.include_router(decisions.router, dependencies=_OPERATOR)
api_router.include_router(camera.router, dependencies=_OPERATOR)
api_router.include_router(cameras.router, dependencies=_OPERATOR)
api_router.include_router(operations.router, dependencies=_OPERATOR)
api_router.include_router(global_intel.router, dependencies=_OPERATOR)
api_router.include_router(history.router, dependencies=_OPERATOR)
api_router.include_router(queue.router, dependencies=_OPERATOR)
api_router.include_router(simulation.router, dependencies=_OPERATOR)
api_router.include_router(hardware.router, dependencies=_OPERATOR)

#: WebSocket routes. Kept separate from REST (``09:74-78``): they are a
#: different protocol with a different contract, and mixing them makes neither
#: clearer. The socket authenticates inside its handler, so it can close with a
#: code the client understands.
websocket_router = APIRouter()
websocket_router.include_router(realtime.router, prefix=WS_COMMAND_CENTER_PATH)
