"""Live Camera Mode frame source - Stage 1.

A real camera cannot be unplugged from a test, so the capture is replaced with a
double whose availability is controlled directly. What is exercised is the
source's own behaviour: how it distinguishes a momentary gap from a lost camera,
and what it does about each.
"""

from __future__ import annotations

import numpy as np
import pytest

from surgeguard_ai.contracts import SourceMode
from surgeguard_ai.errors import SourceUnavailableError
from surgeguard_ai.perception import LiveCameraSource
from surgeguard_ai.perception import live_camera_source as module


class FakeCapture:
    """Stands in for ``cv2.VideoCapture``, with scriptable failures."""

    #: Every instance created during a test, so reconnection can be observed.
    instances: list[FakeCapture] = []

    def __init__(self, target, api_preference=None, *, openable: bool = True) -> None:
        self.target = target
        self._openable = openable
        self.released = False
        self.fail_reads = 0
        FakeCapture.instances.append(self)

    def isOpened(self) -> bool:  # noqa: N802 - mirrors the OpenCV API
        return self._openable and not self.released

    def read(self):
        if self.fail_reads > 0:
            self.fail_reads -= 1
            return False, None
        return True, np.zeros((240, 320, 3), dtype=np.uint8)

    def get(self, prop):
        return 30.0

    def set(self, prop, value):
        return True

    def grab(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True


@pytest.fixture
def fake_capture(monkeypatch: pytest.MonkeyPatch):
    """Replace ``cv2.VideoCapture`` and remove the reconnection sleep."""
    FakeCapture.instances = []
    openable = {"value": True}

    def factory(target, api_preference=None):
        return FakeCapture(target, api_preference, openable=openable["value"])

    monkeypatch.setattr(module.cv2, "VideoCapture", factory)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return openable


class TestReading:
    def test_reports_live_provenance(self) -> None:
        assert LiveCameraSource("cam", 0).source_mode is SourceMode.LIVE

    def test_reads_frames_with_a_monotonic_sequence(self, fake_capture) -> None:
        source = LiveCameraSource("cam", 0)
        with source:
            frames = [source.read() for _ in range(3)]

        assert [frame.seq for frame in frames] == [0, 1, 2]

    def test_timestamps_are_wall_clock(self, fake_capture) -> None:
        """A live frame is happening now, so its timestamp is now."""
        source = LiveCameraSource("cam", 0)
        with source:
            first = source.read()
            second = source.read()

        assert second.ts >= first.ts

    def test_resize_is_applied(self, fake_capture) -> None:
        source = LiveCameraSource("cam", 0, resize=(160, 120))
        with source:
            frame = source.read()

        assert (frame.width, frame.height) == (160, 120)

    def test_a_camera_that_cannot_be_opened_is_reported(self, fake_capture) -> None:
        fake_capture["value"] = False
        with pytest.raises(SourceUnavailableError, match="Could not open"):
            LiveCameraSource("cam", 0).open()

    def test_a_brief_gap_is_not_a_failure(self, fake_capture) -> None:
        """A handful of dropped frames is normal on a camera; only a run is not."""
        source = LiveCameraSource("cam", 0)
        with source:
            source._capture.fail_reads = 3
            assert source.read() is None
            assert source.read() is None
            assert source.read() is None
            assert source.read() is not None


def lose_camera(source: LiveCameraSource, *, max_reads: int = 200) -> int:
    """Fail the camera continuously and read until the source has reconnected.

    A single failed read is a gap, not a dropout: the source tolerates a bounded
    run of them before concluding the camera has gone. Reconnection is therefore
    only reachable by sustaining the failure, and the number of reads it takes is
    the source's business, not the test's.

    Returns:
        How many reads reported a gap before reconnection completed.
    """
    source._capture.fail_reads = 10_000
    before = source.reconnections

    for attempt in range(1, max_reads + 1):
        source.read()
        if source.reconnections > before:
            return attempt

    raise AssertionError(f"the source did not reconnect within {max_reads} reads")


class TestReconnection:
    def test_a_lost_camera_is_reconnected(self, fake_capture) -> None:
        source = LiveCameraSource("cam", 0, reconnect_attempts=3)
        with source:
            gaps = lose_camera(source)

            assert gaps > 1, "a single failed read should not be treated as a dropout"
            assert source.reconnections == 1
            assert source.read() is not None  # the camera is working again

    def test_reconnection_restarts_the_frame_sequence(self, fake_capture) -> None:
        """The restart is the signal that movement history spans a gap.

        A consumer that kept tracking across a dropout would be describing motion
        that never happened.
        """
        source = LiveCameraSource("cam", 0, reconnect_attempts=2)
        with source:
            assert source.read().seq == 0
            assert source.read().seq == 1
            lose_camera(source)
            recovered = source.read()

        assert recovered.seq == 0

    def test_an_unreachable_camera_is_declared_lost(self, fake_capture) -> None:
        source = LiveCameraSource("cam", 0, reconnect_attempts=2)
        source.open()
        source._capture.fail_reads = 10_000
        fake_capture["value"] = False  # reopening will fail from here on

        with pytest.raises(SourceUnavailableError):
            for _ in range(40):
                source.read()

    def test_reconnection_can_be_disabled(self, fake_capture) -> None:
        source = LiveCameraSource("cam", 0, reconnect_attempts=0)
        with source:
            source._capture.fail_reads = 10_000
            with pytest.raises(SourceUnavailableError):
                for _ in range(40):
                    source.read()
        assert source.reconnections == 0


class TestNetworkStalls:
    """A phone that leaves the network must be noticed within seconds.

    Observed in the field: with no read timeout, a DroidCam phone that dropped
    off the network left the pipeline reporting itself RUNNING for minutes after
    its last frame, because the blocking read simply never returned.
    """

    def test_timeouts_are_passed_to_the_capture_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created: list[tuple[object, object, object]] = []

        def factory(target, api_preference=None, params=None):
            created.append((target, api_preference, params))
            return FakeCapture(target, api_preference)

        monkeypatch.setattr(module.cv2, "VideoCapture", factory)

        source = LiveCameraSource(
            "cam", "http://phone:4747/video", open_timeout_ms=4000, read_timeout_ms=2500
        )
        with source:
            pass

        (target, api, params) = created[0]
        assert api == module.cv2.CAP_FFMPEG
        assert params == [
            module.cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            4000,
            module.cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            2500,
        ]

    def test_a_source_without_timeouts_is_opened_as_before(self, fake_capture) -> None:
        """No timeout configured, no change to how the device is opened."""
        with LiveCameraSource("cam", 0):
            pass
        assert FakeCapture.instances[0].target == 0

    def test_a_stall_is_declared_by_elapsed_time_not_only_by_count(
        self, fake_capture
    ) -> None:
        now = {"t": 100.0}
        source = LiveCameraSource(
            "cam",
            0,
            reconnect_attempts=0,
            max_stall_seconds=5.0,
            clock=lambda: now["t"],
        )
        with source:
            source._capture.fail_reads = 10_000
            assert source.read() is None  # the stall begins
            now["t"] += 3.0
            assert source.read() is None  # still within the allowance
            now["t"] += 2.5
            with pytest.raises(SourceUnavailableError, match="no frame for"):
                source.read()

    def test_a_frame_ends_the_stall(self, fake_capture) -> None:
        now = {"t": 0.0}
        source = LiveCameraSource(
            "cam", 0, reconnect_attempts=0, max_stall_seconds=5.0, clock=lambda: now["t"]
        )
        with source:
            source._capture.fail_reads = 1
            assert source.read() is None
            now["t"] += 4.0
            assert source.read() is not None  # recovered - the clock restarts
            source._capture.fail_reads = 1
            now["t"] += 4.0
            assert source.read() is None, "a new gap is not added to the old one"

    def test_the_native_resolution_is_reported_before_resizing(self, fake_capture) -> None:
        source = LiveCameraSource("cam", 0, resize=(160, 120))
        assert source.native_size is None
        with source:
            frame = source.read()
        assert (frame.width, frame.height) == (160, 120)
        assert source.native_size == (320, 240)


class TestAvailability:
    def test_a_working_camera_is_available(self, fake_capture) -> None:
        assert LiveCameraSource.is_available(0) is True

    def test_a_camera_that_will_not_open_is_unavailable(self, fake_capture) -> None:
        fake_capture["value"] = False
        assert LiveCameraSource.is_available(0) is False

    def test_probing_releases_the_device(self, fake_capture) -> None:
        """Probing must not leave a camera claimed - the pipeline needs it next."""
        LiveCameraSource.is_available(0)
        assert all(capture.released for capture in FakeCapture.instances)

    def test_listing_devices_probes_each_index(self, fake_capture) -> None:
        assert LiveCameraSource.list_available_devices(2) == (0, 1, 2)
