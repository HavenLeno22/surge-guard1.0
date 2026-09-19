"""The line protocol of the SurgeGuard alert firmware.

Mirrors ``hardware/arduino/surgeguard_alert/surgeguard_alert.ino``: one ASCII
command per line at 115200 baud, answered by one line.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .levels import HardwareLevel

__all__ = ["HardwareCommand", "Reply", "ReplyKind", "level_command", "parse_reply"]


class HardwareCommand(StrEnum):
    """Every command the firmware accepts that changes what it shows."""

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    NO_DATA = "NO_DATA"

    TEST_RED = "TEST_RED"
    TEST_GREEN = "TEST_GREEN"
    TEST_BLUE = "TEST_BLUE"
    TEST_YELLOW = "TEST_YELLOW"
    TEST_WARNING_TONE = "TEST_WARNING_TONE"
    TEST_ALARM = "TEST_ALARM"
    TEST_SEQUENCE = "TEST_SEQUENCE"
    TEST_OFF = "TEST_OFF"

    @property
    def is_test(self) -> bool:
        return self.value.startswith("TEST_")

    @property
    def wire(self) -> str:
        """The line sent to the firmware, without its terminator."""
        if self.is_test:
            return "TEST " + self.value.removeprefix("TEST_")
        return self.value


def level_command(level: HardwareLevel) -> HardwareCommand:
    """The command that shows an alert level."""
    return HardwareCommand(level.value)


class ReplyKind(StrEnum):
    READY = "READY"
    OK = "OK"
    PONG = "PONG"
    ERROR = "ERR"
    STATE = "STATE"
    LINK_LOST = "LINK_LOST"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class Reply:
    kind: ReplyKind
    detail: str


_PREFIXES = (
    ReplyKind.READY,
    ReplyKind.OK,
    ReplyKind.PONG,
    ReplyKind.ERROR,
    ReplyKind.STATE,
    ReplyKind.LINK_LOST,
)


def parse_reply(line: str) -> Reply:
    """Classify one line from the firmware.

    Anything unrecognised is kept as ``OTHER`` rather than raised: a board that
    has just reset can emit partial bytes, and the link has to ride through that.
    """
    text = line.strip()
    head, _, rest = text.partition(" ")
    for kind in _PREFIXES:
        if head == kind.value:
            return Reply(kind, rest.strip())
    return Reply(ReplyKind.OTHER, text)
