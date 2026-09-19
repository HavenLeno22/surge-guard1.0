"""Crowd intelligence endpoints.

Expose the Crowd Stability Index, the Operational Status derived from it,
Decision Confidence, and the observations that explain them.

A read surface over live state, not history - with one deliberate exception.
``/evidence/history`` is history, because an observation's *onset* is
operationally meaningful in a way a frame's is not: knowing that movement
started slowing four minutes ago is a different and more useful fact than
knowing it is slow now.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...core.exceptions import ServiceUnavailableError
from ...schemas.common import ApiResponse
from ...schemas.intelligence import (
    CrowdIntelligenceRead,
    CrowdSummary,
    EvidenceHistoryRead,
)
from ..deps import CrowdIntelligenceDep, PerceptionWorkerDep

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get(
    "/current",
    response_model=ApiResponse[CrowdIntelligenceRead],
    summary="Retrieve the current crowd assessment",
)
async def get_current_intelligence(
    intelligence: CrowdIntelligenceDep,
    worker: PerceptionWorkerDep,
) -> ApiResponse[CrowdIntelligenceRead]:
    """Return the platform's current assessment of the crowd.

    Carries the Crowd Stability Index raw and smoothed, the Operational Status
    after hysteresis, the per-indicator breakdown that produced the index,
    Decision Confidence with its limiting factor, the prioritised evidence
    explaining it, and how old the whole thing is.

    Raises:
        ServiceUnavailableError: No assessment has been produced yet - because
            crowd analysis is disabled, because the pipeline has not yet
            delivered a frame, or because every window so far has failed.
            Deliberately an error rather than a success carrying null, for the
            same reason ``/perception/latest`` does it: "no assessment is
            available" and "the crowd is perfectly stable" are opposite facts,
            and a caller that cannot distinguish them will eventually display
            one as the other.
    """
    snapshot = intelligence.snapshot()
    if snapshot is None:
        raise ServiceUnavailableError(
            _unavailable_message(intelligence.enabled),
            context={
                "csi_enabled": intelligence.enabled,
                "worker_state": worker.state.value,
                "analysis_failures": intelligence.failures,
                "last_error": intelligence.last_error,
            },
        )

    result = snapshot.result

    return ApiResponse.ok(
        data=CrowdIntelligenceRead(
            camera_id=result.camera_id,
            source_mode=result.source_mode,
            frame_seq=result.frame_seq,
            stability=result.stability,
            evidence=result.evidence,
            crowd=CrowdSummary.from_crowd(result.crowd),
            received_at=snapshot.received_at,
            age_seconds=snapshot.age_seconds,
            is_stale=snapshot.is_stale,
            degraded=result.degraded,
            degraded_reason=result.degraded_reason,
        ),
        message="Current crowd assessment retrieved",
    )


@router.get(
    "/evidence/history",
    response_model=ApiResponse[EvidenceHistoryRead],
    summary="Retrieve observations recorded this session",
)
async def get_evidence_history(
    intelligence: CrowdIntelligenceDep,
) -> ApiResponse[EvidenceHistoryRead]:
    """Return the observations recorded since analysis started or was reset.

    Always answerable, including before the first assessment - an empty history
    is a fact, not a failure, and a caller should not have to catch an error to
    learn that nothing has happened yet.
    """
    items = intelligence.evidence_history()
    return ApiResponse.ok(
        data=EvidenceHistoryRead(
            items=list(items),
            total=len(items),
            analysed=intelligence.analysed,
        ),
        message="Evidence history retrieved",
    )


def _unavailable_message(enabled: bool) -> str:
    """Say which kind of "not available" this is.

    A disabled analyser and a starting one call for different operator
    responses, and one message covering both would tell them apart for nobody.
    """
    if not enabled:
        return "Crowd analysis is disabled on this deployment."
    return "Crowd analysis has not produced an assessment yet."
