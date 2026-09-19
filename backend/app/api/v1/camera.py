"""Live camera video.

The one endpoint that returns pixels rather than JSON. Everything else the
Command Center shows arrives over the WebSocket; video is a long-lived HTTP
response instead, because a browser can render an MJPEG stream directly in an
``<img>`` with no client-side decoding, buffering or frame scheduling.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from ...core.exceptions import ServiceUnavailableError
from ...schemas.common import ApiResponse
from ...streaming import MJPEG_CONTENT_TYPE
from ...workers.perception_worker import PerceptionWorkerState
from ..deps import LiveStreamDep, PerceptionWorkerDep

router = APIRouter(prefix="/camera", tags=["camera"])

#: Worker states in which frames are arriving, or are expected to shortly.
#:
#: ``STARTING`` and ``RECOVERING`` are included so a viewer that opens during
#: model warmup or a camera reconnection holds the stream open and sees frames
#: appear, rather than being refused and having to retry.
_STREAMING_STATES = frozenset(
    {
        PerceptionWorkerState.RUNNING,
        PerceptionWorkerState.STARTING,
        PerceptionWorkerState.RECOVERING,
    }
)


def _is_streaming(state: PerceptionWorkerState) -> bool:
    """Whether opening a stream now could produce frames."""
    return state in _STREAMING_STATES


@router.get(
    "/stream",
    summary="Stream the annotated camera feed",
    responses={
        200: {"content": {MJPEG_CONTENT_TYPE: {}}, "description": "MJPEG stream"},
        503: {"description": "The AI Pipeline has not produced a frame yet"},
    },
)
async def stream_camera(
    stream: LiveStreamDep,
    worker: PerceptionWorkerDep,
) -> StreamingResponse:
    """Serve the live feed with operational overlays burned in.

    Held open until the client disconnects; each part supersedes the last, so a
    viewer always sees the current view of the crowd rather than a backlog.

    Raises:
        ServiceUnavailableError: The pipeline is not running. Deliberately an
            error rather than an empty stream: a browser given a stream that
            never produces a frame shows a broken image with no explanation,
            while a failed request lets the interface say what is wrong.
    """
    if not _is_streaming(worker.state):
        raise ServiceUnavailableError(
            "The AI Pipeline is not running, so there is no video to stream.",
            context={"worker_state": worker.state.value, "worker_detail": worker.detail},
        )

    return StreamingResponse(
        stream.stream(),
        media_type=MJPEG_CONTENT_TYPE,
        headers={
            # A frame is current only at the instant it is sent. Any cache
            # between here and the operator would serve a stale crowd.
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Connection": "close",
        },
    )


@router.get(
    "/stream/status",
    status_code=status.HTTP_200_OK,
    summary="Whether the video stream has anything to serve",
)
async def stream_status(
    stream: LiveStreamDep,
    worker: PerceptionWorkerDep,
) -> ApiResponse[dict[str, object]]:
    """Report whether a stream would produce frames.

    Always answerable, so the interface can decide whether to open a stream at
    all rather than discovering the answer through a broken image.
    """
    return ApiResponse.ok(
        data={
            "available": _is_streaming(worker.state),
            "has_frame": stream.has_frame,
            "viewers": stream.viewers,
            "worker_state": worker.state.value,
        },
        message="Stream status retrieved",
    )
