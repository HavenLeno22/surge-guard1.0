"""Background health checks for a network camera.

The network calls are replaced with recorded answers, so what is tested is the
monitor's judgement: when it may open the stream, when it must not, and when a
returning device should cut a recovery backoff short.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from surgeguard_ai.contracts import SourceMode

from app.cameras import health as health_module
from app.cameras.health import CameraHealthMonitor, probe_address
from app.cameras.probe import CameraDeviceInfo, StreamDiagnosis, StreamOutcome
from app.workers.perception_worker import PerceptionWorkerState

URL = "http://192.0.2.10:4747/video"
DEVICE = CameraDeviceInfo(network_rtt_ms=12.0, device_name="A015", battery_percent=58)


@dataclass
class _Network:
    """What the camera's address answers, and how often it was asked."""

    device: CameraDeviceInfo | None = DEVICE
    diagnosis: StreamDiagnosis = field(
        default_factory=lambda: StreamDiagnosis(StreamOutcome.BUSY, "DroidCam is busy.")
    )
    device_checks: int = 0
    stream_diagnoses: int = 0

    def fetch_device_info(self, _url: str) -> CameraDeviceInfo | None:
        self.device_checks += 1
        return self.device

    def diagnose_stream(self, _url: str) -> StreamDiagnosis:
        self.stream_diagnoses += 1
        return self.diagnosis


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> _Network:
    fake = _Network()
    monkeypatch.setattr(health_module, "fetch_device_info", fake.fetch_device_info)
    monkeypatch.setattr(health_module, "diagnose_stream", fake.diagnose_stream)
    return fake


class _Camera:
    def __init__(self, state: PerceptionWorkerState, url: str | None = URL) -> None:
        self.state = state
        self.url = url
        self.retries = 0

    def retry_now(self) -> None:
        self.retries += 1


def _monitor(camera: _Camera) -> CameraHealthMonitor:
    return CameraHealthMonitor(
        camera_id="cam-02",
        url_provider=lambda: camera.url,
        state_provider=lambda: camera.state,
        diagnose_interval_seconds=60.0,
        on_device_returned=camera.retry_now,
    )


async def test_a_running_camera_has_its_device_checked_but_its_stream_left_alone(
    network: _Network,
) -> None:
    camera = _Camera(PerceptionWorkerState.RUNNING)
    monitor = _monitor(camera)

    await monitor.check_once()

    assert monitor.device == DEVICE
    assert monitor.device_reachable is True
    # SurgeGuard holds the stream; a diagnosis would be a second viewer.
    assert network.stream_diagnoses == 0
    assert monitor.diagnosis is None


async def test_a_recovering_camera_whose_device_is_silent_is_reported_unreachable(
    network: _Network,
) -> None:
    network.device = None
    camera = _Camera(PerceptionWorkerState.RECOVERING)
    monitor = _monitor(camera)

    await monitor.check_once()

    assert monitor.device_reachable is False
    assert monitor.diagnosis is not None
    assert monitor.diagnosis.outcome is StreamOutcome.UNREACHABLE
    # Opening the stream of a device that does not answer would say no more.
    assert network.stream_diagnoses == 0
    assert camera.retries == 0


async def test_a_reachable_recovering_camera_is_diagnosed_at_most_once_per_interval(
    network: _Network,
) -> None:
    camera = _Camera(PerceptionWorkerState.RECOVERING)
    monitor = _monitor(camera)

    await monitor.check_once()
    await monitor.check_once()

    assert network.device_checks == 2
    assert network.stream_diagnoses == 1
    assert monitor.diagnosis is not None
    assert monitor.diagnosis.outcome is StreamOutcome.BUSY


async def test_a_device_that_answers_again_cuts_the_recovery_backoff_short(
    network: _Network,
) -> None:
    network.device = None
    camera = _Camera(PerceptionWorkerState.RECOVERING)
    monitor = _monitor(camera)
    await monitor.check_once()

    network.device = DEVICE
    await monitor.check_once()

    assert camera.retries == 1
    # Reconnecting is the test: the stream is not opened first, so the phone is
    # not still counting a diagnosis as its one viewer when the worker arrives.
    assert network.stream_diagnoses == 0
    assert monitor.diagnosis is None


async def test_a_device_that_was_never_lost_does_not_trigger_a_reconnection(
    network: _Network,
) -> None:
    camera = _Camera(PerceptionWorkerState.RECOVERING)
    monitor = _monitor(camera)

    await monitor.check_once()
    await monitor.check_once()

    assert camera.retries == 0


async def test_a_returning_device_does_not_disturb_a_camera_that_is_not_recovering(
    network: _Network,
) -> None:
    network.device = None
    camera = _Camera(PerceptionWorkerState.RUNNING)
    monitor = _monitor(camera)
    await monitor.check_once()

    network.device = DEVICE
    await monitor.check_once()

    assert camera.retries == 0


async def test_an_address_change_forgets_what_was_learned_about_the_old_one(
    network: _Network,
) -> None:
    network.device = None
    camera = _Camera(PerceptionWorkerState.RECOVERING)
    monitor = _monitor(camera)
    await monitor.check_once()

    monitor.reset()

    assert monitor.device_reachable is None
    assert monitor.diagnosis is None
    # A first answer from the new address is not a device "returning".
    network.device = DEVICE
    await monitor.check_once()
    assert camera.retries == 0


async def test_a_demonstration_camera_is_not_diagnosed_through_its_phone(
    network: _Network,
) -> None:
    """In Demonstration Mode frames come from a clip: a silent phone is not the reason it failed."""
    network.device = None
    camera = _Camera(PerceptionWorkerState.FAILED)
    monitor = CameraHealthMonitor(
        camera_id="cam-02",
        url_provider=lambda: probe_address(camera.url, SourceMode.DEMO),
        state_provider=lambda: camera.state,
        diagnose_interval_seconds=60.0,
    )

    await monitor.check_once()

    assert network.device_checks == 0
    assert monitor.diagnosis is None


def test_a_live_camera_is_probed_at_its_stream_address() -> None:
    assert probe_address(URL, SourceMode.LIVE) == URL


async def test_a_local_device_index_is_never_probed_over_the_network(
    network: _Network,
) -> None:
    camera = _Camera(PerceptionWorkerState.RECOVERING, url="0")
    monitor = _monitor(camera)

    await monitor.check_once()

    assert network.device_checks == 0
    assert monitor.device_reachable is None
