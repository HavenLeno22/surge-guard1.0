"""Build a placeholder demonstration clip from a still photograph.

Real demonstration footage is an unowned dependency with lead time
(`02_Hackathon_Execution_Plan.md` risk register). Development must not wait for
it, and it must not begin against a video that contains no people either - a
clip with nothing to detect verifies nothing.

This composites a still photograph across a moving camera view, producing a
video whose subjects are genuine people at genuine scale. Detection and tracking
run over it exactly as they run over real footage; only the camera motion is
synthetic.

It is **not** a substitute for real footage in a demonstration. Crowd density,
occlusion and pedestrian flow are the phenomena the platform measures, and this
clip has none of them.

    python scripts/make_placeholder_clip.py --output data/scenarios/00_placeholder.mp4
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

DEFAULT_OUTPUT = Path("data/scenarios/00_placeholder.mp4")
DEFAULT_SIZE = (960, 540)
DEFAULT_FPS = 25.0
DEFAULT_SECONDS = 20.0


def default_source_image() -> Path:
    """The photograph bundled with Ultralytics, which contains several people."""
    try:
        from ultralytics.utils import ASSETS
    except ImportError:  # pragma: no cover - environment-dependent
        raise SystemExit(
            "Ultralytics is not installed and no --image was given. "
            "Pass --image with a photograph containing people."
        ) from None
    return Path(ASSETS) / "bus.jpg"


def build_frame(
    photo: NDArray[np.uint8],
    index: int,
    total: int,
    size: tuple[int, int],
) -> NDArray[np.uint8]:
    """Render one frame: the photograph under a slow pan and zoom.

    Movement is what makes the clip useful - a static image would let the tracker
    hold identities without ever being asked to associate anything.
    """
    width, height = size
    progress = index / max(total - 1, 1)

    # A gentle zoom keeps apparent person size changing, and a horizontal pan
    # keeps them moving across the view.
    scale = 1.15 + 0.10 * math.sin(progress * 2 * math.pi)
    scaled_width = int(width * scale)
    scaled_height = int(height * scale)
    scaled = cv2.resize(photo, (scaled_width, scaled_height), interpolation=cv2.INTER_AREA)

    max_x = max(scaled_width - width, 0)
    max_y = max(scaled_height - height, 0)
    offset_x = int(max_x * (0.5 - 0.5 * math.cos(progress * 2 * math.pi)))
    offset_y = int(max_y * progress)

    frame = np.zeros((height, width, 3), dtype=np.uint8)
    crop = scaled[offset_y : offset_y + height, offset_x : offset_x + width]
    frame[: crop.shape[0], : crop.shape[1]] = crop
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", type=Path, default=None, help="Source photograph.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    args = parser.parse_args(argv)

    image_path = args.image or default_source_image()
    photo = cv2.imread(str(image_path))
    if photo is None:
        print(f"Could not read image: {image_path}", file=sys.stderr)
        return 1

    size = (args.width, args.height)
    total = max(round(args.fps * args.seconds), 1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        args.fps,
        size,
    )
    if not writer.isOpened():
        print(f"Could not open video writer for {args.output}", file=sys.stderr)
        return 1

    try:
        for index in range(total):
            writer.write(build_frame(photo, index, total, size))
    finally:
        writer.release()

    print(
        f"Wrote {args.output} - {total} frames, {args.fps:g} fps, "
        f"{size[0]}x{size[1]}, {total / args.fps:.1f}s (source: {image_path.name})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
