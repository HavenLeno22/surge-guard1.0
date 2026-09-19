"""Finding the alert hardware's serial port."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.hardware import serial_transport
from app.hardware.serial_transport import HardwareUnavailableError, resolve_port


@dataclass
class _Port:
    device: str
    vid: int | None
    description: str


def _ports(monkeypatch: pytest.MonkeyPatch, *ports: _Port) -> None:
    monkeypatch.setattr(serial_transport, "_comports", lambda: list(ports))


def test_an_explicit_port_is_used_as_given(monkeypatch: pytest.MonkeyPatch) -> None:
    _ports(monkeypatch)
    assert resolve_port("COM8") == "COM8"


def test_auto_finds_a_genuine_arduino_among_other_serial_ports(monkeypatch) -> None:
    _ports(
        monkeypatch,
        _Port("COM3", None, "Standard Serial over Bluetooth link (COM3)"),
        _Port("COM5", 0x1A86, "USB-SERIAL CH340 (COM5)"),
        _Port("COM8", 0x2341, "Arduino Uno (COM8)"),
    )
    assert resolve_port("auto") == "COM8"


def test_auto_accepts_a_common_clone_when_no_genuine_board_is_present(monkeypatch) -> None:
    _ports(
        monkeypatch,
        _Port("COM3", None, "Standard Serial over Bluetooth link (COM3)"),
        _Port("COM5", 0x1A86, "USB-SERIAL CH340 (COM5)"),
    )
    assert resolve_port("AUTO") == "COM5"


def test_auto_with_no_board_says_so(monkeypatch) -> None:
    _ports(monkeypatch, _Port("COM3", None, "Standard Serial over Bluetooth link (COM3)"))
    with pytest.raises(HardwareUnavailableError, match="No Arduino"):
        resolve_port("auto")
