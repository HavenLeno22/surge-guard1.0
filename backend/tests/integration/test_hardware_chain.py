"""The whole alert chain, from tracked people to the command the Arduino receives.

    tracks -> crowd analysis -> Crowd Stability Index -> Decision Engine
      -> DecisionService (OIR_GENERATED on the event bus)
      -> HardwareAlertService -> serial line

Everything is the production code the backend builds, through the same factory
it uses, except two ends: the tracks are synthetic (no camera or model in a
test) and the serial port is a scripted board. The crowd is not scripted into a
status: an ordinary moving crowd surges - packing in, slowing almost to a stop,
two in five pushing against the flow - and the index and the Decision Engine
decide what that means.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from surgeguard_ai.contracts import (
    BoundingBox,
    CameraConnectionStatus,
    Detection,
    DetectionResult,
    ImagePoint,
    OperationalStatus,
    PerceptionResult,
    SourceMode,
    Track,
    TrackingResult,
    Vector2D,
)

from app.core.config import Settings
from app.core.event_bus import EventBus
from app.hardware.levels import HardwareLevel
from app.hardware.protocol import level_command
from app.hardware.readings import decision_reading
from app.hardware.service import HardwareAlertService
from app.services.decision_service import DecisionService
from app.services.operational_state import OperationalStateService
from app.services.timeline_service import TimelineService
from app.services.zone_store import ZoneStore
from app.workers.perception_factory import build_analysis_pipeline

from ..unit.test_hardware_service import FakeBoard

_STATUS_COMMAND = {
    OperationalStatus.STABLE: level_command(HardwareLevel.NORMAL).wire,
    OperationalStatus.OBSERVE: level_command(HardwareLevel.NORMAL).wire,
    OperationalStatus.ATTENTION_REQUIRED: level_command(HardwareLevel.WARNING).wire,
    OperationalStatus.HIGH_ALERT: level_command(HardwareLevel.WARNING).wire,
    OperationalStatus.CRITICAL: level_command(HardwareLevel.CRITICAL).wire,
}

START = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)


def _perception(
    seq: int, *, count: int, speed: float, spread_px: float, opposing: bool
) -> PerceptionResult:
    """People along one line of the view, ``spread_px`` wide, walking at ``speed``.

    With ``opposing``, two in every five walk the other way.
    """
    timestamp = START + timedelta(seconds=seq)
    step = spread_px / max(count, 1)
    tracks = tuple(
        Track(
            track_id=index + 1,
            bbox=BoundingBox(x1=120 + index * step, y1=200.0, x2=150 + index * step, y2=400.0),
            confidence=0.9,
            age_frames=40,
            foot_point=ImagePoint(x=135 + index * step, y=400.0),
            velocity_image=Vector2D(dx=-speed if opposing and index % 5 < 2 else speed, dy=0.0),
        )
        for index in range(count)
    )
    return PerceptionResult(
        camera_id="cam-01",
        source_mode=SourceMode.LIVE,
        frame_seq=seq,
        frame_ts=timestamp,
        produced_at=timestamp,
        person_count=count,
        detections=DetectionResult(
            frame_seq=seq,
            frame_ts=timestamp,
            detections=tuple(Detection(bbox=t.bbox, confidence=0.9) for t in tracks),
            inference_ms=12.0,
        ),
        tracking=TrackingResult(frame_seq=seq, frame_ts=timestamp, tracks=tracks),
        inference_ms=12.0,
        processing_ms=15.0,
        achieved_fps=10.0,
    )


async def test_a_crowd_that_becomes_critical_turns_the_alert_hardware_to_critical(
    settings: Settings, tmp_path
) -> None:
    bus = EventBus()
    decisions = DecisionService(
        TimelineService(), OperationalStateService(), bus, camera_id="cam-01"
    )
    pipeline = build_analysis_pipeline(settings, ZoneStore(tmp_path / "zones", "cam-01"))
    board = FakeBoard()
    service = HardwareAlertService(
        transport_factory=lambda: board,
        readings=lambda: [
            decision_reading(
                camera_id="cam-01",
                name="Camera 01",
                decisions=decisions,
                connection=CameraConnectionStatus.ONLINE,
                enabled=True,
            )
        ],
        event_bus=bus,
        keepalive_seconds=600.0,
        ready_timeout_seconds=0.0,
        ack_timeout_seconds=0.0,
        tick_seconds=600.0,  # only the Decision Engine's reports can move it
    )
    await service.start()
    try:
        # Before any analysis there is nothing current to show.
        async with asyncio.timeout(2.0):
            while board.written != ["NO_DATA"]:
                await asyncio.sleep(0.01)

        statuses: list[OperationalStatus] = []
        for seq in range(400):
            surge = max(seq - 40, 0)  # 40 s of an ordinary crowd, then the surge
            perception = _perception(
                seq,
                count=min(8 + surge * 4, 90),
                speed=max(30.0 - surge * 3.0, 1.0),
                spread_px=max(800.0 - surge * 60.0, 40.0),
                opposing=surge > 0,
            )
            decisions.handle_analysis(pipeline.process(perception))
            report = decisions.latest
            if report is None:
                continue
            statuses.append(report.status)
            # Frames here are simulated seconds apart but processed back to back;
            # wait for the hardware as a real second would, so every level the
            # Decision Engine passes through reaches the board.
            expected = _STATUS_COMMAND[report.status]
            async with asyncio.timeout(2.0):
                while board.written[-1] != expected:
                    await asyncio.sleep(0.005)
            if report.status is OperationalStatus.CRITICAL:
                break
    finally:
        await service.stop()

    assert statuses[0] is OperationalStatus.STABLE, "the crowd began stable"
    assert OperationalStatus.CRITICAL in statuses, "the index reached its critical band"
    commands = [line for line in board.written if line != "NO_DATA"]
    assert commands[0] == "NORMAL"
    assert "WARNING" in commands, "the hardware warned before it alarmed"
    assert commands.index("WARNING") < commands.index("CRITICAL")
    assert board.written[-1] == "NO_DATA", "stopping does not leave the last alarm showing"
