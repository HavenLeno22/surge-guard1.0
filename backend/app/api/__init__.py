"""HTTP and WebSocket surface.

Route handlers are thin: they validate, delegate to a service, and shape the
response (``09:305-315``). Operational logic lives in ``app.services``.
"""

from __future__ import annotations

from .errors import register_exception_handlers
from .router import api_router, websocket_router

__all__ = ["api_router", "register_exception_handlers", "websocket_router"]
