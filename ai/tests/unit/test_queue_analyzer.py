"""Queue Intelligence end to end, over configured zones.

The behaviour under test is the one Problem Statement 9 actually asks for:
telling a queue apart from a crowd, and turning that into a waiting time an
operator can act on - while declining to answer when the evidence is thin.
"""

from __future__ import annotations

import math

import pytest

from surgeguard_ai.contracts import (
    BoundingBox,
    CameraConfig,
    CameraZone,
    ImagePoint,
    ImagePolygon,
    QueueFormation,
    RateSource,
    Track,
    Vector2D,
    ZoneType,
)
from surgeguard_ai.queue import CounterSettings, QueueAnalysisConfig, QueueAnalyzer

from .conftest import make_perception, make_tracks


def rectangle(x1: float, y1: float, x2: float, y2: float) -> ImagePolygon:
    return ImagePolygon(
        points=(
            ImagePoint(x=x1, y=y1),
            ImagePoint(x=x2, y=y1),
            ImagePoint(x=x2, y=y2),
            ImagePoint(x=x1, y=y2),
        )
    )


QUEUE_ZONE = CameraZone(
    zone_id="queue-a",
    name="Ticket Hall Queue",
    zone_type=ZoneType.QUEUE,
    polygon=rectangle(0.0, 250.0, 960.0, 540.0),
)

#: Placed at the +x end of the hall, which is the end the test queues point at.
COUNTER_ZONE = CameraZone(
    zone_id="counter-1",
    name="Counter 1",
    zone_type=ZoneType.COUNTER,
    polygon=rectangle(860.0, 330.0, 950.0, 470.0),
)


@pytest.fixture
def queue_camera() -> CameraConfig:
    return CameraConfig(
        camera_id="cam-01",
        name="Camera 01",
        location="Ticket Hall",
        zones=(QUEUE_ZONE, COUNTER_ZONE),
    )


def scattered_tracks(
    count: int, *, age_frames: int = 40, radius_scale: float = 30.0, squash: float = 1.0
) -> tuple[Track, ...]:
    """People spread over a 2-D area, each drifting a different way.

    A concourse, not a line. Positions follow a golden-angle spiral rather than a
    random generator, so the arrangement is deterministic and inspectable; at the
    default ``radius_scale`` the whole spread fits inside the queue zone, which
    matters because people outside it are correctly not counted.

    ``squash`` compresses the spiral vertically. At 1.0 it is a disc. Below about
    0.5 it becomes a genuinely elongated cluster - which is a real, ambiguous
    arrangement, not a degenerate one, and is used to test that the classifier
    declines rather than guesses.
    """
    tracks = []
    for index in range(count):
        angle = index * 2.399963  # golden angle - spreads without clustering
        radius = radius_scale * math.sqrt(index + 1)
        x = 470.0 + radius * math.cos(angle)
        y = 395.0 + squash * radius * math.sin(angle)
        tracks.append(
            Track(
                track_id=index + 1,
                bbox=BoundingBox(x1=x - 15.0, y1=y - 60.0, x2=x + 15.0, y2=y),
                confidence=0.9,
                age_frames=age_frames,
                foot_point=ImagePoint(x=x, y=y),
                velocity_image=Vector2D(
                    dx=20.0 * math.cos(angle * 3.0), dy=20.0 * math.sin(angle * 3.0)
                ),
            )
        )
    return tuple(tracks)


class TestConfiguration:
    def test_a_camera_with_no_queue_zone_reports_unconfigured(self) -> None:
        """Zeroes would look like a measured empty queue. Saying nothing is
        configured is the honest answer."""
        analyzer = QueueAnalyzer(
            CameraConfig(camera_id="cam-01", name="Camera 01", location="Platform 3")
        )
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=10, speed=5.0), seconds=0.0)
        )

        assert report.unconfigured is True
        assert report.queues == ()
        assert report.total_waiting == 0
        assert report.busiest is None

    def test_a_configured_zone_is_measured(self, queue_camera: CameraConfig) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=10, speed=5.0), seconds=0.0)
        )

        assert report.unconfigured is False
        assert analyzer.queue_zone_ids == ("queue-a",)
        assert report.by_zone("queue-a") is not None
        assert report.by_zone("nonexistent") is None


class TestFormationClassification:
    def test_a_line_pointed_at_the_counter_is_a_queue(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=12, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.formation is QueueFormation.QUEUE
        assert queue.is_queue is True
        assert queue.person_count == 12
        assert queue.geometry.linearity == pytest.approx(1.0, abs=1e-6)
        assert queue.geometry.counter_alignment == pytest.approx(1.0, abs=1e-3)

    def test_the_classification_carries_its_reasons(
        self, queue_camera: CameraConfig
    ) -> None:
        """'This is a queue' must always be answerable with 'because...'."""
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=12, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.formation_basis
        joined = " ".join(queue.formation_basis)
        assert "linearly" in joined
        assert "Counter 1" in joined, "a named counter beats an invented location"

    def test_a_scattered_crowd_is_not_a_queue(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(seq=1, tracks=scattered_tracks(20), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.formation is QueueFormation.GENERAL_CROWD
        assert queue.is_queue is False
        assert queue.geometry.linearity is not None
        assert queue.geometry.linearity < 0.2

    def test_an_ambiguous_arrangement_is_left_undetermined(
        self, queue_camera: CameraConfig
    ) -> None:
        """A cluster that is elongated toward the counter but irregularly spaced
        and incoherently moving is genuinely ambiguous. Forcing it onto one side
        would be a guess presented as a measurement; the gap between the two
        thresholds exists precisely so the platform can say it cannot tell.
        """
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(
                seq=1,
                tracks=scattered_tracks(20, radius_scale=90.0, squash=0.45),
                seconds=0.0,
            )
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.formation is QueueFormation.UNDETERMINED
        assert queue.is_queue is False

    def test_too_few_people_is_reported_as_sparse(
        self, queue_camera: CameraConfig
    ) -> None:
        """Three people standing near each other are always collinear."""
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=3, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.formation is QueueFormation.SPARSE
        assert "below the" in queue.formation_basis[0]

    def test_young_tracks_are_excluded_from_geometry_but_not_the_count(
        self, queue_camera: CameraConfig
    ) -> None:
        """Filtering the headcount too would under-report a queue that is
        filling quickly - precisely when the count matters."""
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(
                seq=1,
                tracks=make_tracks(count=10, speed=5.0, age_frames=1),
                seconds=0.0,
            )
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.person_count == 10
        assert queue.geometry.sample_size == 0
        assert queue.formation is QueueFormation.UNDETERMINED

    def test_people_outside_the_zone_are_not_counted(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        # y=100 is above the zone's top edge at y=250.
        report = analyzer.analyze(
            make_perception(
                seq=1, tracks=make_tracks(count=8, speed=5.0, y=100.0), seconds=0.0
            )
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.person_count == 0


class TestWaitEstimate:
    def test_wait_is_queue_length_over_effective_service_rate(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        analyzer.set_counters(
            "queue-a",
            CounterSettings(
                total_counters=4, active_counters=2, configured_rate_per_min=2.0
            ),
        )
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=12, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.capacity.effective_service_rate_per_min == pytest.approx(4.0)
        assert queue.wait.minutes == pytest.approx(3.0)
        assert queue.capacity.idle_counters == 2
        assert queue.capacity.utilisation == pytest.approx(0.5)

    def test_an_undrained_queue_reports_an_unknown_wait_not_a_huge_one(
        self, queue_camera: CameraConfig
    ) -> None:
        """A very large number would read as a measurement of a very long wait.
        It is an absence of one."""
        analyzer = QueueAnalyzer(queue_camera)
        analyzer.set_counters(
            "queue-a",
            CounterSettings(
                total_counters=3, active_counters=0, configured_rate_per_min=2.0
            ),
        )
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=15, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.wait.minutes is None
        assert queue.wait.is_unbounded is True

    def test_an_empty_queue_has_no_wait(self, queue_camera: CameraConfig) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(make_perception(seq=1, tracks=(), seconds=0.0))

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.wait.minutes == pytest.approx(0.0)
        assert queue.wait.is_unbounded is False

    def test_assumptions_travel_with_the_estimate(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        analyzer.set_counters(
            "queue-a",
            CounterSettings(
                total_counters=3, active_counters=3, configured_rate_per_min=2.0
            ),
        )
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=9, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        joined = " ".join(queue.wait.assumptions)
        assert "assumed" in joined, "an assumed rate must say so"
        assert "all 3 active counters stay open" in joined
        assert queue.wait.rate_source is RateSource.CONFIGURED

    def test_an_unobserved_queue_reports_low_confidence(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=10, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.wait.confidence < 0.2, (
            "a wait derived from an assumed rate on one frame of observation "
            "must not present itself as confident"
        )


class TestFlowOverTime:
    def test_arrivals_accumulate_as_the_queue_fills(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)

        for step in range(1, 7):
            report = analyzer.analyze(
                make_perception(
                    seq=step,
                    tracks=make_tracks(count=step * 2, speed=5.0),
                    seconds=step * 10.0,
                )
            )

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.flow.arrivals > 0
        assert queue.flow.arrival_rate_per_min > 0.0
        assert queue.flow.observation_seconds == pytest.approx(50.0)
        assert analyzer.observation_seconds("queue-a") == pytest.approx(50.0)

    def test_dwell_is_reported_for_people_who_stay(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        tracks = make_tracks(count=6, speed=0.0)

        analyzer.analyze(make_perception(seq=1, tracks=tracks, seconds=0.0))
        report = analyzer.analyze(make_perception(seq=2, tracks=tracks, seconds=120.0))

        queue = report.by_zone("queue-a")
        assert queue is not None
        assert queue.mean_dwell_seconds == pytest.approx(120.0)
        assert queue.max_dwell_seconds == pytest.approx(120.0)

    def test_net_rate_is_arrivals_less_everything_leaving(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        report = analyzer.analyze(
            make_perception(seq=1, tracks=make_tracks(count=8, speed=5.0), seconds=0.0)
        )

        queue = report.by_zone("queue-a")
        assert queue is not None
        flow = queue.flow
        assert flow.net_rate_per_min == pytest.approx(
            flow.arrival_rate_per_min
            - flow.service_rate_per_min
            - flow.abandonment_rate_per_min
        )


class TestCounterSettings:
    def test_active_counters_cannot_exceed_total(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            CounterSettings(total_counters=2, active_counters=3)

    def test_a_zone_never_configured_gets_a_usable_default(
        self, queue_camera: CameraConfig
    ) -> None:
        analyzer = QueueAnalyzer(queue_camera)
        settings = analyzer.counters_for("queue-a")
        assert settings.total_counters == 1
        assert settings.active_counters == 1

    def test_reopening_a_counter_changes_the_wait(
        self, queue_camera: CameraConfig
    ) -> None:
        """The lever the resource recommendation will pull must actually move
        the number it claims to move."""
        analyzer = QueueAnalyzer(queue_camera)
        tracks = make_tracks(count=20, speed=5.0)

        analyzer.set_counters(
            "queue-a",
            CounterSettings(
                total_counters=4, active_counters=1, configured_rate_per_min=2.0
            ),
        )
        before = analyzer.analyze(make_perception(seq=1, tracks=tracks, seconds=0.0))

        analyzer.set_counters(
            "queue-a",
            CounterSettings(
                total_counters=4, active_counters=2, configured_rate_per_min=2.0
            ),
        )
        after = analyzer.analyze(make_perception(seq=2, tracks=tracks, seconds=1.0))

        wait_before = before.by_zone("queue-a")
        wait_after = after.by_zone("queue-a")
        assert wait_before is not None and wait_after is not None
        assert wait_before.wait.minutes == pytest.approx(10.0)
        assert wait_after.wait.minutes == pytest.approx(5.0)


class TestConfigValidation:
    def test_formation_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="must sum to 1.0"):
            QueueAnalysisConfig(
                linearity_weight=0.5,
                spacing_weight=0.5,
                heading_weight=0.5,
                counter_weight=0.5,
            )

    def test_the_undetermined_band_cannot_be_empty(self) -> None:
        with pytest.raises(ValueError, match="crowd_threshold must be below"):
            QueueAnalysisConfig(queue_threshold=0.5, crowd_threshold=0.5)
