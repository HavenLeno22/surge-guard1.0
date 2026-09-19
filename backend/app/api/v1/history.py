"""Stored history - what each camera and the site measured, over days.

Answers from aggregated buckets, never frames. A range with nothing recorded
returns an empty series rather than zeroes: an unrecorded hour and an empty one
are different facts.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from starlette.requests import HTTPConnection
from surgeguard_ai.contracts import SourceMode

from ...core.config import normalise_camera_id
from ...core.exceptions import ServiceUnavailableError, ValidationError
from ...models.history import SITE_HISTORY_ID
from ...schemas.common import ApiResponse
from ...schemas.history import HistorySeriesRead, HistorySummaryRead
from ...services.history_query import HistoryQuery

router = APIRouter(prefix="/history", tags=["history"])

_FROM = Query(default=None, alias="from", description="Range start (ISO 8601). Default 24 h ago.")
_TO = Query(default=None, alias="to", description="Range end (ISO 8601). Default now.")
_RESOLUTION = Query(
    default=None,
    ge=1,
    le=86_400,
    description="Seconds per point. Rounded up to whole buckets and to at most 720 points.",
)
_MODE = Query(
    default=None,
    description="LIVE or DEMO. Defaults to this deployment's mode; the two are never mixed.",
)


def _query(connection: HTTPConnection) -> HistoryQuery:
    query = getattr(connection.app.state, "history_query", None)
    if not isinstance(query, HistoryQuery):
        raise ServiceUnavailableError("History is not available yet.")
    return query


@router.get(
    "/cameras/{camera_id}",
    response_model=ApiResponse[HistorySeriesRead],
    summary="One camera's history over a range",
)
async def get_camera_history(
    camera_id: str,
    connection: HTTPConnection,
    start: datetime | None = _FROM,
    end: datetime | None = _TO,
    resolution: int | None = _RESOLUTION,
    source_mode: SourceMode | None = _MODE,
) -> ApiResponse[HistorySeriesRead]:
    try:
        resolved_id = normalise_camera_id(camera_id)
    except ValueError as error:
        raise ValidationError(str(error)) from error
    series = await _query(connection).series(
        resolved_id,
        start=start,
        end=end,
        resolution_seconds=resolution,
        source_mode=source_mode,
    )
    return ApiResponse.ok(series, message="Camera history retrieved.")


@router.get(
    "/site",
    response_model=ApiResponse[HistorySeriesRead],
    summary="The whole site's history over a range",
)
async def get_site_history(
    connection: HTTPConnection,
    start: datetime | None = _FROM,
    end: datetime | None = _TO,
    resolution: int | None = _RESOLUTION,
    source_mode: SourceMode | None = _MODE,
) -> ApiResponse[HistorySeriesRead]:
    series = await _query(connection).series(
        SITE_HISTORY_ID,
        start=start,
        end=end,
        resolution_seconds=resolution,
        source_mode=source_mode,
    )
    return ApiResponse.ok(series, message="Site history retrieved.")


@router.get(
    "/summary",
    response_model=ApiResponse[HistorySummaryRead],
    summary="What every camera and the site recorded over a range",
)
async def get_history_summary(
    connection: HTTPConnection,
    start: datetime | None = _FROM,
    end: datetime | None = _TO,
    source_mode: SourceMode | None = _MODE,
) -> ApiResponse[HistorySummaryRead]:
    summary = await _query(connection).summary(start=start, end=end, source_mode=source_mode)
    return ApiResponse.ok(summary, message="History summary retrieved.")
