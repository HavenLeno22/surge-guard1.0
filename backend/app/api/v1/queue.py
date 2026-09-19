"""Queue Intelligence endpoints.

Three read routes, deliberately separate:

- ``/queue/current``      what is happening now
- ``/queue/prediction``   what is expected to happen
- ``/recommendations``    what the operator could do

Problem Statement 9 section 15 requires those three to be clearly distinguished,
and an API that returns them in one object invites a client to render them in
one panel. Keeping them apart at the boundary is the cheapest possible way to
keep them apart on screen.

Plus two write routes - ``/counters`` and ``/zones`` - which carry operator
knowledge the platform cannot observe for itself: how many service counters
exist, which are staffed, and where the queue actually is.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...auth.dependencies import require_admin
from ...core.exceptions import NotFoundError, ServiceUnavailableError
from ...schemas.common import ApiResponse
from ...schemas.queue import (
    CounterSettingsWrite,
    CountersRead,
    QueueCurrentRead,
    QueuePredictionRead,
    RecommendationsRead,
    ZonesRead,
    ZonesWrite,
)
from ...services.zone_store import ZoneStoreError
from ..deps import QueueServiceDep

router = APIRouter(tags=["queue"])


def _require_analysis(queue: QueueServiceDep):
    """The latest analysis, or an explanation of why there isn't one.

    An error rather than a success carrying null, for the same reason
    ``/intelligence/current`` does it: "no measurement is available" and "the
    queue is empty" are opposite facts, and a caller that cannot tell them apart
    will eventually display one as the other.
    """
    if not queue.enabled:
        raise ServiceUnavailableError(
            "Queue Intelligence is not running. Either it is disabled "
            "(SURGEGUARD_QUEUE_ENABLED), or crowd analysis itself is off."
        )

    result = queue.latest
    if result is None:
        raise ServiceUnavailableError(
            "No analysis has been produced yet. The pipeline may still be "
            "starting, or no frame has reached it."
        )
    return result


@router.get(
    "/queue/current",
    response_model=ApiResponse[QueueCurrentRead],
    summary="Measured state of every configured queue",
)
async def get_queue_current(queue: QueueServiceDep) -> ApiResponse[QueueCurrentRead]:
    """Return what every configured queue is doing right now.

    Carries the headcount, the queue-versus-crowd classification with the
    measurements behind it, counted arrival and service rates, and the estimated
    wait with its stated assumptions.

    A camera with no QUEUE zone returns a report flagged ``unconfigured`` rather
    than an empty one: "no queue is configured" and "the queue is empty" are
    different facts.
    """
    result = _require_analysis(queue)
    if result.queue is None:
        raise ServiceUnavailableError(
            "Queue Intelligence produced no report for the latest frame."
        )

    return ApiResponse.ok(
        QueueCurrentRead(
            camera_id=result.camera_id,
            source_mode=result.source_mode,
            frame_ts=result.frame_ts,
            age_seconds=queue.age_seconds(result),
            queue=result.queue,
        ),
        message="Current queue measurements.",
    )


@router.get(
    "/queue/prediction",
    response_model=ApiResponse[QueuePredictionRead],
    summary="Forecast queue length at each configured horizon",
)
async def get_queue_prediction(
    queue: QueueServiceDep,
) -> ApiResponse[QueuePredictionRead]:
    """Return where each queue is expected to be at +5, +10 and +15 minutes.

    Each horizon carries a prediction interval that widens with distance, both
    forecasting methods are reported alongside the consensus, and the
    abnormal-growth assessment states whether the queue is growing faster than
    its own established baseline.
    """
    result = _require_analysis(queue)
    if result.forecast is None:
        raise ServiceUnavailableError(
            "No forecast has been produced. Forecasting needs a configured "
            "queue zone and enough observation history to project from."
        )

    return ApiResponse.ok(
        QueuePredictionRead(
            camera_id=result.camera_id,
            source_mode=result.source_mode,
            frame_ts=result.frame_ts,
            age_seconds=queue.age_seconds(result),
            forecast=result.forecast,
        ),
        message="Queue forecast.",
    )


@router.get(
    "/recommendations",
    response_model=ApiResponse[RecommendationsRead],
    summary="Counter allocation recommendations",
)
async def get_recommendations(
    queue: QueueServiceDep,
) -> ApiResponse[RecommendationsRead]:
    """Return the capacity recommendation for each queue.

    Every plan discloses current demand, current capacity, predicted demand,
    required capacity, the recommended action and its expected effect - the
    latter computed by re-running the projection at the proposed staffing level
    rather than asserted.
    """
    result = _require_analysis(queue)
    if result.resources is None:
        raise ServiceUnavailableError(
            "No resource plan has been produced. Allocation needs at least one "
            "configured queue zone."
        )

    return ApiResponse.ok(
        RecommendationsRead(
            camera_id=result.camera_id,
            source_mode=result.source_mode,
            frame_ts=result.frame_ts,
            age_seconds=queue.age_seconds(result),
            resources=result.resources,
        ),
        message="Resource allocation recommendations.",
    )


@router.get(
    "/counters",
    response_model=ApiResponse[CountersRead],
    summary="Current counter allocation",
)
async def get_counters(queue: QueueServiceDep) -> ApiResponse[CountersRead]:
    """Return how many counters each queue has and how many are open."""
    return ApiResponse.ok(
        CountersRead(counters=queue.counters()), message="Counter allocation."
    )


@router.post(
    "/counters/{zone_id}",
    response_model=ApiResponse[CountersRead],
    summary="Set the counter allocation for a queue zone",
)
async def set_counters(
    zone_id: str, body: CounterSettingsWrite, queue: QueueServiceDep
) -> ApiResponse[CountersRead]:
    """Tell the platform how many counters are open on a queue.

    Takes effect on the next analysis window, changing the effective service
    rate and therefore every wait and forecast derived from it. The *measured*
    rate then follows reality on its own, so a counter that is open but not
    serving anyone is visible rather than assumed away.
    """
    if not queue.enabled:
        raise ServiceUnavailableError("Queue Intelligence is not running.")

    if not queue.set_counters(zone_id, body):
        raise NotFoundError(
            f"No queue zone {zone_id!r} is configured on this camera."
        )

    return ApiResponse.ok(
        CountersRead(counters=queue.counters()), message="Counter allocation updated."
    )


@router.get(
    "/zones",
    response_model=ApiResponse[ZonesRead],
    summary="Retrieve the camera's zone definitions",
)
async def get_zones(queue: QueueServiceDep) -> ApiResponse[ZonesRead]:
    """Return every zone drawn on this camera."""
    try:
        zones = queue.zones()
    except ZoneStoreError as error:
        raise ServiceUnavailableError(str(error)) from error

    return ApiResponse.ok(
        ZonesRead(
            camera_id=queue.camera_id,
            zones=zones,
            requires_restart=queue.requires_restart,
        ),
        message="Camera zone definitions.",
    )


@router.post(
    "/zones",
    response_model=ApiResponse[ZonesRead],
    status_code=status.HTTP_200_OK,
    summary="Replace the camera's zone definitions",
    dependencies=[Depends(require_admin)],
)
async def replace_zones(
    body: ZonesWrite, queue: QueueServiceDep
) -> ApiResponse[ZonesRead]:
    """Replace every zone on this camera and persist the result.

    A replacement rather than a patch: partial updates invite a state where the
    stored set and the operator's mental model differ, and the operator is the
    one who has to notice.

    The response reports ``requires_restart`` when the running pipeline is still
    measuring against the previous set, so a newly drawn zone is never silently
    inert.
    """
    try:
        saved = queue.save_zones(body.zones)
    except ZoneStoreError as error:
        raise ServiceUnavailableError(str(error)) from error

    return ApiResponse.ok(
        ZonesRead(
            camera_id=queue.camera_id,
            zones=saved,
            requires_restart=queue.requires_restart,
        ),
        message=(
            "Zones saved. Restart the pipeline for them to take effect."
            if queue.requires_restart
            else "Zones saved."
        ),
    )
