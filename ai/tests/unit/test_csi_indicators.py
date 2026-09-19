"""The five Crowd Stability Index indicators, and the curves behind them.

These are checked against hand-computed values on purpose.
``02_Hackathon_Execution_Plan.md`` section 7 names the failure mode explicitly:
*"A plausible-looking wrong formula is undetectable by inspection and will
misbehave on stage."* An assertion that a density of 4 p/m2 produces a pressure
of exactly 50 is the only thing that catches a curve quietly shifted by one
knot.
"""

from __future__ import annotations

import pytest

from surgeguard_ai.contracts import (
    CameraConfig,
    CountMethod,
    CrowdMetrics,
    DensityCell,
    DensityMap,
    FlowMetrics,
    ZoneOccupancy,
)
from surgeguard_ai.stability import (
    METRIC_DENSITY_CURVE,
    CsiConfig,
    IndicatorWeights,
    NormalizationCurve,
    indicators,
)

from .conftest import SCENARIO_START


def make_metrics(
    *,
    density_max: float = 0.0,
    is_metric: bool = True,
    median_speed: float | None = None,
    baseline_speed: float | None = None,
    opposing_fraction: float | None = None,
    zone_occupancy: tuple[ZoneOccupancy, ...] = (),
) -> CrowdMetrics:
    """Crowd metrics built directly, so an indicator is tested in isolation."""
    return CrowdMetrics(
        frame_seq=0,
        frame_ts=SCENARIO_START,
        person_count=0,
        count_method=CountMethod.TRACKED,
        density_map=DensityMap(
            rows=1,
            cols=1,
            cells=(DensityCell(row=0, col=0, persons=1.0, density=density_max),),
            is_metric=is_metric,
            cell_area_m2=1.0 if is_metric else None,
        ),
        density_max=density_max,
        density_mean=density_max,
        flow=FlowMetrics(
            median_speed=median_speed,
            baseline_speed=baseline_speed,
            dominant_heading_deg=0.0 if opposing_fraction is not None else None,
            opposing_fraction=opposing_fraction,
        ),
        zone_occupancy=zone_occupancy,
    )


# ---------------------------------------------------------------------------
# Normalization curves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("density", "expected"),
    [
        (0.0, 0.0),
        (2.0, 0.0),
        (3.0, 25.0),
        (4.0, 50.0),
        (4.5, 65.0),
        (5.0, 80.0),
        (6.0, 100.0),
    ],
)
def test_metric_density_curve_matches_the_frozen_specification(
    density: float, expected: float
) -> None:
    """The published-guidance anchors are exactly where the specification puts them."""
    assert METRIC_DENSITY_CURVE.pressure_for(density) == pytest.approx(expected)


def test_density_curve_holds_rather_than_extrapolating_past_its_anchors() -> None:
    """Beyond the last knot the pressure is held, not extrapolated.

    A curve anchored to published density guidance says nothing about what lies
    past its last anchor. Extrapolating would invent a claim the anchoring does
    not support - and would let pressure exceed 100, which the contract forbids.
    """
    assert METRIC_DENSITY_CURVE.pressure_for(20.0) == 100.0
    assert METRIC_DENSITY_CURVE.pressure_for(-5.0) == 0.0


def test_a_curve_rejects_unordered_knots() -> None:
    with pytest.raises(ValueError, match="ordered"):
        NormalizationCurve(knots=((4.0, 50.0), (2.0, 0.0)))


def test_weights_must_sum_to_one() -> None:
    """A weight set that does not sum to 1 silently rescales the whole index."""
    with pytest.raises(ValueError, match="sum to 1.0"):
        IndicatorWeights(density_pressure=0.5, motion_suppression=0.5, egress_congestion=0.5)


# ---------------------------------------------------------------------------
# Individual indicators
# ---------------------------------------------------------------------------


def test_density_pressure_uses_the_relative_curve_when_uncalibrated() -> None:
    """An uncalibrated camera is normalized against cells, not against p/m2.

    Applying the metric curve to persons-per-cell would read three people
    sharing a grid cell as an unremarkable 3 p/m2 - a quarter of the pressure
    the relative curve gives it.
    """
    config = CsiConfig()
    metric = indicators.density_pressure(make_metrics(density_max=3.0, is_metric=True), config)
    relative = indicators.density_pressure(
        make_metrics(density_max=3.0, is_metric=False), config
    )

    assert metric.pressure == pytest.approx(25.0)
    assert relative.pressure == pytest.approx(50.0)


def test_motion_suppression_is_a_ratio_against_the_camera_baseline() -> None:
    """Speed 30% below baseline is 30 points of pressure, in any unit."""
    measurement = indicators.motion_suppression(
        make_metrics(median_speed=7.0, baseline_speed=10.0), CsiConfig()
    )

    assert measurement.available
    assert measurement.raw_value == pytest.approx(0.7)
    assert measurement.pressure == pytest.approx(30.0)


def test_motion_faster_than_baseline_produces_no_pressure() -> None:
    """A crowd moving freely is not unstable, however far above baseline it is."""
    measurement = indicators.motion_suppression(
        make_metrics(median_speed=14.0, baseline_speed=10.0), CsiConfig()
    )
    assert measurement.pressure == pytest.approx(0.0)


def test_motion_suppression_is_unavailable_without_a_baseline() -> None:
    """Reported unmeasurable, never as zero.

    A missing baseline means the platform does not yet know this camera's
    normal. Scoring that as "movement is fine" is the most dangerous kind of
    false reassurance the index can produce.
    """
    measurement = indicators.motion_suppression(
        make_metrics(median_speed=7.0, baseline_speed=None), CsiConfig()
    )

    assert not measurement.available
    assert measurement.pressure is None
    assert measurement.unavailable_reason is not None


def test_egress_congestion_is_unavailable_without_a_configured_exit(
    camera: CameraConfig,
) -> None:
    """Nothing tells the platform where an exit is until an operator draws one."""
    measurement = indicators.egress_congestion(make_metrics(), camera, CsiConfig())

    assert not measurement.available
    assert "exit zone" in (measurement.unavailable_reason or "").lower()


def test_egress_congestion_takes_the_worst_exit(calibrated_camera: CameraConfig) -> None:
    """An evacuation is limited by its most congested route, not the average."""
    metrics = make_metrics(
        zone_occupancy=(
            ZoneOccupancy(zone_id="exit-b", persons=8.0, density=4.0, capacity_ratio=0.8),
        )
    )
    measurement = indicators.egress_congestion(metrics, calibrated_camera, CsiConfig())

    assert measurement.available
    assert measurement.raw_value == pytest.approx(0.8)
    assert measurement.pressure == pytest.approx(80.0)


def test_flow_conflict_is_attenuated_by_density() -> None:
    """Two people passing in an empty concourse are not a conflict.

    The frozen specification calls for flow conflict to be density-weighted.
    ``flow_density_floor`` keeps some of it at zero density, so opposing
    movement still registers as the early warning it is before a space fills.
    """
    config = CsiConfig()
    metrics = make_metrics(opposing_fraction=0.5)

    empty = indicators.flow_conflict(metrics, config, density_pressure_value=0.0)
    packed = indicators.flow_conflict(metrics, config, density_pressure_value=100.0)

    assert packed.pressure == pytest.approx(100.0)
    assert empty.pressure == pytest.approx(100.0 * config.flow_density_floor)
    assert empty.pressure is not None and empty.pressure > 0.0


def test_flow_conflict_is_unattenuated_when_density_is_unknown() -> None:
    """Scaling by an unknown would invent the quantity the scaling accounts for."""
    measurement = indicators.flow_conflict(
        make_metrics(opposing_fraction=0.5), CsiConfig(), density_pressure_value=None
    )
    assert measurement.pressure == pytest.approx(100.0)


def test_rate_of_change_ignores_a_falling_density() -> None:
    """A dispersing crowd is not an unstable one.

    The signed rate is still reported, because the Evidence Engine needs to
    tell "occupancy increasing" from "crowd dispersing" without measuring
    density a second time.
    """
    config = CsiConfig()
    metrics = make_metrics(density_max=3.0)

    falling = indicators.rate_of_change(-0.04, metrics, config)
    rising = indicators.rate_of_change(0.025, metrics, config)

    assert falling.pressure == pytest.approx(0.0)
    assert falling.raw_value == pytest.approx(-0.04)
    assert rising.pressure == pytest.approx(50.0)


def test_rate_of_change_is_unavailable_without_history() -> None:
    measurement = indicators.rate_of_change(None, make_metrics(), CsiConfig())
    assert not measurement.available
