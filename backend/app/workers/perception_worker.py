"""Background supervision of the perception pipeline.

The pipeline runs independently of the HTTP surface. The worker starts it,
watches it, and puts it back when it falls over - none of which may block a
request, and none of which may take the backend down with it.

**Why supervision is not optional.** ``04:793-855`` and ``05:866-945`` require
the platform to degrade rather than fail: a camera that disconnects is
reconnected, an AI failure leaves the rest of the platform serving, and
processing resumes automatically once the fault clears. A pipeline started once
and never watched satisfies none of that - it stops silently, and the Command
Center goes on displaying the last crowd it saw.

**Startup never blocks.** Loading model weights and initialising CUDA takes
seconds. The worker returns as soon as its supervision task is scheduled, so the
API answers while the model is still loading and the System Health panel reports
the AI Pipeline as starting rather than the process appearing hung.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto

from surgeguard_ai.contracts import CameraConfig
from surgeguard_ai.errors import (
    DetectionError,
    SourceUnavailableError,
    SurgeGuardAIError,
)
from surgeguard_ai.perception import DeviceInfo, FrameSource, YoloDetector
from surgeguard_ai.pipeline import PerceptionPipeline
from surgeguard_ai.pipeline.perception_pipeline import FrameHandler, PipelineStatus
from surgeguard_ai.sinks import PerceptionSink

from ..core.config import Settings
from ..core.exceptions import ConfigurationError
from ..core.logging import get_logger
from ..services.perception_state import PerceptionStateService
from .perception_factory import (
    build_detector,
    build_frame_source,
    build_pipeline,
    build_tracker,
)

__all__ = ["PerceptionWorker", "PerceptionWorkerState"]

logger = get_logger(__name__)

#: How long shutdown waits for the supervision task to unwind before cancelling.
_SHUTDOWN_TIMEOUT_SECONDS = 15.0


class PerceptionWorkerState(StrEnum):
    """What the worker is currently doing.

    Distinguishes the ways monitoring can be absent, because they call for
    different operator responses: a clip that finished is not a camera that
    failed, and neither is a pipeline that was never switched on.
    """

    DISABLED = "disabled"
    """Not configured to run. The API serves without a camera or a GPU."""

    STOPPED = "stopped"
    """Configured but not started, or deliberately stopped."""

    STARTING = "starting"
    """Loading model weights, initialising the device, opening the source."""

    RUNNING = "running"
    """Processing frames."""

    RECOVERING = "recovering"
    """Failed and waiting to retry. Monitoring is not happening."""

    COMPLETED = "completed"
    """The source ended of its own accord - a demonstration clip finished."""

    FAILED = "failed"
    """Gave up. The rest of the platform continues to serve."""

    @property
    def is_monitoring(self) -> bool:
        """Whether frames are actually being processed in this state."""
        return self is PerceptionWorkerState.RUNNING


class _Outcome(StrEnum):
    """How one supervision attempt ended.

    Three outcomes, not two. Collapsing "the clip finished" and "there is no
    clip configured" into a single "not running" would report a
    misconfiguration as a completed demonstration - which is exactly the class
    of silent wrongness this platform is built to avoid.
    """

    COMPLETED = auto()
    """The source ended of its own accord. Expected; do not retry."""

    RECOVERABLE = auto()
    """Something failed that trying again might fix."""

    ABANDONED = auto()
    """Something failed that trying again cannot fix."""


@dataclass(frozen=True, slots=True)
class _AttemptResult:
    """The outcome of one supervision attempt, with its explanation."""

    outcome: _Outcome
    detail: str | None = None


class PerceptionWorker:
    """Runs and supervises the perception pipeline.

    Owns the pipeline, the detector and the tracker for the life of the process.
    Recovery swaps in a fresh frame source rather than rebuilding any of them:
    a rebuild would reload the model and move inference onto a new thread, and
    both cost seconds that a recovering camera should not also have to pay.
    """

    def __init__(
        self,
        settings: Settings,
        sink: PerceptionSink,
        state: PerceptionStateService,
        on_frame: FrameHandler | None = None,
        *,
        source_factory: Callable[[], FrameSource] | None = None,
        camera_factory: Callable[[], CameraConfig] | None = None,
        camera_id: str | None = None,
    ) -> None:
        """
        Args:
            settings: Configuration.
            sink: Where perception results are delivered.
            state: The perception state this worker clears when it stops.
            on_frame: Pixel consumer - the live video stream - called on the
                pipeline thread that already holds each image.
            source_factory: Builds a fresh frame source for this camera. A
                worker supervising one camera among several is handed its own;
                without one, the configured primary camera is used, exactly as
                before multi-camera support existed.
            camera_factory: Describes the camera being watched. Defaults to the
                primary camera from settings.
            camera_id: Identity for logs and status. Defaults to the primary
                camera's.
        """
        self._settings = settings
        self._sink = sink
        self._state = state
        # Handed to the pipeline so a pixel consumer - the live video stream -
        # receives images on the thread that already holds them.
        self._on_frame = on_frame
        self._source_factory = source_factory
        self._camera_factory = camera_factory
        self._camera_id = camera_id or settings.camera_id

        self._detector: YoloDetector | None = None
        self._pipeline: PerceptionPipeline | None = None
        self._source: FrameSource | None = None

        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._retry_requested = asyncio.Event()
        self._lifecycle = asyncio.Lock()
        # Incremented whenever the source is replaced deliberately while running,
        # so supervision can tell a swap from the pipeline stopping on its own.
        self._swap_generation = 0
        self._swap_error: BaseException | None = None

        self._worker_state = (
            PerceptionWorkerState.STOPPED
            if settings.pipeline_enabled
            else PerceptionWorkerState.DISABLED
        )
        self._detail: str | None = (
            None if settings.pipeline_enabled else "The perception pipeline is disabled."
        )
        self._state_changed_at = datetime.now(UTC)
        self._restart_attempts = 0
        self._total_restarts = 0

    # -- Observation --------------------------------------------------------

    @property
    def state(self) -> PerceptionWorkerState:
        """What the worker is currently doing."""
        return self._worker_state

    @property
    def detail(self) -> str | None:
        """Why the worker is in its current state, in operator-readable terms."""
        return self._detail

    @property
    def state_changed_at(self) -> datetime:
        """When the worker last changed state."""
        return self._state_changed_at

    @property
    def restart_attempts(self) -> int:
        """Consecutive recovery attempts since the last successful start."""
        return self._restart_attempts

    @property
    def total_restarts(self) -> int:
        """Recoveries performed since startup. A rising count means instability."""
        return self._total_restarts

    @property
    def source_mode(self) -> str:
        """Configured mode - Live Camera or Demonstration."""
        return self._settings.pipeline_source_mode.value

    @property
    def pipeline_status(self) -> PipelineStatus | None:
        """The pipeline's own status, or ``None`` before it has been built."""
        return self._pipeline.status if self._pipeline is not None else None

    @property
    def device(self) -> DeviceInfo | None:
        """The compute device inference resolved to, once the model has loaded.

        Reported rather than assumed: a configured ``cuda`` that silently became
        CPU looks identical to a working GPU until the frame rate matters.
        """
        return self._detector.device_info if self._detector is not None else None

    @property
    def uses_half_precision(self) -> bool:
        """Whether inference is actually running in FP16.

        Asked of the detector rather than inferred from the device: a GPU that
        supports half precision is not the same as one using it.
        """
        return self._detector is not None and self._detector.uses_half_precision

    @property
    def model_name(self) -> str | None:
        """The detection checkpoint in use."""
        return self._detector.name if self._detector is not None else None

    @property
    def camera_id(self) -> str:
        """The camera this worker supervises."""
        return self._camera_id

    @property
    def source(self) -> FrameSource | None:
        """The frame source currently attached, if any.

        Exposed for health reporting - its native resolution and declared frame
        rate - and never for reading: frames belong to the pipeline thread.
        """
        return self._source

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Begin supervising. Returns as soon as the task is scheduled.

        Deliberately does not wait for the model to load or the source to open.
        Those take seconds, and a backend that cannot answer a health check until
        a GPU has warmed up is a backend that looks broken while it is working.
        """
        if not self._settings.pipeline_enabled:
            logger.info("Perception pipeline is disabled by configuration")
            return

        if self._task is not None and not self._task.done():
            logger.debug("Perception worker is already running")
            return

        self._stopping.clear()
        self._restart_attempts = 0
        self._set_state(PerceptionWorkerState.STARTING, "Starting the perception pipeline.")

        self._task = asyncio.create_task(
            self._supervise(), name=f"perception-worker:{self._camera_id}"
        )
        logger.info(
            "Perception worker started",
            extra={
                "source_mode": self.source_mode,
                "camera_id": self._camera_id,
                "model": self._settings.detection_model,
                "device": self._settings.detection_device,
            },
        )

    def retry_now(self) -> None:
        """End a recovery backoff early and try to connect immediately.

        For when an operator has just fixed the cause - corrected an address,
        closed the other client holding a DroidCam stream - and should not have
        to wait out a doubling delay that was sized for an absent camera.

        A camera whose supervision has already given up (a misconfiguration is
        deliberately not retried on its own) is started again: an operator
        asking, or a corrected source arriving, is exactly the signal that the
        cause may be gone. A stopped worker stays stopped.
        """
        supervision_ended = self._task is not None and self._task.done()
        if supervision_ended and not self._stopping.is_set() and self._settings.pipeline_enabled:
            self._restart_attempts = 0
            self._retry_requested.clear()
            self._set_state(PerceptionWorkerState.STARTING, "Retrying the perception pipeline.")
            self._task = asyncio.create_task(
                self._supervise(), name=f"perception-worker:{self._camera_id}"
            )
            return
        self._retry_requested.set()

    async def replace_source(self, source_factory: Callable[[], FrameSource]) -> None:
        """Point this camera at a new stream without restarting the worker.

        When the pipeline is running the source is swapped in place, keeping
        the loaded model and the warmed inference thread. When it is not - still
        starting, recovering, or failed - the new factory is simply what the
        next attempt uses, and a pending backoff is cut short.

        A new source that cannot be opened is not raised to the caller: the
        worker records it and goes into recovery against the new address,
        which is the same path a camera dropping out takes.
        """
        async with self._lifecycle:
            self._source_factory = source_factory
            pipeline = self._pipeline

            if pipeline is None or not pipeline.status.running:
                self.retry_now()
                return

            try:
                source = source_factory()
            except Exception as error:  # noqa: BLE001 - reported through recovery
                self._swap_error = error
                self._swap_generation += 1
                await pipeline.stop()
                return

            self._swap_generation += 1
            try:
                await pipeline.swap_source(source)
            except Exception as error:  # noqa: BLE001 - reported through recovery
                self._swap_error = error
                return
            self._source = source
            logger.info(
                "Camera source replaced",
                extra={"camera_id": self._camera_id, "source_id": source.source_id},
            )

    async def stop(self) -> None:
        """Stop supervising and release the pipeline. Idempotent.

        Stops the pipeline first: the supervision task is usually parked in
        ``wait_closed()``, and it is the pipeline finishing that lets it notice
        the shutdown.
        """
        self._stopping.set()

        async with self._lifecycle:
            if self._pipeline is not None:
                await self._pipeline.stop()

        if self._task is not None:
            await self._await_task(self._task)
            self._task = None

        # The platform is no longer monitoring; continuing to serve the last
        # result would imply that it is.
        self._state.clear()

        if self._worker_state is not PerceptionWorkerState.DISABLED:
            self._set_state(PerceptionWorkerState.STOPPED, "The pipeline was stopped.")

        logger.info(
            "Perception worker stopped",
            extra={"total_restarts": self._total_restarts},
        )

    async def _await_task(self, task: asyncio.Task[None]) -> None:
        """Let the supervision task unwind, cancelling it if it will not."""
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning(
                "Perception worker did not stop within %.0fs; cancelling",
                _SHUTDOWN_TIMEOUT_SECONDS,
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise
        except Exception as error:  # noqa: BLE001 - shutdown reports, never fails
            logger.error("Perception worker ended with an error", exc_info=error)

    # -- Supervision --------------------------------------------------------

    async def _supervise(self) -> None:
        """Run the pipeline, and keep running it, until asked to stop."""
        try:
            while not self._stopping.is_set():
                attempt = await self._run_once()

                if self._stopping.is_set():
                    return

                if attempt.outcome is _Outcome.ABANDONED:
                    # The state and the reason were recorded where the decision
                    # was made, by whichever handler knew why retrying is futile.
                    return

                if attempt.outcome is _Outcome.COMPLETED:
                    # The source ended of its own accord. A demonstration clip
                    # finishing is the expected outcome, not a fault to retry.
                    self._set_state(
                        PerceptionWorkerState.COMPLETED,
                        "The frame source reached its end.",
                    )
                    logger.info(
                        "Perception source completed",
                        extra={"source_mode": self.source_mode},
                    )
                    return

                if not await self._schedule_recovery(attempt.detail or "The pipeline failed."):
                    return
        except asyncio.CancelledError:
            logger.debug("Perception supervision cancelled")
            raise
        except Exception as error:  # noqa: BLE001 - the supervisor must not die quietly
            # Without this the exception would be stored on an unretrieved task
            # and monitoring would simply stop, with the worker still reporting
            # whatever state it was last in.
            self._set_state(
                PerceptionWorkerState.FAILED,
                "The perception worker failed unexpectedly.",
            )
            logger.exception("Perception supervision failed", exc_info=error)

    async def _run_once(self) -> _AttemptResult:
        """Run the pipeline until it stops, and say why it stopped."""
        try:
            async with self._lifecycle:
                if self._stopping.is_set():
                    return _AttemptResult(_Outcome.ABANDONED)
                await self._attach_source()
        except ConfigurationError as error:
            # Retrying a misconfiguration only produces the same failure more
            # often. Stop, and make the reason the operator-facing detail.
            self._set_state(PerceptionWorkerState.FAILED, error.message)
            logger.error(
                "Perception pipeline is misconfigured",
                extra={"error_code": error.error_code, **error.context},
            )
            return _AttemptResult(_Outcome.ABANDONED, error.message)
        except SourceUnavailableError as error:
            return self._recoverable(
                "The camera or video source could not be opened.", error
            )
        except DetectionError as error:
            return self._recoverable("The detection model could not be loaded.", error)
        except SurgeGuardAIError as error:
            return self._recoverable("The AI Pipeline could not be started.", error)
        except Exception as error:  # noqa: BLE001 - any start failure is recoverable
            return self._recoverable(
                "The perception pipeline could not be started.", error
            )

        self._restart_attempts = 0
        self._set_state(PerceptionWorkerState.RUNNING, None)
        logger.info(
            "Perception pipeline running",
            extra={
                "source_mode": self.source_mode,
                "device": self.device.device if self.device else "unknown",
                "model": self.model_name,
            },
        )

        assert self._pipeline is not None  # noqa: S101 - set by _attach_source
        while True:
            generation = self._swap_generation
            await self._pipeline.wait_closed()
            if self._stopping.is_set() or generation == self._swap_generation:
                break
            # The frame loop ended because an operator replaced the source.
            # Wait for the lifecycle lock so the swap has finished one way or
            # the other before deciding what happened.
            async with self._lifecycle:
                pass
            if self._swap_error is not None:
                error, self._swap_error = self._swap_error, None
                if isinstance(error, ConfigurationError):
                    self._set_state(PerceptionWorkerState.FAILED, error.message)
                    return _AttemptResult(_Outcome.ABANDONED, error.message)
                return self._recoverable(
                    "The camera could not be opened at its new address.", error
                )
            if not self._pipeline.status.running:
                break

        status = self._pipeline.status
        if status.degraded:
            return self._recoverable(
                status.degraded_reason or "The perception pipeline stopped unexpectedly.",
                None,
            )
        return _AttemptResult(_Outcome.COMPLETED)

    async def _attach_source(self) -> None:
        """Build a fresh frame source and give it to the pipeline.

        The first attempt builds the pipeline; later ones swap the source,
        keeping the loaded model and the warmed inference thread.
        """
        source = (
            self._source_factory()
            if self._source_factory is not None
            else build_frame_source(self._settings)
        )

        if self._pipeline is None:
            self._detector = build_detector(self._settings)
            tracker = build_tracker(self._settings, source.fps)
            camera = (
                {"camera": self._camera_factory()} if self._camera_factory is not None else {}
            )
            self._pipeline = build_pipeline(
                self._settings,
                self._sink,
                on_frame=self._on_frame,
                detector=self._detector,
                tracker=tracker,
                **camera,
            )
            await self._pipeline.start(source)
        else:
            await self._pipeline.swap_source(source)

        self._source = source

    async def _schedule_recovery(self, failure: str) -> bool:
        """Wait before the next attempt.

        Returns:
            True to try again, False when the worker has given up.
        """
        self._restart_attempts += 1
        self._total_restarts += 1

        limit = self._settings.pipeline_max_restart_attempts
        if limit and self._restart_attempts > limit:
            self._set_state(
                PerceptionWorkerState.FAILED,
                f"{failure} Recovery was attempted {limit} times without success.",
            )
            logger.error(
                "Perception worker gave up after %d recovery attempts",
                limit,
                extra={"failure": failure},
            )
            return False

        delay = self._backoff_seconds()
        self._set_state(
            PerceptionWorkerState.RECOVERING,
            f"{failure} Retrying in {delay:.0f}s.",
        )
        logger.warning(
            "Perception pipeline recovering",
            extra={
                "failure": failure,
                "attempt": self._restart_attempts,
                "retry_in_seconds": delay,
            },
        )

        # Interruptible: a shutdown during backoff must not wait out the delay,
        # and neither should an operator who has just fixed the camera.
        self._retry_requested.clear()
        stopping = asyncio.ensure_future(self._stopping.wait())
        retry = asyncio.ensure_future(self._retry_requested.wait())
        try:
            await asyncio.wait(
                {stopping, retry}, timeout=delay, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for waiter in (stopping, retry):
                waiter.cancel()
            await asyncio.gather(stopping, retry, return_exceptions=True)

        if self._stopping.is_set():
            return False
        if self._retry_requested.is_set():
            self._retry_requested.clear()
            logger.info("Recovery retried early", extra={"camera_id": self._camera_id})
        return True

    def _backoff_seconds(self) -> float:
        """Doubling backoff, capped.

        A camera that has been unplugged for an hour should not be probed
        thousands of times, and should still recover the moment it returns.
        """
        delay = self._settings.pipeline_restart_delay_seconds * (
            2 ** (self._restart_attempts - 1)
        )
        return min(delay, self._settings.pipeline_max_restart_delay_seconds)

    # -- Internals ----------------------------------------------------------

    def _recoverable(self, message: str, error: BaseException | None) -> _AttemptResult:
        """Log a failure worth retrying and describe it in operator terms."""
        logger.error(
            "Perception pipeline failure: %s",
            message,
            exc_info=error,
            extra={
                "source_mode": self.source_mode,
                "camera_id": self._camera_id,
            },
        )
        return _AttemptResult(_Outcome.RECOVERABLE, message)

    def _set_state(self, state: PerceptionWorkerState, detail: str | None) -> None:
        """Record a state change, logging only genuine transitions."""
        if state is not self._worker_state:
            logger.info(
                "Perception worker state changed",
                extra={
                    "from": self._worker_state.value,
                    "to": state.value,
                    "detail": detail,
                },
            )
        self._worker_state = state
        self._detail = detail
        self._state_changed_at = datetime.now(UTC)
