"""Person detection with YOLO - Stage 2.

Split in two. The first part tests what the detector decides - device, precision,
weight location, which frames it refuses - without loading a model, so it runs
anywhere in milliseconds. The second part is marked ``model`` and exercises real
inference; it is skipped where the weights are absent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from surgeguard_ai.errors import DetectionError
from surgeguard_ai.perception import YoloDetector, resolve_device

from .conftest import make_frame

WEIGHTS = Path("data/models/yolo11s.pt")

requires_model = pytest.mark.skipif(
    not (Path.cwd().parent / WEIGHTS).exists() and not WEIGHTS.exists(),
    reason=f"detection weights not present at {WEIGHTS}",
)


def weights_path() -> Path:
    """Locate the weights whether pytest runs from the repository root or ``ai/``."""
    for candidate in (WEIGHTS, Path.cwd().parent / WEIGHTS):
        if candidate.exists():
            return candidate
    raise AssertionError("weights should exist - the skip marker is misconfigured")


class TestDeviceResolution:
    def test_cpu_can_be_requested_explicitly(self) -> None:
        info = resolve_device("cpu")

        assert info.device == "cpu"
        assert not info.is_cuda
        assert not info.supports_fp16
        assert not info.is_fallback  # CPU was asked for, so CPU is not a fallback

    def test_auto_never_raises(self) -> None:
        """Device selection must always yield something runnable.

        Refusing to start because a GPU is missing would be worse than running
        slowly - the documented behaviour is to degrade, not to stop.
        """
        info = resolve_device("auto")

        assert info.device in {"cpu"} or info.device.startswith("cuda:")
        assert info.name

    def test_an_impossible_gpu_index_falls_back_rather_than_failing(self) -> None:
        info = resolve_device("cuda:99")

        assert info.device in {"cpu", "cuda:0"}
        if info.device == "cpu":
            assert info.fallback_reason

    def test_a_fallback_always_states_its_reason(self) -> None:
        """A silent CPU fallback looks exactly like a working GPU until it matters."""
        info = resolve_device("cuda")

        if not info.is_cuda:
            assert info.fallback_reason
            assert info.is_fallback

    def test_the_description_names_the_device(self) -> None:
        assert resolve_device("cpu").describe().startswith("cpu")


class TestConfiguration:
    def test_the_image_size_must_suit_the_model_stride(self) -> None:
        with pytest.raises(ValueError, match="multiple of 32"):
            YoloDetector(image_size=1000)

    @pytest.mark.parametrize("confidence", [0.0, 1.0, -0.1, 1.5])
    def test_the_confidence_threshold_must_be_a_probability(
        self,
        confidence: float,
    ) -> None:
        with pytest.raises(ValueError, match="confidence"):
            YoloDetector(confidence=confidence)

    def test_a_bare_checkpoint_name_lands_in_the_weights_directory(
        self,
        tmp_path: Path,
    ) -> None:
        """Downloaded weights should not scatter into the working directory."""
        detector = YoloDetector(model="yolo11s.pt", weights_dir=tmp_path)

        assert detector._model_ref == str(tmp_path / "yolo11s.pt")
        assert tmp_path.exists()

    def test_an_explicit_path_is_left_alone(self, tmp_path: Path) -> None:
        explicit = tmp_path / "elsewhere" / "custom.pt"
        detector = YoloDetector(model=explicit, weights_dir=tmp_path)

        assert detector._model_ref == str(explicit)

    def test_the_name_is_the_checkpoint(self, tmp_path: Path) -> None:
        assert YoloDetector(model="yolo11s.pt", weights_dir=tmp_path).name == "yolo11s.pt"

    def test_a_detector_starts_unloaded(self) -> None:
        detector = YoloDetector()

        assert not detector.is_ready
        assert detector.device_info is None
        assert detector.stats.is_empty

    def test_unloading_an_unloaded_detector_is_harmless(self) -> None:
        YoloDetector().unload()


class TestUsageErrors:
    def test_detecting_before_loading_is_reported(self) -> None:
        with pytest.raises(DetectionError, match="before load"):
            YoloDetector().detect(make_frame(0))


@pytest.fixture(scope="module")
def sample_photo():
    """A real photograph containing several people, shipped with Ultralytics."""
    import cv2
    from ultralytics.utils import ASSETS

    image = cv2.imread(str(Path(ASSETS) / "bus.jpg"))
    assert image is not None, "the Ultralytics sample photograph is missing"
    return image


@pytest.fixture(scope="module")
def detector() -> YoloDetector:
    """One loaded detector for the whole module - loading costs seconds."""
    instance = YoloDetector(
        model=weights_path(),
        image_size=640,
        warmup_iterations=1,
        log_every=0,
    )
    instance.load()
    yield instance
    instance.unload()


@requires_model
@pytest.mark.model
class TestRealInference:
    def test_loading_selects_and_reports_a_device(self, detector: YoloDetector) -> None:
        assert detector.is_ready
        assert detector.device_info is not None
        assert detector.device_info.name

    def test_half_precision_follows_the_device(self, detector: YoloDetector) -> None:
        info = detector.device_info
        assert info is not None
        assert detector.uses_half_precision == (info.is_cuda and info.supports_fp16)

    def test_people_are_detected_in_a_photograph(
        self,
        detector: YoloDetector,
        sample_photo,
    ) -> None:
        frame = make_frame(0)
        result = detector.detect(
            type(frame)(seq=0, ts=frame.ts, image=sample_photo, source_id="photo")
        )

        assert result.count >= 3  # the sample photograph shows four people
        assert all(0.0 <= d.confidence <= 1.0 for d in result.detections)
        assert result.inference_ms is not None and result.inference_ms > 0

    def test_detections_stay_inside_the_frame(
        self,
        detector: YoloDetector,
        sample_photo,
    ) -> None:
        """Foot points are projected to the ground; they must be in the image."""
        frame = make_frame(0)
        result = detector.detect(
            type(frame)(seq=0, ts=frame.ts, image=sample_photo, source_id="photo")
        )

        height, width = sample_photo.shape[:2]
        for detection in result.detections:
            box = detection.bbox
            assert 0 <= box.x1 <= box.x2 <= width
            assert 0 <= box.y1 <= box.y2 <= height

    def test_a_blank_frame_yields_no_people(self, detector: YoloDetector) -> None:
        """Nothing there is a valid observation, and must not be an error."""
        result = detector.detect(make_frame(0, size=(640, 480)))

        assert result.count == 0
        assert result.frame_seq == 0

    def test_the_result_carries_the_frame_it_came_from(
        self,
        detector: YoloDetector,
    ) -> None:
        """Overlays are aligned by sequence; a mismatched result draws on the wrong frame."""
        frame = make_frame(17, size=(640, 480))
        result = detector.detect(frame)

        assert result.frame_seq == 17
        assert result.frame_ts == frame.ts

    def test_an_empty_buffer_is_refused_rather_than_counted_as_zero(
        self,
        detector: YoloDetector,
    ) -> None:
        """An unreadable frame is a fault, not a frame with nobody in it."""
        frame = make_frame(0)
        empty = type(frame)(
            seq=0,
            ts=frame.ts,
            image=np.zeros((0, 0, 3), dtype=np.uint8),
            source_id="broken",
        )

        with pytest.raises(DetectionError, match="no image data"):
            detector.detect(empty)

    def test_a_malformed_buffer_is_refused(self, detector: YoloDetector) -> None:
        frame = make_frame(0)
        greyscale = type(frame)(
            seq=0,
            ts=frame.ts,
            image=np.zeros((64, 64), dtype=np.uint8),
            source_id="broken",
        )

        with pytest.raises(DetectionError, match="3-channel"):
            detector.detect(greyscale)

    def test_a_float_buffer_is_refused(self, detector: YoloDetector) -> None:
        """A float buffer infers without complaint and counts people from noise.

        NaN included. Refusing it is the difference between a reported fault and
        a confident number with nothing behind it.
        """
        frame = make_frame(0)
        floating = type(frame)(
            seq=0,
            ts=frame.ts,
            image=np.full((64, 64, 3), np.nan, dtype=np.float32),
            source_id="broken",
        )

        with pytest.raises(DetectionError, match="8-bit"):
            detector.detect(floating)

    def test_timing_statistics_accumulate(self, detector: YoloDetector) -> None:
        for seq in range(3):
            detector.detect(make_frame(seq, size=(640, 480)))

        stats = detector.stats
        assert stats.frames >= 3
        assert stats.mean_inference_ms is not None and stats.mean_inference_ms > 0
        assert stats.inference_fps is not None and stats.inference_fps > 0
