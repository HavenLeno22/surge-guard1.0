"""Serving the built frontend with client-side routing.

The Command Center's socket, video streams and cookies all assume one origin.
Serving the built interface from the API process makes that true in production
without a reverse proxy: open the backend's address and the product is there.

Any path the interface owns (``/command-center``, ``/cameras/cam-02``) falls back
to ``index.html`` so a reload or a shared link works. Paths the API owns are
never answered with the page: an unknown ``/api/...`` route stays a JSON 404 in
the documented envelope.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Message, Receive, Scope, Send

from ..core.logging import get_logger

__all__ = ["SinglePageApp", "mount_frontend"]

logger = get_logger(__name__)

#: Prefixes the API owns. Never shadowed by the interface.
RESERVED_PREFIXES: tuple[str, ...] = ("/api", "/ws", "/docs", "/redoc", "/openapi.json")

#: Build output under this directory carries content hashes in its file names.
_HASHED_ASSETS = "/assets/"


def _envelope(status_code: int, message: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": message, "error_code": error_code, "data": None},
    )


class SinglePageApp:
    """Static files with an ``index.html`` fallback for client routes."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._index = directory / "index.html"
        self._static = StaticFiles(directory=directory, check_dir=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        path: str = scope.get("path", "/")

        if path.startswith(RESERVED_PREFIXES):
            await _envelope(404, "Not Found", "NOT_FOUND")(scope, receive, send)
            return
        if scope.get("method") not in ("GET", "HEAD"):
            await _envelope(405, "Method Not Allowed", "METHOD_NOT_ALLOWED")(scope, receive, send)
            return

        try:
            await self._static(scope, receive, _with_cache_headers(path, send))
        except HTTPException as error:
            if error.status_code != 404 or path.startswith(_HASHED_ASSETS):
                raise
            # A client-side route. The page decides what it shows; it must never be
            # cached, or a deploy would leave browsers on an old build.
            await FileResponse(self._index, headers={"Cache-Control": "no-cache"})(
                scope, receive, send
            )


def _with_cache_headers(path: str, send: Send) -> Send:
    """Long-lived caching for content-hashed assets, revalidation for everything else."""
    cache = (
        "public, max-age=31536000, immutable" if path.startswith(_HASHED_ASSETS) else "no-cache"
    )

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            headers.append((b"cache-control", cache.encode("latin-1")))
            message = {**message, "headers": headers}
        await send(message)

    return wrapped


def mount_frontend(app: FastAPI, directory: Path) -> bool:
    """Serve ``directory`` at the site root when it holds a build. Returns whether it did."""
    if not (directory / "index.html").is_file():
        logger.info(
            "No built frontend found; serving the API only",
            extra={"frontend_dist_dir": str(directory)},
        )
        return False
    # Mounted last, so every API and socket route is matched before it.
    app.mount("/", SinglePageApp(directory), name="frontend")
    logger.info("Serving the built frontend", extra={"frontend_dist_dir": str(directory)})
    return True
