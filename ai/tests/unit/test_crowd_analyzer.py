"""Crowd analysis - Stages 4 and 5.

The measurements every later stage rests on. Two things matter most here and
are tested hardest: that a calibrated camera produces persons/m2 and an
uncalibrated one does not silently pretend to, and that the speed baseline is a
comparison against this camera's own history rather than an absolute.
"""

from __future__ import annotations

import pytest

from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
from surgeguard_ai.contracts import CameraConfig, CountMethod, TrackingResult

from .conftest import ANALYSIS_SIZE, SCENARIO_START, make_tracks


def analyzer() -> GridCrowdAnalyzer:
    width, height = ANALYSIS_SIZE
    return GridCrowdAnalyzer(CrowdAnalysisConfig(frame_width=width, frame_height=height))


def tracking(tracks, *, seq: int = 0, seconds: float = 0.0) -> TrackingResult:
    from datetime import timedelta

    return TrackingResult(
        frame_seq=seq,
        frame_ts=SCENARIO_START + timedelta(seconds=seconds),
        tracks=tracks,
    )


def test_an_empty_scene_measures_zero_rather_than_failing(camera: CameraConfig) -> None:
    """No people is a measurement, not a missing one."""
    metrics = analyzer().analyze(tracking(()), camera)

    assert metrics.person_count == 0
    assert metrics.density_max == 0.0
    assert metrics.density_mean == 0.0
    assert metrics.flow.median_speed is None


def test_an_uncalibrated_camera_reports_relative_density(camera: CameraConfig) -> None:
    """`is_metric` is False and no cell area is claimed.

    This flag is the only thing standing between a relative figure and a
    display presenting it as persons/m2 (Architecture Review C21).
    """
    metrics = analyzer().analyze(tracking(make_tracks(count=6, speed=20.0)), camera)

    assert metrics.is_metric is False
    assert metrics.density_map.cell_area_m2 is None
    assert metrics.density_max > 0.0


def test_a_calibrated_camera_reports_persons_per_square_metre(
    calibrated_camera: CameraConfig,
) -> None:
    """Cell area comes from the homography, so density is a real measurement.

    The fixture's homography scales one pixel to 0.02 m, so the 960x540 view is
    19.2 m by 10.8 m = 207.36 m2, and one cell of the default 6x8 grid is
    207.36 / 48 = 4.32 m2.
    """
    metrics = analyzer().analyze(
        tracking(make_tracks(count=4, speed=20.0, spread_px=40.0)), calibrated_camera
    )

    assert metrics.is_metric is True
    assert metrics.density_map.cell_area_m2 == pytest.approx(4.32)
    # Four people in one cell of 4.32 m2.
    assert metrics.density_max == pytest.approx(4 / 4.32)


def test_peak_density_reflects_clustering_not_headcount(camera: CameraConfig) -> None:
    """The same headcount packed and spread are different crowds.

    Peak rather than mean, deliberately: a crush happens in one place, and a
    mean across the view would let a dangerous corner be averaged away by the
    empty space beside it.
    """
    packed = analyzer().analyze(
        tracking(make_tracks(count=8, speed=20.0, spread_px=30.0)), camera
    )
    spread = analyzer().analyze(
        tracking(make_tracks(count=8, speed=20.0, spread_px=900.0)), camera
    )

    assert packed.density_max > spread.density_max


def test_the_speed_baseline_needs_enough_samples_before_it_is_reported(
    camera: CameraConfig,
) -> None:
    """Below the sample floor there is no baseline, rather than a baseline of one frame."""
    subject = analyzer()
    tracks = make_tracks(count=5, speed=30.0)

    first = subject.analyze(tracking(tracks, seq=0, seconds=0.0), camera)
    assert first.flow.baseline_speed is None

    for step in range(1, 15):
        metrics = subject.analyze(tracking(tracks, seq=step, seconds=step), camera)

    assert metrics.flow.baseline_speed == pytest.approx(30.0)


def test_the_baseline_is_a_median_so_one_collapsed_frame_does_not_poison_it(
    camera: CameraConfig,
) -> None:
    """A frame where tracking briefly collapsed must not distort five minutes of normal."""
    subject = analyzer()

    for step in range(20):
        speed = 1.0 if step == 10 else 30.0
        metrics = subject.analyze(
            tracking(make_tracks(count=5, speed=speed), seq=step, seconds=step), camera
        )

    assert metrics.flow.baseline_speed == pytest.approx(30.0)


def test_opposing_movement_is_measured_against_the_dominant_heading(
    camera: CameraConfig,
) -> None:
    """Three of ten going the other way is an opposing fraction of 0.3."""
    metrics = analyzer().analyze(
        tracking(make_tracks(count=10, speed=25.0, opposing=3)), camera
    )

    assert metrics.flow.opposing_fraction == pytest.approx(0.3)
    assert metrics.flow.dominant_heading_deg == pytest.approx(0.0)


def test_a_crowd_with_no_majority_direction_reports_no_opposing_fraction(
    camera: CameraConfig,
) -> None:
    """"Opposing the majority" is not a meaningful question without a majority."""
    metrics = analyzer().analyze(
        tracking(make_tracks(count=10, speed=25.0, opposing=5)), camera
    )

    assert metrics.flow.dominant_heading_deg is None
    assert metrics.flow.opposing_fraction is None


def test_the_count_becomes_an_estimate_above_the_tracking_ceiling(
    camera: CameraConfig,
) -> None:
    """Detection-plus-tracking does not survive extreme density, and says so.

    Reporting the method is what stops an estimate being displayed as a tracked
    count (Architecture Review C11).
    """
    width, height = ANALYSIS_SIZE
    subject = GridCrowdAnalyzer(
        CrowdAnalysisConfig(frame_width=width, frame_height=height, tracked_count_ceiling=5)
    )

    below = subject.analyze(tracking(make_tracks(count=5, speed=20.0)), camera)
    above = subject.analyze(tracking(make_tracks(count=6, speed=20.0)), camera)

    assert below.count_method is CountMethod.TRACKED
    assert above.count_method is CountMethod.ESTIMATED


def test_zone_occupancy_is_measured_only_for_configured_zones(
    camera: CameraConfig, calibrated_camera: CameraConfig
) -> None:
    """No zones means no occupancy, not an occupancy of zero for an assumed exit."""
    tracks = make_tracks(count=6, speed=20.0, origin_x=20.0, spread_px=180.0, y=500.0)

    assert analyzer().analyze(tracking(tracks), camera).zone_occupancy == ()

    occupancy = analyzer().analyze(tracking(tracks), calibrated_camera).zone_occupancy
    assert len(occupancy) == 1
    assert occupancy[0].zone_id == "exit-b"
    assert occupancy[0].persons > 0
    # Capacity ratio is persons over (width_m * capacity per metre) = 2.0 * 5.0.
    assert occupancy[0].capacity_ratio == pytest.approx(occupancy[0].persons / 10.0)


def test_reset_discards_the_speed_baseline(camera: CameraConfig) -> None:
    """A baseline learned from one source must never describe another."""
    subject = analyzer()
    for step in range(15):
        subject.analyze(
            tracking(make_tracks(count=5, speed=30.0), seq=step, seconds=step), camera
        )

    subject.reset()
    metrics = subject.analyze(tracking(make_tracks(count=5, speed=30.0)), camera)

    assert metrics.flow.baseline_speed is None
