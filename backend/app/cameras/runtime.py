"""Everything one camera needs to run.

A :class:`CameraRuntime` is the single-camera platform that SurgeGuard used to
be, packaged so that there can be several: its own perception worker and model,
its own perception state, its own analysis pipeline with its own baselines, its
own queue and decision services, its own live video.

Two things are deliberately **shared** between runtimes rather than duplicated:

- the event bus, because consumers such as the realtime publisher and the site
  intelligence layer need every camera's output in one place - which is why each
  per-camera handler filters on ``camera_id``;
- the timeline, because an operator reconstructing an incident reads one
  chronology, with each entry saying which camera it concerns.
"""

from __future__ import annotations

from datetime import UTC, datetime

from surgeguard_ai.contracts import CameraConfig, CameraConnectionStatus, SourceMode, ZoneType
from surgeguard_ai.perception import FrameSource
from surgeguard_ai.pipeline import AnalysisPipeline

from ..core.config import Settings
from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from ..ingest.perception_sink import InProcessPerceptionSink
from ..services.crowd_intelligence import CrowdIntelligenceService
from ..services.decision_service import DecisionService
from ..services.operational_state import OperationalStateService
from ..services.perception_state import PerceptionStateService
from ..services.queue_service import QueueService
from ..services.timeline_service import TimelineService
from ..services.zone_store import ZoneStore, ZoneStoreError
from ..streaming import LiveStreamService
from ..workers.perception_factory import (
    build_analysis_pipeline,
    build_camera_config,
    build_frame_source,
    build_zone_store,
)
from ..workers.perception_worker import PerceptionWorker, PerceptionWorkerState
from .definitions import CameraDefinition
from .health import CameraHealthMonitor, probe_address
from .probe import StreamOutcome
from .status import CameraMetrics, StatusThresholds, derive_status

__all__ = ["CameraRuntime", "CameraStatusSnapshot"]

logger = get_logger(__name__)


class CameraStatusSnapshot:
    """One camera's status, reason and measurements at a moment."""

    __slots__ = (
        "camera_id",
        "status",
        "detail",
        "worker_state",
        "state_changed_at",
        "metrics",
        "diagnosis",
        "source_mode",
        "zone_count",
        "queue_zone_count",
    )

    def __init__(
        self,
        *,
        camera_id: str,
        status: CameraConnectionStatus,
        detail: str | None,
        worker_state: PerceptionWorkerState,
        state_changed_at: datetime,
        metrics: CameraMetrics,
        diagnosis: StreamOutcome | None,
        source_mode: SourceMode,
        zone_count: int,
        queue_zone_count: int,
    ) -> None:
        self.camera_id = camera_id
        self.status = status
        self.detail = detail
        self.worker_state = worker_state
        self.state_changed_at = state_changed_at
        self.metrics = metrics
        self.diagnosis = diagnosis
        self.source_mode = source_mode
        self.zone_count = zone_count
        self.queue_zone_count = queue_zone_count


class CameraRuntime:
    """One camera's perception, analysis, video and operator services."""

    def __init__(
        self,
        definition: CameraDefinition,
        *,
        settings: Settings,
        event_bus: EventBus,
        timeline: TimelineService,
        thresholds: StatusThresholds | None = None,
    ) -> None:
        self._definition = definition
        self._settings = settings
        self._event_bus = event_bus
        self._thresholds = thresholds or StatusThresholds()
        self._subscribed = False
        camera_id = definition.camera_id

        self.perception_state = PerceptionStateService()
        self.sink = InProcessPerceptionSink(self.perception_state, event_bus)
        self.zone_store: ZoneStore = build_zone_store(settings, camera_id)

        self.analysis_pipeline: AnalysisPipeline | None = (
            build_analysis_pipeline(settings, self.zone_store, definition=definition)
            if settings.csi_enabled
            else None
        )
        self.intelligence = CrowdIntelligenceService(
            self.analysis_pipeline, event_bus, camera_id=camera_id
        )
        self.queue_service = QueueService(
            self.intelligence,
            self.zone_store,
            self.analysis_pipeline,
            camera_id=camera_id,
            default_service_rate_per_min=settings.default_service_rate_per_min,
        )
        self.decisions = DecisionService(
            timeline,
            OperationalStateService(),
            event_bus,
            camera_id=camera_id,
            history_limit=settings.decision_history_limit,
        )
        self.live_stream = LiveStreamService(
            jpeg_quality=settings.stream_jpeg_quality,
            target_fps=settings.stream_target_fps,
            camera_id=camera_id,
        )
        self.worker = PerceptionWorker(
            settings,
            self.sink,
            self.perception_state,
            on_frame=self.live_stream.handle_frame,
            source_factory=self._build_source,
            camera_factory=self._build_camera_config,
            camera_id=camera_id,
        )
        self.health = CameraHealthMonitor(
            camera_id=camera_id,
            url_provider=lambda: probe_address(
                self._definition.stream_url, settings.pipeline_source_mode
            ),
            state_provider=lambda: self.worker.state,
            interval_seconds=settings.camera_health_probe_interval_seconds,
            on_device_returned=self.worker.retry_now,
        )

    # -- Identity -----------------------------------------------------------

    @property
    def camera_id(self) -> str:
        return self._definition.camera_id

    @property
    def definition(self) -> CameraDefinition:
        return self._definition

    # -- Event wiring -------------------------------------------------------

    def subscribe(self) -> None:
        """Attach this camera's handlers to the shared bus. Idempotent."""
        if self._subscribed:
            return
        bus = self._event_bus
        bus.subscribe(DomainEvent.PERCEPTION_RECEIVED, self.intelligence.handle_perception)
        bus.subscribe(DomainEvent.ANALYSIS_RECEIVED, self.decisions.handle_analysis)
        bus.subscribe(DomainEvent.ANALYSIS_RECEIVED, self.live_stream.update_overlay)
        self._subscribed = True

    def unsubscribe(self) -> None:
        if not self._subscribed:
            return
        bus = self._event_bus
        bus.unsubscribe(DomainEvent.PERCEPTION_RECEIVED, self.intelligence.handle_perception)
        bus.unsubscribe(DomainEvent.ANALYSIS_RECEIVED, self.decisions.handle_analysis)
        bus.unsubscribe(DomainEvent.ANALYSIS_RECEIVED, self.live_stream.update_overlay)
        self._subscribed = False

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Begin supervising the camera, if it is enabled. Returns immediately."""
        if not self._definition.enabled:
            return
        await self.worker.start()
        if self._settings.pipeline_enabled:
            self.health.start()

    async def stop(self) -> None:
        """Stop the camera and discard what it was showing."""
        await self.health.stop()
        await self.worker.stop()
        self.live_stream.clear()
        self.intelligence.clear()

    async def apply(self, definition: CameraDefinition) -> None:
        """Adopt an edited definition while running.

        Only what changed is acted on: a renamed camera keeps streaming, a
        re-addressed one swaps its source in place, and enabling or disabling
        starts or stops it.
        """
        previous = self._definition
        self._definition = definition

        if previous.enabled and not definition.enabled:
            await self.stop()
            return
        if not previous.enabled and definition.enabled:
            await self.start()
            return
        if not definition.enabled:
            return

        address_changed = (
            previous.stream_url != definition.stream_url
            or previous.demo_video_path != definition.demo_video_path
        )
        if address_changed:
            self.health.reset()
            await self.worker.replace_source(self._build_source)

    def rebuild_analysis(self) -> None:
        """Rebuild the analysis pipeline against the camera's current zones.

        Counter allocations the operator set are carried across for every queue
        zone that still exists - redrawing a queue's outline is not a statement
        about how many counters are open.
        """
        if not self._settings.csi_enabled:
            return

        previous = self.analysis_pipeline
        rebuilt = build_analysis_pipeline(
            self._settings, self.zone_store, definition=self._definition
        )

        old_queues = previous.queue_analyzer if previous is not None else None
        new_queues = rebuilt.queue_analyzer
        if old_queues is not None and new_queues is not None:
            for zone_id in new_queues.queue_zone_ids:
                if zone_id in old_queues.queue_zone_ids:
                    new_queues.set_counters(zone_id, old_queues.counters_for(zone_id))

        self.analysis_pipeline = rebuilt
        self.intelligence.rebind(rebuilt)
        self.queue_service.rebind(rebuilt)
        logger.info("Analysis rebuilt against new zones", extra={"camera_id": self.camera_id})

    # -- Status -------------------------------------------------------------

    def snapshot(self, *, now: datetime | None = None) -> CameraStatusSnapshot:
        """Current status, reason and measurements."""
        reference = now or datetime.now(UTC)
        worker = self.worker
        pipeline = worker.pipeline_status
        latest = self.perception_state.latest
        received_at = self.perception_state.received_at

        frame_age = (
            max(0.0, (reference - received_at).total_seconds()) if received_at is not None else None
        )
        diagnosis = self.health.diagnosis
        diagnosis_detail = (
            diagnosis.detail
            if diagnosis is not None
            and diagnosis.outcome not in (StreamOutcome.STREAMING, StreamOutcome.OK)
            else None
        )

        status, detail = derive_status(
            enabled=self._definition.enabled,
            worker_state=worker.state,
            worker_detail=worker.detail,
            frame_age_seconds=frame_age,
            achieved_fps=pipeline.achieved_fps if pipeline is not None else None,
            pipeline_degraded_reason=pipeline.degraded_reason if pipeline is not None else None,
            diagnosis_detail=diagnosis_detail,
            thresholds=self._thresholds,
        )

        source = worker.source
        native = getattr(source, "native_size", None)
        device = self.health.device
        analysis_width, analysis_height = self._settings.detection_size

        # A frame rate is a measurement of frames arriving. A camera that is not
        # delivering has no frame rate - not a frame rate of zero.
        metrics = CameraMetrics(
            achieved_fps=(
                pipeline.achieved_fps
                if pipeline is not None and status.is_contributing
                else None
            ),
            source_fps=source.fps if source is not None else None,
            native_width=native[0] if native else None,
            native_height=native[1] if native else None,
            analysis_width=analysis_width,
            analysis_height=analysis_height,
            frames_processed=pipeline.frames_processed if pipeline is not None else 0,
            frames_dropped=pipeline.frames_dropped if pipeline is not None else 0,
            last_frame_at=latest.frame_ts if latest is not None else None,
            frame_age_seconds=frame_age,
            inference_ms=latest.inference_ms if latest is not None else None,
            processing_ms=latest.processing_ms if latest is not None else None,
            pipeline_latency_ms=(
                max(0.0, (latest.produced_at - latest.frame_ts).total_seconds() * 1000.0)
                if latest is not None
                else None
            ),
            network_rtt_ms=device.network_rtt_ms if device is not None else None,
            device_name=device.device_name if device is not None else None,
            battery_percent=device.battery_percent if device is not None else None,
            device_checked_at=self.health.device_checked_at,
            people_count=(
                latest.person_count if latest is not None and status.is_contributing else None
            ),
            tracked_count=(
                latest.tracking.count if latest is not None and status.is_contributing else None
            ),
            detection_active=status.is_contributing and worker.model_name is not None,
            tracking_active=status.is_contributing and latest is not None and not latest.degraded,
            reconnections=worker.total_restarts,
        )

        zones = self._zones_safely()
        return CameraStatusSnapshot(
            camera_id=self.camera_id,
            status=status,
            detail=detail,
            worker_state=worker.state,
            state_changed_at=worker.state_changed_at,
            metrics=metrics,
            diagnosis=diagnosis.outcome if diagnosis is not None else None,
            source_mode=self._settings.pipeline_source_mode,
            zone_count=len(zones),
            queue_zone_count=sum(1 for zone in zones if zone.zone_type is ZoneType.QUEUE),
        )

    # -- Factories handed to the worker -------------------------------------

    def _build_source(self) -> FrameSource:
        return build_frame_source(self._settings, definition=self._definition)

    def _build_camera_config(self) -> CameraConfig:
        return build_camera_config(self._settings, self.zone_store, definition=self._definition)

    def _zones_safely(self):
        try:
            return self.zone_store.zones
        except ZoneStoreError:
            return ()
