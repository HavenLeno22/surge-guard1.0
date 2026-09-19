"""Person detection with Ultralytics YOLO - Stage 2 of the AI Pipeline.

Implements :class:`~surgeguard_ai.perception.detector.Detector` (``05:315-347``).

The detector answers exactly one question - *where are the people in this
frame?* - and answers it with a confidence per detection, so that Decision
Confidence can later reflect detection quality rather than assert a number.

**Person class only.** Filtering happens inside inference rather than after it,
so non-human objects never reach post-processing at all (``05:335``).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ..contracts.geometry import BoundingBox
from ..contracts.perception import Detection, DetectionResult
from ..errors import DetectionError
from ._device import DeviceInfo, resolve_device
from .detector import Detector
from .frame_source import Frame

__all__ = ["DetectorStats", "YoloDetector"]

logger = logging.getLogger(__name__)

#: COCO class name for people. Resolved to an index from the loaded model rather
#: than hard-coded, so a model with a different class order cannot silently
#: detect the wrong thing.
_PERSON_CLASS_NAME = "person"

#: Fallback index when a model publishes no class names. 0 is `person` in COCO,
#: which every stock YOLO checkpoint uses.
_PERSON_CLASS_FALLBACK = 0

#: Default checkpoint. The `s` variant is chosen over `n` because detection
#: stability matters more here than headroom above the 10 Hz analysis budget
#: (``02_Hackathon_Execution_Plan.md`` section 4): missed people at the back of a
#: crowd corrupt the count and every density figure derived from it.
_DEFAULT_MODEL = "yolo11s.pt"

#: Inference resolution. Matches the 960x540 analysis input in the performance
#: budget; YOLO letterboxes the 16:9 frame to 960x544.
_DEFAULT_IMAGE_SIZE = 960

#: Frames of timing history kept for the rolling throughput figure.
_STATS_WINDOW = 100

#: Inferences run before timing begins. The first inference on a cold GPU costs
#: seconds - CUDA context creation, kernel loading, memory pool setup - against
#: tens of milliseconds in steady state. Measuring the performance budget against
#: it would be meaningless.
_DEFAULT_WARMUP_ITERATIONS = 10


@dataclass(frozen=True, slots=True)
class DetectorStats:
    """Rolling detector performance, for the health panel and the budget check."""

    frames: int
    last_inference_ms: float | None
    mean_inference_ms: float | None
    inference_fps: float | None

    @property
    def is_empty(self) -> bool:
        return self.frames == 0


class YoloDetector(Detector):
    """Detects people using an Ultralytics YOLO checkpoint.

    **Device selection is automatic and reported.** CUDA is used when present,
    with half precision on hardware that benefits from it; otherwise inference
    falls back to CPU and :attr:`device_info` records why. A silent CPU fallback
    would look identical to a working GPU until the frame rate missed the budget
    at the worst possible moment.

    Not thread-safe: one detector serves one pipeline thread, which is what the
    :class:`~surgeguard_ai.perception.detector.Detector` contract requires.
    """

    def __init__(
        self,
        *,
        model: str | Path = _DEFAULT_MODEL,
        weights_dir: str | Path | None = None,
        device: str = "auto",
        confidence: float = 0.3,
        iou: float = 0.5,
        image_size: int = _DEFAULT_IMAGE_SIZE,
        half: bool | None = None,
        max_detections: int = 1000,
        cudnn_benchmark: bool = False,
        warmup_shape: tuple[int, int] | None = None,
        warmup_iterations: int = _DEFAULT_WARMUP_ITERATIONS,
        log_every: int = 100,
    ) -> None:
        """
        Args:
            model: Checkpoint name (downloaded on first use) or a path to one.
            weights_dir: Directory a bare checkpoint name resolves into. Keeps
                downloaded weights out of the working directory.
            device: ``"auto"``, ``"cpu"``, ``"cuda"`` or ``"cuda:N"``.
            confidence: Minimum detection confidence. Lower values recover
                distant people at the cost of false positives; both distort the
                count, so this is a calibration decision, not a preference.
            iou: Non-maximum-suppression IoU threshold. Crowds overlap heavily,
                so suppressing too aggressively deletes real people.
            image_size: Inference resolution, in pixels. Must be a multiple of 32.
            half: Force half precision on or off. ``None`` enables it whenever
                the resolved device supports it.
            max_detections: Cap on detections per frame. Reached, it silently
                truncates the crowd count, so it is set well above any plausible
                single-frame population.
            cudnn_benchmark: Let cuDNN autotune convolution algorithms for the
                input shape. Off by default on measurement: on the RTX 4060
                Laptop target it bought 41.6 ms against 44.0 ms sustained - about
                5% - and cost **61 seconds** of autotuning at startup, against 10
                seconds without. Autotuning also re-runs on every new input
                shape. Worth enabling only where the tuning cost amortises over a
                long unattended run, never before a demonstration.
            warmup_shape: ``(height, width)`` of the frames this detector will
                see. When given, warm-up happens at load. When omitted it happens
                on the first frame instead, which is slower to first result but
                guarantees warm-up matches the real input shape.
            warmup_iterations: Inferences run before timing begins.
            log_every: Frames between throughput log lines. Zero disables them.
        """
        if image_size % 32 != 0:
            raise ValueError(f"image_size must be a multiple of 32, got {image_size}")
        if not 0.0 < confidence < 1.0:
            raise ValueError(f"confidence must be in (0, 1), got {confidence}")

        self._model_ref = self._resolve_model_path(model, weights_dir)
        self._requested_device = device
        self._confidence = confidence
        self._iou = iou
        self._image_size = image_size
        self._requested_half = half
        self._max_detections = max_detections
        self._cudnn_benchmark = cudnn_benchmark
        self._warmup_shape = warmup_shape
        self._warmup_iterations = max(warmup_iterations, 0)
        self._log_every = max(log_every, 0)
        self._warmed_shape: tuple[int, int] | None = None

        self._model: Any | None = None
        self._device_info: DeviceInfo | None = None
        self._half = False
        self._precision_kwargs: dict[str, Any] = {}
        self._person_class = _PERSON_CLASS_FALLBACK

        self._frames = 0
        self._last_inference_ms: float | None = None
        self._recent_ms: deque[float] = deque(maxlen=_STATS_WINDOW)

    @staticmethod
    def _resolve_model_path(model: str | Path, weights_dir: str | Path | None) -> str:
        """Place a bare checkpoint name inside ``weights_dir`` when one is given."""
        reference = Path(model)
        if weights_dir is None or reference.parent != Path("."):
            return str(model)
        directory = Path(weights_dir)
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory / reference.name)

    # -- Identity -----------------------------------------------------------

    @property
    def name(self) -> str:
        return Path(self._model_ref).name

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        """The resolved compute device. ``None`` until :meth:`load` has run."""
        return self._device_info

    @property
    def uses_half_precision(self) -> bool:
        """Whether inference runs in FP16."""
        return self._half

    @property
    def stats(self) -> DetectorStats:
        """Rolling inference timing over the most recent frames."""
        mean = float(np.mean(self._recent_ms)) if self._recent_ms else None
        return DetectorStats(
            frames=self._frames,
            last_inference_ms=self._last_inference_ms,
            mean_inference_ms=mean,
            inference_fps=(1000.0 / mean) if mean else None,
        )

    # -- Lifecycle ----------------------------------------------------------

    def load(self) -> None:
        """Load weights, select a device, and warm up.

        A CUDA failure at this point is not fatal: the detector retries on CPU
        and records the fallback, because degrading to a slower device is
        preferable to refusing to monitor (``05:889-897``).
        """
        if self.is_ready:
            return

        yolo = self._import_yolo()
        device_info = resolve_device(self._requested_device)

        try:
            self._activate(yolo, device_info)
        except Exception as exc:  # noqa: BLE001 - any CUDA failure must degrade, not crash
            if not device_info.is_cuda:
                raise DetectionError(
                    f"Could not load detection model {self._model_ref!r}: {exc}"
                ) from exc

            logger.warning(
                "Detection model failed to initialise on %s (%s); retrying on CPU",
                device_info.device,
                exc,
            )
            cpu_info = resolve_device("cpu")
            fallback_info = DeviceInfo(
                device=cpu_info.device,
                is_cuda=False,
                name=cpu_info.name,
                total_memory_mb=None,
                supports_fp16=False,
                torch_version=cpu_info.torch_version,
                cuda_version=device_info.cuda_version,
                requested=device_info.requested,
                fallback_reason=f"GPU initialisation failed: {exc}",
            )
            try:
                self._activate(yolo, fallback_info)
            except Exception as cpu_exc:  # noqa: BLE001 - report both failures
                raise DetectionError(
                    f"Could not load detection model {self._model_ref!r} on GPU "
                    f"({exc}) or CPU ({cpu_exc})"
                ) from cpu_exc

    def _activate(self, yolo: Any, device_info: DeviceInfo) -> None:
        """Instantiate the model on a device and bring it to steady state."""
        model = yolo(self._model_ref)
        model.to(device_info.device)

        self._model = model
        self._device_info = device_info
        self._half = (
            device_info.supports_fp16 if self._requested_half is None else self._requested_half
        ) and device_info.is_cuda
        self._precision_kwargs = self._build_precision_kwargs(self._half)
        self._person_class = self._resolve_person_class(model)

        if device_info.is_cuda:
            self._enable_cudnn_autotuning()

        self._log_activation(device_info)
        if self._warmup_shape is not None:
            self._warm_up(self._warmup_shape)

    @staticmethod
    def _build_precision_kwargs(half: bool) -> dict[str, Any]:
        """Express the requested precision in the vocabulary this Ultralytics uses.

        Recent versions replaced the boolean ``half`` flag with a ``quantize``
        scheme and warn on every call that still uses the old name. Resolving it
        once at load keeps a deprecation notice out of the per-frame path without
        dropping support for the older flag.
        """
        try:
            from ultralytics.cfg import DEFAULT_CFG_DICT
        except ImportError:  # pragma: no cover - very old Ultralytics
            return {"half": half}

        if "quantize" in DEFAULT_CFG_DICT:
            return {"quantize": 16} if half else {}
        return {"half": half}

    def _enable_cudnn_autotuning(self) -> None:
        """Let cuDNN pick the fastest convolution algorithms for our fixed shape."""
        if not self._cudnn_benchmark:
            return
        try:
            import torch

            torch.backends.cudnn.benchmark = True
        except Exception:  # noqa: BLE001 - an optimisation must never block startup
            logger.debug("Could not enable cuDNN autotuning", exc_info=True)

    @staticmethod
    def _import_yolo() -> Any:
        """Import Ultralytics lazily.

        Kept out of module scope so that importing ``surgeguard_ai.perception``
        does not pull in a model runtime - the contracts and the frame sources
        are useful without one.
        """
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise DetectionError(
                "Ultralytics is not installed; person detection is unavailable. "
                "Install the AI package with its detection dependencies."
            ) from exc
        return YOLO

    @staticmethod
    def _resolve_person_class(model: Any) -> int:
        """Find the model's index for people, rather than assuming COCO ordering."""
        names = getattr(model, "names", None) or {}
        for index, label in dict(names).items():
            if str(label).strip().lower() == _PERSON_CLASS_NAME:
                return int(index)

        logger.warning(
            "Detection model publishes no %r class; assuming index %d",
            _PERSON_CLASS_NAME,
            _PERSON_CLASS_FALLBACK,
        )
        return _PERSON_CLASS_FALLBACK

    def _warm_up(self, shape: tuple[int, int]) -> None:
        """Run throwaway inferences at ``shape`` so timed frames are representative.

        **The shape matters.** CUDA initialisation, kernel loading and any cuDNN
        autotuning are all per input shape. Warming up at one resolution and then
        running at another pays that cost twice - the second time on a real
        frame, in the middle of monitoring. Warming at the shape the pipeline
        actually delivers is what makes the first measured frame meaningful.

        Args:
            shape: ``(height, width)`` of the frames to warm up on.
        """
        self._warmed_shape = shape

        if self._warmup_iterations == 0:
            return

        height, width = shape
        blank = np.zeros((height, width, 3), dtype=np.uint8)

        timings: list[float] = []
        for _ in range(self._warmup_iterations):
            started = time.perf_counter()
            self._infer(blank)
            timings.append((time.perf_counter() - started) * 1000.0)

        # The early iterations carry one-time initialisation and are several
        # orders slower; the median of the later half is the settled figure.
        settled = float(np.median(timings[len(timings) // 2 :]))
        logger.info(
            "Detector warmed up at %dx%d: %d iteration(s) in %.1fs, settled at "
            "%.1f ms/frame (~%.1f fps)",
            width,
            height,
            self._warmup_iterations,
            sum(timings) / 1000.0,
            settled,
            1000.0 / settled if settled > 0 else 0.0,
        )

    def _log_activation(self, device_info: DeviceInfo) -> None:
        logger.info(
            "Detector ready: model=%s device=%s gpu=%s precision=%s imgsz=%d conf=%.2f "
            "cudnn_autotune=%s",
            self.name,
            device_info.device,
            device_info.name,
            "FP16" if self._half else "FP32",
            self._image_size,
            self._confidence,
            self._cudnn_benchmark and device_info.is_cuda,
        )
        if device_info.is_fallback:
            logger.warning(
                "Detector is not running on the requested device (%s): %s",
                device_info.requested,
                device_info.fallback_reason,
            )

    def unload(self) -> None:
        """Release the model and any GPU memory it holds. Idempotent."""
        if self._model is None:
            return

        self._model = None
        self._warmed_shape = None
        if self._device_info is not None and self._device_info.is_cuda:
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - releasing memory must never fail a shutdown
                logger.debug("Could not empty the CUDA cache during unload", exc_info=True)
        logger.info("Detector unloaded: %s", self.name)

    # -- Detection ----------------------------------------------------------

    def detect(self, frame: Frame) -> DetectionResult:
        """Detect every visible person in one frame."""
        if self._model is None:
            raise DetectionError("Detector was used before load() was called")

        self._require_usable_image(frame)

        # Warm up on the first frame of a given shape rather than at load, so
        # one-time initialisation is never charged to a frame that gets timed and
        # reported. A shape change - a source swap to a differently-sized clip -
        # re-warms for the same reason.
        shape = (frame.height, frame.width)
        if shape != self._warmed_shape:
            self._warm_up(shape)

        started = time.perf_counter()
        try:
            result = self._infer(frame.image)
        except Exception as exc:  # noqa: BLE001 - one bad frame must not stop monitoring
            raise DetectionError(
                f"Inference failed for frame {frame.seq} of {frame.source_id!r}: {exc}"
            ) from exc
        inference_ms = (time.perf_counter() - started) * 1000.0

        detections = self._to_detections(result, width=frame.width, height=frame.height)
        self._record(inference_ms)

        return DetectionResult(
            frame_seq=frame.seq,
            frame_ts=frame.ts,
            detections=detections,
            inference_ms=inference_ms,
        )

    @staticmethod
    def _require_usable_image(frame: Frame) -> None:
        """Reject a frame that cannot be inferred on.

        An empty or malformed buffer is a source fault, not a frame with nobody
        in it, and the two must not produce the same answer: reporting "zero
        people" for an unreadable frame would be a fabricated observation.
        """
        image = frame.image
        if image is None or getattr(image, "size", 0) == 0:
            raise DetectionError(
                f"Frame {frame.seq} of {frame.source_id!r} carries no image data"
            )
        if image.ndim != 3 or image.shape[2] != 3:
            raise DetectionError(
                f"Frame {frame.seq} of {frame.source_id!r} is not a 3-channel image "
                f"(shape={image.shape})"
            )
        if image.dtype != np.uint8:
            # A float buffer reaches the model without complaint and produces
            # detections from whatever the values happen to be - including from
            # NaN. Refusing it is the difference between a reported fault and a
            # confident count with nothing behind it.
            raise DetectionError(
                f"Frame {frame.seq} of {frame.source_id!r} is not an 8-bit image "
                f"(dtype={image.dtype})"
            )

    def _infer(self, image: NDArray[np.uint8]) -> Any:
        """Run one inference, filtering to people inside the model call."""
        assert self._model is not None  # noqa: S101 - guarded by callers
        device = self._device_info.device if self._device_info else "cpu"
        results = self._model.predict(
            source=image,
            classes=[self._person_class],
            conf=self._confidence,
            iou=self._iou,
            imgsz=self._image_size,
            device=device,
            max_det=self._max_detections,
            verbose=False,
            **self._precision_kwargs,
        )
        return results[0]

    def _to_detections(self, result: Any, *, width: int, height: int) -> tuple[Detection, ...]:
        """Convert one Ultralytics result into contract detections."""
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return ()

        xyxy = boxes.xyxy.detach().cpu().numpy()
        confidences = boxes.conf.detach().cpu().numpy()

        # Boxes may extend a little past the frame for a partially visible
        # person. Clamping keeps foot points inside the image, which is what
        # ground-plane projection assumes.
        xyxy[:, 0::2] = np.clip(xyxy[:, 0::2], 0.0, float(width))
        xyxy[:, 1::2] = np.clip(xyxy[:, 1::2], 0.0, float(height))

        return tuple(
            Detection(
                bbox=BoundingBox(x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2)),
                confidence=float(min(max(confidence, 0.0), 1.0)),
            )
            for (x1, y1, x2, y2), confidence in zip(xyxy, confidences, strict=True)
        )

    def _record(self, inference_ms: float) -> None:
        """Update rolling timing and emit the periodic throughput line."""
        self._frames += 1
        self._last_inference_ms = inference_ms
        self._recent_ms.append(inference_ms)

        if self._log_every and self._frames % self._log_every == 0:
            stats = self.stats
            device = self._device_info
            logger.info(
                "Detector throughput: device=%s gpu=%s frames=%d inference=%.1f ms "
                "(mean %.1f ms, %.1f fps)",
                device.device if device else "unknown",
                device.name if device else "unknown",
                stats.frames,
                inference_ms,
                stats.mean_inference_ms or 0.0,
                stats.inference_fps or 0.0,
            )
