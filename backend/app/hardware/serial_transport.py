"""USB serial link to the alert hardware, over pyserial."""

from __future__ import annotations

import time
from typing import Any

__all__ = ["HardwareUnavailableError", "PySerialTransport", "resolve_port"]

#: Arduino LLC and Arduino SRL - genuine boards.
_GENUINE_VIDS = frozenset({0x2341, 0x2A03})
#: USB-serial chips on common compatible boards: WCH CH340, FTDI, Silicon Labs CP210x.
_CLONE_VIDS = frozenset({0x1A86, 0x0403, 0x10C4})


class HardwareUnavailableError(RuntimeError):
    """No usable serial port for the alert hardware."""


def _comports() -> list[Any]:
    from serial.tools import list_ports

    return list(list_ports.comports())


def resolve_port(configured: str) -> str:
    """The serial port to open: the configured one, or a detected Arduino for ``auto``.

    A genuine Arduino is preferred over a clone's USB-serial chip, which other
    devices use too. Bluetooth serial links have no USB vendor and are never
    chosen.
    """
    if configured.strip().lower() != "auto":
        return configured.strip()

    ports = _comports()
    for vids in (_GENUINE_VIDS, _CLONE_VIDS):
        for port in ports:
            if port.vid in vids:
                return str(port.device)
    raise HardwareUnavailableError(
        "No Arduino is connected over USB. Plug it in, or set "
        "SURGEGUARD_HARDWARE_SERIAL_PORT to its port."
    )


class PySerialTransport:
    """A line-oriented pyserial link. Every method blocks; call from a worker thread."""

    def __init__(self, port: str = "auto", baud_rate: int = 115200) -> None:
        self._configured_port = port
        self._baud_rate = baud_rate
        self._serial: Any = None
        self._buffer = bytearray()
        self.description = port

    def open(self) -> None:
        import serial

        port = resolve_port(self._configured_port)
        self.description = port
        self._buffer.clear()
        self._serial = serial.Serial(port, self._baud_rate, timeout=0, write_timeout=1.0)

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def write_line(self, line: str) -> None:
        if self._serial is None:
            raise HardwareUnavailableError("The alert hardware port is not open.")
        self._serial.write((line + "\n").encode("ascii"))
        self._serial.flush()

    def read_line(self, timeout_seconds: float) -> str | None:
        """One complete line, or ``None`` if none arrives in time. Partial lines are kept."""
        if self._serial is None:
            raise HardwareUnavailableError("The alert hardware port is not open.")
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                return raw.decode("ascii", errors="replace").strip("\r")
            waiting = self._serial.in_waiting
            if waiting:
                self._buffer.extend(self._serial.read(waiting))
                continue
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)
