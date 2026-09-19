"""Queue Intelligence inside the analysis pipeline.

The property under test is that Queue Intelligence is genuinely *additive*: a
pipeline built without it produces exactly what it always did, and a pipeline
built with it produces the same crowd and stability results plus three more.
That is what makes this an extension rather than a change (Rule 2).
"""

from __future__ import annotations

import pytest

from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
from surgeguard_ai.contracts import (
    CameraConfig,
    ImagePoint,
    ImagePolygon,
    QueueFormation,
    ZoneType,
)
from surgeguard_ai.contracts.camera import CameraZone
from surgeguard_ai.evidence import EvidenceConfig, RuleEvidenceEngine
from surgeguard_ai.forecast import ForecastConfig, QueueForecaster
from surgeguard_ai.pipeline.analysis_pipeline import AnalysisPipeline
from surgeguard_ai.queue import CounterSettings, QueueAnalyzer
from surgeguard_ai.resources import AllocationConfig, ResourceAllocator
from surgeguard_ai.stability import CsiConfig, WeightedStabilityAssessor

from .conftest import ANALYSIS_SIZE, make_perception, make_tracks


def rectangle(x1: float, y1: float, x2: float, y2: float) -> ImagePolygon:
    return ImagePolygon(
        points=(
            ImagePoint(x=x1, y=y1),
            ImagePoint(x=x2, y=y1),
            ImagePoint(x=x2, y=y2),
            ImagePoint(x=x1, y=y2),
        )
    )


@pytest.fixture
def ticket_hall() -> CameraConfig:
    return CameraConfig(
        camera_id="cam-01",
        name="Camera 01",
        location="Ticket Hall",
        zones=(
            CameraZone(
                zone_id="queue-a",
                name="Ticket Hall Queue",
                zone_type=ZoneType.QUEUE,
                polygon=rectangle(0.0, 250.0, 960.0, 540.0),
            ),
            CameraZone(
                zone_id="counter-1",
                name="Counter 1",
                zone_type=ZoneType.COUNTER,
                polygon=rectangle(860.0, 330.0, 950.0, 470.0),
            ),
        ),
    )


def build_pipeline(
    camera: CameraConfig, *, with_queues: bool
) -> tuple[AnalysisPipeline, QueueAnalyzer | None]:
    width, height = ANALYSIS_SIZE
    analyzer = GridCrowdAnalyzer(
        CrowdAnalysisConfig(frame_width=width, frame_height=height)
    )
    assessor = WeightedStabilityAssessor(CsiConfig())
    evidence = RuleEvidenceEngine(EvidenceConfig())

    queues = QueueAnalyzer(camera) if with_queues else None
    if queues is not None:
        queues.set_counters(
            "queue-a",
            CounterSettings(
                total_counters=4, active_counters=2, configured_rate_per_min=2.0
            ),
        )

    pipeline = AnalysisPipeline(
        camera,
        analyzer,
        assessor,
        evidence,
        None,
        queues=queues,
        forecaster=QueueForecaster(ForecastConfig()) if with_queues else None,
        allocator=ResourceAllocator(AllocationConfig()) if with_queues else None,
    )
    return pipeline, queues


class TestAdditivity:
    def test_a_pipeline_without_queue_intelligence_is_unchanged(
        self, ticket_hall: CameraConfig
    ) -> None:
        pipeline, _ = build_pipeline(ticket_hall, with_queues=False)
        result = pipeline.process(
            make_perception(seq=1, tracks=make_tracks(count=12, speed=5.0), seconds=0.0)
        )

        assert result.crowd is not None
        assert result.stability is not None
        assert result.queue is None
        assert result.forecast is None
        assert result.resources is None

    def test_crowd_and_stability_are_identical_either_way(
        self, ticket_hall: CameraConfig
    ) -> None:
        """Adding Queue Intelligence must not perturb the existing spine."""
        perception = make_perception(
            seq=1, tracks=make_tracks(count=12, speed=5.0), seconds=0.0
        )

        without, _ = build_pipeline(ticket_hall, with_queues=False)
        with_queues, _ = build_pipeline(ticket_hall, with_queues=True)

        plain = without.process(perception)
        extended = with_queues.process(perception)

        assert extended.crowd.person_count == plain.crowd.person_count
        assert extended.stability.csi_raw == pytest.approx(plain.stability.csi_raw)
        assert extended.stability.status is plain.stability.status


class TestQueueIntelligenceInPipeline:
    def test_all_three_layers_are_produced(self, ticket_hall: CameraConfig) -> None:
        pipeline, _ = build_pipeline(ticket_hall, with_queues=True)
        result = pipeline.process(
            make_perception(seq=1, tracks=make_tracks(count=12, speed=5.0), seconds=0.0)
        )

        assert result.queue is not None
        assert result.forecast is not None
        assert result.resources is not None

        queue = result.queue.by_zone("queue-a")
        assert queue is not None
        assert queue.formation is QueueFormation.QUEUE
        assert queue.person_count == 12

    def test_the_three_layers_stay_distinct(self, ticket_hall: CameraConfig) -> None:
        """Measurement, prediction and recommendation must never be conflated."""
        pipeline, _ = build_pipeline(ticket_hall, with_queues=True)

        result = None
        for step in range(40):
            result = pipeline.process(
                make_perception(
                    seq=step + 1,
                    tracks=make_tracks(count=10 + step, speed=5.0),
                    seconds=step * 11.0,
                )
            )

        assert result is not None
        queue = result.queue.by_zone("queue-a")
        forecast = result.forecast.by_zone("queue-a")
        plan = result.resources.by_zone("queue-a")
        assert queue is not None and forecast is not None and plan is not None

        # Measured now.
        assert queue.person_count == 49
        # Predicted later - a different, larger number, on a stated horizon.
        assert forecast.points
        assert forecast.at_horizon(15) is not None
        # Recommended action - neither of the above.
        assert plan.action is not None
        assert plan.recommended.active_counters >= 0

    def test_a_growing_queue_reaches_a_recommendation(
        self, ticket_hall: CameraConfig
    ) -> None:
        """The full intelligence loop: observe, predict, recommend."""
        pipeline, _ = build_pipeline(ticket_hall, with_queues=True)

        result = None
        for step in range(45):
            result = pipeline.process(
                make_perception(
                    seq=step + 1,
                    tracks=make_tracks(count=8 + step * 2, speed=5.0),
                    seconds=step * 11.0,
                )
            )

        assert result is not None
        plan = result.resources.by_zone("queue-a")
        assert plan is not None
        assert plan.rationale
        assert plan.options

    def test_counter_changes_take_effect_through_the_pipeline(
        self, ticket_hall: CameraConfig
    ) -> None:
        pipeline, queues = build_pipeline(ticket_hall, with_queues=True)
        assert queues is not None

        tracks = make_tracks(count=20, speed=5.0)
        before = pipeline.process(make_perception(seq=1, tracks=tracks, seconds=0.0))

        queues.set_counters(
            "queue-a",
            CounterSettings(
                total_counters=4, active_counters=4, configured_rate_per_min=2.0
            ),
        )
        after = pipeline.process(make_perception(seq=2, tracks=tracks, seconds=1.0))

        wait_before = before.queue.by_zone("queue-a").wait.minutes
        wait_after = after.queue.by_zone("queue-a").wait.minutes
        assert wait_before is not None and wait_after is not None
        assert wait_after < wait_before

    def test_a_camera_with_no_queue_zone_reports_unconfigured(self) -> None:
        plain_camera = CameraConfig(
            camera_id="cam-01", name="Camera 01", location="Concourse"
        )
        pipeline, _ = build_pipeline(plain_camera, with_queues=True)
        result = pipeline.process(
            make_perception(seq=1, tracks=make_tracks(count=15, speed=5.0), seconds=0.0)
        )

        assert result.queue is not None
        assert result.queue.unconfigured is True
        assert result.resources is None, (
            "there is nothing to plan for when no queue zone exists"
        )


class TestContinuity:
    def test_a_sequence_restart_clears_forecast_history(
        self, ticket_hall: CameraConfig
    ) -> None:
        """A looping clip must not forecast across the seam."""
        pipeline, _ = build_pipeline(ticket_hall, with_queues=True)

        for step in range(30):
            pipeline.process(
                make_perception(
                    seq=step + 1,
                    tracks=make_tracks(count=10 + step, speed=5.0),
                    seconds=step * 11.0,
                )
            )

        restarted = pipeline.process(
            make_perception(seq=0, tracks=make_tracks(count=5, speed=5.0), seconds=0.0)
        )

        forecast = restarted.forecast.by_zone("queue-a")
        assert forecast is not None
        assert forecast.observation_minutes == pytest.approx(0.0, abs=0.01)
