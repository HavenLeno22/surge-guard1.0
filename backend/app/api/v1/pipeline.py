"""AI Pipeline status endpoints.

Answer whether the platform is still watching, as distinct from what it sees.

Read-only. Starting, stopping and switching between Live Camera Mode and
Demonstration Mode are operator actions belonging to the demonstration control
surface, which is a later phase; exposing them here early would put the
pipeline's lifecycle in two places at once.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas.common import ApiResponse
from ...schemas.pipeline import PipelineStatusRead
from ..deps import PerceptionWorkerDep, SettingsDep
from ._presenters import to_pipeline_status

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get(
    "/status",
    response_model=ApiResponse[PipelineStatusRead],
    summary="Retrieve AI Pipeline status",
)
async def get_pipeline_status(
    worker: PerceptionWorkerDep,
    settings: SettingsDep,
) -> ApiResponse[PipelineStatusRead]:
    """Report what the perception pipeline is doing.

    Always returns 200, including when the pipeline is failed or disabled. A
    stopped pipeline is a fact for the caller to display, not a failed request -
    reporting it as an error would mean the one call that explains an outage
    also fails during it.
    """
    status = to_pipeline_status(worker, settings)
    return ApiResponse.ok(data=status, message="Pipeline status retrieved")
