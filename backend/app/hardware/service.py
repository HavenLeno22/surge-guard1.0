"""Keeps the alert hardware showing the Operational Decision Engine's level.

One reconcile pass (:meth:`HardwareAlertService.step`) works out what the
hardware should show - a running hardware test, or else the most urgent current
Decision Engine priority - and sends it when it differs from what was last sent,
or when the keepalive is due. Passes run on a short tick and immediately
whenever a camera's Decision Engine issues a report, so an escalation reaches
the LED and buzzer without waiting for the tick.

Serial I/O blocks, so every call on the transport runs in a worker thread and
never on the event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from .levels import CameraReading, HardwareLevel, LevelDerivation, derive_level
from .protocol import HardwareCommand, ReplyKind, level_command, parse_reply

__all__ = ["HardwareAlertService", "HardwareStatus", "SerialTransport"]

logger = get_logger(__name__)

#: Longest a hardware test may override live monitoring. A forgotten test must
#: not leave the LED green through a real emergency.
MAX_TEST_SECONDS = 120.0


class SerialTransport(Protocol):
    """A line-oriented link to the firmware. Every method may block."""

    description: str

    def open(self) -> None: ...

    def close(self) -> None: ...

    def write_line(self, line: str) -> None: ...

    def read_line(self, timeout_seconds: float) -> str | None: ...


@dataclass(frozen=True, slots=True)
class HardwareStatus:
    """What the hardware is doing, and what it should be doing, for the interface."""

    enabled: bool
    connected: bool
    port: str | None
    firmware: str | None
    mode: Literal["live", "test"]
    #: The live level from the Decision Engine, reported even during a test.
    level: HardwareLevel
    reason: str
    camera_id: str | None
    csi: float | None
    commanded: HardwareCommand | None
    commanded_at: datetime | None
    acknowledged: HardwareCommand | None
    acknowledged_at: datetime | None
    last_error: str | None
    test_command: HardwareCommand | None
    test_expires_at: datetime | None


class HardwareAlertService:
    """Drives the RGB LED and buzzer from the Decision Engine's reports."""

    def __init__(
        self,
        *,
        transport_factory: Callable[[], SerialTransport],
        readings: Callable[[], Iterable[CameraReading]],
        event_bus: EventBus | None = None,
        enabled: bool = True,
        keepalive_seconds: float = 3.0,
        reconnect_seconds: float = 5.0,
        ready_timeout_seconds: float = 4.0,
        ack_timeout_seconds: float = 1.0,
        tick_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Args:
            transport_factory: Builds a fresh, unopened link for each connection.
            readings: Every camera's current Decision Engine output.
            event_bus: Where Decision Engine reports are published; a report
                triggers an immediate pass.
            keepalive_seconds: Resend an unchanged command this often. Must stay
                well inside the firmware's 10 s link timeout.
            reconnect_seconds: Wait this long after a failure before reopening.
            ready_timeout_seconds: How long to wait for the READY banner after
                opening. Opening an Uno's port resets it, and it takes about two
                seconds to boot.
            ack_timeout_seconds: How long to wait for a command's reply.
            tick_seconds: Longest interval between passes when nothing happens.
            clock: Monotonic time source, injectable for tests.
        """
        self._transport_factory = transport_factory
        self._readings = readings
        self._event_bus = event_bus
        self._enabled = enabled
        self._keepalive = keepalive_seconds
        self._reconnect = reconnect_seconds
        self._ready_timeout = ready_timeout_seconds
        self._ack_timeout = ack_timeout_seconds
        self._tick = tick_seconds
        self._clock = clock

        self._transport: SerialTransport | None = None
        self._connected = False
        self._next_connect_at: float | None = None
        self._firmware: str | None = None
        self._last_error: str | None = None

        self._commanded: HardwareCommand | None = None
        self._commanded_mono: float | None = None
        self._commanded_at: datetime | None = None
        self._acknowledged: HardwareCommand | None = None
        self._acknowledged_at: datetime | None = None

        self._test_command: HardwareCommand | None = None
        self._test_expires_mono: float | None = None

        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Begin keeping the hardware in step. Returns immediately."""
        if not self._enabled or self._task is not None:
            return
        self._stopping = False
        if self._event_bus is not None:
            self._event_bus.subscribe(DomainEvent.OIR_GENERATED, self._on_report)
        self._task = asyncio.create_task(self._run(), name="hardware-alerts")
        logger.info("Alert hardware service started")

    async def stop(self) -> None:
        """Stop, leaving the hardware saying it has no data rather than a stale level."""
        self._stopping = True
        if self._event_bus is not None:
            self._event_bus.unsubscribe(DomainEvent.OIR_GENERATED, self._on_report)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        async with self._lock:
            if self._connected and self._transport is not None:
                with contextlib.suppress(Exception):
                    await self._send(self._transport, HardwareCommand.NO_DATA)
            await self._close()
        logger.info("Alert hardware service stopped")

    def notify(self) -> None:
        """Run a pass as soon as possible."""
        self._wake.set()

    async def _run(self) -> None:
        while not self._stopping:
            self._wake.clear()
            try:
                await self.step()
            except Exception as error:  # noqa: BLE001 - the loop must survive anything
                logger.error("Alert hardware pass failed", exc_info=error)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._tick)

    def _on_report(self, _payload: object) -> None:
        self._wake.set()

    # -- Hardware tests -----------------------------------------------------

    def start_test(self, command: HardwareCommand, *, duration_seconds: float) -> None:
        """Override live monitoring with one command for a bounded time."""
        duration = min(max(duration_seconds, 1.0), MAX_TEST_SECONDS)
        self._test_command = command
        self._test_expires_mono = self._clock() + duration
        logger.info(
            "Alert hardware test started",
            extra={"command": command.value, "duration_seconds": duration},
        )
        self.notify()

    def stop_test(self) -> None:
        """End a hardware test and return to live monitoring at once."""
        if self._test_command is not None:
            logger.info("Alert hardware test stopped")
        self._test_command = None
        self._test_expires_mono = None
        self.notify()

    # -- Reconciliation -----------------------------------------------------

    async def step(self) -> None:
        """One pass: connect if needed, then send what the hardware should show."""
        if not self._enabled:
            return
        async with self._lock:
            now = self._clock()
            if not self._connected and not await self._connect(now):
                return
            transport = self._transport
            assert transport is not None  # noqa: S101 - set by _connect

            try:
                await self._drain(transport)
                desired = self._desired(now)
                due = (
                    desired is not self._commanded
                    or self._commanded_mono is None
                    or now - self._commanded_mono >= self._keepalive
                )
                if due:
                    await self._send(transport, desired)
                    self._commanded_mono = now
            except Exception as error:  # noqa: BLE001 - any link fault means reconnect
                self._fail(f"Lost the alert hardware on {transport.description}: {error}", now)
                await self._close()

    def _desired(self, now: float) -> HardwareCommand:
        if self._test_command is not None and self._test_expires_mono is not None:
            if now < self._test_expires_mono:
                return self._test_command
            logger.info("Alert hardware test ended; returning to live monitoring")
            self._test_command = None
            self._test_expires_mono = None
        return level_command(self._derive().level)

    def _derive(self) -> LevelDerivation:
        return derive_level(self._readings())

    async def _connect(self, now: float) -> bool:
        if self._next_connect_at is not None and now < self._next_connect_at:
            return False
        transport = self._transport_factory()
        try:
            await asyncio.to_thread(transport.open)
        except Exception as error:  # noqa: BLE001 - reported, then retried
            self._fail(f"Alert hardware unavailable: {error}", now)
            return False

        self._transport = transport
        self._connected = True
        self._next_connect_at = None
        self._commanded = None
        self._commanded_mono = None
        self._acknowledged = None
        self._last_error = None
        logger.info("Alert hardware connected", extra={"port": transport.description})

        try:
            reply = await asyncio.to_thread(
                self._read_until, transport, {ReplyKind.READY}, self._ready_timeout
            )
        except Exception as error:  # noqa: BLE001
            self._fail(f"Alert hardware did not respond: {error}", now)
            await self._close()
            return False
        if reply is not None:
            self._firmware = reply.detail
        return True

    async def _drain(self, transport: SerialTransport) -> None:
        """Handle anything the board said unprompted - above all, that it reset."""
        while True:
            line = await asyncio.to_thread(transport.read_line, 0.0)
            if line is None:
                return
            reply = parse_reply(line)
            if reply.kind is ReplyKind.READY:
                logger.info("Alert hardware restarted; resending its level")
                self._firmware = reply.detail
                self._commanded = None
                self._acknowledged = None
            elif reply.kind is ReplyKind.LINK_LOST:
                self._commanded = None
            elif reply.kind is ReplyKind.ERROR:
                self._last_error = f"Alert hardware reported: {reply.detail}"

    async def _send(self, transport: SerialTransport, command: HardwareCommand) -> None:
        await asyncio.to_thread(transport.write_line, command.wire)
        if command is not self._commanded:
            logger.info("Alert hardware commanded", extra={"command": command.value})
        self._commanded = command
        self._commanded_at = datetime.now(UTC)

        reply = await asyncio.to_thread(
            self._read_until, transport, {ReplyKind.OK, ReplyKind.ERROR}, self._ack_timeout
        )
        if reply is None:
            self._last_error = f"No reply to {command.wire} from the alert hardware."
        elif reply.kind is ReplyKind.ERROR:
            self._last_error = f"Alert hardware rejected {command.wire}: {reply.detail}"
        elif reply.detail == command.wire:
            self._acknowledged = command
            self._acknowledged_at = datetime.now(UTC)
            self._last_error = None

    @staticmethod
    def _read_until(transport: SerialTransport, kinds: set[ReplyKind], timeout: float):
        """Read lines until one of ``kinds`` arrives or the timeout passes. Always reads once."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(deadline - time.monotonic(), 0.0)
            line = transport.read_line(remaining)
            if line is not None:
                reply = parse_reply(line)
                if reply.kind in kinds:
                    return reply
                continue
            if time.monotonic() >= deadline:
                return None

    def _fail(self, message: str, now: float) -> None:
        if message != self._last_error:
            logger.warning(message)
        self._last_error = message
        self._next_connect_at = now + self._reconnect

    async def _close(self) -> None:
        transport, self._transport = self._transport, None
        self._connected = False
        if transport is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(transport.close)

    # -- Reading ------------------------------------------------------------

    def status(self) -> HardwareStatus:
        derivation = self._derive()
        now = self._clock()
        testing = (
            self._test_command is not None
            and self._test_expires_mono is not None
            and now < self._test_expires_mono
        )
        return HardwareStatus(
            enabled=self._enabled,
            connected=self._connected,
            port=self._transport.description if self._transport is not None else None,
            firmware=self._firmware,
            mode="test" if testing else "live",
            level=derivation.level,
            reason=derivation.reason,
            camera_id=derivation.camera_id,
            csi=derivation.csi,
            commanded=self._commanded,
            commanded_at=self._commanded_at,
            acknowledged=self._acknowledged,
            acknowledged_at=self._acknowledged_at,
            last_error=self._last_error,
            test_command=self._test_command if testing else None,
            test_expires_at=(
                datetime.now(UTC) + timedelta(seconds=self._test_expires_mono - now)
                if testing and self._test_expires_mono is not None
                else None
            ),
        )
