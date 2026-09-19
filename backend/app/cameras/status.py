"""A camera's connection status, derived from what is actually happening.

The perception worker reports what it is *doing* - starting, running,
recovering. That is not the same as whether a camera is *delivering*: observed
in the field, a phone that left the network left the worker reporting RUNNING
for minutes after its last frame, because a blocked read never returned. So the
status here is judged from evidence - the age of the last frame and the frame
rate actually achieved - with the worker's state as context rather than as the
answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from surgeguard_ai.contracts import CameraConnectionStatus

from ..workers.perception_worker import PerceptionWorkerState

__all__ = ["CameraMetrics", "StatusThresholds", "derive_status"]


@dataclass(frozen=True, slots=True)
class StatusThresholds:
    """When a running camera stops counting as healthy.

    Attributes:
        stale_after_seconds: A frame older than this is late - the camera is
            degraded. Matches the platform's perception staleness threshold.
        offline_after_seconds: A frame older than this means frames have
            stopped, whatever the worker believes.
        min_fps: Below this the camera is delivering, but too slowly for
            tracking and flow counting to be trusted.
    """

    stale_after_seconds: float = 2.0
    offline_after_seconds: float = 10.0
    min_fps: float = 5.0


@dataclass(frozen=True, slots=True)
class CameraMetrics:
    """Measured figures for one camera - every one of them observed, none assumed."""

    achieved_fps: float | None = None
    source_fps: float | None = None
    native_width: int | None = None
    native_height: int | None = None
    analysis_width: int | None = None
    analysis_height: int | None = None
    frames_processed: int = 0
    frames_dropped: int = 0
    last_frame_at: datetime | None = None
    frame_age_seconds: float | None = None
    inference_ms: float | None = None
    processing_ms: float | None = None
    pipeline_latency_ms: float | None = None
    network_rtt_ms: float | None = None
    device_name: str | None = None
    battery_percent: int | None = None
    device_checked_at: datetime | None = None
    people_count: int | None = None
    tracked_count: int | None = None
    detection_active: bool = False
    tracking_active: bool = False
    reconnections: int = 0


def derive_status(
    *,
    enabled: bool,
    worker_state: PerceptionWorkerState,
    worker_detail: str | None,
    frame_age_seconds: float | None,
    achieved_fps: float | None,
    pipeline_degraded_reason: str | None,
    diagnosis_detail: str | None = None,
    thresholds: StatusThresholds | None = None,
) -> tuple[CameraConnectionStatus, str | None]:
    """Decide a camera's connection status and the operator-facing reason.

    Args:
        enabled: Whether an operator has the camera switched on.
        worker_state: What the camera's perception worker is doing.
        worker_detail: The worker's own explanation of its state.
        frame_age_seconds: Age of the most recent analysed frame, if any.
        achieved_fps: Measured throughput, if the pipeline has run.
        pipeline_degraded_reason: Why a running pipeline is degraded, if it is.
        diagnosis_detail: The latest stream diagnosis - "DroidCam is busy",
            "no response" - which explains a failure better than "could not be
            opened" and is preferred when present.
        thresholds: Staleness and frame-rate limits.
    """
    limits = thresholds or StatusThresholds()

    if not enabled:
        return CameraConnectionStatus.DISABLED, "Disabled by an operator."

    failure_detail = diagnosis_detail or worker_detail

    if worker_state is PerceptionWorkerState.DISABLED:
        return (
            CameraConnectionStatus.OFFLINE,
            "The perception pipeline is disabled on this deployment.",
        )
    if worker_state is PerceptionWorkerState.STARTING:
        return (
            CameraConnectionStatus.CONNECTING,
            "Loading the detection model and opening the stream.",
        )
    if worker_state is PerceptionWorkerState.RECOVERING:
        return CameraConnectionStatus.RECOVERING, failure_detail or "Reconnecting to the camera."
    if worker_state is PerceptionWorkerState.FAILED:
        return (
            CameraConnectionStatus.OFFLINE,
            failure_detail or "The camera could not be recovered.",
        )
    if worker_state is PerceptionWorkerState.COMPLETED:
        return (
            CameraConnectionStatus.OFFLINE,
            worker_detail or "The demonstration clip reached its end.",
        )
    if worker_state is PerceptionWorkerState.STOPPED:
        return CameraConnectionStatus.OFFLINE, worker_detail or "Not running."

    # RUNNING - judged on evidence, not on the worker's say-so.
    if frame_age_seconds is None:
        return CameraConnectionStatus.CONNECTING, "Connected; waiting for the first frame."
    if frame_age_seconds > limits.offline_after_seconds:
        return (
            CameraConnectionStatus.OFFLINE,
            f"No frame for {frame_age_seconds:.0f}s - the stream appears to have stopped.",
        )
    if frame_age_seconds > limits.stale_after_seconds:
        return CameraConnectionStatus.DEGRADED, f"Frames are late ({frame_age_seconds:.1f}s old)."
    if pipeline_degraded_reason:
        return CameraConnectionStatus.DEGRADED, pipeline_degraded_reason
    if achieved_fps is not None and 0 < achieved_fps < limits.min_fps:
        return (
            CameraConnectionStatus.DEGRADED,
            f"Running at {achieved_fps:.1f} fps - too slow to track movement reliably.",
        )
    return CameraConnectionStatus.ONLINE, None
