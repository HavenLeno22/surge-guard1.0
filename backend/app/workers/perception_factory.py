"""Construction of the AI Pipeline from backend configuration.

Separated from the worker so that *what to build* and *keeping it running* are
different jobs. The worker supervises; this decides which frame source, which
model and which thresholds a given deployment gets.

This is the only module in the backend that knows the AI Pipeline's constructors.
Everything else works through :class:`~surgeguard_ai.pipeline.PerceptionPipeline`
and :class:`~surgeguard_ai.sinks.PerceptionSink`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
from surgeguard_ai.contracts import CameraConfig, SourceMode
from surgeguard_ai.evidence import EvidenceConfig, RuleEvidenceEngine
from surgeguard_ai.forecast import ForecastConfig, QueueForecaster
from surgeguard_ai.intelligence import DecisionConfig, DeterministicDecisionEngine
from surgeguard_ai.perception import (
    ByteTrackTracker,
    FrameSource,
    LiveCameraSource,
    VideoFileSource,
    YoloDetector,
)
from surgeguard_ai.pipeline import AnalysisPipeline, PerceptionPipeline
from surgeguard_ai.pipeline.perception_pipeline import FrameHandler
from surgeguard_ai.queue import CounterSettings, QueueAnalysisConfig, QueueAnalyzer
from surgeguard_ai.resources import AllocationConfig, ResourceAllocator
from surgeguard_ai.sinks import PerceptionSink
from surgeguard_ai.stability import (
    ConfidenceConfig,
    CsiConfig,
    IndicatorWeights,
    NormalizationCurve,
    WeightedStabilityAssessor,
)
from surgeguard_ai.zones import ZoneTransitionTracker

from ..cameras.definitions import CameraDefinition
from ..core.config import Settings
from ..core.exceptions import ConfigurationError
from ..core.logging import get_logger
from ..services.zone_store import ZoneStore, ZoneStoreError

__all__ = [
    "build_allocation_config",
    "build_analysis_pipeline",
    "build_camera_config",
    "build_crowd_analysis_config",
    "build_csi_config",
    "build_decision_config",
    "build_detector",
    "build_evidence_config",
    "build_forecast_config",
    "build_frame_source",
    "build_pipeline",
    "build_queue_analysis_config",
    "build_queue_analyzer",
    "build_tracker",
    "build_zone_store",
]

logger = get_logger(__name__)

#: Downloaded model weights live beside the other runtime data rather than in
#: whatever directory the server happened to be started from.
_WEIGHTS_SUBDIRECTORY = "models"

#: In-place reconnection attempts for a network camera before the worker's
#: supervised recovery takes over. See :func:`_live_source`.
_NETWORK_RECONNECT_ATTEMPTS = 1


def build_zone_store(settings: Settings, camera_id: str | None = None) -> ZoneStore:
    """The zone store for one camera - the primary camera unless another is named."""
    return ZoneStore(settings.zones_dir, camera_id or settings.camera_id)


def build_camera_config(
    settings: Settings,
    zones: ZoneStore | None = None,
    *,
    definition: CameraDefinition | None = None,
) -> CameraConfig:
    """Describe the camera being watched.

    Calibration is absent: the prototype has no ground-plane homography, so
    tracking reports image-space positions only and the contract's ground-space
    fields stay unset rather than carrying pixels labelled as metres
    (Architecture Review C21).

    Zones come from the zone store, which an operator writes by drawing them.
    A camera with none defined is an ordinary state - Queue Intelligence then
    reports itself unconfigured rather than reporting an empty queue.

    Args:
        settings: Configuration.
        zones: The camera's zone store, when the caller already holds it.
        definition: The camera to describe. Omitted, the primary camera from
            settings is described, as it always was.
    """
    camera_id = definition.camera_id if definition is not None else settings.camera_id
    store = zones if zones is not None else build_zone_store(settings, camera_id)

    try:
        defined = store.zones
    except ZoneStoreError as error:
        # A malformed zone file must not stop the platform starting: the crowd
        # spine does not depend on zones, and a control room with a broken zone
        # definition is better served by a running system that says so.
        logger.error(
            "Could not load camera zones; continuing without them: %s", error
        )
        defined = ()

    if definition is not None:
        return CameraConfig(
            camera_id=definition.camera_id,
            name=definition.name,
            location=definition.location,
            zones=defined,
        )
    return CameraConfig(
        camera_id=settings.camera_id,
        name=settings.camera_name,
        location=settings.camera_location,
        zones=defined,
    )


def build_frame_source(
    settings: Settings, *, definition: CameraDefinition | None = None
) -> FrameSource:
    """Construct the frame source for the configured mode.

    **This function is the whole of Live/Demo switching.** Everything downstream
    is identical in both modes: the pipeline never learns which kind of source it
    was handed, and ``source_mode`` reaches the backend as provenance on the
    result rather than as a behavioural switch (Rule 7, ``02`` §2).

    A fresh source is built for every start and every recovery attempt, because
    a finished clip is at its end and a lost camera needs reopening.

    Args:
        settings: Configuration, including the Live/Demo mode.
        definition: The camera to build a source for. Omitted, the primary
            camera's settings are used exactly as before multi-camera support.

    Raises:
        ConfigurationError: Demonstration Mode is selected with no usable clip,
            or a camera has no stream address to open.
    """
    resize = settings.detection_size

    if settings.pipeline_source_mode is SourceMode.DEMO:
        path = (
            _require_demo_video(settings)
            if definition is None
            else _require_camera_demo_video(settings, definition)
        )
        return VideoFileSource(
            source_id=path.stem,
            path=path,
            realtime_pacing=True,
            loop=settings.demo_video_loop,
            resize=resize,
        )

    if definition is None:
        return _live_source(settings, settings.live_camera_device)

    if not definition.stream_url:
        raise ConfigurationError(
            f"{definition.display_id} has no stream address. Add one on the Camera "
            "Network page, or declare it in .env.",
            context={"camera_id": definition.camera_id},
        )
    return _live_source(settings, definition.stream_url)


def _live_source(settings: Settings, device_setting: str) -> LiveCameraSource:
    """A live camera source, with network timeouts wherever the device is a URL.

    A device index is opened exactly as before: the timeouts are an FFmpeg
    facility, and forcing that backend onto a local webcam would break it.

    A network camera also gets a single in-place reconnection attempt rather
    than the source's default run of retries. A brief Wi-Fi blip is still
    absorbed, but a phone that has gone away is handed to the worker's
    supervised recovery within seconds instead of after half a minute of silent
    retries - and only supervised recovery reports why the camera is down,
    diagnoses the stream, and answers "Reconnect now".
    """
    device = _as_camera_device(device_setting)
    network: dict[str, Any] = {}
    if isinstance(device, str) and "://" in device:
        network = {
            "open_timeout_ms": int(settings.live_camera_open_timeout_seconds * 1000),
            "read_timeout_ms": int(settings.live_camera_read_timeout_seconds * 1000),
            "max_stall_seconds": settings.live_camera_stall_seconds,
            "reconnect_attempts": _NETWORK_RECONNECT_ATTEMPTS,
        }
    return LiveCameraSource(
        source_id=f"camera-{device_setting}",
        device=device,
        fallback_fps=settings.live_camera_fallback_fps,
        resize=settings.detection_size,
        **network,
    )


def build_detector(settings: Settings) -> YoloDetector:
    """Construct the person detector.

    ``warmup_shape`` is supplied because the frame size is known from
    configuration. Warming up at the shape the pipeline will actually deliver
    means the seconds of one-time GPU initialisation are spent before the source
    starts, rather than during monitoring while a paced clip runs on without us.
    """
    width, height = settings.detection_size

    return YoloDetector(
        model=settings.detection_model,
        weights_dir=settings.data_dir / _WEIGHTS_SUBDIRECTORY,
        device=settings.detection_device,
        confidence=settings.detection_confidence_threshold,
        image_size=settings.detection_image_size,
        warmup_shape=(height, width),
    )


def build_tracker(settings: Settings, frame_rate: float) -> ByteTrackTracker:
    """Construct the person tracker.

    Args:
        settings: Configuration.
        frame_rate: The source's declared frame rate, used to convert the
            lost-track timeout from seconds into frames. A source whose true
            rate differs from its declared one shifts that window
            proportionally, which is immaterial: the timeout is a judgement
            about how long somebody may be hidden, not a precise quantity.
    """
    return ByteTrackTracker(
        frame_rate=frame_rate,
        lost_track_timeout_s=settings.tracker_lost_track_timeout_seconds,
    )


def build_pipeline(
    settings: Settings,
    sink: PerceptionSink,
    *,
    detector: YoloDetector,
    tracker: ByteTrackTracker,
    on_frame: FrameHandler | None = None,
    camera: CameraConfig | None = None,
) -> PerceptionPipeline:
    """Assemble the perception pipeline, wired to the backend's sink.

    The detector and tracker are passed in rather than built here so the caller
    keeps a reference to them - the detector is the only thing that knows which
    compute device inference actually landed on, and the platform is required to
    report that rather than assume it.

    Built once and kept for the life of the process. Recovery replaces the frame
    source rather than the pipeline: rebuilding would reload the model and move
    inference to a new thread, both of which cost seconds
    (``04_AI_Walking_Skeleton.md`` A9).
    """
    return PerceptionPipeline(
        camera if camera is not None else build_camera_config(settings),
        detector,
        tracker,
        on_result=sink.emit,
        on_frame=on_frame,
    )


def build_crowd_analysis_config(settings: Settings) -> CrowdAnalysisConfig:
    """Describe how the crowd is measured.

    The frame size is taken from the detector's configured input size, because
    that is the resolution tracking actually ran at and therefore the space the
    density grid has to be laid over. Deriving it rather than configuring it
    separately removes a way for the two to disagree silently, which would
    misplace every person in the grid.
    """
    width, height = settings.detection_size
    return CrowdAnalysisConfig(
        frame_width=width,
        frame_height=height,
        grid_rows=settings.crowd_grid_rows,
        grid_cols=settings.crowd_grid_cols,
    )


def build_csi_config(settings: Settings) -> CsiConfig:
    """Assemble the Crowd Stability Index configuration from settings.

    Weights come from configuration rather than the engine's own defaults, so
    that a deployment tuning them changes an environment variable and not a
    line of Python (``16:142-168``).
    """
    return CsiConfig(
        weights=IndicatorWeights(
            density_pressure=settings.csi_weight_density,
            motion_suppression=settings.csi_weight_motion,
            egress_congestion=settings.csi_weight_egress,
            flow_conflict=settings.csi_weight_flow,
            rate_of_change=settings.csi_weight_rate,
        ),
        relative_density_curve=NormalizationCurve(knots=settings.csi_relative_density_knots),
        rate_ceiling_relative=settings.csi_rate_ceiling_relative,
        smoothing_seconds=settings.csi_smoothing_seconds,
        escalate_windows=settings.csi_escalate_windows,
        de_escalate_windows=settings.csi_de_escalate_windows,
        # Detection quality scores zero at the detector's own threshold - a frame
        # of detections sitting exactly there is made of marginal ones - so the
        # floor follows the threshold rather than assuming its default.
        confidence=ConfidenceConfig(
            detection_floor=min(
                settings.detection_confidence_threshold,
                ConfidenceConfig().detection_target - 0.05,
            ),
        ),
    )


def build_evidence_config(settings: Settings) -> EvidenceConfig:
    """Assemble the Evidence Engine configuration from settings."""
    return EvidenceConfig(
        max_items=settings.evidence_max_items,
        min_confidence=settings.evidence_min_confidence,
        history_limit=settings.evidence_history_limit,
    )


def build_decision_config(settings: Settings) -> DecisionConfig:
    """Assemble the Operational Decision Engine's policy from settings.

    ``18:99-109`` lists *configurable* alongside transparent, explainable,
    deterministic and auditable. Escalation points are venue policy, so a
    deployment tunes an environment variable rather than a rule.
    """
    return DecisionConfig(
        max_actions=settings.ode_max_actions,
        min_action_confidence=settings.ode_min_action_confidence,
        report_min_interval_seconds=settings.ode_report_min_interval_seconds,
    )


def build_queue_analysis_config(settings: Settings) -> QueueAnalysisConfig:
    """Queue Intelligence tuning from configuration."""
    return QueueAnalysisConfig(
        min_track_age_frames=settings.queue_min_track_age_frames,
        sparse_threshold=settings.queue_sparse_threshold,
        flow_window_seconds=settings.queue_flow_window_seconds,
        default_service_rate_per_min=settings.default_service_rate_per_min,
    )


def build_forecast_config(settings: Settings) -> ForecastConfig:
    """Forecast tuning from configuration."""
    return ForecastConfig(
        horizons_minutes=settings.forecast_horizons,
        sample_interval_seconds=settings.forecast_sample_interval_seconds,
        alpha=settings.forecast_alpha,
        beta=settings.forecast_beta,
        growth_z_threshold=settings.growth_z_threshold,
        growth_min_rate_per_min=settings.growth_min_rate_per_min,
    )


def build_allocation_config(settings: Settings) -> AllocationConfig:
    """Resource allocation tuning from configuration."""
    return AllocationConfig(
        decision_horizon_minutes=settings.allocation_horizon_minutes,
        target_wait_minutes=settings.allocation_target_wait_minutes,
    )


def build_queue_analyzer(
    settings: Settings, camera: CameraConfig
) -> QueueAnalyzer | None:
    """Queue Intelligence for this camera, or ``None`` when it is disabled.

    Every QUEUE zone starts with the configured default counter allocation. An
    operator changes it through the API, and the *measured* service rate then
    follows reality on its own - which is how the platform notices that a
    newly opened counter is not actually serving anybody.
    """
    if not settings.queue_enabled:
        return None

    analyzer = QueueAnalyzer(camera, build_queue_analysis_config(settings))

    defaults = CounterSettings(
        total_counters=settings.default_total_counters,
        active_counters=min(
            settings.default_active_counters, settings.default_total_counters
        ),
        configured_rate_per_min=settings.default_service_rate_per_min,
    )
    for zone_id in analyzer.queue_zone_ids:
        analyzer.set_counters(zone_id, defaults)

    return analyzer


def build_analysis_pipeline(
    settings: Settings,
    zones: ZoneStore | None = None,
    *,
    definition: CameraDefinition | None = None,
) -> AnalysisPipeline:
    """Assemble Stages 4 to 7 plus Queue Intelligence.

    Separate from :func:`build_pipeline` because they are separate pipelines
    with separate lifecycles: perception owns a camera, a model and a thread,
    while analysis owns only arithmetic and can be reset, replaced or run twice
    without any of that being disturbed.

    One analysis pipeline follows one camera: its baselines, smoothing and
    forecast history describe that camera's view and nobody else's.
    """
    camera = build_camera_config(settings, zones, definition=definition)
    queue_analyzer = build_queue_analyzer(settings, camera)

    return AnalysisPipeline(
        camera,
        GridCrowdAnalyzer(build_crowd_analysis_config(settings)),
        WeightedStabilityAssessor(build_csi_config(settings)),
        RuleEvidenceEngine(build_evidence_config(settings)),
        (
            DeterministicDecisionEngine(build_decision_config(settings))
            if settings.ode_enabled
            else None
        ),
        queues=queue_analyzer,
        # Forecasting and allocation are meaningless without a measured queue,
        # so they are constructed only alongside one.
        forecaster=(
            QueueForecaster(build_forecast_config(settings))
            if queue_analyzer is not None
            else None
        ),
        allocator=(
            ResourceAllocator(build_allocation_config(settings))
            if queue_analyzer is not None
            else None
        ),
        # Entries, exits and transitions for every zone, over the same window
        # and with the same track-age threshold Queue Intelligence counts with,
        # so a queue's arrivals and its zone's entries agree.
        zone_flow=ZoneTransitionTracker(
            camera,
            window_seconds=settings.queue_flow_window_seconds,
            min_track_age_frames=settings.queue_min_track_age_frames,
        ),
    )


def _require_demo_video(settings: Settings) -> Path:
    """Resolve the demonstration clip, failing loudly if it is not there.

    A misconfigured demonstration should say so at startup rather than present
    an empty Command Center to an audience.
    """
    path = settings.demo_video_path
    if path is None:
        raise ConfigurationError(
            "Demonstration Mode is selected but no demonstration video is "
            "configured. Set SURGEGUARD_DEMO_VIDEO_PATH.",
            context={"pipeline_source_mode": SourceMode.DEMO.value},
        )

    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ConfigurationError(
            "The configured demonstration video does not exist.",
            context={"demo_video_path": str(resolved)},
        )
    return resolved


def _require_camera_demo_video(settings: Settings, definition: CameraDefinition) -> Path:
    """Resolve one camera's demonstration clip.

    The primary camera falls back to ``SURGEGUARD_DEMO_VIDEO_PATH``, so the
    long-standing two-line switch to Demonstration Mode still works. Every other
    camera needs a clip of its own: one recording cannot honestly stand in for
    two viewpoints, and replaying it twice would double-count its crowd.
    """
    path = definition.demo_video_path
    if path is None and definition.is_primary:
        return _require_demo_video(settings)
    if path is None:
        raise ConfigurationError(
            f"Demonstration Mode is selected but {definition.display_id} has no "
            "demonstration clip. Set its demo video path, or disable the camera.",
            context={"camera_id": definition.camera_id},
        )

    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ConfigurationError(
            f"The demonstration clip for {definition.display_id} does not exist.",
            context={"camera_id": definition.camera_id, "demo_video_path": str(resolved)},
        )
    return resolved


def _as_camera_device(value: str) -> int | str:
    """Interpret a camera setting as a device index where it is one, else a URL.

    OpenCV distinguishes the two by type rather than by content: ``0`` is the
    first attached camera and ``"0"`` is a filename.
    """
    return int(value) if value.isdigit() else value
