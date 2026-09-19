"""The perception pipeline - Stages 1 to 3 wired together.

These use stage doubles rather than a model. The behaviour under test is the
pipeline's own: what it does when a frame is unreadable, when a stage fails, when
continuity breaks, when a consumer misbehaves, and when it is asked to stop. Each
of those is a failure mode the platform is required to survive, and none of them
needs a GPU to provoke.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from surgeguard_ai.contracts import CameraConfig, PerceptionResult, SourceMode
from surgeguard_ai.errors import PipelineError, SourceEnded, SourceUnavailableError
from surgeguard_ai.perception import Frame, FrameSource, VideoFileSource
from surgeguard_ai.pipeline import PerceptionPipeline, PerceptionPipelineConfig

from .conftest import VIDEO_FRAMES, FakeDetector, FakeTracker, make_frame


class ScriptedSource(FrameSource):
    """Delivers a fixed script of frames, gaps and failures.

    ``None`` in the script is a recoverable gap; an exception class is raised.
    """

    def __init__(self, script: list, *, mode: SourceMode = SourceMode.DEMO) -> None:
        self._script = list(script)
        self._mode = mode
        self._index = 0
        self.opened = False
        self.closed = False

    @property
    def source_id(self) -> str:
        return "scripted"

    @property
    def source_mode(self) -> SourceMode:
        return self._mode

    @property
    def fps(self) -> float:
        return 20.0

    @property
    def is_open(self) -> bool:
        return self.opened and not self.closed

    def open(self) -> None:
        self.opened = True
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def read(self) -> Frame | None:
        if self._index >= len(self._script):
            raise SourceEnded("script exhausted")
        item = self._script[self._index]
        self._index += 1
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("scripted source failure")
        return item


class Collector:
    """Captures emitted results; optionally raises, to test consumer isolation."""

    def __init__(self, *, raises: bool = False) -> None:
        self.results: list[PerceptionResult] = []
        self.raises = raises

    async def __call__(self, result: PerceptionResult) -> None:
        self.results.append(result)
        if self.raises:
            raise RuntimeError("synthetic consumer failure")


async def run_to_completion(pipeline: PerceptionPipeline, source: FrameSource) -> None:
    await pipeline.start(source)
    await pipeline.wait_closed()
    await pipeline.stop()


@pytest.fixture
def pipeline_parts(camera: CameraConfig):
    """A pipeline with stage doubles, plus handles on each part."""

    def build(*, detector=None, tracker=None, handler=None, config=None):
        detector = detector or FakeDetector()
        tracker = tracker or FakeTracker()
        handler = handler or Collector()
        pipeline = PerceptionPipeline(
            camera,
            detector,
            tracker,
            on_result=handler,
            config=config,
        )
        return pipeline, detector, tracker, handler

    return build


class TestProcessing:
    async def test_every_frame_becomes_a_result(self, pipeline_parts) -> None:
        pipeline, _, _, handler = pipeline_parts()
        source = ScriptedSource([make_frame(seq) for seq in range(5)])

        await run_to_completion(pipeline, source)

        assert [result.frame_seq for result in handler.results] == [0, 1, 2, 3, 4]

    async def test_results_carry_the_camera_and_provenance(self, pipeline_parts) -> None:
        pipeline, _, _, handler = pipeline_parts()
        source = ScriptedSource([make_frame(0)], mode=SourceMode.DEMO)

        await run_to_completion(pipeline, source)

        result = handler.results[0]
        assert result.camera_id == "cam-01"
        assert result.source_mode is SourceMode.DEMO
        assert result.is_demo

    async def test_live_provenance_is_carried_unchanged(self, pipeline_parts) -> None:
        """Provenance is a tag. The pipeline copies it and never acts on it."""
        pipeline, _, _, handler = pipeline_parts()
        source = ScriptedSource([make_frame(0)], mode=SourceMode.LIVE)

        await run_to_completion(pipeline, source)

        assert handler.results[0].source_mode is SourceMode.LIVE
        assert not handler.results[0].is_demo

    async def test_the_person_count_comes_from_tracks(self, pipeline_parts) -> None:
        pipeline, _, _, handler = pipeline_parts(detector=FakeDetector(people=3))
        source = ScriptedSource([make_frame(seq) for seq in range(3)])

        await run_to_completion(pipeline, source)

        for result in handler.results:
            assert result.person_count == 3
            assert len(result.track_ids) == 3

    async def test_timings_are_reported(self, pipeline_parts) -> None:
        pipeline, _, _, handler = pipeline_parts()
        source = ScriptedSource([make_frame(seq) for seq in range(5)])

        await run_to_completion(pipeline, source)

        assert all(result.processing_ms >= 0 for result in handler.results)
        assert handler.results[-1].achieved_fps > 0

    async def test_the_detector_is_loaded_before_the_first_frame(
        self,
        pipeline_parts,
    ) -> None:
        pipeline, detector, _, _ = pipeline_parts()
        source = ScriptedSource([make_frame(0)])

        await run_to_completion(pipeline, source)

        assert detector.loaded


class TestSurvivingBadFrames:
    async def test_a_gap_is_skipped_without_a_result(self, pipeline_parts) -> None:
        pipeline, _, _, handler = pipeline_parts()
        source = ScriptedSource([make_frame(0), None, make_frame(1)])

        await run_to_completion(pipeline, source)

        assert [result.frame_seq for result in handler.results] == [0, 1]
        assert pipeline.status.frames_dropped == 1

    async def test_a_corrupted_frame_is_reported_and_processing_continues(
        self,
        pipeline_parts,
    ) -> None:
        """A frame the detector cannot use must not end monitoring, or pass silently."""
        pipeline, _, _, handler = pipeline_parts(detector=FakeDetector(fail_on={2}))
        source = ScriptedSource([make_frame(seq) for seq in range(5)])

        await run_to_completion(pipeline, source)

        assert [result.frame_seq for result in handler.results] == [0, 1, 2, 3, 4]

        failed = handler.results[2]
        assert failed.degraded
        assert "Detection unavailable" in failed.degraded_reason
        assert failed.person_count == 0
        assert not handler.results[3].degraded

    async def test_an_empty_frame_reaches_the_detector_as_a_frame(
        self,
        pipeline_parts,
    ) -> None:
        """An unusable buffer must be judged by the detector, not silently counted."""
        empty = Frame(
            seq=0,
            ts=make_frame(0).ts,
            image=np.zeros((0, 0, 3), dtype=np.uint8),
            source_id="empty",
        )
        detector = FakeDetector(fail_on={0})
        pipeline, _, _, handler = pipeline_parts(detector=detector)

        await run_to_completion(pipeline, ScriptedSource([empty, make_frame(1)]))

        assert detector.seen == [0, 1]
        assert handler.results[0].degraded
        assert not handler.results[1].degraded

    async def test_a_tracking_failure_falls_back_to_the_detection_count(
        self,
        pipeline_parts,
    ) -> None:
        """Reporting zero people because tracking failed would be a false reading."""
        pipeline, _, _, handler = pipeline_parts(
            detector=FakeDetector(people=4),
            tracker=FakeTracker(fail_on={1}),
        )
        source = ScriptedSource([make_frame(seq) for seq in range(3)])

        await run_to_completion(pipeline, source)

        degraded = handler.results[1]
        assert degraded.degraded
        assert "Tracking unavailable" in degraded.degraded_reason
        assert degraded.person_count == 4
        assert degraded.tracking.count == 0

    async def test_an_unbroken_run_of_failures_stops_the_loop(
        self,
        pipeline_parts,
    ) -> None:
        """Continuing forever on a broken detector would report a silent zero crowd."""
        pipeline, _, _, handler = pipeline_parts(
            detector=FakeDetector(fail_on=set(range(20))),
            config=PerceptionPipelineConfig(max_consecutive_failures=5),
        )
        source = ScriptedSource([make_frame(seq) for seq in range(20)])

        await run_to_completion(pipeline, source)

        assert len(handler.results) == 4  # the fifth failure ends the run
        assert pipeline.status.degraded
        assert "consecutive frames failed" in pipeline.status.degraded_reason


class TestSourceLifecycle:
    async def test_the_end_of_a_clip_is_a_clean_finish(self, pipeline_parts) -> None:
        """A demonstration clip ending is the expected outcome, not a fault."""
        pipeline, _, _, _ = pipeline_parts()

        await run_to_completion(pipeline, ScriptedSource([make_frame(0)]))

        assert not pipeline.is_running
        assert not pipeline.status.degraded

    async def test_a_lost_source_is_reported_as_degraded(self, pipeline_parts) -> None:
        pipeline, _, _, _ = pipeline_parts()
        source = ScriptedSource([make_frame(0), SourceUnavailableError])

        await run_to_completion(pipeline, source)

        assert pipeline.status.degraded
        assert "Frame source lost" in pipeline.status.degraded_reason

    async def test_an_unexpected_failure_is_recorded_rather_than_swallowed(
        self,
        pipeline_parts,
    ) -> None:
        """A frame loop that dies quietly leaves the platform reporting itself healthy.

        That is the one failure a safety display must not have: monitoring stops
        and nothing on screen changes.
        """
        pipeline, _, _, _ = pipeline_parts()
        source = ScriptedSource([make_frame(0), ValueError])

        await run_to_completion(pipeline, source)

        assert pipeline.status.degraded
        assert "Frame loop failed" in pipeline.status.degraded_reason
        assert not pipeline.is_running

    async def test_the_source_is_released_on_stop(self, pipeline_parts) -> None:
        pipeline, _, _, _ = pipeline_parts()
        source = ScriptedSource([make_frame(seq) for seq in range(3)])

        await run_to_completion(pipeline, source)

        assert source.closed

    async def test_stop_is_idempotent(self, pipeline_parts) -> None:
        pipeline, _, _, _ = pipeline_parts()
        await run_to_completion(pipeline, ScriptedSource([make_frame(0)]))

        await pipeline.stop()
        await pipeline.stop()

    async def test_starting_twice_is_refused(self, pipeline_parts) -> None:
        pipeline, _, _, _ = pipeline_parts()
        source = ScriptedSource([make_frame(seq) for seq in range(500)])

        await pipeline.start(source)
        try:
            with pytest.raises(PipelineError, match="already running"):
                await pipeline.start(ScriptedSource([make_frame(0)]))
        finally:
            await pipeline.stop()

    async def test_status_still_names_the_source_after_shutdown(
        self,
        pipeline_parts,
    ) -> None:
        pipeline, _, _, _ = pipeline_parts()

        await run_to_completion(pipeline, ScriptedSource([make_frame(0)]))

        assert pipeline.status.source_id == "scripted"
        assert pipeline.status.source_mode is SourceMode.DEMO
        assert not pipeline.status.running


class TestContinuity:
    async def test_a_restarted_sequence_discards_tracking_state(
        self,
        pipeline_parts,
    ) -> None:
        """A camera reconnection or a clip wrap restarts the sequence at 0.

        Movement history spanning that seam describes motion that never happened,
        so it has to go.
        """
        pipeline, _, tracker, _ = pipeline_parts()
        source = ScriptedSource(
            [make_frame(0), make_frame(1), make_frame(0), make_frame(1)]
        )

        await run_to_completion(pipeline, source)

        assert tracker.resets == 1

    async def test_a_continuous_sequence_keeps_tracking_state(
        self,
        pipeline_parts,
    ) -> None:
        pipeline, _, tracker, _ = pipeline_parts()
        source = ScriptedSource([make_frame(seq) for seq in range(6)])

        await run_to_completion(pipeline, source)

        assert tracker.resets == 0

    async def test_frames_the_source_skipped_are_counted(self, pipeline_parts) -> None:
        """Dropped material belongs in the health figures, not quietly discarded."""
        pipeline, _, _, _ = pipeline_parts()
        source = ScriptedSource([make_frame(0), make_frame(5)])

        await run_to_completion(pipeline, source)

        assert pipeline.status.frames_dropped == 4


class TestModeSwitchingAndReset:
    async def test_swapping_the_source_resets_state_and_keeps_the_model(
        self,
        pipeline_parts,
    ) -> None:
        """Live/Demo switching is a source swap - nothing else changes."""
        pipeline, detector, tracker, handler = pipeline_parts()

        demo = ScriptedSource([make_frame(seq) for seq in range(3)], mode=SourceMode.DEMO)
        await pipeline.start(demo)
        await pipeline.wait_closed()

        live = ScriptedSource([make_frame(seq) for seq in range(3)], mode=SourceMode.LIVE)
        await pipeline.swap_source(live)
        await pipeline.wait_closed()
        await pipeline.stop()

        assert demo.closed
        assert detector.loaded and not detector.unloaded  # the model was not reloaded
        assert tracker.resets >= 1
        assert {result.source_mode for result in handler.results[:3]} == {SourceMode.DEMO}
        assert {result.source_mode for result in handler.results[3:]} == {SourceMode.LIVE}

    async def test_swapping_the_source_keeps_the_pipeline_thread(
        self,
        pipeline_parts,
    ) -> None:
        """A swap must not move inference to a fresh thread.

        Inference is far slower on a thread that has not run it before - on CUDA,
        seconds - so a swap that replaced the thread would stall at exactly the
        moment a presenter changes scenario.
        """
        pipeline, detector, _, _ = pipeline_parts()

        await pipeline.start(ScriptedSource([make_frame(seq) for seq in range(3)]))
        await pipeline.wait_closed()

        await pipeline.swap_source(ScriptedSource([make_frame(seq) for seq in range(3)]))
        await pipeline.wait_closed()
        await pipeline.stop()

        assert len(detector.threads) == 1, f"inference moved between threads: {detector.threads}"

    async def test_all_inference_runs_on_one_thread(self, pipeline_parts) -> None:
        pipeline, detector, _, _ = pipeline_parts()
        source = ScriptedSource([make_frame(seq) for seq in range(20)])

        await run_to_completion(pipeline, source)

        assert len(detector.threads) == 1

    async def test_reset_clears_state_without_touching_the_source(
        self,
        pipeline_parts,
    ) -> None:
        """One-Click Reset: the clip keeps playing, the accumulated state does not."""
        pipeline, _, tracker, _ = pipeline_parts()
        source = ScriptedSource([make_frame(seq) for seq in range(500)])

        await pipeline.start(source)
        await asyncio.sleep(0.05)
        await pipeline.reset()

        assert tracker.resets == 1
        assert pipeline.status.frames_processed == 0
        assert pipeline.is_running
        assert not source.closed

        await pipeline.stop()


class TestConsumerIsolation:
    async def test_a_failing_consumer_does_not_stop_monitoring(
        self,
        pipeline_parts,
    ) -> None:
        """A broken display must never take the analysis down with it."""
        handler = Collector(raises=True)
        pipeline, _, _, _ = pipeline_parts(handler=handler)
        source = ScriptedSource([make_frame(seq) for seq in range(5)])

        await run_to_completion(pipeline, source)

        assert len(handler.results) == 5
        assert not pipeline.status.degraded

    async def test_a_pipeline_without_a_consumer_still_runs(
        self,
        camera: CameraConfig,
    ) -> None:
        pipeline = PerceptionPipeline(camera, FakeDetector(), FakeTracker())
        source = ScriptedSource([make_frame(seq) for seq in range(3)])

        await run_to_completion(pipeline, source)

        assert pipeline.status.frames_processed == 3


class TestAgainstARealClip:
    async def test_a_recorded_clip_runs_to_its_end(
        self,
        pipeline_parts,
        sample_video: Path,
    ) -> None:
        """The stages are doubles, but the frame source is real, and so is the file."""
        pipeline, _, _, handler = pipeline_parts()
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)

        await run_to_completion(pipeline, source)

        assert len(handler.results) == VIDEO_FRAMES
        assert pipeline.status.frames_processed == VIDEO_FRAMES
        assert not pipeline.status.degraded
