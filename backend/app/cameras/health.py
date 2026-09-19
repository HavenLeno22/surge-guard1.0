"""Background health checks for one network camera.

Two things are learned on a slow timer, both without touching the video stream:

- **Device details** - round-trip time, battery level and device name, from
  DroidCam's small device endpoints. Battery matters more than it sounds: a
  phone camera at 8% is a camera about to go offline mid-demonstration.
- **Why a camera is not connecting** - only while it is not connected. A
  diagnosis while SurgeGuard holds the stream would be a second client, which is
  exactly what a DroidCam phone refuses.

And one thing is acted on: a device that stops answering and then answers again
has come back, so a camera waiting out a recovery backoff is told to reconnect
now. A backoff is sized for an absent camera; a phone that has rejoined the
network should not sit idle for the rest of it.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime

from surgeguard_ai.contracts import SourceMode

from ..core.logging import get_logger
from ..workers.perception_worker import PerceptionWorkerState
from .probe import (
    CameraDeviceInfo,
    StreamDiagnosis,
    StreamOutcome,
    diagnose_stream,
    fetch_device_info,
    is_network_url,
)

__all__ = ["CameraHealthMonitor", "probe_address"]

logger = get_logger(__name__)

#: Worker states in which the stream is not held, so a diagnosis competes with
#: nothing.
_DIAGNOSABLE_STATES = frozenset(
    {PerceptionWorkerState.RECOVERING, PerceptionWorkerState.FAILED}
)


def probe_address(stream_url: str | None, source_mode: SourceMode) -> str | None:
    """The address a camera's health checks should probe, if any.

    Only a live camera reads its stream address. In Demonstration Mode frames
    come from a recorded clip, so the phone or IP camera configured for it is
    not what the camera depends on: probing it would report a silent phone as
    the reason a clip failed, and show that phone's battery beside a recording.
    """
    return stream_url if source_mode is SourceMode.LIVE else None


class CameraHealthMonitor:
    """Periodically checks one camera's device and, when it is down, why."""

    def __init__(
        self,
        *,
        camera_id: str,
        url_provider: Callable[[], str | None],
        state_provider: Callable[[], PerceptionWorkerState],
        interval_seconds: float = 10.0,
        diagnose_interval_seconds: float = 15.0,
        on_device_returned: Callable[[], None] | None = None,
    ) -> None:
        """
        Args:
            camera_id: The camera being checked, for logs.
            url_provider: The camera's current stream address.
            state_provider: The camera worker's current state.
            interval_seconds: Time between device checks.
            diagnose_interval_seconds: Minimum time between stream diagnoses
                while the camera is down.
            on_device_returned: Called when the device answers again after
                failing to, while the camera is recovering - the worker's
                ``retry_now``.
        """
        self._camera_id = camera_id
        self._url_provider = url_provider
        self._state_provider = state_provider
        self._interval = interval_seconds
        self._diagnose_interval = diagnose_interval_seconds
        self._on_device_returned = on_device_returned

        self._task: asyncio.Task[None] | None = None
        self._device: CameraDeviceInfo | None = None
        self._device_checked_at: datetime | None = None
        self._device_reachable: bool | None = None
        self._diagnosis: StreamDiagnosis | None = None
        self._diagnosed_at: datetime | None = None
        self._wake = asyncio.Event()

    # -- Reading ------------------------------------------------------------

    @property
    def device(self) -> CameraDeviceInfo | None:
        return self._device

    @property
    def device_checked_at(self) -> datetime | None:
        return self._device_checked_at

    @property
    def device_reachable(self) -> bool | None:
        """Whether the device answered its last check; ``None`` before the first."""
        return self._device_reachable

    @property
    def diagnosis(self) -> StreamDiagnosis | None:
        """Why the stream is not delivering, when that has been determined."""
        return self._diagnosis

    @property
    def diagnosed_at(self) -> datetime | None:
        return self._diagnosed_at

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"camera-health:{self._camera_id}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def reset(self) -> None:
        """Forget everything learned - the camera's address has changed."""
        self._device = None
        self._device_checked_at = None
        self._device_reachable = None
        self._diagnosis = None
        self._diagnosed_at = None
        self._wake.set()

    def check_soon(self) -> None:
        """Run the next check now rather than at the end of the interval."""
        self._wake.set()

    # -- Loop ---------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a health check must never die
                logger.warning(
                    "Camera health check failed",
                    exc_info=error,
                    extra={"camera_id": self._camera_id},
                )
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)

    async def check_once(self) -> None:
        """Run one round of checks."""
        url = self._url_provider()
        if not is_network_url(url):
            self._device = None
            self._device_reachable = None
            return
        assert url is not None  # noqa: S101 - is_network_url rejects None

        info = await asyncio.to_thread(fetch_device_info, url)
        returned = info is not None and self._device_reachable is False
        self._device = info
        self._device_reachable = info is not None
        self._device_checked_at = datetime.now(UTC)

        state = self._state_provider()
        if state not in _DIAGNOSABLE_STATES:
            if state is PerceptionWorkerState.RUNNING:
                self._diagnosis = None
                self._diagnosed_at = None
            return

        if returned and state is PerceptionWorkerState.RECOVERING and self._on_device_returned:
            # Reconnecting is the test, so the stream is not diagnosed first: a
            # DroidCam phone can still be counting a diagnosis as its one viewer
            # when the worker arrives a moment later, and would turn it away.
            logger.info(
                "Camera device answers again; reconnecting now",
                extra={"camera_id": self._camera_id},
            )
            self._diagnosis = None
            self._diagnosed_at = None
            self._on_device_returned()
            return

        if self._diagnosed_at is not None and (
            (datetime.now(UTC) - self._diagnosed_at).total_seconds() < self._diagnose_interval
        ):
            return

        if info is None:
            # The device did not answer at all; opening the stream would say no more.
            self._diagnosis = StreamDiagnosis(
                StreamOutcome.UNREACHABLE,
                "The camera's device does not answer on the network. Check that the "
                "phone is awake, on the same network, and DroidCam is open.",
            )
        else:
            self._diagnosis = await asyncio.to_thread(diagnose_stream, url)
        self._diagnosed_at = datetime.now(UTC)
