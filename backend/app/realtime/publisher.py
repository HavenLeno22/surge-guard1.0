"""Domain events to WebSocket messages.

The one place that knows both vocabularies. Services publish domain events and
never touch a socket (:mod:`app.realtime.broadcaster` states that rule); this
module subscribes to those events and decides what reaches the operator, in
what shape, and how often.

Keeping the translation here rather than inside each service is what allows the
WebSocket contract to change without touching operational logic, and what keeps
every service testable with no socket present.

**Throttling is a deliberate part of the contract.** The assessment stream runs
at the analysis rate - ten windows a second - and forwarding every one of them
would spend bandwidth and client render time re-drawing a gauge that moved by a
tenth of a point. Assessment updates are therefore rate-limited, with one
exception that matters: a window carrying a **status change** is always sent
immediately. Delaying a band transition to save a frame would be exactly the
wrong trade for a safety display.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from surgeguard_ai.contracts import (
    AnalysisResult,
    PerceptionResult,
    SiteReport,
)

from ..api.v1._camera_presenters import to_camera_reads
from ..api.v1._presenters import to_perception_read
from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from ..schemas.intelligence import CrowdSummary
from ..schemas.timeline import TimelineEntry
from ..services.decision_service import IssuedReport, StateChange
from ..services.perception_state import PerceptionStateService
from ..workers.perception_worker import PerceptionWorker
from .broadcaster import Broadcaster
from .envelope import WSEventType

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from ..cameras.manager import CameraManager
    from ..services.system_health import SystemHealthService

__all__ = ["RealtimePublisher", "assessment_payload", "camera_analysis_payload"]

logger = get_logger(__name__)

#: How often every camera's status and measurements are pushed. Frame rate,
#: latency and battery change continuously; once a second reads as live without
#: flooding the socket.
CAMERA_STATUS_INTERVAL_SECONDS = 1.0

#: How often component health is checked for a change worth pushing. Health
#: moves on the scale of seconds, and only a change is sent.
HEALTH_CHECK_INTERVAL_SECONDS = 5.0


class RealtimePublisher:
    """Translates domain events into Command Center messages."""

    def __init__(
        self,
        broadcaster: Broadcaster,
        event_bus: EventBus,
        *,
        perception_state: PerceptionStateService,
        worker: PerceptionWorker,
        assessment_min_interval_seconds: float = 0.5,
        manager: CameraManager | None = None,
        health: SystemHealthService | None = None,
        health_interval_seconds: float = HEALTH_CHECK_INTERVAL_SECONDS,
    ) -> None:
        """
        Args:
            broadcaster: The outbound path to connected clients.
            event_bus: Bus to subscribe to.
            perception_state: The primary camera's perception, for the
                single-camera detection payload.
            worker: The primary camera's worker, which knows the compute device.
            assessment_min_interval_seconds: Floor between assessment and
                perception updates. A status change bypasses it.
            manager: Every camera. When present, per-camera messages are sent
                alongside the single-camera ones, and ``csi.updated`` and
                ``detections.updated`` keep describing the primary camera only -
                a client built for one camera must not see two cameras'
                assessments alternating in one panel.
            health: Component health, pushed as ``health.updated`` when it
                changes. Without it health reaches a client only in a snapshot.
            health_interval_seconds: How often health is checked for a change.
        """
        self._broadcaster = broadcaster
        self._event_bus = event_bus
        self._perception_state = perception_state
        self._worker = worker
        self._manager = manager
        self._health = health
        self._health_interval = health_interval_seconds
        self._last_health_signature: tuple[tuple[str, str, str | None], ...] | None = None
        self._primary_camera_id = worker.camera_id if manager is not None else None
        self._min_interval = max(assessment_min_interval_seconds, 0.0)
        self._last_assessment_at: float | None = None
        self._last_perception_at: float | None = None
        self._last_camera_analysis_at: dict[str, float] = {}
        self._status_task: asyncio.Task[None] | None = None
        self._health_task: asyncio.Task[None] | None = None
        self._subscribed = False

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Subscribe to the events this publisher forwards. Idempotent."""
        if self._subscribed:
            return
        self._event_bus.subscribe(DomainEvent.PERCEPTION_RECEIVED, self._on_perception)
        self._event_bus.subscribe(DomainEvent.ANALYSIS_RECEIVED, self._on_analysis)
        self._event_bus.subscribe(DomainEvent.OIR_GENERATED, self._on_report)
        self._event_bus.subscribe(DomainEvent.OPERATIONAL_STATE_CHANGED, self._on_state)
        self._event_bus.subscribe(DomainEvent.TIMELINE_ENTRY_ADDED, self._on_timeline)
        self._event_bus.subscribe(DomainEvent.CAMERAS_CHANGED, self._on_cameras_changed)
        self._event_bus.subscribe(DomainEvent.SITE_UPDATED, self._on_site)
        if self._manager is not None:
            self._status_task = asyncio.create_task(
                self._broadcast_camera_status(), name="realtime-camera-status"
            )
        if self._health is not None:
            self._health_task = asyncio.create_task(
                self._broadcast_health_changes(), name="realtime-health"
            )
        self._subscribed = True
        logger.info(
            "Realtime publisher started",
            extra={"assessment_min_interval_seconds": self._min_interval},
        )

    def stop(self) -> None:
        """Unsubscribe. Idempotent."""
        if not self._subscribed:
            return
        self._event_bus.unsubscribe(DomainEvent.PERCEPTION_RECEIVED, self._on_perception)
        self._event_bus.unsubscribe(DomainEvent.ANALYSIS_RECEIVED, self._on_analysis)
        self._event_bus.unsubscribe(DomainEvent.OIR_GENERATED, self._on_report)
        self._event_bus.unsubscribe(DomainEvent.OPERATIONAL_STATE_CHANGED, self._on_state)
        self._event_bus.unsubscribe(DomainEvent.TIMELINE_ENTRY_ADDED, self._on_timeline)
        self._event_bus.unsubscribe(DomainEvent.CAMERAS_CHANGED, self._on_cameras_changed)
        self._event_bus.unsubscribe(DomainEvent.SITE_UPDATED, self._on_site)
        if self._status_task is not None:
            self._status_task.cancel()
            self._status_task = None
        if self._health_task is not None:
            self._health_task.cancel()
            self._health_task = None
        self._subscribed = False
        logger.info("Realtime publisher stopped")

    # -- Handlers -----------------------------------------------------------

    async def _on_perception(self, result: PerceptionResult) -> None:
        """Forward the current perception view, subject to the rate floor.

        Read back from the state service rather than taken from the event
        payload, because the panel needs the age and device context the bare
        contract does not carry - and because that is the same shape the REST
        route serves, so a client cannot tell which path delivered it.
        """
        if not self._is_primary(result.camera_id):
            return
        if not self._has_clients or not self._should_send_perception():
            return

        read = to_perception_read(self._perception_state, self._worker)
        if read is None:
            return

        await self._publish(
            WSEventType.DETECTIONS_UPDATED,
            read.model_dump(mode="json"),
            read.result.camera_id,
        )

    async def _on_analysis(self, analysis: AnalysisResult) -> None:
        """Forward an assessment, subject to the rate floor.

        Two messages from one analysis when several cameras are managed: the
        long-standing ``csi.updated`` for the primary camera, and
        ``camera.analysis`` for every camera - throttled per camera, so a busy
        camera cannot starve a quiet one of updates.
        """
        if not self._has_clients:
            return

        if self._manager is not None and self._should_send_camera_analysis(analysis):
            await self._publish(
                WSEventType.CAMERA_ANALYSIS,
                camera_analysis_payload(analysis),
                analysis.camera_id,
            )

        if not self._is_primary(analysis.camera_id):
            return
        if not self._should_send_assessment(analysis):
            return

        await self._publish(
            WSEventType.CSI_UPDATED,
            assessment_payload(analysis),
            analysis.camera_id,
        )

    async def _on_cameras_changed(self, change: dict[str, Any]) -> None:
        """Forward a change to the camera set, with every camera's new state."""
        if not self._has_clients or self._manager is None:
            return
        await self._publish(
            WSEventType.CAMERAS_CHANGED,
            {
                "change": change,
                "cameras": [
                    read.model_dump(mode="json") for read in to_camera_reads(self._manager)
                ],
            },
            change.get("camera_id"),
        )

    async def _on_site(self, report: SiteReport) -> None:
        """Forward site intelligence. Already produced at a steady cadence."""
        if not self._has_clients:
            return
        await self._publish(WSEventType.SITE_UPDATED, report.model_dump(mode="json"))

    async def _broadcast_camera_status(self) -> None:
        """Push every camera's status and measurements once a second."""
        assert self._manager is not None  # noqa: S101 - task only started with a manager
        while True:
            await asyncio.sleep(CAMERA_STATUS_INTERVAL_SECONDS)
            if not self._has_clients:
                continue
            try:
                cameras = [
                    read.model_dump(mode="json") for read in to_camera_reads(self._manager)
                ]
            except Exception as error:  # noqa: BLE001 - a status push must never end the loop
                logger.warning("Camera status could not be built", exc_info=error)
                continue
            await self._publish(WSEventType.CAMERA_STATUS, {"cameras": cameras})

    async def _on_report(self, issued: IssuedReport) -> None:
        """Forward a new Operational Intelligence Report, always.

        Never throttled: the engine has already decided this report is worth
        issuing, and suppressing it here would silently undo that judgement.

        Tagged with the camera that issued it. The payload is the report exactly
        as before; the envelope's ``camera_id`` is what lets a client with
        several cameras put each report in the right place.
        """
        if not self._has_clients:
            return
        await self._publish(
            WSEventType.OIR_UPDATED, issued.report.model_dump(mode="json"), issued.camera_id
        )

    async def _on_state(self, change: StateChange) -> None:
        """Forward an Operational State change, always.

        Previously a client learned the workflow phase only from a snapshot, so
        the strip on screen stayed wherever it was at connection until the next
        resync. Changes are rare by construction; nothing to throttle.
        """
        if not self._has_clients:
            return
        await self._publish(
            WSEventType.STATE_UPDATED,
            {
                "camera_id": change.camera_id,
                "operational_state": change.state.value,
                "actor": change.actor,
            },
            change.camera_id,
        )

    async def _broadcast_health_changes(self) -> None:
        """Push component health whenever a component's status or reason changes."""
        assert self._health is not None  # noqa: S101 - task only started with a health service
        while True:
            await asyncio.sleep(self._health_interval)
            if not self._has_clients:
                # Re-announce on the next check after a client appears.
                self._last_health_signature = None
                continue
            try:
                health = await self._health.check()
            except Exception as error:  # noqa: BLE001 - a health push must never end the loop
                logger.warning("Health could not be checked for push", exc_info=error)
                continue
            signature = tuple(
                (component.component.value, component.status.value, component.detail)
                for component in health.components
            )
            if signature == self._last_health_signature:
                continue
            self._last_health_signature = signature
            await self._publish(WSEventType.HEALTH_UPDATED, health.model_dump(mode="json"))

    async def _on_timeline(self, entry: TimelineEntry) -> None:
        """Forward one timeline entry, always.

        Timeline entries are already rare by construction - the decision service
        records a change, not a window - so there is nothing to throttle.
        """
        if not self._has_clients:
            return
        await self._publish(
            WSEventType.TIMELINE_APPENDED,
            entry.model_dump(mode="json"),
            entry.camera_id,
        )

    # -- Internals ----------------------------------------------------------

    @property
    def _has_clients(self) -> bool:
        """Whether anything is listening.

        Checked before building a payload, not after. Serialising a full
        assessment - the stability breakdown, every confidence factor and the
        whole evidence report - costs the same whether or not a client exists,
        and with none connected it is work done entirely for the garbage
        collector. The broadcaster would discard it a moment later anyway; this
        just declines to produce it.
        """
        return self._broadcaster.client_count > 0

    def _is_primary(self, camera_id: str) -> bool:
        """Whether a result belongs on the single-camera messages."""
        return self._primary_camera_id is None or camera_id == self._primary_camera_id

    def _should_send_camera_analysis(self, analysis: AnalysisResult) -> bool:
        """Rate-limit per camera, but never a band transition."""
        now = time.monotonic()
        last = self._last_camera_analysis_at.get(analysis.camera_id)
        if (
            not analysis.stability.status_changed
            and last is not None
            and now - last < self._min_interval
        ):
            return False
        self._last_camera_analysis_at[analysis.camera_id] = now
        return True

    def _should_send_assessment(self, analysis: AnalysisResult) -> bool:
        """Rate-limit assessments, but never a band transition."""
        if analysis.stability.status_changed:
            self._last_assessment_at = time.monotonic()
            return True

        now = time.monotonic()
        if (
            self._last_assessment_at is not None
            and now - self._last_assessment_at < self._min_interval
        ):
            return False

        self._last_assessment_at = now
        return True

    def _should_send_perception(self) -> bool:
        """Rate-limit perception updates.

        Perception arrives at the full frame rate and carries every detection
        and track, so it is the heaviest thing on the socket. The Live Camera
        panel shows counters rather than overlays, and a counter refreshed twice
        a second already looks continuous.
        """
        now = time.monotonic()
        if (
            self._last_perception_at is not None
            and now - self._last_perception_at < self._min_interval
        ):
            return False

        self._last_perception_at = now
        return True

    async def _publish(
        self,
        event_type: WSEventType,
        data: dict[str, Any],
        camera_id: str | None = None,
    ) -> None:
        """Send, isolating the analysis path from a broadcast failure.

        The publisher runs on the event bus, whose ultimate upstream is the AI
        Pipeline. A socket problem is a socket problem, never a reason to stop
        analysing frames (``04:838-849``).
        """
        try:
            await self._broadcaster.publish(event_type, data, camera_id)
        except Exception as error:  # noqa: BLE001 - never propagate to the pipeline
            logger.error(
                "Realtime publish failed",
                exc_info=error,
                extra={"event_type": event_type.value},
            )


def assessment_payload(analysis: AnalysisResult) -> dict[str, Any]:
    """The wire shape of one assessment.

    Mirrors :class:`~app.schemas.intelligence.CrowdIntelligenceRead` minus the
    envelope's own age fields - a pushed message is current by definition, and
    the client measures staleness from the socket rather than from a field.

    Defined here rather than in each handler so the socket and the REST surface
    cannot drift into describing the same assessment two different ways.
    """
    return {
        "camera_id": analysis.camera_id,
        "source_mode": analysis.source_mode.value,
        "frame_seq": analysis.frame_seq,
        "stability": analysis.stability.model_dump(mode="json"),
        "evidence": (
            analysis.evidence.model_dump(mode="json") if analysis.evidence else None
        ),
        # Built through the same schema the REST route uses, not restated here:
        # the two paths must produce an identical crowd summary for a client to
        # apply a pushed message and a fetched one interchangeably.
        "crowd": CrowdSummary.from_crowd(analysis.crowd).model_dump(mode="json"),
        # Queue Intelligence rides the same message as the assessment it was
        # computed from, so the measurement, the forecast and the recommendation
        # the operator sees always describe one frame. Sending them as three
        # separate messages would let the panels disagree by a window - and the
        # one moment they would disagree most visibly is a surge, which is the
        # moment they most need to agree.
        #
        # Null rather than absent when Queue Intelligence is not running: a
        # client can then distinguish "not configured" from "an older server".
        "queue": analysis.queue.model_dump(mode="json") if analysis.queue else None,
        "forecast": (
            analysis.forecast.model_dump(mode="json") if analysis.forecast else None
        ),
        "resources": (
            analysis.resources.model_dump(mode="json") if analysis.resources else None
        ),
        "degraded": analysis.degraded,
        "degraded_reason": analysis.degraded_reason,
    }


def camera_analysis_payload(analysis: AnalysisResult) -> dict[str, Any]:
    """The wire shape of one camera's analysis on ``camera.analysis``.

    The assessment payload, plus what a multi-camera view needs that a
    single-camera one never did: when the frame was captured, how many people
    are tracked rather than estimated, and zone flow.
    """
    payload = assessment_payload(analysis)
    payload["frame_ts"] = analysis.frame_ts.isoformat()
    payload["tracked_count"] = analysis.tracking.count if analysis.tracking is not None else None
    payload["zone_flow"] = (
        analysis.zone_flow.model_dump(mode="json") if analysis.zone_flow is not None else None
    )
    return payload
