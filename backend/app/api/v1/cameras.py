"""Camera management endpoints - the Camera Network.

Every camera is addressed the same way, by id. The primary camera is not a
special case here; the single-camera routes elsewhere (``/camera/stream``,
``/perception/latest``, ``/queue/current``) simply continue to describe it.

Operator changes take effect immediately: an added camera starts connecting, a
changed address reconnects in place, redrawn zones are measured from the next
frame. None of them needs a restart.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response, StreamingResponse

from ...auth.dependencies import require_admin
from ...cameras.definitions import CameraChanges, CameraSpec
from ...cameras.registry import (
    CameraConflictError,
    CameraNotFoundError,
    CameraRegistryError,
)
from ...cameras.runtime import CameraRuntime
from ...core.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from ...schemas.cameras import (
    CameraRead,
    CamerasRead,
    ConnectionTestRead,
    ConnectionTestWrite,
)
from ...schemas.common import ApiResponse
from ...schemas.intelligence import CrowdSummary
from ...schemas.queue import CounterSettingsWrite, CountersRead, ZonesRead, ZonesWrite
from ...services.queue_service import zone_from_write
from ...services.zone_store import ZoneStoreError
from ...streaming import MJPEG_CONTENT_TYPE
from ...streaming.annotator import parse_layers
from ...workers.perception_worker import PerceptionWorkerState
from ..deps import CameraManagerDep
from ._camera_presenters import to_camera_read, to_connection_test_read

router = APIRouter(prefix="/cameras", tags=["cameras"])

#: Changing which cameras exist, where they point and what their zones are is
#: set-up work for an administrator. Watching, retrying and testing are not.
_ADMIN = [Depends(require_admin)]

#: Worker states in which a stream viewer may be held open waiting for frames.
_STREAMING_STATES = frozenset(
    {
        PerceptionWorkerState.RUNNING,
        PerceptionWorkerState.STARTING,
        PerceptionWorkerState.RECOVERING,
    }
)


def _runtime(manager: CameraManagerDep, camera_id: str) -> CameraRuntime:
    runtime = manager.get(camera_id)
    if runtime is None:
        raise NotFoundError(f"No camera {camera_id!r} is configured.")
    return runtime


def _translate(error: Exception) -> Exception:
    """Map a camera-layer failure to the API's documented error responses."""
    if isinstance(error, CameraNotFoundError):
        return NotFoundError(str(error))
    if isinstance(error, CameraConflictError):
        return ConflictError(str(error))
    if isinstance(error, CameraRegistryError):
        return ServiceUnavailableError(str(error))
    if isinstance(error, ValueError):
        return ValidationError(str(error))
    return error


# -- The camera set -----------------------------------------------------------


@router.get("", response_model=ApiResponse[CamerasRead], summary="List every camera")
async def list_cameras(manager: CameraManagerDep) -> ApiResponse[CamerasRead]:
    """Every camera with its status and measurements, in display order."""
    reads = [to_camera_read(runtime) for runtime in manager.runtimes()]
    return ApiResponse.ok(
        CamerasRead(
            cameras=reads,
            total=len(reads),
            enabled=sum(1 for read in reads if read.enabled),
            contributing=sum(1 for read in reads if read.status.is_contributing),
            registry_error=manager.registry.load_error,
        ),
        message="Cameras retrieved.",
    )


@router.post(
    "",
    response_model=ApiResponse[CameraRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a camera",
    dependencies=_ADMIN,
)
async def add_camera(body: CameraSpec, manager: CameraManagerDep) -> ApiResponse[CameraRead]:
    """Add a camera and start connecting to it immediately."""
    try:
        runtime = await manager.add_camera(body)
    except (CameraRegistryError, ValueError) as error:
        raise _translate(error) from error
    return ApiResponse.ok(
        to_camera_read(runtime),
        message=f"{runtime.definition.display_id} added. Connecting now.",
    )


@router.post(
    "/test-connection",
    response_model=ApiResponse[ConnectionTestRead],
    summary="Test a stream address",
)
async def test_connection(
    body: ConnectionTestWrite, manager: CameraManagerDep
) -> ApiResponse[ConnectionTestRead]:
    """Open an address briefly and report what it delivers.

    An address a running camera already owns is answered from that camera's
    live measurements, never by opening a second client: DroidCam serves one
    client per phone, and the test would steal the stream it was testing.
    """
    try:
        result = await manager.test_connection(body.url, camera_id=body.camera_id)
    except ValueError as error:
        raise _translate(error) from error
    return ApiResponse.ok(
        to_connection_test_read(result),
        message="Connection succeeded." if result.success else "Connection failed.",
    )


# -- One camera ------------------------------------------------------------------


@router.get("/{camera_id}", response_model=ApiResponse[CameraRead], summary="Retrieve one camera")
async def get_camera(camera_id: str, manager: CameraManagerDep) -> ApiResponse[CameraRead]:
    return ApiResponse.ok(to_camera_read(_runtime(manager, camera_id)), message="Camera retrieved.")


@router.get(
    "/{camera_id}/status",
    response_model=ApiResponse[CameraRead],
    summary="Retrieve one camera's live status and measurements",
)
async def get_camera_status(camera_id: str, manager: CameraManagerDep) -> ApiResponse[CameraRead]:
    return ApiResponse.ok(
        to_camera_read(_runtime(manager, camera_id)), message="Camera status retrieved."
    )


@router.patch(
    "/{camera_id}",
    response_model=ApiResponse[CameraRead],
    summary="Edit a camera",
    dependencies=_ADMIN,
)
async def update_camera(
    camera_id: str, body: CameraChanges, manager: CameraManagerDep
) -> ApiResponse[CameraRead]:
    """Apply an edit. A changed address reconnects the camera in place."""
    try:
        runtime = await manager.update_camera(camera_id, body)
    except (CameraRegistryError, ValueError) as error:
        raise _translate(error) from error
    return ApiResponse.ok(
        to_camera_read(runtime), message=f"{runtime.definition.display_id} updated."
    )


@router.delete(
    "/{camera_id}",
    response_model=ApiResponse[None],
    summary="Remove a camera",
    dependencies=_ADMIN,
)
async def remove_camera(camera_id: str, manager: CameraManagerDep) -> ApiResponse[None]:
    """Stop and remove a camera. The primary camera can be disabled, not removed."""
    try:
        await manager.remove_camera(camera_id)
    except (CameraRegistryError, ValueError) as error:
        raise _translate(error) from error
    return ApiResponse.ok(None, message=f"{camera_id.upper()} removed.")


@router.post(
    "/{camera_id}/test-connection",
    response_model=ApiResponse[ConnectionTestRead],
    summary="Test one camera's configured stream address",
)
async def test_camera_connection(
    camera_id: str, manager: CameraManagerDep
) -> ApiResponse[ConnectionTestRead]:
    runtime = _runtime(manager, camera_id)
    url = runtime.definition.stream_url
    if not url:
        raise ValidationError(f"{runtime.definition.display_id} has no stream address to test.")
    result = await manager.test_connection(url, camera_id=runtime.camera_id)
    return ApiResponse.ok(
        to_connection_test_read(result),
        message="Connection succeeded." if result.success else "Connection failed.",
    )


@router.post(
    "/{camera_id}/retry",
    response_model=ApiResponse[CameraRead],
    summary="Reconnect a camera now instead of waiting out its backoff",
)
async def retry_camera(camera_id: str, manager: CameraManagerDep) -> ApiResponse[CameraRead]:
    try:
        runtime = await manager.retry(camera_id)
    except CameraRegistryError as error:
        raise _translate(error) from error
    return ApiResponse.ok(to_camera_read(runtime), message="Reconnection requested.")


# -- Per-camera analytics ---------------------------------------------------------


@router.get("/{camera_id}/analytics", summary="One camera's latest crowd and queue analysis")
async def get_camera_analytics(camera_id: str, manager: CameraManagerDep) -> ApiResponse[dict]:
    """The latest analysis for one camera.

    Raises 503 rather than returning zeroes when nothing has been analysed: an
    offline camera and an empty room are different facts.
    """
    runtime = _runtime(manager, camera_id)
    snapshot = runtime.intelligence.snapshot()
    if snapshot is None:
        raise ServiceUnavailableError(
            f"{runtime.definition.display_id} has not produced an analysis yet.",
            context={"camera_id": runtime.camera_id, "worker_state": runtime.worker.state.value},
        )

    result = snapshot.result
    return ApiResponse.ok(
        {
            "camera_id": result.camera_id,
            "source_mode": result.source_mode.value,
            "frame_seq": result.frame_seq,
            "frame_ts": result.frame_ts.isoformat(),
            "received_at": snapshot.received_at.isoformat(),
            "age_seconds": snapshot.age_seconds,
            "is_stale": snapshot.is_stale,
            "crowd": CrowdSummary.from_crowd(result.crowd).model_dump(mode="json"),
            "stability": result.stability.model_dump(mode="json"),
            "evidence": result.evidence.model_dump(mode="json") if result.evidence else None,
            "queue": result.queue.model_dump(mode="json") if result.queue else None,
            "forecast": result.forecast.model_dump(mode="json") if result.forecast else None,
            "resources": result.resources.model_dump(mode="json") if result.resources else None,
            "zone_flow": result.zone_flow.model_dump(mode="json") if result.zone_flow else None,
            "degraded": result.degraded,
            "degraded_reason": result.degraded_reason,
        },
        message="Camera analysis retrieved.",
    )


# -- Video ---------------------------------------------------------------------------


@router.get(
    "/{camera_id}/stream",
    summary="Stream one camera's annotated feed",
    responses={
        200: {"content": {MJPEG_CONTENT_TYPE: {}}, "description": "MJPEG stream"},
        503: {"description": "The camera is not running"},
    },
)
async def stream_camera(
    camera_id: str,
    manager: CameraManagerDep,
    layers: str | None = Query(
        default=None,
        description="Comma-separated overlays: zones, tracks, trails, flow, heatmap, hud.",
    ),
) -> StreamingResponse:
    runtime = _runtime(manager, camera_id)
    if not runtime.definition.enabled or runtime.worker.state not in _STREAMING_STATES:
        raise ServiceUnavailableError(
            f"{runtime.definition.display_id} is not running, so there is no video to stream.",
            context={"camera_id": runtime.camera_id, "worker_state": runtime.worker.state.value},
        )
    return StreamingResponse(
        runtime.live_stream.stream(parse_layers(layers)),
        media_type=MJPEG_CONTENT_TYPE,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Connection": "close",
        },
    )


@router.get(
    "/{camera_id}/snapshot",
    summary="One annotated frame from a camera",
    responses={
        200: {"content": {"image/jpeg": {}}, "description": "A single JPEG frame"},
        503: {"description": "The camera is not running or delivered no frame in time"},
    },
)
async def camera_snapshot(
    camera_id: str,
    manager: CameraManagerDep,
    layers: str | None = Query(
        default=None,
        description="Comma-separated overlays; an empty value gives a clean picture.",
    ),
) -> Response:
    """A single fresh frame, for thumbnails that must not hold a connection open."""
    runtime = _runtime(manager, camera_id)
    if not runtime.definition.enabled or runtime.worker.state not in _STREAMING_STATES:
        raise ServiceUnavailableError(
            f"{runtime.definition.display_id} is not running, so there is no picture to show.",
            context={"camera_id": runtime.camera_id, "worker_state": runtime.worker.state.value},
        )
    payload = await runtime.live_stream.snapshot(parse_layers(layers))
    if payload is None:
        raise ServiceUnavailableError(
            f"{runtime.definition.display_id} did not deliver a frame in time.",
            context={"camera_id": runtime.camera_id},
        )
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


# -- Zones and counters ------------------------------------------------------------


@router.get("/{camera_id}/zones", response_model=ApiResponse[ZonesRead], summary="A camera's zones")
async def get_camera_zones(camera_id: str, manager: CameraManagerDep) -> ApiResponse[ZonesRead]:
    runtime = _runtime(manager, camera_id)
    try:
        zones = runtime.queue_service.zones()
    except ZoneStoreError as error:
        raise ServiceUnavailableError(str(error)) from error
    return ApiResponse.ok(
        ZonesRead(camera_id=runtime.camera_id, zones=zones, requires_restart=False),
        message="Camera zone definitions.",
    )


@router.put(
    "/{camera_id}/zones",
    response_model=ApiResponse[ZonesRead],
    summary="Replace a camera's zones and apply them immediately",
    dependencies=_ADMIN,
)
async def replace_camera_zones(
    camera_id: str, body: ZonesWrite, manager: CameraManagerDep
) -> ApiResponse[ZonesRead]:
    """Replace every zone on one camera. Measured from the next frame, no restart."""
    runtime = _runtime(manager, camera_id)
    try:
        manager.save_zones(runtime.camera_id, (zone_from_write(zone) for zone in body.zones))
        zones = runtime.queue_service.zones()
    except ZoneStoreError as error:
        raise ServiceUnavailableError(str(error)) from error
    return ApiResponse.ok(
        ZonesRead(camera_id=runtime.camera_id, zones=zones, requires_restart=False),
        message="Zones saved and applied.",
    )


@router.get(
    "/{camera_id}/counters",
    response_model=ApiResponse[CountersRead],
    summary="A camera's counter allocation",
)
async def get_camera_counters(
    camera_id: str, manager: CameraManagerDep
) -> ApiResponse[CountersRead]:
    runtime = _runtime(manager, camera_id)
    return ApiResponse.ok(
        CountersRead(counters=runtime.queue_service.counters()), message="Counter allocation."
    )


@router.post(
    "/{camera_id}/counters/{zone_id}",
    response_model=ApiResponse[CountersRead],
    summary="Set the counters for one of a camera's queue zones",
)
async def set_camera_counters(
    camera_id: str, zone_id: str, body: CounterSettingsWrite, manager: CameraManagerDep
) -> ApiResponse[CountersRead]:
    runtime = _runtime(manager, camera_id)
    if not runtime.queue_service.enabled:
        raise ServiceUnavailableError("Queue Intelligence is not running.")
    if not runtime.queue_service.set_counters(zone_id, body):
        raise NotFoundError(
            f"No queue zone {zone_id!r} is configured on {runtime.definition.display_id}."
        )
    return ApiResponse.ok(
        CountersRead(counters=runtime.queue_service.counters()),
        message="Counter allocation updated.",
    )
