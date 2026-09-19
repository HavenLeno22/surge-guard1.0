"""Shared pytest fixtures for the SurgeGuard AI Pipeline test suite."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from numpy.typing import NDArray

from surgeguard_ai.contracts import CameraConfig
from surgeguard_ai.perception import Frame


@pytest.fixture
def blank_image() -> NDArray[np.uint8]:
    """A small black BGR image, for tests that need a frame but not content."""
    return np.zeros((360, 640, 3), dtype=np.uint8)


@pytest.fixture
def frame(blank_image: NDArray[np.uint8]) -> Frame:
    """A single frame with a fixed timestamp, for deterministic assertions."""
    return Frame(
        seq=0,
        ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        image=blank_image,
        source_id="test-source",
    )


@pytest.fixture
def uncalibrated_camera() -> CameraConfig:
    """A camera with no calibration and no zones.

    Density from this camera is relative, not persons/m2, and egress congestion
    is unmeasurable.
    """
    return CameraConfig(
        camera_id="cam-test",
        name="Test Camera",
        location="Test Location",
    )
