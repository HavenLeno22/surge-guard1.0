"""Fixtures and doubles for the perception unit tests.

The stage doubles here are deliberately trivial. They exist so that pipeline
behaviour - continuity breaks, degraded frames, shutdown - can be tested without
a model, in milliseconds, and deterministically. Tests that need the real
detector are marked ``model`` and skipped when the weights are absent.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from surgeguard_ai.contracts import (
    BoundingBox,
    CameraCalibration,
    CameraConfig,
    CameraZone,
    Detection,
    DetectionResult,
    ImagePoint,
    ImagePolygon,
    PerceptionResult,
    SourceMode,
    Track,
    TrackingResult,
    Vector2D,
    ZoneType,
)
from surgeguard_ai.errors import DetectionError, TrackingError
from surgeguard_ai.perception import Detector, Frame, Tracker

VIDEO_FPS = 20.0
VIDEO_FRAMES = 40
VIDEO_SIZE = (320, 240)

#: The frame size the crowd analyser's default grid is laid over, matching the
#: detector input size the backend configures.
ANALYSIS_SIZE = (960, 540)
SCENARIO_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _painted_frame(index: int, size: tuple[int, int]) -> NDArray[np.uint8]:
    """A frame whose content changes with the index, so frames are distinguishable."""
    width, height = size
    image = np.zeros((height, width, 3), dtype=np.uint8)
    x = (index * 5) % max(width - 40, 1)
    image[40:120, x : x + 40] = (0, 200, 255)
    return image


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A short real video file, written once for the whole session."""
    path = tmp_path_factory.mktemp("clips") / "sample.mp4"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        VIDEO_FPS,
        VIDEO_SIZE,
    )
    assert writer.isOpened(), "OpenCV could not open a video writer for the test clip"
    try:
        for index in range(VIDEO_FRAMES):
            writer.write(_painted_frame(index, VIDEO_SIZE))
    finally:
        writer.release()
    return path


@pytest.fixture
def camera() -> CameraConfig:
    """An uncalibrated camera - the prototype's current state."""
    return CameraConfig(camera_id="cam-01", name="Camera 01", location="Platform 3")


@pytest.fixture
def calibrated_camera() -> CameraConfig:
    """A camera with a ground-plane homography and a measured EXIT zone.

    The homography is a plain scale: one pixel is 0.02 m, so the 960x540 view
    covers 19.2 m by 10.8 m. Chosen because the resulting cell areas are
    checkable by hand, which is the whole point of testing a density figure.
    """
    return CameraConfig(
        camera_id="cam-01",
        name="Camera 01",
        location="Platform 3",
        calibration=CameraCalibration(
            homography=((0.02, 0.0, 0.0), (0.0, 0.02, 0.0), (0.0, 0.0, 1.0)),
            ground_area_m2=19.2 * 10.8,
        ),
        zones=(
            CameraZone(
                zone_id="exit-b",
                name="Exit Gate B",
                zone_type=ZoneType.EXIT,
                polygon=ImagePolygon(
                    points=(
                        ImagePoint(x=0.0, y=400.0),
                        ImagePoint(x=240.0, y=400.0),
                        ImagePoint(x=240.0, y=540.0),
                        ImagePoint(x=0.0, y=540.0),
                    )
                ),
                width_m=2.0,
            ),
        ),
    )


def make_tracks(
    *,
    count: int,
    speed: float,
    spread_px: float = 700.0,
    origin_x: float = 120.0,
    y: float = 400.0,
    age_frames: int = 40,
    opposing: int = 0,
) -> tuple[Track, ...]:
    """Tracks laid out across the view, all moving at one speed.

    ``spread_px`` controls how far apart people stand, which is what decides
    peak density: the same headcount packed into one grid cell and spread over
    eight are very different crowds, and only the first is congested.
    ``opposing`` sends that many of them the other way, for flow conflict.
    """
    if count == 0:
        return ()

    step = spread_px / count
    return tuple(
        Track(
            track_id=index + 1,
            bbox=BoundingBox(
                x1=origin_x + index * step,
                y1=y - 200.0,
                x2=origin_x + index * step + 30.0,
                y2=y,
            ),
            confidence=0.9,
            age_frames=age_frames,
            foot_point=ImagePoint(x=origin_x + index * step + 15.0, y=y),
            velocity_image=Vector2D(dx=-speed if index < opposing else speed, dy=0.0),
        )
        for index in range(count)
    )


def make_perception(
    *,
    seq: int,
    tracks: tuple[Track, ...],
    seconds: float,
    detection_confidence: float = 0.9,
    id_switches: int = 0,
    degraded: bool = False,
    detections: tuple[Track, ...] | None = None,
) -> PerceptionResult:
    """A perception result carrying the given tracks at a given moment.

    ``detections`` defaults to mirroring ``tracks``. Passing a different set is
    how a *false detection* scenario is expressed: boxes the detector reported
    that tracking never confirmed into an identity.
    """
    timestamp = SCENARIO_START + timedelta(seconds=seconds)
    boxes = detections if detections is not None else tracks

    return PerceptionResult(
        camera_id="cam-01",
        source_mode=SourceMode.DEMO,
        frame_seq=seq,
        frame_ts=timestamp,
        produced_at=timestamp,
        person_count=len(tracks),
        detections=DetectionResult(
            frame_seq=seq,
            frame_ts=timestamp,
            detections=tuple(
                Detection(bbox=track.bbox, confidence=detection_confidence)
                for track in boxes
            ),
            inference_ms=12.0,
        ),
        tracking=TrackingResult(
            frame_seq=seq,
            frame_ts=timestamp,
            tracks=tracks,
            id_switches=id_switches,
        ),
        inference_ms=12.0,
        processing_ms=15.0,
        achieved_fps=10.0,
        degraded=degraded,
        degraded_reason="synthetic stage failure" if degraded else None,
    )


def make_frame(seq: int, *, size: tuple[int, int] = (64, 64), source_id: str = "test") -> Frame:
    """A frame with a paced timestamp, for deterministic velocity assertions."""
    width, height = size
    return Frame(
        seq=seq,
        ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seq / VIDEO_FPS),
        image=np.zeros((height, width, 3), dtype=np.uint8),
        source_id=source_id,
    )


def make_detections(
    frame: Frame,
    boxes: list[tuple[float, float, float, float]],
    confidence: float = 0.9,
) -> DetectionResult:
    """Detections for a frame, from plain corner tuples."""
    return DetectionResult(
        frame_seq=frame.seq,
        frame_ts=frame.ts,
        detections=tuple(
            Detection(
                bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                confidence=confidence,
            )
            for (x1, y1, x2, y2) in boxes
        ),
        inference_ms=1.0,
    )


class FakeDetector(Detector):
    """Returns a fixed number of detections, or fails on nominated frames."""

    def __init__(self, *, people: int = 2, fail_on: set[int] | None = None) -> None:
        self.people = people
        self.fail_on = fail_on or set()
        self.loaded = False
        self.unloaded = False
        self.seen: list[int] = []
        #: Names of the threads inference has run on. Inference is many times
        #: slower on a thread that has not run it before, so a pipeline that
        #: moves between threads stalls; this is what makes that visible.
        self.threads: set[str] = set()

    @property
    def name(self) -> str:
        return "fake-detector"

    @property
    def is_ready(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.unloaded = True

    def detect(self, frame: Frame) -> DetectionResult:
        self.seen.append(frame.seq)
        self.threads.add(threading.current_thread().name)
        if frame.seq in self.fail_on:
            raise DetectionError(f"synthetic detection failure on frame {frame.seq}")
        return make_detections(
            frame,
            [(index * 10.0, 0.0, index * 10.0 + 8.0, 20.0) for index in range(self.people)],
        )


class FakeTracker(Tracker):
    """Turns every detection into a track, and records every reset."""

    def __init__(self, *, fail_on: set[int] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.resets = 0
        self.updates = 0

    @property
    def is_reliable(self) -> bool:
        return True

    def update(
        self,
        frame: Frame,
        detections: DetectionResult,
        camera: CameraConfig,
    ) -> TrackingResult:
        self.updates += 1
        if frame.seq in self.fail_on:
            raise TrackingError(f"synthetic tracking failure on frame {frame.seq}")
        return TrackingResult(
            frame_seq=frame.seq,
            frame_ts=frame.ts,
            tracks=tuple(
                Track(
                    track_id=index + 1,
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                    age_frames=1,
                    foot_point=detection.bbox.foot_point,
                )
                for index, detection in enumerate(detections.detections)
            ),
        )

    def reset(self) -> None:
        self.resets += 1
