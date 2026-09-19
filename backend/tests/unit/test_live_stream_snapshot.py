"""Single-frame snapshots for thumbnails."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import numpy as np
from surgeguard_ai.perception import Frame

from app.streaming.annotator import parse_layers
from app.streaming.live_stream import LiveStreamService

from ..conftest import make_perception_result


def _frame(seq: int) -> Frame:
    image = np.full((90, 160, 3), 40, dtype=np.uint8)
    return Frame(seq=seq, ts=datetime(2026, 1, 1, tzinfo=UTC), image=image, source_id="test")


async def test_no_frame_in_time_returns_nothing_rather_than_a_stale_picture() -> None:
    stream = LiveStreamService(camera_id="cam-01")

    assert await stream.snapshot(timeout_seconds=0.1) is None
    assert stream.viewers == 0


async def test_an_old_frame_is_not_served_as_current() -> None:
    """A frame captured before the request must not be returned by it."""
    stream = LiveStreamService(camera_id="cam-01")
    stream._viewers = 1  # a viewer was watching earlier
    stream.handle_frame(_frame(0), make_perception_result(frame_seq=0))
    stream._viewers = 0

    assert stream.has_frame
    assert await stream.snapshot(timeout_seconds=0.1) is None


async def test_a_frame_arriving_while_waiting_is_returned_as_a_jpeg() -> None:
    stream = LiveStreamService(camera_id="cam-01")

    async def deliver() -> None:
        # The pipeline only captures frames while someone is watching; the
        # snapshot counts as a viewer, so this frame is captured.
        for _ in range(50):
            if stream.viewers:
                break
            await asyncio.sleep(0.01)
        stream.handle_frame(_frame(1), make_perception_result(frame_seq=1))

    delivery = asyncio.create_task(deliver())
    payload = await stream.snapshot(parse_layers(""), timeout_seconds=1.0)
    await delivery

    assert payload is not None
    assert payload[:2] == b"\xff\xd8"
    assert stream.viewers == 0
