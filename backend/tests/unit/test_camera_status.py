"""A camera's connection status, judged from evidence.

The case that motivated this module: a phone that left the network left its
worker reporting RUNNING for minutes, because a blocked read never returned. A
status taken from the worker's word would have shown that camera ONLINE.
"""

from __future__ import annotations

import pytest
from surgeguard_ai.contracts import CameraConnectionStatus

from app.cameras.status import StatusThresholds, derive_status
from app.workers.perception_worker import PerceptionWorkerState


def status_of(**overrides):
    arguments = {
        "enabled": True,
        "worker_state": PerceptionWorkerState.RUNNING,
        "worker_detail": None,
        "frame_age_seconds": 0.1,
        "achieved_fps": 22.0,
        "pipeline_degraded_reason": None,
        "diagnosis_detail": None,
        "thresholds": StatusThresholds(),
    }
    arguments.update(overrides)
    return derive_status(**arguments)


def test_a_running_camera_with_fresh_frames_is_online() -> None:
    assert status_of() == (CameraConnectionStatus.ONLINE, None)


def test_a_disabled_camera_is_disabled_whatever_its_worker_says() -> None:
    status, detail = status_of(enabled=False)
    assert status is CameraConnectionStatus.DISABLED
    assert "operator" in detail


def test_a_running_worker_with_no_recent_frame_is_offline() -> None:
    """The field failure: RUNNING, but the last frame was minutes ago."""
    status, detail = status_of(frame_age_seconds=160.0)
    assert status is CameraConnectionStatus.OFFLINE
    assert "160" in detail


def test_late_frames_are_degraded_rather_than_offline() -> None:
    status, _ = status_of(frame_age_seconds=4.0)
    assert status is CameraConnectionStatus.DEGRADED


def test_a_running_worker_before_its_first_frame_is_connecting() -> None:
    status, _ = status_of(frame_age_seconds=None)
    assert status is CameraConnectionStatus.CONNECTING


def test_too_low_a_frame_rate_is_degraded() -> None:
    status, detail = status_of(achieved_fps=2.5)
    assert status is CameraConnectionStatus.DEGRADED
    assert "2.5 fps" in detail


def test_a_degraded_pipeline_is_degraded_with_its_reason() -> None:
    status, detail = status_of(pipeline_degraded_reason="Detection unavailable: CUDA error")
    assert status is CameraConnectionStatus.DEGRADED
    assert detail == "Detection unavailable: CUDA error"


def test_a_recovering_camera_prefers_the_diagnosis_over_the_generic_reason() -> None:
    """ "Could not be opened" says nothing; "DroidCam is busy" says what to do."""
    status, detail = status_of(
        worker_state=PerceptionWorkerState.RECOVERING,
        worker_detail="The camera or video source could not be opened. Retrying in 4s.",
        diagnosis_detail="DroidCam at 172.18.225.59:4747 is busy: another client is connected.",
    )
    assert status is CameraConnectionStatus.RECOVERING
    assert "busy" in detail


@pytest.mark.parametrize(
    ("worker_state", "expected"),
    [
        (PerceptionWorkerState.STARTING, CameraConnectionStatus.CONNECTING),
        (PerceptionWorkerState.RECOVERING, CameraConnectionStatus.RECOVERING),
        (PerceptionWorkerState.FAILED, CameraConnectionStatus.OFFLINE),
        (PerceptionWorkerState.STOPPED, CameraConnectionStatus.OFFLINE),
        (PerceptionWorkerState.COMPLETED, CameraConnectionStatus.OFFLINE),
        (PerceptionWorkerState.DISABLED, CameraConnectionStatus.OFFLINE),
    ],
)
def test_non_running_workers_map_to_a_status_with_a_reason(
    worker_state: PerceptionWorkerState, expected: CameraConnectionStatus
) -> None:
    status, detail = status_of(worker_state=worker_state, frame_age_seconds=None)
    assert status is expected
    assert detail


@pytest.mark.parametrize(
    ("status", "contributing"),
    [
        (CameraConnectionStatus.ONLINE, True),
        (CameraConnectionStatus.DEGRADED, True),
        (CameraConnectionStatus.CONNECTING, False),
        (CameraConnectionStatus.RECOVERING, False),
        (CameraConnectionStatus.OFFLINE, False),
        (CameraConnectionStatus.DISABLED, False),
    ],
)
def test_only_delivering_cameras_contribute_to_site_figures(
    status: CameraConnectionStatus, contributing: bool
) -> None:
    assert status.is_contributing is contributing
