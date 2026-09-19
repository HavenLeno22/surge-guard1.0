"""Camera management API schemas.

A camera is presented as three things side by side, kept separate on purpose:

- **configuration** - name, role, coverage, stream address and where that
  address came from;
- **status** - whether it is delivering frames right now, and if not, why;
- **metrics** - what was measured: frame rate, resolution, latency, battery.

None of the metrics is ever filled in for a camera that has not measured it. A
camera that is offline reports no frame rate rather than a frame rate of zero.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import CameraConnectionStatus, CameraRole, SourceMode

from ..cameras.definitions import CameraOrigin, UrlSource
from ..cameras.probe import StreamOutcome
from ..workers.perception_worker import PerceptionWorkerState

__all__ = [
    "CameraMetricsRead",
    "CameraRead",
    "CamerasRead",
    "ConnectionTestRead",
    "ConnectionTestWrite",
]


class CameraMetricsRead(BaseModel):
    """What was measured for one camera. ``None`` means not measured."""

    model_config = ConfigDict(extra="forbid")

    achieved_fps: float | None = Field(default=None, description="Frames analysed per second.")
    source_fps: float | None = Field(default=None, description="Rate the stream declares.")
    native_width: int | None = Field(default=None, description="Resolution the camera sends.")
    native_height: int | None = None
    analysis_width: int | None = Field(default=None, description="Resolution analysis runs at.")
    analysis_height: int | None = None
    frames_processed: int = 0
    frames_dropped: int = 0
    last_frame_at: datetime | None = None
    frame_age_seconds: float | None = None
    inference_ms: float | None = Field(default=None, description="Detector time, latest frame.")
    processing_ms: float | None = Field(default=None, description="Detection plus tracking.")
    pipeline_latency_ms: float | None = Field(
        default=None, description="From frame capture to perception complete."
    )
    network_rtt_ms: float | None = Field(
        default=None, description="Round trip to the device's own endpoint, not the stream."
    )
    device_name: str | None = None
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    device_checked_at: datetime | None = None
    people_count: int | None = Field(
        default=None, description="Latest count. None whenever the camera is not contributing."
    )
    tracked_count: int | None = None
    detection_active: bool = False
    tracking_active: bool = False
    reconnections: int = 0


class CameraRead(BaseModel):
    """One camera: configuration, status and measurements."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    display_id: str = Field(description="The id as operators read it, e.g. CAM-02.")
    name: str
    location: str
    role: CameraRole
    coverage_area: str
    enabled: bool
    is_primary: bool = Field(
        description="The camera the single-camera routes describe. Cannot be removed."
    )
    origin: CameraOrigin
    order: int

    stream_url: str | None = Field(
        default=None, description="Stream address, with any password masked."
    )
    url_source: UrlSource
    demo_video_path: str | None = None
    source_mode: SourceMode

    status: CameraConnectionStatus
    status_detail: str | None = None
    status_since: datetime
    worker_state: PerceptionWorkerState
    diagnosis: StreamOutcome | None = Field(
        default=None, description="Latest diagnosis of why the stream is not delivering."
    )

    zone_count: int = 0
    queue_zone_count: int = 0
    metrics: CameraMetricsRead


class CamerasRead(BaseModel):
    """Every camera, with the site-wide counts an operator reads first."""

    model_config = ConfigDict(extra="forbid")

    cameras: list[CameraRead]
    total: int
    enabled: int
    contributing: int = Field(description="Cameras delivering analysable frames now.")
    registry_error: str | None = Field(
        default=None,
        description=(
            "Why the camera registry file could not be read. While set, edits are "
            "refused rather than risk overwriting it."
        ),
    )


class ConnectionTestWrite(BaseModel):
    """A stream address to test."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(
        min_length=1,
        max_length=512,
        description="A URL, a device index, or a DroidCam IP and port.",
    )
    camera_id: str | None = Field(
        default=None, description="The camera this address is being tested for, if any."
    )


class ConnectionTestRead(BaseModel):
    """What a connection test found."""

    model_config = ConfigDict(extra="forbid")

    url: str
    success: bool
    outcome: StreamOutcome
    detail: str
    tested_at: datetime
    duration_seconds: float
    width: int | None = None
    height: int | None = None
    reported_fps: float | None = None
    measured_fps: float | None = None
    first_frame_ms: float | None = None
    frames_read: int = 0
    failed_reads: int = 0
    network_rtt_ms: float | None = None
    device_name: str | None = None
    battery_percent: int | None = None
    live_measurement: bool = Field(
        default=False,
        description=(
            "True when the figures come from SurgeGuard's own connection to the "
            "camera, because opening a second one would have stolen its stream."
        ),
    )
