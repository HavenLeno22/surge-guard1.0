"""Person tracking with ByteTrack - Stage 3.

Tracking is fed synthetic detections rather than a model's, so that identity
stability can be asserted against known motion. What is being tested is the
adaptation this package owns - identity persistence, ageing, velocity, reset -
not ByteTrack's association algorithm.
"""

from __future__ import annotations

import pytest

from surgeguard_ai.contracts import CameraConfig
from surgeguard_ai.perception import ByteTrackTracker

from .conftest import make_detections, make_frame

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def walk(
    tracker: ByteTrackTracker,
    camera: CameraConfig,
    frames: int,
    *,
    step: float = 4.0,
    start: float = 20.0,
    people: int = 1,
    size: tuple[int, int] = (640, 480),
):
    """Move ``people`` upright boxes steadily to the right and track them."""
    results = []
    for index in range(frames):
        frame = make_frame(index, size=size)
        boxes = [
            (
                start + index * step + person * 120.0,
                100.0,
                start + index * step + person * 120.0 + 40.0,
                220.0,
            )
            for person in range(people)
        ]
        results.append(tracker.update(frame, make_detections(frame, boxes), camera))
    return results


class TestIdentity:
    def test_a_person_walking_keeps_one_identity(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0)
        results = walk(tracker, camera, frames=25)

        confirmed = [result for result in results if result.count]
        assert confirmed, "tracking never confirmed the walking person"

        identities = {track.track_id for result in confirmed for track in result.tracks}
        assert identities == {1}, f"identity was not stable: {identities}"

    def test_separate_people_get_separate_identities(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0)
        results = walk(tracker, camera, frames=20, people=3)

        assert results[-1].count == 3
        assert len({track.track_id for track in results[-1].tracks}) == 3

    def test_track_age_grows_with_every_frame(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0)
        results = walk(tracker, camera, frames=20)

        ages = [result.tracks[0].age_frames for result in results if result.count]
        assert ages == sorted(ages)
        assert ages[-1] > ages[0]

    def test_an_empty_frame_produces_no_tracks(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0)
        frame = make_frame(0)
        result = tracker.update(frame, make_detections(frame, []), camera)

        assert result.count == 0
        assert result.frame_seq == 0


class TestMovement:
    def test_velocity_follows_the_direction_of_travel(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0)
        results = walk(tracker, camera, frames=25, step=4.0)

        moving = [
            track
            for result in results
            for track in result.tracks
            if track.velocity_image is not None
        ]
        assert moving, "no velocity was ever estimated"

        latest = moving[-1].velocity_image
        # 4 px per frame at 20 fps is 80 px/s to the right, and no vertical motion.
        assert latest.dx == pytest.approx(80.0, rel=0.25)
        assert latest.dy == pytest.approx(0.0, abs=5.0)

    def test_velocity_is_unknown_until_there_is_history(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0)
        first = walk(tracker, camera, frames=1)[0]

        for track in first.tracks:
            assert track.velocity_image is None

    def test_ground_measurements_stay_unset_without_calibration(
        self,
        camera: CameraConfig,
    ) -> None:
        """An uncalibrated camera cannot produce metres, and must not pretend to."""
        assert not camera.is_calibrated

        tracker = ByteTrackTracker(frame_rate=20.0)
        results = walk(tracker, camera, frames=20)

        for result in results:
            for track in result.tracks:
                assert track.ground_point is None
                assert track.velocity_ground is None

    def test_the_foot_point_is_the_bottom_of_the_box(self, camera: CameraConfig) -> None:
        """Ground projection uses where the person stands, not their torso."""
        tracker = ByteTrackTracker(frame_rate=20.0)
        results = walk(tracker, camera, frames=10)

        for result in results:
            for track in result.tracks:
                assert track.foot_point.y == pytest.approx(track.bbox.y2)
                assert track.foot_point.x == pytest.approx(track.bbox.centroid.x)


class TestLifecycle:
    @pytest.mark.parametrize(
        ("frame_rate", "timeout_s", "expected_frames"),
        [(25.0, 1.0, 25), (10.0, 2.0, 20), (30.0, 0.5, 15)],
    )
    def test_lost_track_timeout_is_expressed_in_frames(
        self,
        frame_rate: float,
        timeout_s: float,
        expected_frames: int,
    ) -> None:
        """A timeout in seconds means the same thing at any frame rate."""
        tracker = ByteTrackTracker(frame_rate=frame_rate, lost_track_timeout_s=timeout_s)
        assert tracker.lost_track_timeout_frames == expected_frames

    def test_a_timeout_never_rounds_down_to_zero(self) -> None:
        tracker = ByteTrackTracker(frame_rate=25.0, lost_track_timeout_s=0.001)
        assert tracker.lost_track_timeout_frames == 1

    def test_reset_discards_every_identity(self, camera: CameraConfig) -> None:
        """Identities from before a continuity break must not survive it."""
        tracker = ByteTrackTracker(frame_rate=20.0)
        walk(tracker, camera, frames=20)
        assert tracker.active_track_count > 0

        tracker.reset()

        assert tracker.active_track_count == 0
        assert tracker._histories == {}

    def test_movement_history_is_discarded_on_reset(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0)
        walk(tracker, camera, frames=20)
        tracker.reset()

        first_after = walk(tracker, camera, frames=1)[0]
        for track in first_after.tracks:
            assert track.velocity_image is None

    def test_identity_switches_are_not_guessed(self, camera: CameraConfig) -> None:
        """Counting switches needs ground truth; a guess would corrupt confidence."""
        tracker = ByteTrackTracker(frame_rate=20.0)
        for result in walk(tracker, camera, frames=10):
            assert result.id_switches == 0


class TestReliability:
    def test_a_small_crowd_is_within_the_trusted_range(self, camera: CameraConfig) -> None:
        tracker = ByteTrackTracker(frame_rate=20.0, reliable_track_limit=10)
        walk(tracker, camera, frames=15, people=3)
        assert tracker.is_reliable

    def test_exceeding_the_limit_is_reported(self, camera: CameraConfig) -> None:
        """Above the limit the platform must say so rather than keep asserting."""
        tracker = ByteTrackTracker(frame_rate=20.0, reliable_track_limit=2)
        walk(tracker, camera, frames=15, people=4)
        assert not tracker.is_reliable


class TestConfiguration:
    def test_frame_rate_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="frame_rate"):
            ByteTrackTracker(frame_rate=0)

    def test_velocity_needs_at_least_two_samples(self) -> None:
        with pytest.raises(ValueError, match="velocity_window"):
            ByteTrackTracker(velocity_window=1)
