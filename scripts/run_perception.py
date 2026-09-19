"""Run the AI Pipeline's perception stages and print what they observe.

    FrameSource ──► YOLO detector ──► ByteTrack ──► structured output

No backend, no Command Center, no database. This exists to prove the perception
path works and to measure what it costs on the hardware it will run on.

    # Demonstration Mode - a recorded clip, paced exactly as a live camera
    python scripts/run_perception.py video data/scenarios/00_placeholder.mp4

    # Live Camera Mode - the same pipeline, a different frame source
    python scripts/run_perception.py camera --device 0

    # What cameras are attached?
    python scripts/run_perception.py devices

The pipeline is identical in both modes. Switching between them constructs a
different `FrameSource` and changes nothing else (Rule 7; `02` section 2).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
from pathlib import Path

# Allow running from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from surgeguard_ai.contracts import CameraConfig, PerceptionResult
from surgeguard_ai.perception import (
    ByteTrackTracker,
    FrameSource,
    LiveCameraSource,
    VideoFileSource,
    YoloDetector,
    resolve_device,
)
from surgeguard_ai.pipeline import PerceptionPipeline

DEFAULT_WEIGHTS_DIR = Path("data/models")
DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 540

logger = logging.getLogger("surgeguard.run_perception")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class ConsoleReporter:
    """Writes each perception result to the console.

    Presentation only. Nothing here computes anything - it prints what the
    pipeline measured, so that a number on screen can always be traced back to a
    measurement (`02` section 7).
    """

    def __init__(self, *, as_json: bool, every: int, max_ids: int = 12) -> None:
        self._as_json = as_json
        self._every = max(every, 1)
        self._max_ids = max_ids
        self._seen = 0

    async def __call__(self, result: PerceptionResult) -> None:
        self._seen += 1
        if self._seen % self._every:
            return
        print(self._render(result), flush=True)

    def _render(self, result: PerceptionResult) -> str:
        return self._render_json(result) if self._as_json else self._render_text(result)

    def _render_json(self, result: PerceptionResult) -> str:
        return json.dumps(
            {
                "camera_id": result.camera_id,
                "source_mode": result.source_mode.value,
                "frame_seq": result.frame_seq,
                "frame_ts": result.frame_ts.isoformat(),
                "person_count": result.person_count,
                "track_ids": list(result.track_ids),
                "detections": [
                    {
                        "bbox": [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2],
                        "confidence": round(d.confidence, 4),
                    }
                    for d in result.detections.detections
                ],
                "inference_ms": result.inference_ms,
                "processing_ms": result.processing_ms,
                "achieved_fps": result.achieved_fps,
                "degraded": result.degraded,
                "degraded_reason": result.degraded_reason,
            }
        )

    def _render_text(self, result: PerceptionResult) -> str:
        header = (
            f"[{result.source_mode.value:4s}] "
            f"frame {result.frame_seq:6d}  "
            f"{result.frame_ts.strftime('%H:%M:%S.%f')[:-3]}Z  "
            f"people {result.person_count:4d}  "
            f"inference {self._ms(result.inference_ms)}  "
            f"total {result.processing_ms:6.1f}ms  "
            f"{result.achieved_fps:5.1f} fps"
        )
        lines = [header + ("   DEGRADED" if result.degraded else "")]

        if result.degraded_reason:
            lines.append(f"           ! {result.degraded_reason}")

        for track in result.tracking.tracks[: self._max_ids]:
            box = track.bbox
            velocity = (
                "     -    "
                if track.velocity_image is None
                else f"{track.velocity_image.dx:6.1f},{track.velocity_image.dy:6.1f}"
            )
            lines.append(
                f"           id {track.track_id:4d}  conf {track.confidence:.2f}  "
                f"box ({box.x1:6.1f},{box.y1:6.1f})-({box.x2:6.1f},{box.y2:6.1f})  "
                f"px/s {velocity}  age {track.age_frames:4d}"
            )

        hidden = result.tracking.count - self._max_ids
        if hidden > 0:
            lines.append(f"           ... and {hidden} more track(s)")

        return "\n".join(lines)

    @staticmethod
    def _ms(value: float | None) -> str:
        return "    -   " if value is None else f"{value:6.1f}ms"


def print_summary(pipeline: PerceptionPipeline, detector: YoloDetector) -> None:
    """Print the run's totals and the measured performance."""
    status = pipeline.status
    stats = detector.stats
    device = detector.device_info

    print("\n--- Run summary " + "-" * 48)
    print(f"  source            : {status.source_id} ({status.source_mode})")
    print(f"  frames processed  : {status.frames_processed}")
    print(f"  frames dropped    : {status.frames_dropped}")
    print(f"  achieved fps      : {status.achieved_fps:.2f}")
    if device is not None:
        print(f"  device            : {device.describe()}")
        if device.is_fallback:
            print(f"  device fallback   : {device.fallback_reason}")
    print(f"  model             : {detector.name}")
    if stats.mean_inference_ms is not None:
        print(
            f"  inference         : {stats.mean_inference_ms:.1f} ms mean "
            f"({stats.inference_fps:.1f} fps) over the last {min(stats.frames, 100)} frame(s)"
        )
    if status.degraded:
        print(f"  degraded          : {status.degraded_reason}")
    print("-" * 64)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def build_source(args: argparse.Namespace) -> FrameSource:
    """Construct the frame source the requested mode calls for.

    This function is the *only* place the two modes differ. Everything after it
    is identical.
    """
    resize = None if args.no_resize else (args.width, args.height)

    if args.mode == "video":
        return VideoFileSource(
            source_id=Path(args.path).stem,
            path=args.path,
            fps_override=args.fps,
            realtime_pacing=not args.no_pacing,
            loop=args.loop,
            resize=resize,
        )

    return LiveCameraSource(
        source_id=f"camera-{args.device}",
        device=_as_device(args.device),
        resize=resize,
    )


def _as_device(value: str) -> int | str:
    """Interpret a device argument as an index where it is one, else a URL.

    OpenCV distinguishes the two by type, not by content: ``"0"`` is a filename
    and ``0`` is the first attached camera.
    """
    return int(value) if value.isdigit() else value


async def run(args: argparse.Namespace) -> int:
    source = build_source(args)

    detector = YoloDetector(
        model=args.model,
        weights_dir=args.weights_dir,
        device=args.device_preference,
        confidence=args.confidence,
        image_size=args.imgsz,
        half=args.half,
        cudnn_benchmark=args.cudnn_benchmark,
        # Warm up before the source starts, so the seconds of one-time GPU
        # initialisation are not spent while a paced clip is already running -
        # which would make the pipeline start several seconds behind the crowd.
        # Only possible when the frame shape is known in advance, which resizing
        # is what guarantees.
        warmup_shape=None if args.no_resize else (args.height, args.width),
    )
    tracker = ByteTrackTracker(
        frame_rate=source.fps,
        lost_track_timeout_s=args.lost_track_timeout,
    )
    camera = CameraConfig(
        camera_id=args.camera_id,
        name=args.camera_name,
        location=args.camera_location,
    )

    pipeline = PerceptionPipeline(
        camera,
        detector,
        tracker,
        on_result=ConsoleReporter(as_json=args.json, every=args.print_every),
    )

    stopping = asyncio.Event()
    _install_signal_handlers(stopping)

    try:
        await pipeline.start(source)
    except Exception as exc:  # noqa: BLE001 - report the reason, do not traceback at the user
        logger.error("Could not start the pipeline: %s", exc)
        return 1

    waiter = asyncio.create_task(pipeline.wait_closed())
    interrupt = asyncio.create_task(stopping.wait())
    limit = (
        asyncio.create_task(_frame_limit(pipeline, args.max_frames))
        if args.max_frames
        else None
    )

    pending = {task for task in (waiter, interrupt, limit) if task is not None}
    _, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    await pipeline.stop()
    print_summary(pipeline, detector)
    detector.unload()

    return 1 if pipeline.status.degraded else 0


async def _frame_limit(pipeline: PerceptionPipeline, limit: int) -> None:
    """Return once the pipeline has processed ``limit`` frames."""
    while pipeline.status.frames_processed < limit:
        await asyncio.sleep(0.05)


def _install_signal_handlers(stopping: asyncio.Event) -> None:
    """Make Ctrl-C a graceful shutdown rather than a traceback."""
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        received = getattr(signal, signal_name, None)
        if received is None:
            continue
        try:
            loop.add_signal_handler(received, stopping.set)
        except NotImplementedError:
            # Windows ProactorEventLoop does not support this; the default
            # KeyboardInterrupt path still stops the run cleanly.
            signal.signal(received, lambda *_: stopping.set())


def list_devices(max_index: int) -> int:
    """Report which camera indices deliver a frame."""
    print(f"Probing camera indices 0-{max_index}...")
    available = LiveCameraSource.list_available_devices(max_index)
    if not available:
        print("  no cameras available")
        return 1
    for index in available:
        print(f"  camera {index}: available")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    video = sub.add_parser("video", help="Demonstration Mode - process a recorded clip")
    video.add_argument("path", help="Path to the video file.")
    video.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Declare the clip's true frame rate, overriding the container.",
    )
    video.add_argument(
        "--no-pacing",
        action="store_true",
        help="Process as fast as the file decodes. For offline runs only - "
        "delivery rate changes, results do not.",
    )
    video.add_argument("--loop", action="store_true", help="Restart at the end of the clip.")

    camera = sub.add_parser("camera", help="Live Camera Mode - process a webcam or IP camera")
    camera.add_argument(
        "--device",
        default="0",
        help="Camera index or stream URL.",
    )

    devices = sub.add_parser("devices", help="List cameras that can currently be opened")
    devices.add_argument("--max-index", type=int, default=4)

    for shared in (video, camera):
        _add_shared_arguments(shared)

    return parser


def _add_shared_arguments(parser: argparse.ArgumentParser) -> None:
    frame = parser.add_argument_group("frame")
    frame.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    frame.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    frame.add_argument("--no-resize", action="store_true", help="Deliver frames at source size.")

    model = parser.add_argument_group("model")
    model.add_argument("--model", default="yolo11s.pt")
    model.add_argument("--weights-dir", type=Path, default=DEFAULT_WEIGHTS_DIR)
    model.add_argument(
        "--device-preference",
        default="auto",
        metavar="DEVICE",
        help="auto | cpu | cuda | cuda:N. Default auto.",
    )
    model.add_argument("--confidence", type=float, default=0.3)
    model.add_argument("--imgsz", type=int, default=960)
    model.add_argument(
        "--half",
        dest="half",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force FP16 on or off. Default follows the device.",
    )
    model.add_argument(
        "--cudnn-benchmark",
        action="store_true",
        help="Autotune convolutions. Costs about a minute at startup for a few "
        "percent; not worth it before a demonstration.",
    )

    tracking = parser.add_argument_group("tracking")
    tracking.add_argument("--lost-track-timeout", type=float, default=1.0, metavar="SECONDS")

    camera = parser.add_argument_group("camera identity")
    camera.add_argument("--camera-id", default="cam-01")
    camera.add_argument("--camera-name", default="Camera 01")
    camera.add_argument("--camera-location", default="Platform 3")

    output = parser.add_argument_group("output")
    output.add_argument("--json", action="store_true", help="One JSON object per frame.")
    output.add_argument("--print-every", type=int, default=1, metavar="N")
    output.add_argument("--max-frames", type=int, default=0, metavar="N")
    output.add_argument("--quiet", action="store_true", help="Warnings and errors only.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if getattr(args, "quiet", False) else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-40s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.mode == "devices":
        return list_devices(args.max_index)

    device = resolve_device(args.device_preference)
    logger.info("Compute device: %s", device.describe())
    if device.is_fallback:
        logger.warning("Falling back to CPU: %s", device.fallback_reason)

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
