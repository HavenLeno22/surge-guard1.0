"""The perception pipeline - Stages 1 to 3 wired together.

::

    FrameSource ──► Detector ──► Tracker ──► PerceptionResult

This is the working half of the AI Pipeline that exists today. Crowd analysis,
stability assessment and decision intelligence (Stages 4 to 7) are later phases;
this pipeline stops where perception stops and emits what it actually measured,
rather than passing partially-invented crowd metrics downstream.

**Mode switching costs nothing.** Live Camera Mode and Demonstration Mode differ
only in which :class:`~surgeguard_ai.perception.frame_source.FrameSource` is
attached. There is no branch on
:class:`~surgeguard_ai.contracts.enums.SourceMode` here or anywhere else in the
package; the mode travels to the consumer as provenance on the result.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ParamSpec, TypeVar

from ..contracts.camera import CameraConfig
from ..contracts.enums import SourceMode
from ..contracts.perception import DetectionResult, PerceptionResult, TrackingResult
from ..errors import (
    DetectionError,
    PipelineError,
    SourceEnded,
    SourceUnavailableError,
    TrackingError,
)
from ..perception.detector import Detector
from ..perception.frame_source import Frame, FrameSource
from ..perception.tracker import Tracker
from .pipeline import Pipeline, PipelineStatus

__all__ = [
    "PerceptionPipeline",
    "PerceptionPipelineConfig",
    "PerceptionResultHandler",
    "FrameHandler",
]

logger = logging.getLogger(__name__)

#: Receives each completed perception result. Asynchronous so that the same
#: signature serves a console writer today and an
#: :class:`~surgeguard_ai.sinks.base.AnalysisSink` once later stages exist.
PerceptionResultHandler = Callable[[PerceptionResult], Awaitable[None]]

#: Receives the decoded image alongside the result for that same frame.
#:
#: **Synchronous, and called on the pipeline thread**, because that is where the
#: image already is. A consumer that needs pixels - a video stream, a recorder,
#: a snapshot writer - would otherwise force the frame across a thread boundary
#: it has no reason to cross. Anything slow here costs frames, so a consumer is
#: expected to encode and return.
#:
#: Deliberately not part of :class:`~surgeguard_ai.contracts.perception.PerceptionResult`:
#: a raw image buffer is not serialisable and must never become a contract.
FrameHandler = Callable[["Frame", PerceptionResult], None]

_P = ParamSpec("_P")
_R = TypeVar("_R")


@dataclass(frozen=True, slots=True)
class PerceptionPipelineConfig:
    """Tuning for the frame loop.

    Attributes:
        fps_window: Frames averaged for the reported throughput. Long enough to
            be steady, short enough to show a real slowdown promptly.
        max_consecutive_failures: Frames that may fail in a row before the
            pipeline declares itself degraded and stops. A single undecodable
            frame is normal; an unbroken run of them means the source or the
            model is broken and continuing would produce a silent zero count.
        stop_timeout_s: How long :meth:`PerceptionPipeline.stop` waits for the
            frame loop to finish its current frame before cancelling it.
    """

    fps_window: int = 30
    max_consecutive_failures: int = 30
    stop_timeout_s: float = 5.0


class PerceptionPipeline(Pipeline):
    """Runs frames through detection and tracking, sequentially and in order.

    Every frame the source delivers is processed; nothing is sampled or skipped
    here. When the consumer cannot keep up it is the *source* that drops
    material - exactly as a live camera does under load - so that what is
    analysed is always the most recent view of the crowd rather than a growing
    backlog of the past.

    The frame loop runs as an asyncio task, with the blocking work - frame
    acquisition, inference, association - executed on **one dedicated worker
    thread** so that a slow frame cannot stall an application hosting this
    pipeline.

    That the thread is dedicated rather than borrowed from a shared pool is not
    incidental. The :class:`~surgeguard_ai.perception.detector.Detector` contract
    promises only single-threaded use, and moving inference between threads is
    measurably expensive: each thread that first touches CUDA pays its own
    initialisation, which was observed to cost several seconds mid-run.
    """

    def __init__(
        self,
        camera: CameraConfig,
        detector: Detector,
        tracker: Tracker,
        *,
        on_result: PerceptionResultHandler | None = None,
        on_frame: FrameHandler | None = None,
        config: PerceptionPipelineConfig | None = None,
    ) -> None:
        """
        Args:
            camera: The camera being watched. Supplies identity and, once
                calibrated, the ground-plane projection tracking uses.
            detector: Stage 2.
            tracker: Stage 3.
            on_result: Called with every completed result. A handler that raises
                is logged and ignored - a consumer failure must never stop the
                monitoring it consumes from (``04:838-849``).
            config: Frame-loop tuning. Defaults are suitable for the documented
                performance budget.
        """
        self._camera = camera
        self._detector = detector
        self._tracker = tracker
        self._on_result = on_result
        self._on_frame = on_frame
        self._config = config or PerceptionPipelineConfig()

        self._source: FrameSource | None = None
        # Identity is kept after the source is released so that a summary or a
        # health panel read after shutdown still says what was being watched.
        self._source_id: str | None = None
        self._source_mode = SourceMode.LIVE
        self._task: asyncio.Task[None] | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._stopping = False

        self._frames_processed = 0
        self._frames_dropped = 0
        self._consecutive_failures = 0
        self._last_seq: int | None = None
        self._last_frame_ts: datetime | None = None
        self._recent_completions: deque[float] = deque(maxlen=self._config.fps_window)
        self._degraded_reason: str | None = None

    # -- Observation --------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def status(self) -> PipelineStatus:
        """Current pipeline health, for the System Health panel."""
        return PipelineStatus(
            running=self.is_running,
            source_id=self._source_id,
            source_mode=self._source_mode if self._source_id else None,
            frames_processed=self._frames_processed,
            frames_dropped=self._frames_dropped,
            achieved_fps=self._achieved_fps(),
            last_frame_ts=(
                self._last_frame_ts.isoformat() if self._last_frame_ts is not None else None
            ),
            degraded=self._degraded_reason is not None,
            degraded_reason=self._degraded_reason,
        )

    # -- Lifecycle ----------------------------------------------------------

    async def start(self, source: FrameSource) -> None:
        """Load the detector if needed, open the source, and begin processing."""
        if self.is_running:
            raise PipelineError("Pipeline is already running")

        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"surgeguard-perception-{self._camera.camera_id}",
            )

        # Loading happens on the pipeline thread so that model initialisation and
        # every later inference share one thread, and so the source's clock does
        # not start until the detector is warm.
        if not self._detector.is_ready:
            await self._in_pipeline_thread(self._detector.load)

        await self._in_pipeline_thread(source.open)

        self._source = source
        # Copied once so that provenance is available without the frame loop
        # ever asking the source what kind of source it is.
        self._source_id = source.source_id
        self._source_mode = source.source_mode
        self._stopping = False
        self._degraded_reason = None
        self._consecutive_failures = 0
        self._last_seq = None
        self._recent_completions.clear()

        self._task = asyncio.create_task(self._run(), name=f"perception:{source.source_id}")
        logger.info(
            "Perception pipeline started: camera=%s source=%s mode=%s fps=%.2f",
            self._camera.camera_id,
            source.source_id,
            source.source_mode.value,
            source.fps,
        )

    async def stop(self) -> None:
        """Stop processing, release the source, and end the pipeline thread.

        Idempotent. A pipeline restarted after this pays one-time thread
        initialisation again - on CUDA, several seconds. Switching what is being
        watched should therefore go through :meth:`swap_source`, which keeps the
        thread, rather than a stop-then-start pair.
        """
        await self._halt_loop()

        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

        logger.info(
            "Perception pipeline stopped after %d frame(s), %d dropped",
            self._frames_processed,
            self._frames_dropped,
        )

    async def _halt_loop(self) -> None:
        """End the frame loop and release the current source, keeping the thread."""
        self._stopping = True

        if self._task is not None:
            await self._await_task()
            self._task = None

        if self._source is not None:
            # Closed on a separate thread rather than the pipeline thread: if the
            # loop is wedged inside a blocking read, releasing the capture is
            # what unblocks it, so queueing the close behind that read would
            # deadlock the shutdown it is meant to complete.
            await asyncio.to_thread(self._source.close)
            self._source = None

    async def _in_pipeline_thread(
        self,
        function: Callable[_P, _R],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        """Run blocking work on the single dedicated pipeline thread."""
        if self._executor is None:
            raise PipelineError("Pipeline thread is not running")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: function(*args, **kwargs),
        )

    async def _await_task(self) -> None:
        """Let the current frame finish, then cancel if the loop is wedged."""
        assert self._task is not None  # noqa: S101 - guarded by the caller
        try:
            await asyncio.wait_for(
                asyncio.shield(self._task),
                timeout=self._config.stop_timeout_s,
            )
        except TimeoutError:
            logger.warning(
                "Frame loop did not stop within %.1fs; cancelling",
                self._config.stop_timeout_s,
            )
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        except asyncio.CancelledError:
            await asyncio.gather(self._task, return_exceptions=True)
            raise

    async def swap_source(self, source: FrameSource) -> None:
        """Replace the frame source, discarding state from the previous one.

        This is the whole of Live/Demo switching and of scenario selection. The
        stages themselves are untouched: no model is reloaded, no configuration
        changes - and, deliberately, **the pipeline thread is not replaced**.
        Inference is many times slower on a thread that has not run it before, so
        a swap that recreated the thread would stall for seconds at exactly the
        moment a presenter changes scenario.
        """
        await self._halt_loop()
        self._reset_state()
        await self.start(source)

    async def reset(self) -> None:
        """Discard accumulated state without changing the source.

        Backs One-Click Reset (``11:619-629``). Tracking identities, movement
        history and throughput counters are cleared; the source keeps playing and
        the model stays loaded.
        """
        self._reset_state()
        logger.info("Perception pipeline reset")

    def _reset_state(self) -> None:
        """Clear every stateful stage and every accumulated counter."""
        self._tracker.reset()
        self._frames_processed = 0
        self._frames_dropped = 0
        self._consecutive_failures = 0
        self._last_seq = None
        self._last_frame_ts = None
        self._recent_completions.clear()
        self._degraded_reason = None

    async def wait_closed(self) -> None:
        """Wait for the frame loop to finish.

        Returns as soon as the source is exhausted, is lost beyond recovery, or
        :meth:`stop` has been called. A live camera runs until stopped.
        """
        if self._task is not None:
            await asyncio.shield(asyncio.gather(self._task, return_exceptions=True))

    # -- Frame loop ---------------------------------------------------------

    async def _run(self) -> None:
        """Read, process and emit until the source ends or the pipeline stops."""
        source = self._source
        assert source is not None  # noqa: S101 - set by start()

        try:
            while not self._stopping:
                try:
                    frame = await self._in_pipeline_thread(source.read)
                except SourceEnded:
                    logger.info(
                        "Source %s reached its end after %d processed frame(s)",
                        source.source_id,
                        self._frames_processed,
                    )
                    return
                except SourceUnavailableError as exc:
                    self._degraded_reason = f"Frame source lost: {exc}"
                    logger.error("Frame source %s lost: %s", source.source_id, exc)
                    return

                if frame is None:
                    # A recoverable gap - a dropped packet, a skipped frame, a
                    # camera that just reconnected. Not a failure.
                    self._frames_dropped += 1
                    continue

                result = await self._in_pipeline_thread(self._process, frame)
                if result is None:
                    return

                await self._deliver(result)
        except asyncio.CancelledError:
            logger.debug("Frame loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - the loop must never fail silently
            # An unhandled failure here would otherwise be stored on the task and
            # never retrieved: monitoring would simply stop, with the pipeline
            # still reporting itself healthy. That is the one failure mode a
            # safety display must not have.
            self._degraded_reason = f"Frame loop failed: {exc}"
            logger.exception("Frame loop failed; monitoring has stopped")

    def _process(self, frame: Frame) -> PerceptionResult | None:
        """Run one frame through detection and tracking.

        Returns:
            The result for this frame, or ``None`` when the pipeline has failed
            too many frames in a row to keep going.
        """
        started = time.perf_counter()
        self._note_continuity(frame)

        degraded_reason: str | None = None

        try:
            detections = self._detector.detect(frame)
        except DetectionError as exc:
            logger.warning("Detection failed on frame %d: %s", frame.seq, exc)
            degraded_reason = f"Detection unavailable: {exc}"
            detections = DetectionResult(frame_seq=frame.seq, frame_ts=frame.ts)
            tracking = TrackingResult(frame_seq=frame.seq, frame_ts=frame.ts)
        else:
            try:
                tracking = self._tracker.update(frame, detections, self._camera)
            except TrackingError as exc:
                logger.warning("Tracking failed on frame %d: %s", frame.seq, exc)
                degraded_reason = f"Tracking unavailable: {exc}"
                tracking = TrackingResult(frame_seq=frame.seq, frame_ts=frame.ts)

        if degraded_reason is None:
            self._consecutive_failures = 0
        elif not self._register_failure(degraded_reason):
            return None

        completed = time.perf_counter()
        self._recent_completions.append(completed)
        self._frames_processed += 1
        self._last_frame_ts = frame.ts
        self._degraded_reason = degraded_reason

        result = PerceptionResult(
            camera_id=self._camera.camera_id,
            source_mode=self._source_mode,
            frame_seq=frame.seq,
            frame_ts=frame.ts,
            produced_at=datetime.now(UTC),
            person_count=self._count(detections, tracking, degraded=degraded_reason is not None),
            detections=detections,
            tracking=tracking,
            inference_ms=detections.inference_ms,
            processing_ms=(completed - started) * 1000.0,
            achieved_fps=self._achieved_fps(),
            degraded=degraded_reason is not None,
            degraded_reason=degraded_reason,
        )

        self._offer_frame(frame, result)
        return result

    def _offer_frame(self, frame: Frame, result: PerceptionResult) -> None:
        """Hand the image and its result to a pixel consumer, if one is attached.

        Isolated like every other consumer boundary in this pipeline: a video
        stream that fails is a video problem, never a reason to stop analysing
        (``04:838-849``).
        """
        if self._on_frame is None:
            return
        try:
            self._on_frame(frame, result)
        except Exception:  # noqa: BLE001 - a consumer must never stop monitoring
            logger.exception("Frame handler failed for frame %d", frame.seq)

    @staticmethod
    def _count(
        detections: DetectionResult,
        tracking: TrackingResult,
        *,
        degraded: bool,
    ) -> int:
        """Report the crowd count from the most trustworthy stage that ran.

        Tracks are the better answer - they are distinct people rather than
        distinct boxes - but when tracking did not run, falling back to the
        detection count is more honest than reporting zero.
        """
        if degraded and tracking.count == 0:
            return detections.count
        return tracking.count

    def _note_continuity(self, frame: Frame) -> None:
        """Detect a break in the frame sequence and react to it.

        A source restarts its sequence at 0 whenever it is reopened - a camera
        reconnection, a demonstration clip looping. Movement history spanning
        that gap describes motion that never happened, so tracking state is
        discarded at the seam.
        """
        previous = self._last_seq
        self._last_seq = frame.seq

        if previous is None:
            return

        if frame.seq <= previous:
            logger.info(
                "Frame sequence restarted (%d -> %d); discarding tracking state",
                previous,
                frame.seq,
            )
            self._tracker.reset()
            return

        skipped = frame.seq - previous - 1
        if skipped > 0:
            # The source dropped material to hold real-time pacing. Recorded so
            # the health panel reports the true frame budget rather than only
            # what survived to be analysed.
            self._frames_dropped += skipped

    def _register_failure(self, reason: str) -> bool:
        """Count a failed frame; report whether processing should continue."""
        self._consecutive_failures += 1
        if self._consecutive_failures < self._config.max_consecutive_failures:
            return True

        self._degraded_reason = (
            f"{self._consecutive_failures} consecutive frames failed: {reason}"
        )
        logger.error(
            "Stopping frame loop after %d consecutive failures: %s",
            self._consecutive_failures,
            reason,
        )
        return False

    def _achieved_fps(self) -> float:
        """Throughput over the rolling window, in frames per second."""
        if len(self._recent_completions) < 2:
            return 0.0
        elapsed = self._recent_completions[-1] - self._recent_completions[0]
        if elapsed <= 0:
            return 0.0
        return (len(self._recent_completions) - 1) / elapsed

    async def _deliver(self, result: PerceptionResult) -> None:
        """Hand a result to the consumer, isolating it from consumer failure."""
        if self._on_result is None:
            return
        try:
            await self._on_result(result)
        except Exception:  # noqa: BLE001 - a consumer must never stop monitoring
            logger.exception("Result handler failed for frame %d", result.frame_seq)
