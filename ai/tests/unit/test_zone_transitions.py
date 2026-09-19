"""Zone flow on one camera - entries, exits and tracked transitions.

Scenes are built frame by frame from a few tracks walking between rectangles,
so every expected count can be checked by reading the test.
"""

from __future__ import annotations

import pytest

from surgeguard_ai.contracts import (
    BoundingBox,
    CameraConfig,
    ImagePoint,
    ImagePolygon,
    Track,
    Vector2D,
    ZoneType,
)
from surgeguard_ai.contracts.camera import CameraZone
from surgeguard_ai.zones import ZoneTransitionTracker

from .conftest import make_perception


def rectangle(x1: float, y1: float, x2: float, y2: float) -> ImagePolygon:
    return ImagePolygon(
        points=(
            ImagePoint(x=x1, y=y1),
            ImagePoint(x=x2, y=y1),
            ImagePoint(x=x2, y=y2),
            ImagePoint(x=x1, y=y2),
        )
    )


def zone(
    zone_id: str, zone_type: ZoneType, x1: float, x2: float, *, y1: float = 0.0, y2: float = 540.0
) -> CameraZone:
    return CameraZone(
        zone_id=zone_id,
        name=zone_id.replace("-", " ").title(),
        zone_type=zone_type,
        polygon=rectangle(x1, y1, x2, y2),
    )


#: Entrance, queue and counter side by side across a 960-wide view.
HALL = CameraConfig(
    camera_id="cam-01",
    name="Camera 01",
    location="Ticket Hall",
    zones=(
        zone("entrance", ZoneType.ENTRY, 0.0, 300.0),
        zone("queue", ZoneType.QUEUE, 300.0, 700.0),
        zone("counter", ZoneType.COUNTER, 700.0, 960.0),
    ),
)

ENTRANCE_X, QUEUE_X, COUNTER_X, OUTSIDE_Y = 150.0, 500.0, 820.0, 900.0


def person(
    track_id: int,
    x: float,
    *,
    y: float = 400.0,
    age: int = 10,
    velocity: tuple[float, float] | None = None,
) -> Track:
    return Track(
        track_id=track_id,
        bbox=BoundingBox(x1=x - 15.0, y1=y - 120.0, x2=x + 15.0, y2=y),
        confidence=0.9,
        age_frames=age,
        foot_point=ImagePoint(x=x, y=y),
        velocity_image=Vector2D(dx=velocity[0], dy=velocity[1]) if velocity else None,
    )


class Scene:
    """Feeds a tracker one frame per call, advancing the frame sequence."""

    def __init__(self, tracker: ZoneTransitionTracker) -> None:
        self.tracker = tracker
        self.seq = 0

    def at(self, seconds: float, *tracks: Track):
        report = self.tracker.observe(
            make_perception(seq=self.seq, tracks=tuple(tracks), seconds=seconds)
        )
        self.seq += 1
        return report


@pytest.fixture
def scene() -> Scene:
    return Scene(
        ZoneTransitionTracker(HALL, lost_grace_seconds=2.0, transition_max_gap_seconds=10.0)
    )


def test_the_report_describes_every_zone_on_the_camera_in_order(scene: Scene) -> None:
    report = scene.at(0.0)

    assert report.camera_id == "cam-01"
    assert [z.zone_id for z in report.zones] == ["entrance", "queue", "counter"]
    assert report.by_zone("queue") is not None
    assert report.by_zone("queue").zone_type is ZoneType.QUEUE
    assert report.transitions == ()


def test_people_already_present_when_observation_starts_occupy_but_did_not_enter(
    scene: Scene,
) -> None:
    report = scene.at(0.0, person(1, QUEUE_X), person(2, QUEUE_X + 50))

    queue = report.by_zone("queue")
    assert queue is not None
    assert queue.occupancy == 2
    assert queue.entries == 0


def test_walking_from_one_zone_to_the_next_is_an_exit_an_entry_and_a_transition(
    scene: Scene,
) -> None:
    scene.at(0.0)
    for second in (1.0, 2.0, 3.0):
        scene.at(second, person(1, ENTRANCE_X))
    for second in (4.0, 5.0, 6.0, 7.0):
        report = scene.at(second, person(1, QUEUE_X))

    entrance, queue = report.by_zone("entrance"), report.by_zone("queue")
    assert entrance is not None and queue is not None
    assert (entrance.entries, entrance.exits) == (1, 1)
    assert (queue.entries, queue.exits, queue.occupancy) == (1, 0, 1)

    moved = report.transition("entrance", "queue")
    assert moved is not None
    assert moved.count == 1
    # Last seen in the entrance at 3 s, first seen in the queue at 4 s.
    assert moved.median_transit_seconds == pytest.approx(1.0)


def test_a_brief_tracking_dropout_is_not_an_exit(scene: Scene) -> None:
    scene.at(0.0)
    for second in (1.0, 2.0, 3.0):
        scene.at(second, person(1, QUEUE_X))
    scene.at(4.0)  # lost for one second
    report = scene.at(5.0, person(1, QUEUE_X))

    queue = report.by_zone("queue")
    assert queue is not None
    assert (queue.entries, queue.exits) == (1, 0)


def test_leaving_the_view_is_an_exit_with_no_transition(scene: Scene) -> None:
    scene.at(0.0)
    scene.at(1.0, person(1, QUEUE_X))
    for second in (2.0, 3.0, 4.0):
        report = scene.at(second)

    queue = report.by_zone("queue")
    assert queue is not None
    assert (queue.entries, queue.exits, queue.occupancy) == (1, 1, 0)
    assert report.transitions == ()


def test_a_transition_needs_the_next_zone_reached_within_the_gap(scene: Scene) -> None:
    scene.at(0.0)
    scene.at(1.0, person(1, ENTRANCE_X))
    # Out of every zone for longer than the ten-second gap.
    for second in (2.0, 6.0, 11.0):
        scene.at(second, person(1, ENTRANCE_X, y=OUTSIDE_Y))
    report = scene.at(12.5, person(1, QUEUE_X))

    assert report.by_zone("queue").entries == 1
    assert report.by_zone("entrance").exits == 1
    assert report.transitions == ()


def test_zones_inside_zones_do_not_invent_transitions() -> None:
    concourse = CameraConfig(
        camera_id="cam-01",
        name="Camera 01",
        location="Concourse",
        zones=(
            zone("concourse", ZoneType.CONCOURSE, 0.0, 960.0),
            zone("queue", ZoneType.QUEUE, 300.0, 700.0),
        ),
    )
    scene = Scene(ZoneTransitionTracker(concourse, lost_grace_seconds=2.0))

    scene.at(0.0)
    for second in (1.0, 2.0, 3.0, 4.0):
        scene.at(second, person(1, ENTRANCE_X))  # concourse only
    for second in (5.0, 6.0, 7.0, 8.0):
        scene.at(second, person(1, QUEUE_X))  # concourse and queue
    for second in (9.0, 10.0, 11.0, 12.0):
        report = scene.at(second, person(1, COUNTER_X))  # concourse only again

    assert report.by_zone("queue").entries == 1
    assert report.by_zone("queue").exits == 1
    assert report.by_zone("concourse").exits == 0
    # Walking into a queue drawn inside a concourse is not leaving the concourse.
    assert report.transitions == ()


def test_zones_drawn_slightly_overlapping_still_count_the_transition() -> None:
    # Hand-drawn neighbours overlap a little, so one frame is in both at once.
    both = CameraConfig(
        camera_id="cam-01",
        name="Camera 01",
        location="Ticket Hall",
        zones=(
            zone("entrance", ZoneType.ENTRY, 0.0, 320.0),
            zone("queue", ZoneType.QUEUE, 300.0, 700.0),
        ),
    )
    overlap = Scene(ZoneTransitionTracker(both, lost_grace_seconds=2.0))
    overlap.at(0.0)
    for second in (1.0, 2.0, 3.0):
        overlap.at(second, person(1, ENTRANCE_X))
    overlap.at(3.5, person(1, 310.0))
    for second in (4.0, 5.0, 6.0, 7.0):
        report = overlap.at(second, person(1, QUEUE_X))

    moved = report.transition("entrance", "queue")
    assert moved is not None
    assert moved.count == 1
    assert moved.median_transit_seconds == pytest.approx(0.0)


def test_tracks_too_young_to_trust_occupy_a_zone_but_do_not_enter_it(scene: Scene) -> None:
    scene.at(0.0)
    report = scene.at(1.0, person(1, QUEUE_X, age=1))
    assert report.by_zone("queue").occupancy == 1
    assert report.by_zone("queue").entries == 0

    report = scene.at(2.0, person(1, QUEUE_X, age=5))
    assert report.by_zone("queue").entries == 1


def test_rates_are_per_minute_over_the_time_actually_observed(scene: Scene) -> None:
    scene.at(0.0)
    for track_id, second in ((1, 5.0), (2, 10.0), (3, 20.0)):
        scene.at(second, *(person(t, QUEUE_X + 20 * t) for t in range(1, track_id + 1)))
    report = scene.at(
        30.0, person(1, QUEUE_X + 20), person(2, QUEUE_X + 40), person(3, QUEUE_X + 60)
    )

    queue = report.by_zone("queue")
    assert queue.entries == 3
    assert report.observation_seconds == pytest.approx(30.0)
    assert queue.entry_rate_per_min == pytest.approx(6.0)
    assert queue.net_rate_per_min == pytest.approx(6.0)


def test_nothing_is_divided_before_a_second_of_observation(scene: Scene) -> None:
    scene.at(0.0)
    report = scene.at(0.5, person(1, QUEUE_X))

    assert report.by_zone("queue").entries == 1
    assert report.by_zone("queue").entry_rate_per_min == 0.0


def test_counts_leave_the_rolling_window() -> None:
    scene = Scene(ZoneTransitionTracker(HALL, window_seconds=60.0))
    scene.at(0.0)
    scene.at(1.0, person(1, QUEUE_X))
    report = scene.at(90.0, person(1, QUEUE_X))

    assert report.by_zone("queue").entries == 0
    assert report.by_zone("queue").occupancy == 1


def test_an_orderly_stream_has_a_heading_and_one_person_does_not(scene: Scene) -> None:
    stream = scene.at(
        0.0,
        person(1, QUEUE_X, velocity=(40.0, 0.0)),
        person(2, QUEUE_X + 40, velocity=(35.0, 2.0)),
        person(3, QUEUE_X + 80, velocity=(45.0, -2.0)),
        person(4, ENTRANCE_X, velocity=(0.0, 30.0)),
    )

    queue = stream.by_zone("queue")
    assert queue.moving_count == 3
    assert queue.dominant_heading_deg is not None
    assert queue.dominant_heading_deg == pytest.approx(
        0.0, abs=3.0
    ) or queue.dominant_heading_deg == pytest.approx(360.0, abs=3.0)
    assert queue.heading_coherence == pytest.approx(1.0, abs=0.01)

    entrance = stream.by_zone("entrance")
    assert entrance.moving_count == 1
    assert entrance.dominant_heading_deg is None
    assert entrance.heading_coherence is None


def test_people_standing_still_have_no_heading(scene: Scene) -> None:
    report = scene.at(
        0.0,
        person(1, QUEUE_X, velocity=(1.0, 0.0)),
        person(2, QUEUE_X + 40, velocity=(0.0, 1.0)),
    )

    assert report.by_zone("queue").moving_count == 0
    assert report.by_zone("queue").dominant_heading_deg is None


def test_opposing_movement_has_no_dominant_heading(scene: Scene) -> None:
    report = scene.at(
        0.0,
        person(1, QUEUE_X, velocity=(40.0, 0.0)),
        person(2, QUEUE_X + 40, velocity=(-40.0, 0.0)),
    )

    queue = report.by_zone("queue")
    assert queue.moving_count == 2
    assert queue.heading_coherence == pytest.approx(0.0, abs=1e-6)
    assert queue.dominant_heading_deg is None


def test_downward_movement_in_the_image_is_ninety_degrees(scene: Scene) -> None:
    report = scene.at(
        0.0,
        person(1, QUEUE_X, velocity=(0.0, 40.0)),
        person(2, QUEUE_X + 40, velocity=(1.0, 40.0)),
    )
    assert report.by_zone("queue").dominant_heading_deg == pytest.approx(90.0, abs=2.0)


def test_a_source_restart_starts_the_count_again(scene: Scene) -> None:
    scene.at(10.0)
    scene.at(11.0, person(1, QUEUE_X))
    assert scene.at(12.0, person(1, QUEUE_X)).by_zone("queue").entries == 1

    rewound = scene.at(1.0, person(1, QUEUE_X))

    assert rewound.by_zone("queue").entries == 0
    assert rewound.observation_seconds == 0.0


def test_reset_forgets_everything(scene: Scene) -> None:
    scene.at(0.0)
    scene.at(1.0, person(1, QUEUE_X))
    scene.tracker.reset()

    report = scene.at(2.0, person(1, QUEUE_X))
    assert report.by_zone("queue").entries == 0


def test_transition_figures_summarise_every_person_who_made_the_move(scene: Scene) -> None:
    scene.at(0.0)
    scene.at(1.0, person(1, ENTRANCE_X), person(2, ENTRANCE_X + 30))
    scene.at(2.0, person(1, QUEUE_X), person(2, ENTRANCE_X + 30))
    scene.at(3.0, person(1, QUEUE_X), person(2, ENTRANCE_X + 30))
    scene.at(4.0, person(1, QUEUE_X), person(2, ENTRANCE_X + 30))
    for second in (5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
        report = scene.at(second, person(1, QUEUE_X), person(2, QUEUE_X + 40))

    moved = report.transition("entrance", "queue")
    assert moved is not None
    assert moved.count == 2
    # Transit times of one second each.
    assert moved.median_transit_seconds == pytest.approx(1.0)
    assert moved.rate_per_min == pytest.approx(2 / (10.0 / 60.0))


def test_invalid_settings_are_rejected() -> None:
    with pytest.raises(ValueError):
        ZoneTransitionTracker(HALL, window_seconds=0.0)
    with pytest.raises(ValueError):
        ZoneTransitionTracker(HALL, lost_grace_seconds=-1.0)
    with pytest.raises(ValueError):
        ZoneTransitionTracker(HALL, transition_max_gap_seconds=-1.0)


# ---------------------------------------------------------------------------
# Inside the analysis pipeline
# ---------------------------------------------------------------------------


def _pipeline(camera: CameraConfig, *, zone_flow: bool):
    from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
    from surgeguard_ai.evidence import EvidenceConfig, RuleEvidenceEngine
    from surgeguard_ai.pipeline.analysis_pipeline import AnalysisPipeline
    from surgeguard_ai.stability import CsiConfig, WeightedStabilityAssessor

    from .conftest import ANALYSIS_SIZE

    width, height = ANALYSIS_SIZE
    return AnalysisPipeline(
        camera,
        GridCrowdAnalyzer(CrowdAnalysisConfig(frame_width=width, frame_height=height)),
        WeightedStabilityAssessor(CsiConfig()),
        RuleEvidenceEngine(EvidenceConfig()),
        zone_flow=ZoneTransitionTracker(camera) if zone_flow else None,
    )


def test_the_pipeline_reports_zone_flow_when_given_a_tracker() -> None:
    pipeline = _pipeline(HALL, zone_flow=True)

    result = pipeline.process(make_perception(seq=1, tracks=(person(1, QUEUE_X),), seconds=0.0))

    assert result.zone_flow is not None
    assert result.zone_flow.by_zone("queue").occupancy == 1


def test_zone_flow_is_absent_without_a_tracker_or_without_zones() -> None:
    perception = make_perception(seq=1, tracks=(person(1, QUEUE_X),), seconds=0.0)

    assert _pipeline(HALL, zone_flow=False).process(perception).zone_flow is None
    bare = CameraConfig(camera_id="cam-01", name="Camera 01", location="Hall")
    assert _pipeline(bare, zone_flow=True).process(perception).zone_flow is None


def test_a_frame_sequence_restart_resets_zone_flow() -> None:
    pipeline = _pipeline(HALL, zone_flow=True)
    pipeline.process(make_perception(seq=5, tracks=(), seconds=0.0))
    counted = pipeline.process(make_perception(seq=6, tracks=(person(1, QUEUE_X),), seconds=1.0))
    assert counted.zone_flow.by_zone("queue").entries == 1

    restarted = pipeline.process(make_perception(seq=0, tracks=(person(1, QUEUE_X),), seconds=2.0))

    assert restarted.zone_flow.by_zone("queue").entries == 0
