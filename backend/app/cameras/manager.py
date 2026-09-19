"""The camera manager - every camera runtime, and operator changes applied live.

The manager is the one place that turns an operator's edit into running
behaviour: an added camera starts, a re-addressed one reconnects, a disabled one
stops, a removed one is released. The registry records the change; the runtime
carries it out; the manager keeps the two in step and announces the result.

It is also what keeps connection tests honest. DroidCam serves a single client
per phone, so a test that opened a second connection to a camera SurgeGuard is
already reading would steal the very stream being tested. A test against an
address a running camera owns is answered from that camera's own live
measurements instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime

from surgeguard_ai.contracts import CameraConnectionStatus, CameraZone

from ..core.config import Settings
from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from ..services.timeline_service import TimelineService
from ..workers.perception_worker import PerceptionWorkerState
from .definitions import CameraChanges, CameraSpec, normalise_stream_url
from .probe import (
    ConnectionTestResult,
    StreamOutcome,
    diagnose_stream,
    fetch_device_info,
    is_network_url,
    run_connection_test,
    stream_endpoint,
)
from .registry import CameraNotFoundError, CameraRegistry
from .runtime import CameraRuntime
from .status import StatusThresholds
from .topology_store import TopologyStore

__all__ = ["CameraManager"]

logger = get_logger(__name__)

#: Worker states in which a camera holds, or is trying to take, its stream.
_OWNING_STATES = frozenset(
    {
        PerceptionWorkerState.STARTING,
        PerceptionWorkerState.RUNNING,
        PerceptionWorkerState.RECOVERING,
    }
)


class CameraManager:
    """Owns every camera runtime for the life of the process."""

    def __init__(
        self,
        settings: Settings,
        event_bus: EventBus,
        registry: CameraRegistry,
        topology: TopologyStore,
        timeline: TimelineService,
        *,
        thresholds: StatusThresholds | None = None,
    ) -> None:
        self._settings = settings
        self._event_bus = event_bus
        self._registry = registry
        self._topology = topology
        self._timeline = timeline
        self._thresholds = thresholds or StatusThresholds()
        self._runtimes: dict[str, CameraRuntime] = {}
        self._lock = asyncio.Lock()
        self._started = False

        for definition in registry.cameras():
            self._create_runtime(definition)

    # -- Reading ------------------------------------------------------------

    @property
    def registry(self) -> CameraRegistry:
        return self._registry

    @property
    def topology(self) -> TopologyStore:
        return self._topology

    @property
    def primary(self) -> CameraRuntime:
        """The camera the single-camera routes describe. Always present."""
        return self._runtimes[self._registry.primary_camera_id]

    def runtimes(self) -> tuple[CameraRuntime, ...]:
        """Every camera, in display order."""
        return tuple(
            sorted(self._runtimes.values(), key=lambda runtime: runtime.definition.order)
        )

    def get(self, camera_id: str) -> CameraRuntime | None:
        return self._runtimes.get(camera_id.strip().lower())

    def require(self, camera_id: str) -> CameraRuntime:
        runtime = self.get(camera_id)
        if runtime is None:
            raise CameraNotFoundError(f"No camera {camera_id!r} is configured.")
        return runtime

    def online_count(self) -> tuple[int, int]:
        """``(contributing, enabled)`` - the figure behind "2 / 2 cameras online"."""
        now = datetime.now(UTC)
        enabled = [runtime for runtime in self._runtimes.values() if runtime.definition.enabled]
        contributing = sum(
            1 for runtime in enabled if runtime.snapshot(now=now).status.is_contributing
        )
        return contributing, len(enabled)

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start every enabled camera. Returns as soon as each is scheduled."""
        self._started = True
        for runtime in self.runtimes():
            await self._open_sink(runtime)
            await runtime.start()
        logger.info(
            "Camera manager started",
            extra={"cameras": [runtime.camera_id for runtime in self.runtimes()]},
        )

    async def stop(self) -> None:
        """Stop every camera and detach its handlers."""
        self._started = False
        for runtime in self.runtimes():
            await runtime.stop()
            runtime.unsubscribe()
            await runtime.sink.close()

    # -- Operator changes -----------------------------------------------------

    async def add_camera(self, spec: CameraSpec) -> CameraRuntime:
        async with self._lock:
            definition = self._registry.add(spec)
            runtime = self._create_runtime(definition)
            if self._started:
                await self._open_sink(runtime)
                await runtime.start()
        self._announce(definition.camera_id, "added")
        return runtime

    async def update_camera(self, camera_id: str, changes: CameraChanges) -> CameraRuntime:
        async with self._lock:
            runtime = self.require(camera_id)
            definition = self._registry.update(runtime.camera_id, changes)
            await runtime.apply(definition)
        self._announce(definition.camera_id, "updated")
        return runtime

    async def remove_camera(self, camera_id: str) -> None:
        async with self._lock:
            runtime = self.require(camera_id)
            self._registry.remove(runtime.camera_id)
            await runtime.stop()
            runtime.unsubscribe()
            await runtime.sink.close()
            del self._runtimes[runtime.camera_id]
            self._timeline.clear_camera(runtime.camera_id)
        self._announce(runtime.camera_id, "removed")

    async def retry(self, camera_id: str) -> CameraRuntime:
        """Try to connect a camera now, without waiting out its backoff."""
        runtime = self.require(camera_id)
        runtime.worker.retry_now()
        runtime.health.check_soon()
        return runtime

    def save_zones(self, camera_id: str, zones: Iterable[CameraZone]) -> tuple[CameraZone, ...]:
        """Replace a camera's zones and apply them to its analysis immediately."""
        runtime = self.require(camera_id)
        saved = runtime.zone_store.save(tuple(zones))
        runtime.rebuild_analysis()
        self._announce(runtime.camera_id, "zones")
        return saved

    # -- Connection tests ---------------------------------------------------

    async def test_connection(
        self, url: str, *, camera_id: str | None = None
    ) -> ConnectionTestResult:
        """Test a stream address without competing for a stream SurgeGuard holds.

        Args:
            url: The address to test, as an operator typed it.
            camera_id: The camera the address is being tested for, if any. That
                camera's own connection counts as the owner like any other.

        Raises:
            ValueError: The address is not a usable stream address.
        """
        target = normalise_stream_url(url)
        if target is None:
            raise ValueError("A stream address is required to test a connection.")

        owner = self._owner_of(target)
        if owner is not None and owner.worker.state is PerceptionWorkerState.RUNNING:
            return self._live_measurement(owner, target)

        if owner is not None:
            return await asyncio.to_thread(self._diagnose_owned, owner, target)

        open_target: int | str = int(target) if target.isdigit() else target
        return await asyncio.to_thread(
            run_connection_test,
            target,
            read_seconds=self._settings.camera_connection_test_seconds,
            open_target=open_target,
        )

    def _owner_of(self, target: str) -> CameraRuntime | None:
        endpoint = stream_endpoint(target)
        for runtime in self._runtimes.values():
            configured = runtime.definition.stream_url
            if not runtime.definition.enabled or configured is None:
                continue
            if runtime.worker.state not in _OWNING_STATES:
                continue
            if endpoint is not None and stream_endpoint(configured) == endpoint:
                return runtime
            if endpoint is None and configured == target:
                return runtime
        return None

    def _live_measurement(self, owner: CameraRuntime, target: str) -> ConnectionTestResult:
        snapshot = owner.snapshot()
        metrics = snapshot.metrics
        contributing = snapshot.status.is_contributing
        return ConnectionTestResult(
            url=target,
            success=contributing,
            outcome=StreamOutcome.OK if contributing else StreamOutcome.NO_FRAMES,
            detail=(
                f"{owner.definition.display_id} is already connected to this camera. "
                "These figures come from that connection - no second client was "
                "opened, because DroidCam serves only one."
            )
            + ("" if contributing else f" Status: {snapshot.detail}"),
            width=metrics.native_width,
            height=metrics.native_height,
            reported_fps=metrics.source_fps,
            measured_fps=metrics.achieved_fps,
            frames_read=metrics.frames_processed,
            network_rtt_ms=metrics.network_rtt_ms,
            device_name=metrics.device_name,
            battery_percent=metrics.battery_percent,
            live_measurement=True,
        )

    def _diagnose_owned(self, owner: CameraRuntime, target: str) -> ConnectionTestResult:
        """Explain an address a camera is still trying to connect to.

        Diagnosed over HTTP rather than opened for decoding: the camera's own
        worker will take the stream the moment it is available, and a test
        decoder holding it at that moment would be the reason it failed.
        """
        prefix = (
            f"SurgeGuard is already trying to connect to this address as "
            f"{owner.definition.display_id}. "
        )
        device = fetch_device_info(target) if is_network_url(target) else None
        if not is_network_url(target):
            return ConnectionTestResult(
                url=target,
                success=False,
                outcome=StreamOutcome.NOT_DIAGNOSABLE,
                detail=prefix + "Wait for it to connect, or check the device.",
            )
        diagnosis = diagnose_stream(target)
        return ConnectionTestResult(
            url=target,
            success=diagnosis.outcome is StreamOutcome.STREAMING,
            outcome=diagnosis.outcome,
            detail=prefix + diagnosis.detail,
            network_rtt_ms=device.network_rtt_ms if device else None,
            device_name=device.device_name if device else None,
            battery_percent=device.battery_percent if device else None,
        )

    # -- Internals ----------------------------------------------------------

    def _create_runtime(self, definition) -> CameraRuntime:
        runtime = CameraRuntime(
            definition,
            settings=self._settings,
            event_bus=self._event_bus,
            timeline=self._timeline,
            thresholds=self._thresholds,
        )
        runtime.subscribe()
        self._runtimes[definition.camera_id] = runtime
        return runtime

    @staticmethod
    async def _open_sink(runtime: CameraRuntime) -> None:
        await runtime.sink.open()

    def _announce(self, camera_id: str, change: str) -> None:
        self._event_bus.dispatch(
            DomainEvent.CAMERAS_CHANGED, {"camera_id": camera_id, "change": change}
        )

    def statuses(self) -> dict[str, CameraConnectionStatus]:
        """Every camera's current status, by id."""
        now = datetime.now(UTC)
        return {runtime.camera_id: runtime.snapshot(now=now).status for runtime in self.runtimes()}
