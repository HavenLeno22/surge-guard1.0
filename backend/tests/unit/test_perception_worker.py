"""Supervision of the perception pipeline.

The pipeline itself is replaced by a double. What is under test is the worker's
own judgement: what it does when a camera cannot be opened, when a clip ends,
when the model will not load, and when it is asked to stop mid-recovery. Every
one of those is a documented failure the platform has to survive
(``04:793-855``), and none of them needs a camera to provoke.
"""

from __future__ import annotations

import asyncio

import pytest
from surgeguard_ai.errors import DetectionError, SourceUnavailableError
from surgeguard_ai.pipeline import PipelineStatus

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.services.perception_state import PerceptionStateService
from app.workers import perception_worker as worker_module
from app.workers.perception_worker import PerceptionWorker, PerceptionWorkerState

from ..conftest import make_perception_result


class FakePipeline:
    """Stands in for the AI Pipeline, with a scriptable ending."""

    def __init__(self) -> None:
        self.started = 0
        self.swapped = 0
        self.stopped = 0
        self.sources: list[object] = []
        self.degraded_reason: str | None = None
        self._finished = asyncio.Event()

    async def start(self, source) -> None:
        self.started += 1
        self.sources.append(source)
        self._finished.clear()

    async def swap_source(self, source) -> None:
        self.swapped += 1
        self.sources.append(source)
        self._finished.clear()

    async def stop(self) -> None:
        self.stopped += 1
        self._finished.set()

    async def wait_closed(self) -> None:
        await self._finished.wait()

    def finish(self, *, degraded_reason: str | None = None) -> None:
        """End the current run, optionally as a failure."""
        self.degraded_reason = degraded_reason
        self._finished.set()

    @property
    def status(self) -> PipelineStatus:
        return PipelineStatus(
            running=not self._finished.is_set(),
            source_id="fake-source",
            source_mode=None,
            frames_processed=12,
            frames_dropped=1,
            achieved_fps=20.0,
            last_frame_ts=None,
            degraded=self.degraded_reason is not None,
            degraded_reason=self.degraded_reason,
        )


class FakeSource:
    """Stands in for a frame source. Only its declared frame rate is consulted."""

    fps = 25.0
    source_id = "fake-source"


class FakeSink:
    async def emit(self, result) -> None:
        pass

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.fixture
def worker_settings(tmp_path) -> Settings:
    """Settings with a fast backoff, so recovery tests do not wait on real time."""
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        log_level="WARNING",
        pipeline_enabled=True,
        pipeline_restart_delay_seconds=0.01,
        pipeline_max_restart_delay_seconds=0.02,
    )


@pytest.fixture
def patched_factory(monkeypatch: pytest.MonkeyPatch):
    """Replace the AI construction functions with controllable doubles.

    Returns a dict the test mutates to script what construction does.
    """
    control: dict[str, object] = {
        "pipeline": FakePipeline(),
        "source_error": None,
        "detector_error": None,
        "sources_built": 0,
    }

    def build_frame_source(_settings):
        control["sources_built"] = int(control["sources_built"]) + 1
        error = control["source_error"]
        if error is not None:
            raise error
        return FakeSource()

    def build_detector(_settings):
        error = control["detector_error"]
        if error is not None:
            raise error
        return None

    monkeypatch.setattr(worker_module, "build_frame_source", build_frame_source)
    monkeypatch.setattr(worker_module, "build_detector", build_detector)
    monkeypatch.setattr(worker_module, "build_tracker", lambda _s, _f: None)
    monkeypatch.setattr(
        worker_module,
        "build_pipeline",
        lambda *_args, **_kwargs: control["pipeline"],
    )
    return control


def make_worker(
    settings: Settings, state: PerceptionStateService | None = None
) -> PerceptionWorker:
    return PerceptionWorker(settings, FakeSink(), state or PerceptionStateService())


async def wait_for_state(
    worker: PerceptionWorker,
    state: PerceptionWorkerState,
    timeout: float = 2.0,
) -> None:
    """Poll until the worker reaches a state, so tests do not sleep blindly."""
    async with asyncio.timeout(timeout):
        while worker.state is not state:
            await asyncio.sleep(0.005)


class TestDisabled:
    async def test_a_disabled_worker_never_starts(self, tmp_path) -> None:
        """The API must be serviceable without a camera or a GPU."""
        settings = Settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            pipeline_enabled=False,
        )
        worker = make_worker(settings)

        await worker.start()

        assert worker.state is PerceptionWorkerState.DISABLED
        assert worker.pipeline_status is None
        await worker.stop()
        assert worker.state is PerceptionWorkerState.DISABLED


class TestRunning:
    async def test_starting_does_not_block(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """Loading a model takes seconds; startup must not wait for it."""
        worker = make_worker(worker_settings)

        async with asyncio.timeout(0.5):
            await worker.start()

        assert worker.state in {
            PerceptionWorkerState.STARTING,
            PerceptionWorkerState.RUNNING,
        }
        await worker.stop()

    async def test_the_pipeline_is_started_and_reaches_running(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)

        pipeline = patched_factory["pipeline"]
        assert pipeline.started == 1
        assert worker.pipeline_status is not None
        await worker.stop()

    async def test_stopping_releases_the_pipeline_and_the_current_view(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """After a deliberate stop, serving the last result would imply monitoring."""
        state = PerceptionStateService()
        state.record(make_perception_result())
        worker = make_worker(worker_settings, state)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        await worker.stop()

        assert patched_factory["pipeline"].stopped == 1
        assert worker.state is PerceptionWorkerState.STOPPED
        assert state.latest is None

    async def test_stop_is_idempotent(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        await worker.stop()
        await worker.stop()

        assert worker.state is PerceptionWorkerState.STOPPED


class TestSourceEnd:
    async def test_a_clip_reaching_its_end_is_not_a_failure(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """A demonstration clip finishing is the expected outcome, not a fault."""
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        patched_factory["pipeline"].finish()

        await wait_for_state(worker, PerceptionWorkerState.COMPLETED)

        assert worker.total_restarts == 0
        assert "end" in (worker.detail or "").lower()
        await worker.stop()

    async def test_a_completed_source_is_not_retried(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        patched_factory["pipeline"].finish()
        await wait_for_state(worker, PerceptionWorkerState.COMPLETED)

        await asyncio.sleep(0.1)

        assert patched_factory["pipeline"].started == 1
        assert patched_factory["pipeline"].swapped == 0
        await worker.stop()


class TestRecovery:
    async def test_a_camera_that_cannot_be_opened_is_retried(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """A disconnected camera must be reconnected, not given up on."""
        patched_factory["source_error"] = SourceUnavailableError("camera gone")
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)

        assert worker.restart_attempts >= 1
        assert "could not be opened" in (worker.detail or "")

        # And it keeps trying.
        await asyncio.sleep(0.1)
        assert int(patched_factory["sources_built"]) > 1
        await worker.stop()

    async def test_recovery_succeeds_once_the_camera_returns(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        patched_factory["source_error"] = SourceUnavailableError("camera gone")
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)

        patched_factory["source_error"] = None
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)

        assert worker.restart_attempts == 0  # reset by a successful start
        assert worker.total_restarts >= 1
        await worker.stop()

    async def test_a_degraded_pipeline_is_restarted(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """A pipeline that stopped because a stage broke is put back."""
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)

        patched_factory["pipeline"].finish(degraded_reason="Frame source lost: unplugged")
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)

        assert "unplugged" in (worker.detail or "")
        await worker.stop()

    async def test_recovery_swaps_the_source_and_keeps_the_model(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """Rebuilding would reload the model and move inference to a new thread."""
        worker = make_worker(worker_settings)
        pipeline = patched_factory["pipeline"]

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        pipeline.finish(degraded_reason="synthetic failure")
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)

        assert pipeline.started == 1  # built once
        assert pipeline.swapped >= 1  # source replaced
        await worker.stop()

    async def test_a_model_that_will_not_load_is_retried(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """A GPU or model failure degrades the platform; it does not end it."""
        patched_factory["detector_error"] = DetectionError("no CUDA, no CPU")
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)

        assert "model could not be loaded" in (worker.detail or "")
        await worker.stop()

    async def test_the_worker_gives_up_after_the_configured_limit(
        self, tmp_path, patched_factory
    ) -> None:
        settings = Settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            log_level="WARNING",
            pipeline_enabled=True,
            pipeline_restart_delay_seconds=0.01,
            pipeline_max_restart_delay_seconds=0.01,
            pipeline_max_restart_attempts=2,
        )
        patched_factory["source_error"] = SourceUnavailableError("camera gone")
        worker = make_worker(settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.FAILED)

        assert "2 times" in (worker.detail or "")
        await worker.stop()

    async def test_shutdown_during_backoff_does_not_wait_out_the_delay(
        self, tmp_path, patched_factory
    ) -> None:
        """A shutdown must not be held up by a recovery timer."""
        settings = Settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            log_level="WARNING",
            pipeline_enabled=True,
            pipeline_restart_delay_seconds=30.0,
            pipeline_max_restart_delay_seconds=30.0,
        )
        patched_factory["source_error"] = SourceUnavailableError("camera gone")
        worker = make_worker(settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)

        async with asyncio.timeout(2.0):
            await worker.stop()

        assert worker.state is PerceptionWorkerState.STOPPED


class SwappablePipeline(FakePipeline):
    """A double whose ``swap_source`` ends the current frame loop, as the real one does."""

    def __init__(self, *, swap_error: BaseException | None = None) -> None:
        super().__init__()
        self.swap_error = swap_error

    async def swap_source(self, source) -> None:
        self.swapped += 1
        finished = self._finished
        if self.swap_error is not None:
            finished.set()  # the old loop ended and the new source never started
            raise self.swap_error
        self.sources.append(source)
        self._finished = asyncio.Event()
        finished.set()


class TestPerCamera:
    """One worker per camera: its own source, its own identity, live re-pointing."""

    async def test_a_camera_specific_source_and_description_are_used(
        self, worker_settings: Settings, patched_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def build_pipeline(*_args, **kwargs):
            captured.update(kwargs)
            return patched_factory["pipeline"]

        monkeypatch.setattr(worker_module, "build_pipeline", build_pipeline)
        own_source = FakeSource()
        worker = PerceptionWorker(
            worker_settings,
            FakeSink(),
            PerceptionStateService(),
            source_factory=lambda: own_source,
            camera_factory=lambda: "camera-description",
            camera_id="cam-02",
        )

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)

        assert worker.camera_id == "cam-02"
        assert captured["camera"] == "camera-description"
        assert patched_factory["pipeline"].sources == [own_source]
        assert int(patched_factory["sources_built"]) == 0, "the primary camera was not touched"
        assert worker.source is own_source
        await worker.stop()

    async def test_replacing_the_source_while_running_keeps_supervising(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """An operator changing a phone's address must not leave the camera unwatched."""
        pipeline = SwappablePipeline()
        patched_factory["pipeline"] = pipeline
        first, second = FakeSource(), FakeSource()
        worker = PerceptionWorker(
            worker_settings, FakeSink(), PerceptionStateService(), source_factory=lambda: first
        )

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        await worker.replace_source(lambda: second)
        await asyncio.sleep(0.05)

        assert worker.state is PerceptionWorkerState.RUNNING
        assert pipeline.started == 1, "the model and thread were kept"
        assert pipeline.swapped == 1
        assert pipeline.sources[-1] is second
        assert worker.source is second

        # Still supervised: a later failure is still recovered from.
        pipeline.finish(degraded_reason="Frame source lost: phone left the network")
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)
        await worker.stop()

    async def test_a_new_address_that_cannot_open_goes_into_recovery(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        pipeline = SwappablePipeline(swap_error=SourceUnavailableError("busy"))
        patched_factory["pipeline"] = pipeline
        worker = PerceptionWorker(
            worker_settings, FakeSink(), PerceptionStateService(), source_factory=FakeSource
        )

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        await worker.replace_source(FakeSource)

        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)
        assert "new address" in (worker.detail or "") or "could not be opened" in (
            worker.detail or ""
        )
        await worker.stop()

    async def test_a_fixed_camera_is_retried_without_waiting_out_the_backoff(
        self, tmp_path, patched_factory
    ) -> None:
        settings = Settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            log_level="WARNING",
            pipeline_enabled=True,
            pipeline_restart_delay_seconds=30.0,
            pipeline_max_restart_delay_seconds=30.0,
        )

        def unavailable() -> FakeSource:
            raise SourceUnavailableError("DroidCam is busy")

        worker = PerceptionWorker(
            settings, FakeSink(), PerceptionStateService(), source_factory=unavailable
        )
        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.RECOVERING)

        async with asyncio.timeout(2.0):
            await worker.replace_source(FakeSource)
            await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        await worker.stop()


class TestMisconfiguration:
    async def test_a_misconfigured_pipeline_fails_rather_than_retrying(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """Retrying a missing configuration file only fails more often."""
        patched_factory["source_error"] = ConfigurationError(
            "No demonstration video is configured."
        )
        worker = make_worker(worker_settings)

        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.FAILED)

        assert worker.detail == "No demonstration video is configured."
        assert worker.total_restarts == 0

        await asyncio.sleep(0.1)
        assert int(patched_factory["sources_built"]) == 1
        await worker.stop()

    async def test_a_misconfigured_camera_starts_once_its_source_is_corrected(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """Supervision gave up on the bad clip; the corrected one must still be picked up."""

        def missing_clip() -> FakeSource:
            raise ConfigurationError("The demonstration clip for CAM-02 does not exist.")

        worker = PerceptionWorker(
            worker_settings, FakeSink(), PerceptionStateService(), source_factory=missing_clip
        )
        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.FAILED)

        await worker.replace_source(FakeSource)

        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        await worker.stop()

    async def test_an_operator_retry_restarts_a_misconfigured_camera(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        """The cause was fixed outside SurgeGuard (the clip was restored); Retry must act on it."""
        patched_factory["source_error"] = ConfigurationError("The clip does not exist.")
        worker = make_worker(worker_settings)
        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.FAILED)

        patched_factory["source_error"] = None
        worker.retry_now()

        await wait_for_state(worker, PerceptionWorkerState.RUNNING)
        await worker.stop()

    async def test_a_retry_after_stopping_does_not_start_the_camera(
        self, worker_settings: Settings, patched_factory
    ) -> None:
        patched_factory["source_error"] = ConfigurationError("The clip does not exist.")
        worker = make_worker(worker_settings)
        await worker.start()
        await wait_for_state(worker, PerceptionWorkerState.FAILED)
        await worker.stop()

        patched_factory["source_error"] = None
        worker.retry_now()
        await asyncio.sleep(0.1)

        assert worker.state is not PerceptionWorkerState.RUNNING
        assert int(patched_factory["sources_built"]) == 1
