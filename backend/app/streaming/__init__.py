"""Live video transport.

Annotated MJPEG - Architecture Review §9.5 option A, recorded there as the
documented same-day fallback to option B (raw MJPEG plus a client-side canvas
overlay). Chosen because it needs no per-frame overlay synchronisation, so a
box can never drift a frame behind the image it describes.

The layering concern option B was preferred for is answered by *where* this
lives: drawing happens in the backend, and ``surgeguard_ai`` still produces
measurements and knows nothing about pixels leaving the building.
"""

from __future__ import annotations

from .annotator import OverlayState, annotate
from .live_stream import MJPEG_BOUNDARY, MJPEG_CONTENT_TYPE, LiveStreamService

__all__ = [
    "MJPEG_BOUNDARY",
    "MJPEG_CONTENT_TYPE",
    "LiveStreamService",
    "OverlayState",
    "annotate",
]
