"""Operational decision endpoints.

Expose the platform's guidance, the revision series behind it, and the
operational timeline.

**These are a fallback, not the primary path.** Live updates reach the Command
Center over the WebSocket (Rule 12, ``15:181-186``); REST exists so a client can
recover state when the socket is unavailable, and so the surface remains
scriptable and testable without one. That is why every route here answers the
same question the socket answers, in the same shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...core.exceptions import ServiceUnavailableError
from ...schemas.common import ApiResponse
from ...schemas.decision import DecisionHistoryRead, DecisionRead
from ...schemas.timeline import TimelineRead
from ..deps import DecisionServiceDep, TimelineServiceDep

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get(
    "/current",
    response_model=ApiResponse[DecisionRead],
    summary="Retrieve the current operational guidance",
)
async def get_current_decision(decisions: DecisionServiceDep) -> ApiResponse[DecisionRead]:
    """Return the platform's current Operational Intelligence Report.

    Raises:
        ServiceUnavailableError: No report has been produced yet - because the
            Operational Decision Engine is disabled, because no assessment has
            arrived, or because nothing has yet warranted guidance. An error
            rather than a success carrying null, for the same reason the
            assessment endpoint does it: "no guidance available" and "no action
            required" are different answers, and a caller that cannot tell them
            apart will eventually display one as the other.
    """
    snapshot = decisions.snapshot()
    if snapshot is None:
        raise ServiceUnavailableError(
            "No operational guidance has been produced yet.",
            context={"operational_state": decisions.operational_state.value},
        )

    return ApiResponse.ok(
        data=DecisionRead(
            report=snapshot.report,
            operational_state=decisions.operational_state,
            received_at=snapshot.received_at,
            age_seconds=snapshot.age_seconds,
            is_stale=snapshot.is_stale,
        ),
        message="Current operational guidance retrieved",
    )


@router.get(
    "/history",
    response_model=ApiResponse[DecisionHistoryRead],
    summary="Retrieve the report revision series",
)
async def get_decision_history(
    decisions: DecisionServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[DecisionHistoryRead]:
    """Return the reports issued this session, newest first."""
    reports = decisions.history(limit=limit)
    return ApiResponse.ok(
        data=DecisionHistoryRead(reports=list(reports), total=len(reports)),
        message="Decision history retrieved",
    )


@router.get(
    "/timeline",
    response_model=ApiResponse[TimelineRead],
    summary="Retrieve the Crowd Event Timeline",
)
async def get_timeline(
    timeline: TimelineServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[TimelineRead]:
    """Return the session's operational history, newest first.

    Always answerable. An empty timeline is a fact, not a failure - a caller
    should not have to catch an error to learn that nothing has happened yet.
    """
    entries = timeline.entries(limit=limit)
    return ApiResponse.ok(
        data=TimelineRead(
            entries=list(entries),
            total=timeline.total,
            latest_sequence=timeline.latest_sequence,
        ),
        message="Timeline retrieved",
    )
