"""How a deployment tunes crowd measurement and the Crowd Stability Index.

An uncalibrated camera measures density as people per grid cell, on a scale the
AI package documents as a per-deployment heuristic "that must be tuned against
the actual view". A phone a few metres from a group sees each person spread over
several cells of the default grid, so the busiest cell rarely holds more than
one person and density never registers. These settings are how a deployment
fits the scale to its views without editing code.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.workers.perception_factory import build_crowd_analysis_config, build_csi_config


def _settings(tmp_path, **overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        **overrides,
    )


def test_the_defaults_are_the_frozen_specification(tmp_path) -> None:
    settings = _settings(tmp_path)

    crowd = build_crowd_analysis_config(settings)
    csi = build_csi_config(settings)

    assert (crowd.grid_rows, crowd.grid_cols) == (6, 8)
    assert csi.relative_density_curve.knots == ((1.0, 0.0), (3.0, 50.0), (4.5, 80.0), (6.0, 100.0))
    assert csi.rate_ceiling_relative == pytest.approx(0.05)


def test_the_density_grid_follows_settings(tmp_path) -> None:
    crowd = build_crowd_analysis_config(_settings(tmp_path, crowd_grid_rows=3, crowd_grid_cols=4))

    assert (crowd.grid_rows, crowd.grid_cols) == (3, 4)


def test_the_relative_density_curve_is_read_from_a_knot_list(tmp_path) -> None:
    """Written as `people:pressure` pairs, the form a .env file can hold."""
    settings = _settings(tmp_path, csi_relative_density_knots="1:0, 2:40, 3:75, 4:100")

    curve = build_csi_config(settings).relative_density_curve

    assert curve.knots == ((1.0, 0.0), (2.0, 40.0), (3.0, 75.0), (4.0, 100.0))
    assert curve.pressure_for(2.5) == pytest.approx(57.5)


@pytest.mark.parametrize(
    "knots",
    ["3:50", "2:40,1:0", "1:0,2:140", "one:0,2:40"],
    ids=["single-knot", "out-of-order", "pressure-above-100", "not-a-number"],
)
def test_an_unusable_density_curve_is_refused_at_startup(tmp_path, knots: str) -> None:
    with pytest.raises(ValidationError):
        _settings(tmp_path, csi_relative_density_knots=knots)


def test_the_relative_rate_ceiling_follows_settings(tmp_path) -> None:
    csi = build_csi_config(_settings(tmp_path, csi_rate_ceiling_relative=0.02))

    assert csi.rate_ceiling_relative == pytest.approx(0.02)


def test_decision_confidence_is_floored_at_the_detection_threshold(tmp_path) -> None:
    """A detection exactly at the threshold is marginal, whatever the threshold is set to."""
    csi = build_csi_config(_settings(tmp_path, detection_confidence_threshold=0.25))

    assert csi.confidence.detection_floor == pytest.approx(0.25)
