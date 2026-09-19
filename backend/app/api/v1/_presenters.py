"""Conversions from runtime objects into API schemas.

Route handlers stay thin (``09:305-315``), and services stay free of HTTP. That
leaves a small amount of shaping in between - turning a detector's device record
or a pipeline's status dataclass into the schema the API publishes.

Collected here rather than repeated in each router so that two endpoints
reporting the same thing cannot drift into reporting it differently.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from surgeguard_ai.perception import DeviceInfo
from surgeguard_ai.pipeline import PipelineStatus

from ...schemas.perception import DetectionDevice, PerceptionRead
from ...schemas.pipeline import PipelineStatusRead, PipelineThroughput

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from ...core.config import Settings
    from ...services.perception_state import PerceptionStateService
    from ...workers.perception_worker import PerceptionWorker

__all__ = [
    "to_detection_device",
    "to_perception_read",
    "to_pipeline_status",
    "to_throughput",
]


def to_detection_device(
    info: DeviceInfo | None,
    *,
    uses_half_precision: bool = False,
) -> DetectionDevice | None:
    """Present the resolved compute device.

    Args:
        info: The device inference resolved to.
        uses_half_precision: Whether inference is *actually* running in FP16.
            Taken from the detector rather than inferred from the device, because
            a device that supports half precision is not the same as one using
            it - the two can be told apart only by asking what is running.

    ``fallback_reason`` is carried through rather than dropped: it is the only
    way a caller learns that a requested GPU is not the one doing the work.
    """
    if info is None:
        return None

    return DetectionDevice(
        device=info.device,
        name=info.name,
        is_cuda=info.is_cuda,
        precision="FP16" if uses_half_precision else "FP32",
        total_memory_mb=info.total_memory_mb,
        fallback_reason=info.fallback_reason,
    )


def to_throughput(status: PipelineStatus | None) -> PipelineThroughput | None:
    """Present the frame loop's measured throughput."""
    if status is None:
        return None

    return PipelineThroughput(
        frames_processed=status.frames_processed,
        frames_dropped=status.frames_dropped,
        achieved_fps=status.achieved_fps,
        last_frame_at=_parse_timestamp(status.last_frame_ts),
    )


def to_pipeline_status(
    worker: PerceptionWorker, settings: Settings
) -> PipelineStatusRead:
    """Present the perception worker's operational state.

    Used by ``GET /pipeline/status`` and by the WebSocket snapshot. Extracted
    here so those two cannot drift into describing the same pipeline
    differently - which is exactly the failure a client would hit when a
    reconnect replaced polled state with snapshot state.
    """
    pipeline_status = worker.pipeline_status

    return PipelineStatusRead(
        state=worker.state,
        detail=worker.detail,
        state_changed_at=worker.state_changed_at,
        running=bool(pipeline_status and pipeline_status.running),
        source_mode=worker.source_mode,
        source_id=pipeline_status.source_id if pipeline_status else None,
        camera_id=settings.camera_id,
        model_name=worker.model_name,
        device=to_detection_device(
            worker.device,
            uses_half_precision=worker.uses_half_precision,
        ),
        throughput=to_throughput(pipeline_status),
        degraded=bool(pipeline_status and pipeline_status.degraded),
        degraded_reason=pipeline_status.degraded_reason if pipeline_status else None,
        restart_attempts=worker.restart_attempts,
        total_restarts=worker.total_restarts,
    )


def to_perception_read(
    state: PerceptionStateService, worker: PerceptionWorker
) -> PerceptionRead | None:
    """Present the AI Pipeline's current view of the crowd, or ``None``.

    Used by ``GET /perception/latest``, by the WebSocket snapshot and by the
    realtime publisher, so all three describe one frame identically. That is not
    tidiness: the Live Camera panel reads this shape from whichever path
    delivered it, and a field present on one path and absent on another blanks
    the panel the moment the socket connects.
    """
    snapshot = state.snapshot()
    if snapshot is None:
        return None

    return PerceptionRead(
        result=snapshot.result,
        device=to_detection_device(
            worker.device,
            uses_half_precision=worker.uses_half_precision,
        ),
        received_at=snapshot.received_at,
        age_seconds=snapshot.age_seconds,
        is_stale=snapshot.is_stale,
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating absence and malformed input.

    A status endpoint must answer even when one of its inputs is unreadable;
    reporting the rest is more useful than failing the whole response.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
