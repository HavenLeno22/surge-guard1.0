"""Perception endpoints.

Expose what the AI Pipeline is currently seeing. Detections and tracks only -
there is no crowd assessment behind these routes yet, and none is implied.

These are a read surface over live state, not history. Every response describes
one frame, and the next frame supersedes it.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...core.exceptions import ServiceUnavailableError
from ...schemas.common import ApiResponse
from ...schemas.perception import PerceptionIngestStatus, PerceptionRead
from ..deps import PerceptionStateDep, PerceptionWorkerDep
from ._presenters import to_perception_read

router = APIRouter(prefix="/perception", tags=["perception"])


@router.get(
    "/latest",
    response_model=ApiResponse[PerceptionRead],
    summary="Retrieve the most recent perception result",
)
async def get_latest_perception(
    state: PerceptionStateDep,
    worker: PerceptionWorkerDep,
) -> ApiResponse[PerceptionRead]:
    """Return the AI Pipeline's most recent view of the crowd.

    Carries the frame number and timestamp, the person count, track identities,
    bounding boxes, confidences and timings, together with the device that
    produced them and how old the result is.

    Raises:
        ServiceUnavailableError: No result has been produced yet. Deliberately
            an error rather than a success carrying null: "AI analysis is not
            available" and "the analysis found nobody" are different facts, and
            a caller that cannot distinguish them will eventually display one as
            the other. The status maps to the documented degraded interface
            state (``06:1099-1105``).
    """
    read = to_perception_read(state, worker)
    if read is None:
        raise ServiceUnavailableError(
            "AI analysis has not produced a result yet.",
            context={
                "worker_state": worker.state.value,
                "worker_detail": worker.detail,
            },
        )

    return ApiResponse.ok(data=read, message="Latest perception result retrieved")


@router.get(
    "/status",
    response_model=ApiResponse[PerceptionIngestStatus],
    summary="Retrieve perception ingest status",
)
async def get_perception_status(
    state: PerceptionStateDep,
) -> ApiResponse[PerceptionIngestStatus]:
    """Report whether perception data is arriving.

    Always answerable, including before the first frame - which is what lets a
    caller decide whether to ask for the latest result at all, rather than
    discovering the answer through an error.
    """
    status = PerceptionIngestStatus(
        has_result=state.has_result,
        is_stale=state.is_stale(),
        received=state.received,
        degraded_received=state.degraded_received,
        first_received_at=state.first_received_at,
        last_received_at=state.received_at,
        age_seconds=state.age_seconds(),
    )
    return ApiResponse.ok(data=status, message="Perception status retrieved")
