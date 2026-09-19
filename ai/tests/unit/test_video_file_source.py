"""Demonstration Mode frame source - Stage 1.

The properties tested here are what make "a recorded clip is processed exactly
as a live camera feed" true rather than merely claimed.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from surgeguard_ai.contracts import SourceMode
from surgeguard_ai.errors import SourceEnded, SourceUnavailableError
from surgeguard_ai.perception import VideoFileSource

from .conftest import VIDEO_FPS, VIDEO_FRAMES, VIDEO_SIZE


def read_all(source: VideoFileSource, limit: int = 500) -> list:
    """Drain a source to its end, skipping recoverable gaps."""
    frames = []
    for _ in range(limit):
        try:
            frame = source.read()
        except SourceEnded:
            return frames
        if frame is not None:
            frames.append(frame)
    raise AssertionError("source did not end within the frame limit")


class TestReading:
    def test_reads_every_frame_in_order(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        with source:
            frames = read_all(source)

        assert len(frames) == VIDEO_FRAMES
        assert [frame.seq for frame in frames] == list(range(VIDEO_FRAMES))

    def test_end_of_clip_raises_source_ended(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        with source:
            for _ in range(VIDEO_FRAMES):
                source.read()
            with pytest.raises(SourceEnded):
                source.read()

    def test_reports_demonstration_provenance(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        assert source.source_mode is SourceMode.DEMO

    def test_missing_file_is_reported_before_opening(self, tmp_path: Path) -> None:
        source = VideoFileSource("clip", tmp_path / "absent.mp4")
        with pytest.raises(SourceUnavailableError, match="not found"):
            source.open()

    def test_directory_is_rejected(self, tmp_path: Path) -> None:
        source = VideoFileSource("clip", tmp_path)
        with pytest.raises(SourceUnavailableError, match="not a file"):
            source.open()

    def test_reading_before_opening_is_reported(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video)
        with pytest.raises(SourceUnavailableError, match="before being opened"):
            source.read()

    def test_close_is_idempotent(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        source.open()
        source.close()
        source.close()
        assert not source.is_open


class TestTimestamps:
    def test_timestamps_are_paced_to_the_source_frame_rate(self, sample_video: Path) -> None:
        """Frame N is stamped N/fps after the session start.

        This is what keeps every temporal measurement downstream - walking speed,
        rate of change, smoothing windows - identical between a recording and a
        live camera.
        """
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        with source:
            first = source.read()
            for _ in range(9):
                last = source.read()

        assert first is not None and last is not None
        elapsed = (last.ts - first.ts).total_seconds()
        assert elapsed == pytest.approx(9 / VIDEO_FPS, abs=1e-6)

    def test_timestamps_do_not_depend_on_delivery_speed(self, sample_video: Path) -> None:
        """Disabling pacing changes the delivery rate, not the results.

        This is the property that makes an offline golden-clip regression run
        produce the same curve as the live demonstration.
        """
        paced = VideoFileSource("clip", sample_video, realtime_pacing=True)
        unpaced = VideoFileSource("clip", sample_video, realtime_pacing=False)

        with paced, unpaced:
            paced_frames = [paced.read() for _ in range(5)]
            unpaced_frames = [unpaced.read() for _ in range(5)]

        paced_offsets = [(f.ts - paced_frames[0].ts).total_seconds() for f in paced_frames]
        unpaced_offsets = [(f.ts - unpaced_frames[0].ts).total_seconds() for f in unpaced_frames]
        assert paced_offsets == pytest.approx(unpaced_offsets)


class TestPacing:
    def test_pacing_delivers_at_roughly_real_time(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=True)
        with source:
            started = time.monotonic()
            for _ in range(10):
                source.read()
            elapsed = time.monotonic() - started

        # Ten frames at 20 fps is half a second. A generous lower bound is enough
        # to prove pacing happens at all; timing on a loaded CI machine is not
        # worth asserting tightly.
        assert elapsed >= 0.30

    def test_disabling_pacing_reads_at_full_speed(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        with source:
            started = time.monotonic()
            read_all(source)
            elapsed = time.monotonic() - started

        assert elapsed < VIDEO_FRAMES / VIDEO_FPS


class TestConfiguration:
    def test_frame_rate_override_replaces_the_declared_rate(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, fps_override=10.0, realtime_pacing=False)
        with source:
            first = source.read()
            second = source.read()

        assert source.fps == 10.0
        assert (second.ts - first.ts).total_seconds() == pytest.approx(0.1)

    def test_frame_rate_override_must_be_positive(self, sample_video: Path) -> None:
        with pytest.raises(ValueError, match="fps_override"):
            VideoFileSource("clip", sample_video, fps_override=0)

    def test_resize_changes_the_delivered_frame_size(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False, resize=(160, 120))
        with source:
            frame = source.read()

        assert (frame.width, frame.height) == (160, 120)
        assert source.resize == (160, 120)

    def test_without_resize_frames_arrive_at_source_size(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        with source:
            frame = source.read()

        assert (frame.width, frame.height) == VIDEO_SIZE

    def test_resize_must_be_positive(self, sample_video: Path) -> None:
        with pytest.raises(ValueError, match="resize"):
            VideoFileSource("clip", sample_video, resize=(0, 100))

    def test_declared_duration_uses_the_effective_frame_rate(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        with source:
            assert source.total_frames == VIDEO_FRAMES
            assert source.duration_seconds == pytest.approx(VIDEO_FRAMES / VIDEO_FPS)


class TestLooping:
    def test_looping_restarts_the_frame_sequence(self, sample_video: Path) -> None:
        """A wrap restarts at 0 - the signal a consumer uses to reset its state."""
        source = VideoFileSource("clip", sample_video, realtime_pacing=False, loop=True)
        with source:
            for _ in range(VIDEO_FRAMES):
                source.read()
            wrapped = source.read()

        assert wrapped is not None
        assert wrapped.seq == 0

    def test_looping_never_ends(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False, loop=True)
        with source:
            for _ in range(VIDEO_FRAMES * 2 + 5):
                assert source.read() is not None


class FlakyCapture:
    """Wraps an open capture and fails a scripted number of reads.

    ``cv2.VideoCapture`` will not accept an attribute assignment, so the handle
    is wrapped rather than patched.
    """

    def __init__(self, capture, failures: int) -> None:
        self._capture = capture
        self._failures = failures

    def read(self):
        if self._failures:
            self._failures -= 1
            return False, None
        return self._capture.read()

    def __getattr__(self, name):
        return getattr(self._capture, name)


class TestDecodeFailureRecovery:
    def test_a_damaged_frame_is_skipped_rather_than_ending_the_clip(
        self,
        sample_video: Path,
    ) -> None:
        """One undecodable frame must cost that frame, not the rest of the clip."""
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        source.open()
        source._capture = FlakyCapture(source._capture, failures=1)

        try:
            first = source.read()
            assert first is None  # the damaged frame is reported as a gap
            recovered = source.read()
            assert recovered is not None
            assert recovered.seq == 1  # the sequence advanced over the lost frame

            # And the rest of the clip still plays out to its natural end.
            assert len(read_all(source)) == VIDEO_FRAMES - 1
        finally:
            source.close()

    def test_a_sustained_run_of_failures_ends_the_clip(self, sample_video: Path) -> None:
        source = VideoFileSource("clip", sample_video, realtime_pacing=False)
        source.open()
        source._capture = FlakyCapture(source._capture, failures=10_000)

        try:
            with pytest.raises(SourceEnded):
                for _ in range(50):
                    source.read()
        finally:
            source.close()
