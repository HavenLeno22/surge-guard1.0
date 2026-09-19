"""The service that keeps the alert hardware showing the Decision Engine's level.

The serial port is replaced by a scripted double that answers the way the
firmware does. What is under test is the service's judgement: when it sends,
when it holds back, what a test does to live monitoring, and how it rides
through a board that resets or a cable that is pulled.
"""

from __future__ import annotations

import asyncio
from collections import deque

import pytest
from surgeguard_ai.contracts import AlertPriority, OperationalStatus

from app.core.event_bus import DomainEvent, EventBus
from app.hardware.levels import CameraReading, HardwareLevel
from app.hardware.protocol import HardwareCommand
from app.hardware.service import HardwareAlertService

READY = "READY SURGEGUARD-ALERT 1.0.0 R9 G10 B11 BUZZER8 CATHODE"


class FakeBoard:
    """Answers like the firmware: READY on open, OK for every command."""

    description = "COM-TEST"

    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0
        self.written: list[str] = []
        self.pending: deque[str] = deque()
        self.fail_open = False
        self.fail_writes = False
        self.reject: set[str] = set()

    def open(self) -> None:
        if self.fail_open:
            raise OSError("could not open port")
        self.opened += 1
        self.pending.append(READY)

    def close(self) -> None:
        self.closed += 1

    def write_line(self, line: str) -> None:
        if self.fail_writes:
            raise OSError("device disconnected")
        self.written.append(line)
        if line in self.reject:
            self.pending.append(f"ERR UNKNOWN_COMMAND {line}")
        else:
            self.pending.append(f"OK {line}")

    def read_line(self, timeout_seconds: float) -> str | None:
        return self.pending.popleft() if self.pending else None


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


#: A report's band and the priority the Decision Engine gives it in ordinary conditions.
_BAND = {
    AlertPriority.LOW: (OperationalStatus.STABLE, 92.0),
    AlertPriority.MEDIUM: (OperationalStatus.ATTENTION_REQUIRED, 52.0),
    AlertPriority.HIGH: (OperationalStatus.HIGH_ALERT, 31.0),
    AlertPriority.CRITICAL: (OperationalStatus.CRITICAL, 14.0),
}


def _reading(priority: AlertPriority | None, *, fresh: bool = True) -> CameraReading:
    status, csi = _BAND[priority] if priority is not None else (None, None)
    return CameraReading(
        camera_id="cam-01",
        name="Camera 01",
        priority=priority,
        status=status,
        csi=csi,
        fresh=fresh,
        contributing=True,
    )


@pytest.fixture
def board() -> FakeBoard:
    return FakeBoard()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def readings() -> list[CameraReading]:
    return [_reading(AlertPriority.LOW)]


def _service(
    board: FakeBoard,
    clock: Clock,
    readings: list[CameraReading],
    *,
    enabled: bool = True,
    event_bus: EventBus | None = None,
    tick_seconds: float = 1.0,
) -> HardwareAlertService:
    return HardwareAlertService(
        transport_factory=lambda: board,
        readings=lambda: list(readings),
        event_bus=event_bus,
        enabled=enabled,
        keepalive_seconds=3.0,
        reconnect_seconds=5.0,
        ready_timeout_seconds=0.0,
        ack_timeout_seconds=0.0,
        tick_seconds=tick_seconds,
        clock=clock,
    )


async def test_it_connects_and_shows_the_decision_engine_level(board, clock, readings) -> None:
    readings[:] = [_reading(AlertPriority.CRITICAL)]
    service = _service(board, clock, readings)

    await service.step()

    status = service.status()
    assert board.opened == 1
    assert board.written == ["CRITICAL"]
    assert status.connected
    assert status.firmware == "SURGEGUARD-ALERT 1.0.0 R9 G10 B11 BUZZER8 CATHODE"
    assert status.level is HardwareLevel.CRITICAL
    assert status.commanded is HardwareCommand.CRITICAL
    assert status.acknowledged is HardwareCommand.CRITICAL
    assert status.mode == "live"
    assert "Camera 01" in status.reason


async def test_an_unchanged_level_is_resent_only_to_keep_the_link_alive(
    board, clock, readings
) -> None:
    service = _service(board, clock, readings)

    await service.step()
    clock.now += 1.0
    await service.step()
    assert board.written == ["NORMAL"]

    clock.now += 3.0
    await service.step()
    assert board.written == ["NORMAL", "NORMAL"]


async def test_a_new_level_is_sent_on_the_next_pass(board, clock, readings) -> None:
    service = _service(board, clock, readings)
    await service.step()

    readings[:] = [_reading(AlertPriority.HIGH)]
    await service.step()
    readings[:] = [_reading(AlertPriority.CRITICAL)]
    await service.step()
    readings[:] = [_reading(AlertPriority.LOW, fresh=False)]
    await service.step()

    assert board.written == ["NORMAL", "WARNING", "CRITICAL", "NO_DATA"]


async def test_a_hardware_test_overrides_live_monitoring_until_it_expires(
    board, clock, readings
) -> None:
    service = _service(board, clock, readings)
    await service.step()

    service.start_test(HardwareCommand.TEST_SEQUENCE, duration_seconds=10.0)
    await service.step()
    assert board.written[-1] == "TEST SEQUENCE"
    status = service.status()
    assert status.mode == "test"
    assert status.test_command is HardwareCommand.TEST_SEQUENCE
    assert status.level is HardwareLevel.NORMAL, "the live level is still reported"

    clock.now += 11.0
    await service.step()
    assert board.written[-1] == "NORMAL"
    assert service.status().mode == "live"


async def test_a_test_can_show_an_alert_level_without_a_crowd_event(
    board, clock, readings
) -> None:
    service = _service(board, clock, readings)
    await service.step()

    service.start_test(HardwareCommand.CRITICAL, duration_seconds=5.0)
    await service.step()
    assert board.written[-1] == "CRITICAL"

    service.stop_test()
    await service.step()
    assert board.written[-1] == "NORMAL"


async def test_a_failed_write_disconnects_and_reconnects_after_the_delay(
    board, clock, readings
) -> None:
    service = _service(board, clock, readings)
    await service.step()

    board.fail_writes = True
    clock.now += 3.0
    await service.step()
    status = service.status()
    assert not status.connected
    assert status.last_error and "device disconnected" in status.last_error

    board.fail_writes = False
    clock.now += 1.0
    await service.step()
    assert board.opened == 1, "no reconnection before the delay"

    clock.now += 5.0
    await service.step()
    assert board.opened == 2
    assert board.written[-1] == "NORMAL"
    assert service.status().connected


async def test_a_board_that_reset_is_sent_its_level_again(board, clock, readings) -> None:
    """Opening an Uno's port resets it; so can a brown-out. Either way it has forgotten."""
    service = _service(board, clock, readings)
    await service.step()

    board.pending.append(READY)
    clock.now += 0.5
    await service.step()

    assert board.written == ["NORMAL", "NORMAL"]


async def test_a_rejected_command_is_reported_not_assumed(board, clock, readings) -> None:
    board.reject.add("NORMAL")
    service = _service(board, clock, readings)

    await service.step()

    status = service.status()
    assert status.acknowledged is None
    assert status.last_error and "UNKNOWN_COMMAND" in status.last_error


async def test_a_disabled_service_never_touches_a_port(board, clock, readings) -> None:
    service = _service(board, clock, readings, enabled=False)

    await service.step()

    assert board.opened == 0
    assert not service.status().enabled


async def test_an_unavailable_port_is_retried_later(board, clock, readings) -> None:
    board.fail_open = True
    service = _service(board, clock, readings)

    await service.step()
    assert not service.status().connected
    assert "could not open port" in (service.status().last_error or "")

    board.fail_open = False
    clock.now += 5.0
    await service.step()
    assert service.status().connected


async def test_a_decision_engine_report_wakes_the_service_at_once(board, readings) -> None:
    """Driven by the Decision Engine's own event, not by waiting out a timer."""
    bus = EventBus()
    service = HardwareAlertService(
        transport_factory=lambda: board,
        readings=lambda: list(readings),
        event_bus=bus,
        keepalive_seconds=60.0,
        ready_timeout_seconds=0.0,
        ack_timeout_seconds=0.0,
        tick_seconds=60.0,
    )
    await service.start()
    try:
        async with asyncio.timeout(2.0):
            while board.written != ["NORMAL"]:
                await asyncio.sleep(0.01)

        readings[:] = [_reading(AlertPriority.CRITICAL)]
        bus.dispatch(DomainEvent.OIR_GENERATED, object())

        async with asyncio.timeout(2.0):
            while board.written[-1] != "CRITICAL":
                await asyncio.sleep(0.01)
    finally:
        await service.stop()


async def test_stopping_leaves_the_hardware_saying_it_has_no_data(board, readings) -> None:
    service = HardwareAlertService(
        transport_factory=lambda: board,
        readings=lambda: list(readings),
        ready_timeout_seconds=0.0,
        ack_timeout_seconds=0.0,
        tick_seconds=60.0,
    )
    await service.start()
    async with asyncio.timeout(2.0):
        while not board.written:
            await asyncio.sleep(0.01)

    await service.stop()

    assert board.written[-1] == "NO_DATA"
    assert board.closed >= 1
